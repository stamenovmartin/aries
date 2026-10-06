"""What the machine's power state actually is, and the one setting ARIES writes.

TWO MECHANISMS, AND THE DIFFERENCE MATTERS
------------------------------------------
**Suspend** has an inhibitor. ARIES takes a scoped `sleep`/`block` inhibitor that
logind releases automatically when the holding process dies, and it changes no
configuration at all. Turning Background Mode off restores normal behaviour by
closing a file descriptor — there is nothing left behind to clean up.

**Display blanking has no inhibitor.** There is no "please do blank the screen"
transition to register an interest in; when the display powers off is a GNOME
setting (`org.gnome.desktop.session idle-delay`). So if Background Mode is to
mean "the screen goes dark while ARIES works", that setting has to be written.

ARIES therefore does the smallest reversible thing: it records the value it found
before changing it, and puts it back when Background Mode is switched off. The
previous value is stored in ARIES's own settings, so a crash mid-way does not
lose it — the next disable still restores the right number.

This is the boundary the requirement draws: use a scoped inhibitor where one is
sufficient, and where none exists, change the least possible and be able to undo
it exactly.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

IDLE_DELAY_SCHEMA = "org.gnome.desktop.session"
IDLE_DELAY_KEY = "idle-delay"
POWER_SCHEMA = "org.gnome.settings-daemon.plugins.power"


def _gsettings(*args: str, timeout: float = 8.0) -> tuple[bool, str]:
    if not shutil.which("gsettings"):
        return False, "gsettings is not installed"
    try:
        p = subprocess.run(["gsettings", *args], capture_output=True, text=True,
                           timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, OSError) as e:                 # noqa: BLE001
        return False, str(e)
    if p.returncode != 0:
        return False, (p.stderr or p.stdout).strip()
    return True, p.stdout.strip()


def read_idle_delay() -> int | None:
    """Seconds before the display blanks. 0 means never. None means unreadable.

    `gsettings get` prints the TYPE with the value for non-obvious types:
    `uint32 0`. Stripping every digit out of that string yields "32" from the
    type name followed by the value — so a display timeout of 0 (never) was read
    as 320 seconds, and Background Mode would have "restored" a number the user
    never set. The value is the last whitespace-separated token.
    """
    ok, out = _gsettings("get", IDLE_DELAY_SCHEMA, IDLE_DELAY_KEY)
    if not ok:
        return None
    token = out.strip().split()[-1] if out.strip() else ""
    try:
        return int(token)
    except ValueError:
        return None


def write_idle_delay(seconds: int) -> tuple[bool, str]:
    ok, out = _gsettings("set", IDLE_DELAY_SCHEMA, IDLE_DELAY_KEY, f"uint32 {max(0, int(seconds))}")
    return ok, out


def read_suspend_policy() -> dict:
    """What GNOME would do on idle, on AC and on battery.

    Read, never written. If the machine is configured never to suspend on AC,
    ARIES's inhibitor changes nothing — and the UI should say so rather than
    implying it is holding back a suspend that was never coming.
    """
    out = {}
    for key in ("sleep-inactive-ac-type", "sleep-inactive-ac-timeout",
                "sleep-inactive-battery-type", "sleep-inactive-battery-timeout"):
        ok, value = _gsettings("get", POWER_SCHEMA, key)
        out[key] = value.strip("'") if ok else None
    return out


def display_state() -> tuple[str, str]:
    """('on' | 'off' | 'unknown', why).

    GNOME's screensaver being active is the closest honest proxy for "the display
    is off": it is what blanking sets. It is a proxy, not a panel power reading,
    and `unknown` is returned rather than guessed when the interface is absent.
    """
    if not shutil.which("gdbus"):
        return "unknown", "gdbus is not installed"
    try:
        p = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
             "--object-path", "/org/gnome/ScreenSaver",
             "--method", "org.gnome.ScreenSaver.GetActive"],
            capture_output=True, text=True, timeout=8, check=False)
    except (subprocess.TimeoutExpired, OSError) as e:                 # noqa: BLE001
        return "unknown", str(e)
    if p.returncode != 0:
        return "unknown", "no GNOME screensaver interface on this session"
    return ("off", "the screen is blanked") if "true" in p.stdout.lower() \
        else ("on", "the screen is awake")


def session() -> dict:
    """logind's view of this login session."""
    if not shutil.which("loginctl"):
        return {"available": False, "reason": "loginctl is not installed"}
    try:
        p = subprocess.run(
            ["loginctl", "show-session", "auto", "-p", "Id", "-p", "Active",
             "-p", "IdleHint", "-p", "Type", "-p", "State"],
            capture_output=True, text=True, timeout=8, check=False)
    except (subprocess.TimeoutExpired, OSError) as e:                 # noqa: BLE001
        return {"available": False, "reason": str(e)}
    if p.returncode != 0:
        return {"available": False, "reason": (p.stderr or "no active session").strip()}
    props = {}
    for line in p.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key.strip()] = value.strip()
    return {"available": True, "id": props.get("Id"), "type": props.get("Type"),
            "active": props.get("Active") == "yes",
            "idle": props.get("IdleHint") == "yes",
            "state": props.get("State")}
