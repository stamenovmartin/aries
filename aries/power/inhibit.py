"""Keeping the machine awake while the screen goes dark — properly.

Background Mode means: the user stays logged in, the display powers off as
normal, and the machine does **not** suspend, so ARIES keeps working.

HOW LOGIND INHIBITORS WORK
--------------------------
systemd-logind lets a process register an interest in a system transition. It
answers `Inhibit(what, who, why, mode)` with a **file descriptor**, and the
inhibitor exists for exactly as long as that descriptor is open. There is no
"release" call and no state to clean up: closing the fd releases it, and the
kernel closes every fd of a process that dies — however it dies.

That is the property this is built on. **ARIES cannot leave the machine unable
to suspend.** Crash it, `kill -9` it, cut its power: the descriptor closes and
normal behaviour returns. Verified both ways before this module was written.

    what   sleep · shutdown · idle · handle-lid-switch · handle-power-key …
    mode   block  — the transition does not happen while held
           delay  — the transition waits (up to InhibitDelayMaxSec) then proceeds

WHY `sleep` AND NOT `idle`
--------------------------
This is the whole design, and getting it backwards would break the feature:

* an **`idle`** inhibitor tells logind the session is *not idle*. That keeps the
  machine awake — and also stops the screen ever blanking, because blanking is
  driven by the same idle timer. Background Mode explicitly wants the display
  **off**. An idle inhibitor would burn the panel and the power the mode exists
  to save.
* a **`sleep` block** inhibitor lets idle proceed normally — the screen blanks,
  the session goes idle — and refuses only the suspend itself. GNOME's power
  daemon asks logind to suspend; logind declines while the inhibitor is held.

So: `what=sleep`, `mode=block`. Nothing else.

HOLDING IT FROM PYTHON WITHOUT A D-BUS BINDING
----------------------------------------------
The fd must be held by the long-running ARIES core, which runs in a virtual
environment with no PyGObject (ADR-0004). Rather than add a D-Bus dependency to
parse a fd out of a message, ARIES runs `systemd-inhibit` — part of systemd,
guaranteed present wherever these units run — as a child that blocks reading its
stdin:

    systemd-inhibit --what=sleep --mode=block /bin/sh -c 'read -r _ <&0'

Closing the pipe ends the read, the child exits, the fd closes, the inhibitor is
gone. So release is *explicit* (close the pipe), *automatic* on graceful
shutdown, and *automatic* on a crash — under systemd the whole cgroup is killed,
and in any case the kernel closes the descriptor.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

WHAT = "sleep"
MODE = "block"
WHO = "ARIES"
WHY = "ARIES Background Mode is on — automations keep running while the display is off"


@dataclass
class Held:
    """A live inhibitor, and the process holding its descriptor."""

    process: subprocess.Popen
    why: str

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    @property
    def pid(self) -> int:
        return self.process.pid


_current: Held | None = None


def available() -> tuple[bool, str]:
    if not shutil.which("systemd-inhibit"):
        return False, "systemd-inhibit is not installed — ARIES cannot hold a sleep inhibitor"
    if not os.environ.get("XDG_RUNTIME_DIR") and not os.path.exists("/run/systemd/system"):
        return False, "no systemd session to take an inhibitor from"
    return True, ""


def held() -> bool:
    """Whether ARIES is holding its inhibitor right now, checked against the
    actual child process rather than a remembered flag."""
    global _current
    if _current is None:
        return False
    if not _current.alive:
        # It died without us asking. Forget it so the next reconcile retakes it.
        logger.warning("The sleep inhibitor's holder exited unexpectedly (pid %s)", _current.pid)
        _current = None
        return False
    return True


def acquire(why: str = WHY) -> tuple[bool, str]:
    """Take the inhibitor. Idempotent."""
    global _current
    if held():
        return True, "already held"
    ok, reason = available()
    if not ok:
        return False, reason
    try:
        process = subprocess.Popen(
            ["systemd-inhibit", f"--what={WHAT}", f"--who={WHO}", f"--why={why}",
             f"--mode={MODE}", "/bin/sh", "-c", "read -r _ <&0"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            start_new_session=False)
    except OSError as e:                                   # noqa: BLE001
        return False, f"could not start systemd-inhibit: {e}"

    # It either blocks reading stdin, or it failed immediately.
    try:
        process.wait(timeout=0.6)
        err = (process.stderr.read() or b"").decode(errors="replace").strip()
        return False, err or f"systemd-inhibit exited {process.returncode}"
    except subprocess.TimeoutExpired:
        pass

    _current = Held(process=process, why=why)
    logger.info("Sleep inhibitor taken (pid %s): %s", process.pid, why)
    return True, "taken"


def release() -> tuple[bool, str]:
    """Give it back. Idempotent, and never leaves a child behind."""
    global _current
    if _current is None:
        return True, "not held"
    process = _current.process
    _current = None
    try:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()          # ends the child's read → it exits → fd closes
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("Inhibitor holder did not exit after the pipe closed; killing it")
        process.kill()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            return False, "the inhibitor holder would not exit"
    logger.info("Sleep inhibitor released")
    return True, "released"


def listed(who: str = WHO) -> list[dict]:
    """What logind itself says is inhibiting, filtered to ours.

    Read from systemd rather than from memory: the honest answer to "is suspend
    actually inhibited?" is the one logind would act on, not the one ARIES
    believes.
    """
    if not shutil.which("systemd-inhibit"):
        return []
    try:
        out = subprocess.run(["systemd-inhibit", "--list", "--no-legend"],
                             capture_output=True, text=True, timeout=10, check=False).stdout
    except (subprocess.TimeoutExpired, OSError):
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if not parts or (who and parts[0] != who):
            continue
        rows.append({"who": parts[0], "uid": parts[1] if len(parts) > 1 else "",
                     "pid": parts[3] if len(parts) > 3 else "",
                     "what": parts[5] if len(parts) > 5 else "",
                     "mode": parts[-1], "line": " ".join(parts)})
    return rows


def all_sleep_blockers() -> list[str]:
    """Everything blocking sleep, ARIES or not — so the UI can say whether the
    machine would suspend even with Background Mode off."""
    if not shutil.which("systemd-inhibit"):
        return []
    try:
        out = subprocess.run(["systemd-inhibit", "--list", "--no-legend"],
                             capture_output=True, text=True, timeout=10, check=False).stdout
    except (subprocess.TimeoutExpired, OSError):
        return []
    blockers = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "block" and "sleep" in line:
            blockers.append(" ".join(parts))
    return blockers
