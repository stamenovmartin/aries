"""Talking to systemd --user.

User units live in `~/.config/systemd/user` and need no `sudo`, which is what
makes ARIES installable as part of the login session without touching the system.

Everything here shells out to `systemctl --user`. A D-Bus client would be
tidier, but `systemctl` is guaranteed present wherever these units could run, it
is the same interface a person would use to debug ARIES, and its output is
stable. The cost is one subprocess per query, on a path that runs when a human
asks a question rather than in a loop.

Every call degrades rather than raising: `systemctl` missing, no user session, a
unit that was never installed — each produces a described state, because the one
moment this code matters most is when something is wrong.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field

TARGET = "aries.target"
CORE = "aries-core.service"
UNITS = (CORE,)
UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
TIMEOUT = 10.0


@dataclass
class UnitState:
    """What systemd says about one unit."""

    name: str
    loaded: bool = False
    active: str = "unknown"          # active | inactive | activating | deactivating | failed
    sub: str = ""                    # running | dead | start-pre | failed …
    enabled: str = "unknown"         # enabled | disabled | static | not-found
    since: str = ""
    pid: int | None = None
    restarts: int = 0
    result: str = ""                 # success | exit-code | signal | timeout …
    detail: str = ""

    @property
    def running(self) -> bool:
        return self.active == "active" and self.sub == "running"

    @property
    def starting(self) -> bool:
        return self.active == "activating" or (self.active == "active" and self.sub != "running")

    @property
    def failed(self) -> bool:
        return self.active == "failed"

    def as_dict(self) -> dict:
        return {"name": self.name, "loaded": self.loaded, "active": self.active,
                "sub": self.sub, "enabled": self.enabled, "since": self.since,
                "pid": self.pid, "restarts": self.restarts, "result": self.result,
                "running": self.running, "detail": self.detail}


@dataclass
class Systemd:
    available: bool = False
    reason: str = ""
    units: dict[str, UnitState] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"available": self.available, "reason": self.reason or None,
                "units": {k: v.as_dict() for k, v in self.units.items()}}


def _run(args: list[str], timeout: float = TIMEOUT) -> tuple[int, str, str]:
    try:
        p = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                           timeout=timeout, check=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", "systemctl is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"systemctl did not answer within {timeout:.0f}s"
    except OSError as e:                                  # noqa: BLE001
        return 1, "", str(e)


def available() -> tuple[bool, str]:
    """Whether a systemd user session is usable from here."""
    if not shutil.which("systemctl"):
        return False, "systemctl is not installed — ARIES cannot manage itself as a service"
    if not os.environ.get("XDG_RUNTIME_DIR"):
        return False, ("no XDG_RUNTIME_DIR, so there is no user session to talk to "
                       "(this is normal inside a container or over a bare SSH session)")
    code, out, err = _run(["is-system-running"], timeout=5)
    if code == 127:
        return False, err
    if out in ("offline", "unknown") and code != 0:
        return False, err or f"the user manager reports '{out}'"
    return True, ""


def unit(name: str) -> UnitState:
    """One unit's state, from a single `show` call."""
    # KEY=VALUE, not `--value`. systemd emits properties in ITS OWN order, not the
    # order they were asked for, so positional parsing silently mismatched the
    # fields — "inactive/dead since 0 · last result 0" was the timestamp and the
    # result reading each other's values.
    code, out, err = _run([
        "show", name,
        "--property=LoadState,ActiveState,SubState,UnitFileState,ExecMainPID,"
        "NRestarts,Result,ActiveEnterTimestamp",
        "--no-pager"])
    if code == 127:
        return UnitState(name=name, detail=err)
    props: dict[str, str] = {}
    for line in (out or "").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key.strip()] = value.strip()
    load = props.get("LoadState", "")
    active = props.get("ActiveState", "")
    sub = props.get("SubState", "")
    enabled = props.get("UnitFileState", "")
    pid = props.get("ExecMainPID", "")
    restarts = props.get("NRestarts", "")
    result = props.get("Result", "")
    since = props.get("ActiveEnterTimestamp", "")
    return UnitState(
        name=name,
        loaded=(load == "loaded"),
        active=active or "unknown",
        sub=sub or "",
        enabled=enabled or ("not-found" if load != "loaded" else "unknown"),
        since=since or "",
        pid=int(pid) if pid.isdigit() and int(pid) > 0 else None,
        restarts=int(restarts) if restarts.isdigit() else 0,
        result=result or "",
        detail=err)


def state() -> Systemd:
    ok, reason = available()
    if not ok:
        return Systemd(available=False, reason=reason)
    return Systemd(available=True, units={n: unit(n) for n in (TARGET, *UNITS)})


def installed() -> bool:
    return os.path.exists(os.path.join(UNIT_DIR, TARGET))


# ── control ─────────────────────────────────────────────────────────────────

def _control(verb: str, name: str = TARGET) -> tuple[bool, str]:
    ok, reason = available()
    if not ok:
        return False, reason
    if not installed():
        return False, ("ARIES is not installed as a service yet — run "
                       "./scripts/aries-service install")

    # A unit that hit its start limit refuses to start until it is reset. That is
    # the safe restart policy doing its job — but `aries start` must then be able
    # to actually start ARIES, or the protection becomes a trap that needs an
    # obscure systemd incantation to escape. Clearing the failure is exactly what
    # a person means by "start it".
    if verb in ("start", "restart"):
        core = unit(CORE)
        if core.failed or core.result == "start-limit-hit":
            _run(["reset-failed", CORE, name], timeout=15)

    code, out, err = _run([verb, name], timeout=45)
    if code == 0:
        return True, out or f"{verb} {name}"
    return False, err or out or f"systemctl {verb} {name} exited {code}"


def start() -> tuple[bool, str]:
    return _control("start")


def stop() -> tuple[bool, str]:
    return _control("stop")


def restart() -> tuple[bool, str]:
    return _control("restart")


def enable() -> tuple[bool, str]:
    return _control("enable")


def disable() -> tuple[bool, str]:
    return _control("disable")


def daemon_reload() -> tuple[bool, str]:
    code, out, err = _run(["daemon-reload"], timeout=30)
    return code == 0, err or out


def logs(lines: int = 40, unit_name: str = CORE) -> str:
    try:
        p = subprocess.run(
            ["journalctl", "--user", "-u", unit_name, "-n", str(lines), "--no-pager"],
            capture_output=True, text=True, timeout=TIMEOUT, check=False)
        return p.stdout or p.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        return f"(journal unavailable: {e})"
