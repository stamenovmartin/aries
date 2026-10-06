"""The terminal, which the user asked for, behind the one gate that makes it safe.

WHY THIS WAS RESISTED, AND WHAT CHANGED
---------------------------------------
Every other capability in ARIES is named and typed, and that is the whole design:
a capability that changes something has a verifier that re-reads state afterwards,
which is why ARIES can claim not to report success it did not observe. An
arbitrary command breaks that in three places, and they are worth writing down
because someone will want to remove the gate later:

  1. The input is SPEECH, and the speech layer fabricates commands. On
     2026-09-29 Whisper produced "Ari, play some music." from a song ARIES had
     itself started, passed the wake gate, and looped 44 times (docs/CHANGELOG).
     The same pipeline with an arbitrary command at the end is 44 arbitrary
     commands.
  2. No general verifier can exist. You cannot write a check for "did this
     command do what was meant", so this is the one capability that cannot
     report honestly about its own effect — see `verify_run`, which reports
     exactly what it observed and names what it cannot.
  3. It makes the other capabilities optional. A planner reaches for the easiest
     path, and a shell is always the easiest path; the approval gates and the
     $HOME confinement elsewhere become decoration next to a door with no lock.

WHAT MAKES IT USABLE ANYWAY
---------------------------
`run_shell` is in `capabilities.SENSITIVE`, and that is not a flag — read
service.py around the SENSITIVE check: a sensitive step RETURNS with
`state="proposed"` and a durable approval proposal *before* `execute()` is
reached. So the 44-iteration loop would have produced 44 pending proposals and
zero executions, and the person sees the exact command text before anything runs.
That gate is stronger than filtering by request source, because the router cannot
tell voice from typing — both command bars and the voice daemon post to the same
/api/aries/command.

A shell runs as the user, so its writes cannot be confined the way file
capabilities are confined to $HOME; pretending otherwise would be the dishonest
part. What is bounded instead: how long it may run, how much output is kept, and
a short list of patterns that are refused outright. That list is NOT a security
boundary — anything with a shell can work around it — it is a guard against the
one failure mode that is measured on this machine, a misheard sentence becoming a
destructive command.
"""
import asyncio
import os
import re
import shlex
from pathlib import Path

from aries.workspace.capability_types import Capability, Input
from pydantic import Field

TIMEOUT = 120          # a command a person is waiting on, not a build farm
MAX_OUTPUT = 20000     # per stream; a wall of text is not an answer
MAX_COMMAND = 2000

# Refused before anything runs. Not security: a determined command evades any
# list like this. It exists because "избриши сè" mis-transcribed into a shell is
# a real, measured failure mode on this machine, and a person approving a
# proposal reads the summary, not always every character of it.
CATASTROPHIC = (
    (r"\brm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rf][a-zA-Z]*\s+(-[a-zA-Z]+\s+)*/(\s|$)", "rm -rf on the filesystem root"),
    (r"\bmkfs(\.\w+)?\b", "formatting a filesystem"),
    (r"\bdd\b[^|;]*\bof=/dev/(sd|nvme|vd|hd)", "writing an image over a block device"),
    (r">\s*/dev/(sd|nvme|vd|hd)\w", "redirecting output onto a block device"),
    (r":\(\)\s*\{.*\}\s*;?\s*:", "a fork bomb"),
    (r"\bchmod\s+(-[a-zA-Z]+\s+)*-?R[a-zA-Z]*\s+.*\s+/(\s|$)", "recursive chmod on the filesystem root"),
    (r"\bchown\s+(-[a-zA-Z]+\s+)*-?R[a-zA-Z]*\s+.*\s+/(\s|$)", "recursive chown on the filesystem root"),
    (r"\b(shutdown|poweroff|reboot|halt)\b", "shutting the machine down mid-sentence"),
    (r"\bsudo\b", "sudo, which needs a password ARIES does not have and must never hold"),
)


class ShellCapabilityError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


class RunInput(Input):
    command: str = Field(min_length=1, max_length=MAX_COMMAND)
    cwd: str | None = Field(default=None, max_length=2048)
    timeout: int | None = Field(default=None, ge=1, le=TIMEOUT)


def refuse_reason(command):
    """Why this command will not be run, or None."""
    text = " ".join(command.split())
    for pattern, why in CATASTROPHIC:
        if re.search(pattern, text, re.I):
            return why
    return None


def working_directory(cwd):
    """Where the command runs. Defaults to the ARIES repository root.

    A relative path is resolved against home rather than against whatever
    directory the daemon happens to be in, because a person saying "run it here"
    means their own place, not the service's.
    """
    if not cwd:
        return Path(__file__).resolve().parents[2]
    path = Path(os.path.expanduser(cwd))
    if not path.is_absolute():
        path = Path.home() / path
    path = path.resolve()
    if not path.is_dir():
        raise ShellCapabilityError("TARGET_NOT_FOUND", f"{path} is not a directory")
    return path


async def run(payload, ctx=None):
    """Run one command through a login shell and report what was observed.

    A login shell on purpose: a person asking for a terminal means THEIR
    terminal, with their PATH and their environment. `bash -lc` costs a few
    milliseconds of profile sourcing and gets the command the environment the
    person would have had.
    """
    data = RunInput(**payload) if not isinstance(payload, RunInput) else payload
    command = data.command.strip()
    why = refuse_reason(command)
    if why:
        raise ShellCapabilityError("PERMISSION_REQUIRED",
                                   f"refused before running: {why}. Run it yourself in a terminal "
                                   "if that is genuinely what you meant.")
    directory = working_directory(data.cwd)
    limit = data.timeout or TIMEOUT
    started = asyncio.get_running_loop().time()
    proc = await asyncio.create_subprocess_exec(
        "/bin/bash", "-lc", command, cwd=str(directory),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL)
    timed_out = False
    try:
        out, err = await asyncio.wait_for(proc.communicate(), limit)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        out, err = await proc.communicate()
    elapsed = asyncio.get_running_loop().time() - started
    stdout = out.decode(errors="replace")
    stderr = err.decode(errors="replace")
    return {"command": command, "cwd": str(directory), "shell": "/bin/bash -lc",
            "exit_code": proc.returncode, "timed_out": timed_out,
            "seconds": round(elapsed, 3),
            "stdout": stdout[:MAX_OUTPUT], "stderr": stderr[:MAX_OUTPUT],
            "stdout_truncated": len(stdout) > MAX_OUTPUT, "stderr_truncated": len(stderr) > MAX_OUTPUT,
            "accepted": True}


async def verify_run(payload, result, ctx=None):
    """What can honestly be said about a command that ran.

    This is the one verifier in ARIES that cannot check intent, and it says so
    rather than implying otherwise. An exit status is a fact; "it did what you
    meant" is not something any general check can establish, and claiming it
    would be exactly the kind of unearned success the rest of the project
    refuses to report.
    """
    ran = result.get("exit_code") is not None and not result.get("timed_out")
    return {"met": bool(ran) and result["exit_code"] == 0,
            "data": {"exit_code": result.get("exit_code"), "seconds": result.get("seconds"),
                     "evidence": (f"the command ran to completion in {result.get('seconds')} s and exited "
                                  f"{result.get('exit_code')}. Whether that achieved what you meant is not "
                                  "something ARIES can check — no general verifier exists for an arbitrary "
                                  "command, which is why this capability needs your approval every time.")
                                 if ran else
                                 ("the command was killed after its time limit; anything it had already done "
                                  "is done, and what it had not is unknown")}}


def register(registry):
    registry.register(Capability(
        "shell.run",
        "Run one shell command as you, through a login shell. Approval is required every time, and no "
        "verifier can confirm the command did what was meant — only that it ran and what it printed.",
        RunInput, run, verify_run,
        effect="shell", requires_approval=True, risk_level="high", timeout_seconds=TIMEOUT + 10))


async def voice_run(command):
    """The spoken/typed surface. Approval has already been given by the time this
    is reached — see the SENSITIVE gate in service.py, which returns a proposal
    before execute() is called at all."""
    try:
        out = await run({"command": command})
    except ShellCapabilityError as exc:
        return {"state": "failed", "summary": str(exc)}
    except (OSError, ValueError) as exc:
        return {"state": "failed", "summary": f"{type(exc).__name__}: {exc}"}
    verdict = await verify_run({"command": command}, out)
    body = (out["stdout"] or out["stderr"] or "(no output)").strip()
    head = body.splitlines()[:40]
    return {"state": "done" if verdict["met"] else "unconfirmed",
            "summary": (f"exit {out['exit_code']} in {out['seconds']} s"
                        + (" — timed out" if out["timed_out"] else "")),
            "verification": {"met": verdict["met"], "evidence": verdict["data"]["evidence"]},
            "cards": [{"title": shlex.quote(out["command"])[:120],
                       "text": "\n".join(head) + ("\n…" if len(body.splitlines()) > 40 else ""),
                       "evidence": f"{out['shell']} in {out['cwd']}"}]}
