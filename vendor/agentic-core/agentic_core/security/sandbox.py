"""Sandboxed execution for side-effecting tools.

The marketing backend ran its external agent CLI (backend/app/services/ai/
__init__.py::_cli_agent_run_inner) with: an empty scratch cwd (never the app
dir with .env), its own process group so a timeout kill reaps grandchildren, a
hard timeout, a bounded semaphore, `--sandbox read-only` for codex, and
captured stdout/stderr. That is the sandbox pattern, generalised here for any
subprocess-type tool, plus what a Linux agent needs on top:

  * an allowlist of command prefixes (settings.sandbox_allowed_commands);
  * a denylist of dangerous patterns that always ESCALATE (rm -rf /, mkfs,
    dd of=/dev, shutdown, reboot, writes to /etc/passwd, fork bombs…);
  * dry-run: the command is echoed, never run;
  * an hourly action budget (policy engine) so a runaway loop cannot flood.

Nothing here is a security boundary against a hostile kernel; it is the
application-level control that keeps an agent's mistake small.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import signal
import tempfile
from dataclasses import dataclass, field

from agentic_core.config.settings import settings

logger = logging.getLogger(__name__)

DANGEROUS = [
    r"\brm\s+-[a-z]*r[a-z]*f?\s+/(\s|$)", r"\brm\s+-[a-z]*r[a-z]*\s+/\*", r"\bmkfs(\.|\s)",
    r"\bdd\b.*\bof=/dev/", r"\b(shutdown|reboot|halt|poweroff)\b", r":\(\)\s*\{\s*:\|:&\s*\};:",
    r">\s*/etc/(passwd|shadow|sudoers)", r"\bchmod\s+-R\s+777\s+/", r"\buserdel\b", r"\bcrontab\s+-r\b",
    r"\biptables\s+-F\b", r"\bsystemctl\s+(disable|mask)\s+(ssh|sshd|networking)\b",
]
_DANGEROUS_RX = [re.compile(p, re.I) for p in DANGEROUS]


@dataclass
class SandboxResult:
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    command: str
    dry_run: bool = False
    refused: str | None = None
    uncertain: bool = False
    duration_ms: int = 0

    def as_dict(self) -> dict:
        return {"success": self.ok, "exit_code": self.exit_code, "stdout": self.stdout[-8000:],
                "stderr": self.stderr[-4000:], "command": self.command, "dry_run": self.dry_run,
                "refused": self.refused, "uncertain": self.uncertain, "duration_ms": self.duration_ms,
                "details": self.refused or (self.stderr.strip()[-300:] if not self.ok else "ok")}


def allowed_prefixes() -> list[str]:
    return [p.strip() for p in (settings.sandbox_allowed_commands or "").split(",") if p.strip()]


def is_dangerous(command: str) -> str | None:
    for rx in _DANGEROUS_RX:
        if rx.search(command):
            return f"matches dangerous pattern {rx.pattern!r}"
    return None


def is_allowed(command: str, *, allowlist: list[str] | None = None) -> bool:
    """A command is allowed if it starts with an allowlisted prefix. Pipes and
    chains are checked segment by segment — every segment must be allowed."""
    prefixes = allowlist if allowlist is not None else allowed_prefixes()
    if not prefixes:
        return False
    for segment in re.split(r"\||&&|;|\|\|", command):
        seg = segment.strip()
        if not seg:
            continue
        try:
            words = shlex.split(seg)
        except ValueError:
            return False
        if words and words[0] == "sudo":
            words = words[1:]
        head2 = " ".join(words[:2]) if len(words) >= 2 else " ".join(words)
        head1 = words[0] if words else ""
        if not any(head1 == p or head2 == p or head2.startswith(p + " ") for p in prefixes):
            return False
    return True


_semaphores: dict = {}


def _slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _semaphores.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(max(1, settings.cli_agent_max_concurrency))
        _semaphores[loop] = sem
    return sem


def _kill_tree(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def run_command(command: str, *, timeout: float | None = None, cwd: str | None = None,
                      env: dict | None = None, dry_run: bool | None = None,
                      allowlist: list[str] | None = None, read_only: bool = True,
                      stdin: str | None = None) -> SandboxResult:
    """Run one shell command under the sandbox rules.

    `read_only=True` (the default) demands the allowlist; `read_only=False` is
    for a tool that has been explicitly cleared to mutate (see tools/base.py
    `live`), and still refuses the dangerous patterns.
    """
    import time as _t
    reason = is_dangerous(command)
    if reason:
        return SandboxResult(ok=False, exit_code=None, stdout="", stderr="", command=command,
                             refused=f"refused by sandbox: {reason} — escalate to a human")
    if read_only and not is_allowed(command, allowlist=allowlist):
        return SandboxResult(ok=False, exit_code=None, stdout="", stderr="", command=command,
                             refused="refused by sandbox: command is not on the read-only allowlist")
    if dry_run is None:
        from agentic_core.config.runtime import get_dry_run
        dry_run = get_dry_run() and not read_only
    if dry_run:
        return SandboxResult(ok=True, exit_code=0, stdout=f"[DRY RUN] would run: {command}", stderr="",
                             command=command, dry_run=True)

    scratch = cwd or os.path.join(tempfile.gettempdir(), "agentic-sandbox-cwd")
    os.makedirs(scratch, exist_ok=True)
    safe_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "HOME": scratch}
    if env:
        safe_env.update(env)
    t0 = _t.monotonic()
    sem = _slot()
    await sem.acquire()
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            cwd=scratch, env=safe_env, start_new_session=True)
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin else None),
                                              timeout=timeout or settings.sandbox_timeout_s)
        except asyncio.TimeoutError:
            _kill_tree(proc)
            await proc.wait()
            # A command that timed out MAY have done its work — the honest state
            # is uncertain, never "failed, retry".
            return SandboxResult(ok=False, exit_code=None, stdout="", stderr="timed out", command=command,
                                 uncertain=not read_only, duration_ms=int((_t.monotonic() - t0) * 1000),
                                 refused=None)
    finally:
        sem.release()
    return SandboxResult(ok=proc.returncode == 0, exit_code=proc.returncode,
                         stdout=(out or b"").decode(errors="replace"), stderr=(err or b"").decode(errors="replace"),
                         command=command, duration_ms=int((_t.monotonic() - t0) * 1000))
