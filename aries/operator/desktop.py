"""What is actually on this desktop right now.

THE POINT OF THIS FILE
----------------------
"Open YouTube" is not complete when a command exits 0. It is complete when a
browser is on YouTube. Everything else in the Operator is arrangement; this is
where the claim gets checked against the machine.

TWO OBSERVERS, AND THE DIFFERENCE MATTERS
-----------------------------------------
**Processes** come from `/proc`, which is always there. No session, no shell, no
compositor — if ARIES is running at all it can read `/proc`.

**Windows** come from the ARIES shell over D-Bus, because Wayland has no way for
one client to enumerate another's windows. That is a deliberate security
property of Wayland, not a gap to work around: `wmctrl` and `xdotool` see
nothing, and anything claiming otherwise on this machine is reading XWayland and
missing most of the desktop. Mutter knows, so the extension inside Mutter asks.

The consequence is the honest part. **In an Ubuntu session, or before a re-login
after the extension changes, there is no window list.** ARIES then knows that
Firefox is running and cannot know what page it is on — and must say exactly
that rather than downgrade to a guess. A verifier that quietly substitutes
weaker evidence when the strong evidence is missing is how a system starts
reporting success it did not earn.

WHAT A WINDOW TITLE IS WORTH
----------------------------
Evidence, not proof. There is no way to read a browser's active tab URL from
outside the browser without an extension in it, so "YouTube — Mozilla Firefox"
is what ARIES has. It is good evidence — the title comes from the page — and it
is still a title. Everything here therefore reports *what was checked*, and the
verifier grades its own confidence accordingly.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

BUS_NAME = "org.aries.Shell"
OBJECT_PATH = "/org/aries/Shell"

# Long enough for a shell that is busy repainting, short enough that a dead bus
# name does not become the Operator's latency.
DBUS_TIMEOUT_S = 4.0


@dataclass(frozen=True)
class Window:
    """One mapped window, as Mutter sees it."""

    id: str
    title: str
    wm_class: str
    app_id: str
    pid: int | None
    focused: bool
    workspace: int
    minimised: bool
    maximized: bool | None = None
    geometry: dict | None = None
    # Which monitor, and how much of it is actually free. Geometry on its own
    # cannot be checked against anything: "the left half" is only a claim you
    # can verify once you know the work area the panel and dock left behind.
    monitor: int | None = None
    work_area: dict | None = None

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "wm_class": self.wm_class,
                "app_id": self.app_id, "pid": self.pid, "focused": self.focused,
                "workspace": self.workspace, "minimised": self.minimised,
                **({"maximized": self.maximized} if self.maximized is not None else {}),
                **({"geometry": self.geometry} if self.geometry is not None else {}),
                **({"monitor": self.monitor} if self.monitor is not None else {}),
                **({"work_area": self.work_area} if self.work_area is not None else {})}


@dataclass(frozen=True)
class Process:
    pid: int
    name: str
    cmdline: str

    def as_dict(self) -> dict:
        return {"pid": self.pid, "name": self.name, "cmdline": self.cmdline}


@dataclass
class Desktop:
    """A snapshot. Immutable once taken — a verifier that re-reads the machine
    halfway through its own check can conclude something that was never true at
    any single moment."""

    processes: list[Process] = field(default_factory=list)
    windows: list[Window] | None = None        # None means: could not be observed
    windows_unavailable: str = ""              # and this is why, in a sentence
    shell: dict | None = None                  # the shell's own Ping payload

    @property
    def can_see_windows(self) -> bool:
        return self.windows is not None

    def processes_named(self, name: str) -> list[Process]:
        """Every process whose name or command line mentions `name`.

        Both, because the two miss different things: a Firefox started through a
        wrapper has `name` = the wrapper, and an Electron application has a
        `name` shared with twenty others but a distinctive argv.
        """
        low = name.lower()
        return [p for p in self.processes
                if low in p.name.lower() or low in p.cmdline.lower()]

    def windows_matching(self, *needles: str) -> list[Window]:
        """Windows whose title, class or app id contains every needle."""
        if self.windows is None:
            return []
        out = []
        for w in self.windows:
            hay = f"{w.title} {w.wm_class} {w.app_id}".lower()
            if all(n.lower() in hay for n in needles if n):
                out.append(w)
        return out

    def focused_window(self) -> Window | None:
        for w in self.windows or ():
            if w.focused:
                return w
        return None

    def as_dict(self) -> dict:
        return {
            "processes": len(self.processes),
            "windows": [w.as_dict() for w in self.windows] if self.windows is not None else None,
            "windows_unavailable": self.windows_unavailable,
            "shell": self.shell,
        }


# ── processes ───────────────────────────────────────────────────────────────

def read_processes() -> list[Process]:
    """Every process this user can see, from /proc.

    Only this user's: reading another user's `cmdline` is both usually refused
    and none of ARIES's business. Failures per-process are skipped rather than
    raised — a process that exits between `listdir` and `open` is normal, not an
    error, and the snapshot is still valid without it.
    """
    uid = os.getuid()
    out: list[Process] = []
    try:
        entries = os.listdir("/proc")
    except OSError as exc:
        logger.warning("cannot read /proc: %s", exc)
        return out

    for entry in entries:
        if not entry.isdigit():
            continue
        path = f"/proc/{entry}"
        try:
            if os.stat(path).st_uid != uid:
                continue
            with open(f"{path}/comm") as fh:
                name = fh.read().strip()
            with open(f"{path}/cmdline", "rb") as fh:
                # argv is NUL-separated; the trailing NUL leaves an empty last field.
                cmdline = fh.read().decode("utf-8", "replace").replace("\x00", " ").strip()
        except (OSError, ValueError):
            continue
        out.append(Process(pid=int(entry), name=name, cmdline=cmdline[:400]))
    return out


# ── windows, through the shell ──────────────────────────────────────────────

def _call_shell(method: str, timeout: float = DBUS_TIMEOUT_S, *, args=()) -> tuple[str | None, str]:
    """One D-Bus call to the ARIES shell. Returns (payload, why_not)."""
    try:
        proc = subprocess.run(
            ["gdbus", "call", "--session", "--dest", BUS_NAME,
             "--object-path", OBJECT_PATH, "--method", f"{BUS_NAME}.{method}", *args],
            capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return None, "gdbus is not installed, so the shell cannot be asked"
    except subprocess.TimeoutExpired:
        return None, f"the ARIES shell did not answer {method}() within {timeout:g}s"

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "ServiceUnknown" in err or "was not provided" in err:
            if session_locked() is True:
                return None, "desktop session is locked; background tasks continue, desktop actions await unlock"
            return None, "desktop bridge unavailable; background services are independent"
        if "UnknownMethod" in err:
            return None, (f"the running ARIES shell has no {method}() — it is an older "
                          f"desktop bridge; this capability is unavailable")
        return None, f"the shell refused {method}(): {err[:160]}"

    # gdbus prints a GVariant tuple: ('{"json": ...}',)
    raw = (proc.stdout or "").strip()
    try:
        import ast
        value = ast.literal_eval(raw)
        if isinstance(value, tuple) and len(value) == 1 and isinstance(value[0], str):
            return value[0], ""
    except (SyntaxError, ValueError):
        pass
    return raw, ""


def focus_window(window: Window) -> tuple[bool, str]:
    """Request focus of this exact observed app window; never launch a replacement."""
    payload, why = _call_shell('FocusWindow', args=(window.id, window.app_id))
    if payload is None:
        return False, why
    try:
        data = json.loads(payload)
        if not isinstance(data, dict) or data.get('accepted') is not True:
            return False, str(data.get('reason', 'Focus request refused')) if isinstance(data,dict) else 'Invalid focus response'
    except (ValueError, AttributeError):
        return False, 'The shell returned an invalid focus response'
    import time
    for attempt in range(6):
        observed, why, _ = read_windows()
        if observed is None:
            return False, 'Focus requested but observation unavailable: ' + why
        if any(w.id == window.id and w.app_id == window.app_id and w.focused and not w.minimised for w in observed):
            return True, 'The exact requested window was independently observed focused'
        if attempt < 5:
            time.sleep(.1)
    return False, 'Focus request accepted but the requested window was not observed focused'


def read_windows() -> tuple[list[Window] | None, str, dict | None]:
    """The window list, or an honest reason there is not one."""
    payload, why = _call_shell("Windows")
    if payload is None:
        return None, why, None
    try:
        data = json.loads(payload)
        if not isinstance(data,dict) or not isinstance(data.get('windows'),list) or len(data['windows'])>1000:
            raise ValueError('Expected a bounded windows array')
        windows = []
        for w in data['windows']:
            if not isinstance(w,dict) or not isinstance(w.get('id'),str) or not w['id']:
                raise ValueError('Window identity missing')
            for key in ('title','wm_class','app_id'):
                if not isinstance(w.get(key,''),str):raise ValueError('Invalid window text')
            for key in ('focused','minimised'):
                if type(w.get(key,False)) is not bool:raise ValueError('Invalid window state')
            if type(w.get('workspace',0)) is not int:raise ValueError('Invalid workspace')
            if w.get('pid') is not None and (type(w['pid']) is not int or w['pid']<=0):raise ValueError('Invalid window PID')
            geometry = w.get('geometry')
            if geometry is not None and (not isinstance(geometry, dict) or set(geometry) != {'x','y','width','height'} or any(type(v) is not int for v in geometry.values()) or geometry['width'] <= 0 or geometry['height'] <= 0):
                raise ValueError('Invalid observed geometry')
            if w.get('maximized') is not None and type(w['maximized']) is not bool:
                raise ValueError('Invalid maximized state')
            work_area = w.get('work_area')
            if work_area is not None and (not isinstance(work_area, dict) or set(work_area) != {'x','y','width','height'} or any(type(v) is not int for v in work_area.values())):
                raise ValueError('Invalid observed work area')
            if work_area is not None and (work_area['width'] <= 0 or work_area['height'] <= 0):
                work_area = None      # a size we cannot tile into is absence, not a fault
            # -1 is Mutter's "not on a monitor", which is the honest answer for a
            # window that has just been created and not yet mapped. Rejecting it
            # threw away the WHOLE observation at exactly the moment a launch was
            # being verified, so opening anything reported "cannot confirm".
            if w.get('monitor') is not None and type(w['monitor']) is not int:
                raise ValueError('Invalid monitor index')
            windows.append(Window(id=w['id'],title=w.get('title',''),wm_class=w.get('wm_class',''),
                                  app_id=w.get('app_id',''),pid=w.get('pid'),focused=w.get('focused',False),
                                  workspace=w.get('workspace',0),minimised=w.get('minimised',False),
                                  maximized=w.get('maximized'), geometry=geometry,
                                  monitor=w.get('monitor'), work_area=work_area))
    except (ValueError,TypeError) as exc:
        return None, f'invalid desktop observation: {exc}', None

    return windows, "", data.get("shell")


def observe() -> Desktop:
    """One snapshot of the desktop, taken as close to atomically as it can be.

    Windows first, because that is the observation that can fail and the one a
    verdict usually turns on — if it is going to be unavailable, the caller
    should find out before spending time reading /proc.
    """
    windows, why, shell = read_windows()
    return Desktop(processes=read_processes(), windows=windows,
                   windows_unavailable=why, shell=shell)


def session_locked() -> bool | None:
    """Lock state is distinct from an absent or outdated desktop bridge."""
    try:
        proc = subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
                               "--object-path", "/org/gnome/ScreenSaver",
                               "--method", "org.gnome.ScreenSaver.GetActive"],
                              capture_output=True, text=True, timeout=DBUS_TIMEOUT_S)
        if proc.returncode == 0:
            if proc.stdout.strip() == "(true,)": return True
            if proc.stdout.strip() == "(false,)": return False
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def capabilities() -> dict:
    """Probe actual bridge methods. A source hash difference is not a capability failure."""
    import xml.etree.ElementTree as ET
    required = {"Ping", "Windows", "FocusWindow"}
    try:
        proc = subprocess.run(["gdbus", "introspect", "--session", "--dest", BUS_NAME,
                               "--object-path", OBJECT_PATH, "--xml"],
                              capture_output=True, text=True, timeout=DBUS_TIMEOUT_S)
        if proc.returncode or len(proc.stdout) > 100000:
            raise ValueError("Desktop bridge introspection unavailable")
        root = ET.fromstring(proc.stdout)
        methods = {m.get("name") for interface in root.findall("interface")
                   if interface.get("name") == BUS_NAME for m in interface.findall("method") if m.get("name")}
        version, actions = None, []
        compatible = False
        if 'Capabilities' in methods:
            payload, why = _call_shell('Capabilities')
            handshake = json.loads(payload) if payload else {}
            version = handshake.get('protocol_version')
            advertised = handshake.get('capabilities')
            actions = handshake.get('window_actions', [])
            if type(version) is not int or not isinstance(advertised, list) or not isinstance(actions, list) or any(not isinstance(a,str) for a in advertised + actions):
                raise ValueError('Invalid desktop protocol handshake')
            # 3 and 4 both, deliberately: the shell on disk is upgraded by an
            # install, but the shell in memory only changes at logout. Refusing
            # 3 would take the desktop away between those two moments.
            compatible = version in (3, 4) and set(advertised) <= methods
        return {"available": True, "protocol_version": version,
                "compatibility": 'compatible' if compatible else ('legacy' if version is None else 'incompatible'),
                "window_actions": actions if compatible else [], "methods": sorted(methods),
                "missing": sorted(required-methods), "core_requires_shell": False,
                "full_desktop_support": required.issubset(methods)}
    except (OSError, subprocess.SubprocessError, ValueError, ET.ParseError) as exc:
        return {"available": False, "methods": [], "missing": sorted(required),
                "core_requires_shell": False, "full_desktop_support": False,
                "error": type(exc).__name__, "session_locked": session_locked()}


# ---------------------------------------------------------------------------
# HiDPI: the scale factor, and the rectangle a tile should actually produce
# ---------------------------------------------------------------------------
# WHY THIS IS HERE AND NOT ONLY IN THE SHELL
# ------------------------------------------
# `desktop.tile` computes its rectangle inside the GNOME Shell extension
# (shell/aries@aries.local/lib/dbus.js, TILE_SIDES), from the monitor's WORK AREA
# in logical pixels, with floor for both halves' widths and ceil for the second
# origin so the two meet flush on an odd width. At scale 1 that is exact.
#
# On a fractionally scaled display it stops being exact, and the failure is not
# cosmetic. Mutter places windows on whole DEVICE pixels: a logical width whose
# product with the scale is not an integer is adjusted on the way in. The
# verifier here checks geometry by equality against the rectangle the shell said
# it computed, so an adjusted-by-one-pixel placement makes a CORRECT tile report
# `met: false` — "I did it but cannot confirm it", for a window that is sitting
# exactly where the person asked.
#
# So the scale factor is read from Mutter and the expected rectangle is computed
# on device-pixel boundaries. The arithmetic below reduces EXACTLY to the shell's
# at step 1, which covers scale 1.0 and 2.0 and is the property the test pins:
# this is a generalisation of the existing rule, not a replacement for it.
#
# HONEST LIMIT, stated here rather than in a report: this display is a DELL
# E2422HS at 1920x1080, scale 1.0 (read live from Mutter, logical monitor
# (0, 0, 1.0)). The fractional paths are therefore exercised against Mutter's own
# advertised scale list (1.25, 1.3333, 1.5, 1.6667, 2.0) and against hand-checked
# arithmetic, NOT against a real HiDPI panel. Nothing here has been seen to place
# a window on a fractionally scaled monitor.

#: Where each named side lands inside a work area. Mirrors the shell's TILE_SIDES
#: and must keep mirroring it; tests/test_tile_hidpi.py compares the two by
#: reading the JavaScript.
TILE_SIDES = ('left', 'right', 'top', 'bottom', 'topleft', 'topright',
              'bottomleft', 'bottomright', 'full')

DISPLAY_CONFIG = ('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig')


def device_step(scale: float | None) -> int:
    """How many LOGICAL pixels make a whole number of device pixels.

    scale 1 or 2 → 1 (every logical pixel is a whole number of device pixels).
    scale 1.5 → 2, scale 1.25 or 1.75 → 4, scale 4/3 → 3. GNOME's fractional
    scales are all small rationals, so the denominator is the step, and 16 is a
    ceiling rather than a guess: a step larger than that would move a tile edge
    by more than a window border and is not worth honouring.
    """
    from fractions import Fraction
    if not scale or scale <= 0:
        return 1
    try:
        step = Fraction(float(scale)).limit_denominator(16).denominator
    except (ValueError, OverflowError, ZeroDivisionError):
        return 1
    return step if 1 <= step <= 16 else 1


def tile_rect(work_area: dict, side: str, scale: float | None = 1.0) -> dict:
    """The rectangle for one named side, aligned to whole device pixels.

    The halves are floored to a multiple of the step, and the SECOND tile is
    placed against the far edge of the work area rather than at its own computed
    origin. That is what keeps both edges device-aligned without assuming
    anything about the work area's own width: the far edge is Mutter's, and
    subtracting a device-aligned width from it stays device-aligned.
    """
    if side not in TILE_SIDES:
        raise ValueError(f"unknown tile side {side!r}; one of {TILE_SIDES}")
    for key in ("x", "y", "width", "height"):
        if type(work_area.get(key)) is not int:
            raise ValueError("a work area needs integer x, y, width and height")
    if work_area["width"] <= 0 or work_area["height"] <= 0:
        raise ValueError("a work area with no area cannot be tiled into")
    step = device_step(scale)
    x, y, w, h = work_area["x"], work_area["y"], work_area["width"], work_area["height"]
    half_w = max(step, (w // 2 // step) * step)
    half_h = max(step, (h // 2 // step) * step)
    # Never wider or taller than the area itself, which a 1-pixel work area and a
    # step of 4 would otherwise produce.
    half_w, half_h = min(half_w, w), min(half_h, h)
    left, top = x, y
    right, bottom = x + w - half_w, y + h - half_h
    table = {
        "left": (left, top, half_w, h),
        "right": (right, top, half_w, h),
        "top": (left, top, w, half_h),
        "bottom": (left, bottom, w, half_h),
        "topleft": (left, top, half_w, half_h),
        "topright": (right, top, half_w, half_h),
        "bottomleft": (left, bottom, half_w, half_h),
        "bottomright": (right, bottom, half_w, half_h),
        "full": (x, y, w, h),
    }
    rx, ry, rw, rh = table[side]
    return {"x": rx, "y": ry, "width": rw, "height": rh}


def _current_mode(modes: list) -> tuple[int, int] | None:
    for mode in modes:
        if len(mode) >= 7 and isinstance(mode[6], dict) and mode[6].get("is-current", {}).get("data"):
            return int(mode[1]), int(mode[2])
    return None


def monitor_scales(timeout: float = DBUS_TIMEOUT_S) -> dict:
    """Every logical monitor Mutter currently has, with its scale factor.

    `org.gnome.Mutter.DisplayConfig.GetCurrentState` is the only interface that
    publishes this: `gsettings get org.gnome.desktop.interface scale-factor` is
    the X11-era integer and reads 0 on a Wayland session with fractional scaling,
    and the shell extension's own window payload reports a work area but no
    scale. Read through `busctl --json=short` because the reply is a nested
    variant that gdbus prints in GVariant text, which has no parser here.
    """
    if not shutil.which("busctl"):
        return {"available": False, "monitors": [], "source": "",
                "why": "busctl is not installed, so the Mutter display configuration "
                       "cannot be read; tiles are computed at scale 1"}
    try:
        proc = subprocess.run(["busctl", "--user", "call", DISPLAY_CONFIG[0], DISPLAY_CONFIG[1],
                               DISPLAY_CONFIG[0], "GetCurrentState", "--json=short"],
                              capture_output=True, text=True, timeout=timeout)
        if proc.returncode or len(proc.stdout) > 2_000_000:
            raise ValueError((proc.stderr or "no output").strip()[:200])
        data = json.loads(proc.stdout)["data"]
        physical, logical = data[1], data[2]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError) as exc:
        return {"available": False, "monitors": [], "source": "",
                "why": f"Mutter did not answer GetCurrentState ({type(exc).__name__}: {exc})"}
    modes = {}
    for entry in physical:
        try:
            modes[tuple(entry[0])] = _current_mode(entry[1])
        except (IndexError, TypeError, ValueError):
            continue
    out = []
    for index, entry in enumerate(logical):
        try:
            x, y, scale, transform = int(entry[0]), int(entry[1]), float(entry[2]), int(entry[3])
            connectors = [tuple(c) for c in entry[5]]
        except (IndexError, TypeError, ValueError):
            continue
        size = next((modes[c] for c in connectors if modes.get(c)), None)
        width = height = None
        if size and scale > 0:
            pw, ph = size
            if transform in (1, 3, 5, 7):          # 90/270 degrees: the mode is sideways
                pw, ph = ph, pw
            width, height = round(pw / scale), round(ph / scale)
        out.append({"index": index, "scale": scale, "step": device_step(scale),
                    "transform": transform, "x": x, "y": y,
                    "width": width, "height": height,
                    "connectors": [c[0] for c in connectors],
                    "primary": bool(entry[4]) if len(entry) > 4 else False})
    if not out:
        return {"available": False, "monitors": [], "source": "",
                "why": "Mutter answered with no logical monitors"}
    return {"available": True, "monitors": out, "why": "",
            "source": "org.gnome.Mutter.DisplayConfig GetCurrentState"}


def scale_for(window: dict, monitors: list[dict]) -> tuple[float | None, str]:
    """This window's scale factor, matched by POSITION first and index second.

    Mutter's `get_monitor()` index and the order of GetCurrentState's logical
    monitors agree in practice and are not promised to, so the work area's own
    origin decides when it can: a work area starts inside exactly one logical
    monitor. `monitor == -1` is Mutter's honest answer for a window that exists
    and has not been mapped onto a monitor yet; it stays accepted and simply has
    no scale, because there is no monitor to have one.
    """
    area = window.get("work_area") or {}
    if area:
        inside = [m for m in monitors
                  if m.get("width") and m.get("height")
                  and m["x"] <= area.get("x", -1) < m["x"] + m["width"]
                  and m["y"] <= area.get("y", -1) < m["y"] + m["height"]]
        if len(inside) == 1:
            return inside[0]["scale"], ("matched by work-area origin to logical monitor %d (%s)"
                                        % (inside[0]["index"], ", ".join(inside[0]["connectors"])))
    index = window.get("monitor")
    if index is None:
        return None, "the window carries no monitor index"
    if index < 0:
        return None, ("the window is not on a monitor yet (Mutter reports %d), which is accepted: "
                      "it has just been created and not mapped" % index)
    match = next((m for m in monitors if m["index"] == index), None)
    if match is None:
        return None, f"Mutter has no logical monitor {index}"
    return match["scale"], f"matched by monitor index {index}"


def tile_expectation(window: dict, side: str, monitors: list[dict] | None = None) -> dict:
    """What `desktop.tile <side>` should produce for this window, and on what basis.

    `shell_rect` is what the extension on disk computes (scale 1 arithmetic);
    `rect` is the device-pixel-aligned rectangle. They are the same rectangle on
    every integer scale, so `aligned` being false is the HiDPI case and nothing
    else. A verifier that accepts either is a verifier that cannot call a correct
    tile unconfirmed, and cannot call a wrong one confirmed: both candidates are
    exact rectangles, not a tolerance.
    """
    if monitors is None:
        reading = monitor_scales()
        monitors, why = reading["monitors"], reading["why"]
    else:
        why = ""
    area = window.get("work_area")
    if not area:
        return {"side": side, "scale": None, "step": 1, "rect": None, "shell_rect": None,
                "aligned": None, "monitor": window.get("monitor"),
                "why": why or "the shell reported no work area for this window, so no rectangle "
                              "can be predicted; the tile is verified against the shell's own"}
    scale, how = scale_for(window, monitors)
    try:
        aligned_rect = tile_rect(area, side, scale)
        shell_rect = tile_rect(area, side, 1.0)
    except ValueError as exc:
        return {"side": side, "scale": scale, "step": device_step(scale), "rect": None,
                "shell_rect": None, "aligned": None, "monitor": window.get("monitor"),
                "why": str(exc)}
    return {"side": side, "scale": scale, "step": device_step(scale), "rect": aligned_rect,
            "shell_rect": shell_rect, "aligned": aligned_rect == shell_rect,
            "monitor": window.get("monitor"),
            "why": (why + "; " if why else "") + how,
            "source": "org.gnome.Mutter.DisplayConfig scale applied to the shell's work area"}
