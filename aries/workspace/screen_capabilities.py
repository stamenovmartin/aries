"""ARIES's eyes: the screen as pixels, and the pixels as text.

WHY THIS FILE EXISTS
--------------------
`desktop.observe` knows which windows exist and `inspect_app` knows which
controls they expose, and neither of them can see anything. A window titled
"Untitled Document" could be holding a wall of text or nothing at all; a dialog
that the accessibility tree renders as one unlabelled button is unreadable until
somebody looks at the picture. This is the observation that looks.

THE DOOR THAT ACTUALLY OPENS
----------------------------
Wayland gives a client no way to read another client's pixels, on purpose, so
every screenshot on this machine has to be asked for. Measured on GNOME Shell
50.1, Wayland session, September 2026:

  org.gnome.Shell.Screenshot         AccessDenied: "Screenshot is not allowed".
                                     The Shell only answers a short allow-list of
                                     bus names (the media keys, the portal
                                     backends); ARIES is not on it and cannot be.
  org.freedesktop.portal.Screenshot  Works, unprompted, in 0.52 s, with
                                     interactive=false. The portal IS on the
                                     allow-list and asks the Shell for us.
  grim, gnome-screenshot, spectacle,
  scrot, maim, import, xwd, ffmpeg    None of them installed, and no root to
                                     install them. The X11 ones would have
                                     returned black frames through XWayland anyway.

So: the portal, over D-Bus, through jeepney — which is already here as
SecretStorage's own dependency, so this adds nothing to requirements.txt.

THE BLACK RECTANGLE
-------------------
The portal's failure mode is the dangerous kind. When the screen is blanked —
this machine blanks after 60 s of idle — the call still answers success, still
returns a URI, and still writes a valid 1920x1080 PNG whose every pixel is zero.
Measured: mean 0.00, standard deviation 0.00, one distinct colour. A capability
that reported that as a screenshot would be lying with a file to prove it.

Two guards, in this order. `org.gnome.ScreenSaver.GetActive` is asked first, so
a blanked screen is refused before a useless file is written. Then the pixels
themselves are decoded and measured, because the blank can begin between the
question and the answer, and because pixels are the only ground truth about
pixels. A uniform frame is an error here, never a result.

READING IT
----------
tesseract is not installed either, but `libtesseract.so.5` and its `liblept.so.5`
are on disk inside the gnome-46-2404 snap runtime, so ctypes reaches them the way
aries/speech/rhvoice.py reaches libRHVoice. The snap ships no language data, so
`eng.traineddata` and `mkd.traineddata` (tessdata_fast, 5.7 MB, Apache-2.0) live
in var/models/tessdata. Without them this refuses and says how to get them; it
never returns empty text and calls that an answer.

`eng+mkd` is the default because it is measurably better on this desktop, not as
a courtesy: on the same frame it recovered "Ѓорѓи" where `eng` alone produced
"fopfn", at a higher mean confidence (75 vs 72) for 0.46 s more.

PRIVACY
-------
A screenshot is the most indiscriminate thing ARIES can collect — a password
manager, a bank page and a private message are all just pixels. So captures are
a working artifact with a short life, not an archive: var/screen, directory mode
0700, files 0600, at most 8 kept and nothing older than 15 minutes, pruned on
every capture. The portal insists on writing into ~/Pictures first and ARIES
moves that file out and unlinks it immediately, so nothing accumulates in the
person's own gallery. A window capture never keeps the full-screen frame at all.

What this cannot clean up is text: `screen.read` returns what it read, and
whatever stores the result stores that too.
"""
from __future__ import annotations

import asyncio
import ctypes
import hashlib
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
from jeepney import DBusAddress, HeaderFields, MatchRule, MessageType, message_bus, new_method_call
from jeepney.io.blocking import open_dbus_connection
from pydantic import Field

from aries.operator import desktop
from aries.workspace.capability_types import Capability, Input

ROOT = Path(__file__).resolve().parents[2]
CAPTURES = ROOT / "var" / "screen"
# Eight frames and fifteen minutes: enough for a follow-up question about the
# same screen, far too little to become a record of somebody's day.
KEEP_FILES = 8
KEEP_SECONDS = 900
LANGUAGES = ("eng+mkd", "eng", "mkd")
TESSDATA = (ROOT / "var" / "models" / "tessdata", Path("/usr/share/tesseract-ocr/5/tessdata"),
            Path("/usr/share/tesseract-ocr/4.00/tessdata"), Path("/usr/share/tessdata"))
# A snap revision directory is renamed by every update; `current` is the symlink
# that survives one. The system path is tried first so a real apt install wins.
LIBRARY_DIRS = (Path("/usr/lib/x86_64-linux-gnu"), Path("/usr/local/lib"))
SNAP_LIBRARY_DIRS = "*/current/usr/lib/x86_64-linux-gnu"
# libtesseract's DT_NEEDED leptonica is resolved from already-loaded objects, so
# dlopening it first is what makes the snap copy usable without LD_LIBRARY_PATH.
LEPTONICA = ("liblept.so.5", "libleptonica.so.6", "liblept.so.4")
SCREENSHOT = DBusAddress("/org/freedesktop/portal/desktop", bus_name="org.freedesktop.portal.Desktop",
                         interface="org.freedesktop.portal.Screenshot")
DISPLAY_CONFIG = DBusAddress("/org/gnome/Mutter/DisplayConfig", bus_name="org.gnome.Mutter.DisplayConfig",
                             interface="org.gnome.Mutter.DisplayConfig")
FETCH_TESSDATA = ("mkdir -p var/models/tessdata && for l in eng mkd; do curl -sSL -o "
                  "var/models/tessdata/$l.traineddata "
                  "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$l.traineddata; done")

_lock = threading.Lock()
_pixbuf_library = None
_tesseract_library = None


def now():
    return datetime.now(timezone.utc).isoformat()


class ScreenError(RuntimeError):
    """Carries the planner's error vocabulary; see aries/workspace/agent.error."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.retryable = code == "TRANSIENT"


class CaptureInput(Input):
    # A window is named by the exact ID a desktop observation reported, never by
    # an app name: two windows of one application are two different pictures.
    window_id: str | None = Field(default=None, min_length=1, max_length=80)


class ReadInput(CaptureInput):
    language: Literal["eng+mkd", "eng", "mkd"] = "eng+mkd"


# ── pixels ──────────────────────────────────────────────────────────────────

class _GError(ctypes.Structure):
    _fields_ = [("domain", ctypes.c_uint32), ("code", ctypes.c_int), ("message", ctypes.c_char_p)]


def _pixbuf():
    """gdk-pixbuf over ctypes: the PNG codec this desktop already runs on.

    A pure-Python decoder was the alternative and is not one: libpng's adaptive
    filtering picked Paeth for 350 of 1080 rows in a real frame, and Paeth
    un-filtering is sequential in both axes, so numpy cannot vectorize it.
    gdk-pixbuf decodes the same frame in 27 ms and encodes a crop in 26 ms.
    """
    global _pixbuf_library
    with _lock:
        if _pixbuf_library is None:
            try:
                lib = ctypes.CDLL("libgdk_pixbuf-2.0.so.0")
                glib = ctypes.CDLL("libglib-2.0.so.0")
                gobject = ctypes.CDLL("libgobject-2.0.so.0")
            except OSError as exc:
                raise ScreenError("CAPABILITY_UNAVAILABLE", "gdk-pixbuf is unavailable, so a captured "
                                  "frame cannot be decoded or measured: " + str(exc)) from exc
            lib.gdk_pixbuf_new_from_file.restype = ctypes.c_void_p
            lib.gdk_pixbuf_new_from_file.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
            lib.gdk_pixbuf_new_subpixbuf.restype = ctypes.c_void_p
            lib.gdk_pixbuf_new_subpixbuf.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4
            lib.gdk_pixbuf_savev.restype = ctypes.c_int
            lib.gdk_pixbuf_savev.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                                             ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_char_p),
                                             ctypes.POINTER(ctypes.c_void_p)]
            for name in ("get_width", "get_height", "get_rowstride", "get_n_channels", "get_bits_per_sample"):
                function = getattr(lib, "gdk_pixbuf_" + name)
                function.restype, function.argtypes = ctypes.c_int, [ctypes.c_void_p]
            lib.gdk_pixbuf_read_pixels.restype = ctypes.c_void_p
            lib.gdk_pixbuf_read_pixels.argtypes = [ctypes.c_void_p]
            gobject.g_object_unref.argtypes = [ctypes.c_void_p]
            glib.g_error_free.argtypes = [ctypes.c_void_p]
            _pixbuf_library = (lib, glib, gobject)
        return _pixbuf_library


def _glib_message(lib, glib, error):
    detail = ctypes.cast(error, ctypes.POINTER(_GError)).contents.message if error else None
    text = detail.decode("utf-8", "replace") if detail else "no reason reported"
    if error:
        glib.g_error_free(error)
    return text


def _load(path):
    """A decoded frame. The caller owns it and must release it through _release."""
    lib, glib, _ = _pixbuf()
    error = ctypes.c_void_p()
    handle = lib.gdk_pixbuf_new_from_file(os.fsencode(str(path)), ctypes.byref(error))
    if not handle:
        raise ScreenError("NON_RETRYABLE", "The captured frame could not be decoded: "
                          + _glib_message(lib, glib, error))
    if lib.gdk_pixbuf_get_bits_per_sample(handle) != 8 or lib.gdk_pixbuf_get_n_channels(handle) not in (3, 4):
        _release(handle)
        raise ScreenError("NON_RETRYABLE", "Only 8-bit RGB or RGBA frames are measurable here")
    return handle


def _release(handle):
    if handle:
        _pixbuf()[2].g_object_unref(handle)


def _view(handle):
    """A numpy view of a frame's pixels. Valid only while the frame is alive.

    Rowstride, not width*channels: a sub-frame keeps its parent's stride, and
    reading it as packed rows would shear the image diagonally.
    """
    lib = _pixbuf()[0]
    width, height = lib.gdk_pixbuf_get_width(handle), lib.gdk_pixbuf_get_height(handle)
    stride, channels = lib.gdk_pixbuf_get_rowstride(handle), lib.gdk_pixbuf_get_n_channels(handle)
    buffer = (ctypes.c_uint8 * (stride * height)).from_address(lib.gdk_pixbuf_read_pixels(handle))
    rows = np.frombuffer(buffer, dtype=np.uint8).reshape(height, stride)
    return rows[:, :width * channels].reshape(height, width, channels), buffer, stride


def _write(handle, path):
    lib, glib, _ = _pixbuf()
    error = ctypes.c_void_p()
    if not lib.gdk_pixbuf_savev(handle, os.fsencode(str(path)), b"png", None, None, ctypes.byref(error)):
        raise ScreenError("NON_RETRYABLE", "The capture could not be written: " + _glib_message(lib, glib, error))
    os.chmod(path, 0o600)


def content(pixels):
    """How much is actually in the frame. A uniform frame is a failed capture.

    Sampled every 7th row and column for the distinct-colour count, because the
    question is whether anything varies, and 42k samples answer it in 2 ms.
    """
    visible = pixels[:, :, :3]
    deviation = float(visible.std())
    distinct = int(len(np.unique(visible[::7, ::7].reshape(-1, 3), axis=0)))
    return {"mean_intensity": round(float(visible.mean()), 2), "intensity_deviation": round(deviation, 2),
            "distinct_colours_sampled": distinct,
            # A screen that is genuinely one flat colour is indistinguishable
            # from a compositor that painted nothing, and neither is an answer.
            "uniform": distinct <= 1 or deviation < 0.5}


# ── geometry ────────────────────────────────────────────────────────────────

def _call(address, method, signature=None, body=None, timeout=8.0):
    with open_dbus_connection(bus="SESSION") as connection:
        reply = connection.send_and_get_reply(new_method_call(address, method, signature, body), timeout=timeout)
    if reply.header.message_type is MessageType.error:
        name = reply.header.fields.get(HeaderFields.error_name, "unknown error")
        raise ScreenError("CAPABILITY_UNAVAILABLE", "%s.%s refused: %s" % (address.bus_name, method, name))
    return reply.body


def monitors():
    """Mutter's own logical-monitor state: origin, scale and device mode.

    A window rectangle is in logical pixels and a screenshot is in device
    pixels, so cropping needs the ratio between them. Inferring it from work
    areas was the alternative and it is wrong whenever a dock sits on the bottom
    edge; Mutter simply knows.
    """
    serial, physical, logical, _properties = _call(DISPLAY_CONFIG, "GetCurrentState")
    modes = {}
    for connectors, available, _props in physical:
        current = next((mode for mode in available if mode[6].get("is-current")), None)
        if current:
            modes[connectors[0]] = (int(current[1]), int(current[2]))
    found = []
    for x, y, scale, transform, primary, attached, _props in logical:
        connector = attached[0][0] if attached else ""
        if connector not in modes:
            raise ScreenError("CAPABILITY_UNAVAILABLE", "Mutter reported no current mode for " + (connector or "a monitor"))
        if transform:
            # A rotated monitor swaps the axes between logical and device space.
            raise ScreenError("CAPABILITY_UNAVAILABLE", "Monitor %s is rotated; ARIES will not guess the "
                              "pixel mapping for a rotated frame" % connector)
        device_width, device_height = modes[connector]
        found.append({"connector": connector, "x": int(x), "y": int(y), "scale": float(scale), "primary": bool(primary),
                      "device_width": device_width, "device_height": device_height,
                      "logical_width": round(device_width / float(scale)),
                      "logical_height": round(device_height / float(scale))})
    if not found:
        raise ScreenError("CAPABILITY_UNAVAILABLE", "Mutter reported no logical monitors")
    return {"serial": int(serial), "monitors": found}


def _extent(state):
    found = state["monitors"]
    return (max(m["x"] + m["logical_width"] for m in found), max(m["y"] + m["logical_height"] for m in found))


def _mapping(state, width, height):
    """Logical-to-device scale for this frame, confirmed against the frame itself.

    Two layouts are supported and the rest are refused rather than approximated:
    one logical monitor at any scale, and several at scale 1.0 where the mapping
    is the identity. A mixed-scale multi-monitor stage packs each monitor at its
    own ratio, and one number cannot describe that.
    """
    found = state["monitors"]
    scales = {monitor["scale"] for monitor in found}
    if len(found) > 1 and scales != {1.0}:
        raise ScreenError("CAPABILITY_UNAVAILABLE", "This session has %d monitors at scales %s; ARIES cannot "
                          "place a window rectangle in a mixed-scale frame without guessing"
                          % (len(found), sorted(scales)))
    scale = found[0]["scale"] if len(found) == 1 else 1.0
    extent = _extent(state)
    expected = (round(extent[0] * scale), round(extent[1] * scale))
    if (width, height) != expected:
        # The captured frame is not the desktop Mutter just described, so any
        # rectangle computed from that description lands in the wrong place.
        raise ScreenError("TRANSIENT", "The captured frame is %dx%d but this display layout implies %dx%d; "
                          "the layout changed during the capture" % (width, height, *expected))
    return {"scale": scale, "logical_width": extent[0], "logical_height": extent[1], "monitors": found,
            "layout": "single monitor" if len(found) == 1 else "%d monitors, all unscaled" % len(found)}


def _window(window_id):
    windows, why, _shell = desktop.read_windows()
    if windows is None:
        raise ScreenError("CAPABILITY_UNAVAILABLE", "A window capture needs the desktop window list, and " + why)
    matches = [w for w in windows if w.id == window_id]
    if not matches:
        raise ScreenError("TARGET_NOT_FOUND", "No window is observed with ID " + window_id)
    if len(matches) > 1:
        raise ScreenError("AMBIGUOUS", "More than one observed window claims ID " + window_id)
    window = matches[0]
    if window.minimised:
        raise ScreenError("TARGET_NOT_FOUND", "That window is minimised, so it occupies no pixels on screen")
    if not window.geometry:
        raise ScreenError("CAPABILITY_UNAVAILABLE", "The desktop bridge reported no geometry for that window, "
                          "so the region it occupies is unknown")
    return window


def _placement(window, state):
    """Refuse a target that is nowhere on the desktop BEFORE anything is captured.

    Whether a window is on screen at all is a fact about the layout, not about
    the picture, and finding it out first means a bad target never costs a
    photograph of somebody's screen.
    """
    geometry, extent = window.geometry, _extent(state)
    if (geometry["x"] >= extent[0] or geometry["y"] >= extent[1]
            or geometry["x"] + geometry["width"] <= 0 or geometry["y"] + geometry["height"] <= 0):
        raise ScreenError("TARGET_NOT_FOUND", "That window sits outside the %dx%d desktop, so no part of it is "
                          "on screen" % extent)


def _region(window, mapping, width, height):
    """The on-screen rectangle of a window, in device pixels, clipped to the frame."""
    scale, geometry = mapping["scale"], window.geometry
    left, top = round(geometry["x"] * scale), round(geometry["y"] * scale)
    right, bottom = left + round(geometry["width"] * scale), top + round(geometry["height"] * scale)
    clipped = (max(0, left), max(0, top), min(width, right), min(height, bottom))
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise ScreenError("TARGET_NOT_FOUND", "That window is entirely outside the captured frame")
    return {"x": clipped[0], "y": clipped[1], "width": clipped[2] - clipped[0], "height": clipped[3] - clipped[1],
            "logical": dict(geometry), "scale": scale,
            "clipped": clipped != (left, top, right, bottom),
            # The compositor is not asked for this window's own buffer — it is
            # not on the allow-list that could ask. This is the screen area the
            # window occupies, so anything drawn on top of it is in the picture.
            "covers": "screen area occupied by the window, including anything drawn over it"}


# ── capture ─────────────────────────────────────────────────────────────────

def _portal(timeout=20.0):
    """One non-interactive screenshot through xdg-desktop-portal."""
    token = "aries" + secrets.token_hex(8)
    with open_dbus_connection(bus="SESSION") as connection:
        # The Request path is derived rather than returned, and its Response can
        # arrive before the method reply does, so the match and the filter queue
        # are both in place before the call is sent.
        handle = "/org/freedesktop/portal/desktop/request/%s/%s" % (connection.unique_name[1:].replace(".", "_"), token)
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response", path=handle)
        connection.send_and_get_reply(message_bus.AddMatch(rule), timeout=timeout)
        with connection.filter(rule) as queue:
            reply = connection.send_and_get_reply(new_method_call(
                SCREENSHOT, "Screenshot", "sa{sv}",
                ("", {"handle_token": ("s", token), "interactive": ("b", False), "modal": ("b", False)})),
                timeout=timeout)
            if reply.header.message_type is MessageType.error:
                name = reply.header.fields.get(HeaderFields.error_name, "unknown error")
                raise ScreenError("CAPABILITY_UNAVAILABLE", "The desktop screenshot portal refused: " + str(name))
            try:
                response = connection.recv_until_filtered(queue, timeout=timeout)
            except TimeoutError as exc:
                raise ScreenError("TRANSIENT", "The desktop screenshot portal did not answer within %gs" % timeout) from exc
    code, results = response.body
    if code:
        raise ScreenError("PERMISSION_REQUIRED" if code == 1 else "CAPABILITY_UNAVAILABLE",
                          "The desktop screenshot portal returned response %d (%s)"
                          % (code, "cancelled or not permitted" if code == 1 else "ended without a result"))
    uri = (results.get("uri") or ("s", ""))[1]
    if not uri.startswith("file://"):
        raise ScreenError("CAPABILITY_UNAVAILABLE", "The portal returned no local file for the capture")
    from urllib.parse import unquote, urlsplit
    return Path(unquote(urlsplit(uri).path))


def prune(keep_files=KEEP_FILES, keep_seconds=KEEP_SECONDS):
    """Drop stale captures. Called before every capture, not by a timer, so the
    bound holds even if nothing else about ARIES is running."""
    if not CAPTURES.is_dir():
        return {"removed": 0, "kept": 0}
    frames = sorted(CAPTURES.glob("screen-*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    cutoff = time.time() - keep_seconds
    removed = 0
    for index, frame in enumerate(frames):
        if index >= keep_files or frame.stat().st_mtime < cutoff:
            try:
                frame.unlink()
                removed += 1
            except OSError:
                continue
    return {"removed": removed, "kept": len(frames) - removed}


def _destination():
    CAPTURES.mkdir(parents=True, exist_ok=True)
    CAPTURES.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return CAPTURES / ("screen-%s-%s.png" % (stamp, secrets.token_hex(4)))


def capture(window_id=None):
    """A screenshot that is proved to contain something, or an error.

    Nothing here trusts a return code. The portal answers success on a blanked
    screen, so the screensaver is asked first and the decoded pixels are
    measured afterwards; a uniform frame is deleted and raised, never returned.
    """
    window = layout = None
    if window_id is not None:
        # The target is resolved first: an unobservable window is a refusal that
        # owes nobody a screenshot, and it is true whatever the screen is doing.
        window = _window(window_id)
        layout = monitors()
        _placement(window, layout)
    if desktop.session_locked() is True:
        raise ScreenError("TRANSIENT", "The screen is blanked or locked, so a capture would be a black "
                          "rectangle. GNOME blanks this session after its idle delay; unblank it and ask again")
    started = time.monotonic()
    prune()
    source = _portal()
    capture_seconds = time.monotonic() - started
    destination = _destination()
    frame = region = None
    try:
        if window_id is None:
            # Move the portal's own file rather than re-encoding it: the bytes
            # the compositor produced are the most faithful record there is, and
            # ~/Pictures stops holding a copy of the screen the moment it lands.
            try:
                os.replace(source, destination)
            except OSError:
                destination.write_bytes(Path(source).read_bytes())   # ~/Pictures on another filesystem
                Path(source).unlink(missing_ok=True)
            os.chmod(destination, 0o600)
            source = None
            frame = _load(destination)
        else:
            frame = _load(source)
            lib = _pixbuf()[0]
            width, height = lib.gdk_pixbuf_get_width(frame), lib.gdk_pixbuf_get_height(frame)
            region = _region(window, _mapping(layout, width, height), width, height)
            cropped = lib.gdk_pixbuf_new_subpixbuf(frame, region["x"], region["y"], region["width"], region["height"])
            if not cropped:
                raise ScreenError("NON_RETRYABLE", "The window region could not be cut out of the frame")
            _release(frame)
            frame = cropped
            _write(frame, destination)
        pixels, _buffer, _stride = _view(frame)
        measured = content(pixels)
        result = {"path": str(destination), "width": int(pixels.shape[1]), "height": int(pixels.shape[0]),
                  "channels": int(pixels.shape[2]), "bytes": destination.stat().st_size,
                  "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                  "scope": "window" if window_id else "whole screen",
                  "capture_seconds": round(capture_seconds, 3),
                  "elapsed_seconds": round(time.monotonic() - started, 3),
                  "source": "org.freedesktop.portal.Screenshot (interactive=false)",
                  "retention": "at most %d frames, %d minutes, mode 0600 under %s"
                               % (KEEP_FILES, KEEP_SECONDS // 60, CAPTURES),
                  "content": measured, "observed_at": now()}
        if region:
            result["region"] = region
        if measured["uniform"]:
            destination.unlink(missing_ok=True)
            raise ScreenError("TRANSIENT", "The capture is a uniform %dx%d rectangle (mean %.2f, deviation %.2f, "
                              "%d distinct colour) — the compositor painted nothing, so it is not a screenshot"
                              % (result["width"], result["height"], measured["mean_intensity"],
                                 measured["intensity_deviation"], measured["distinct_colours_sampled"]))
        return result
    finally:
        _release(frame)
        if source is not None:
            # The portal's copy in ~/Pictures is never left behind, on any path.
            try:
                Path(source).unlink(missing_ok=True)
            except OSError:
                pass


def inspect(path):
    """Re-read a stored capture from disk. The verifiers' independent look."""
    path = Path(path)
    if CAPTURES.resolve() != path.resolve().parent:
        raise ScreenError("NON_RETRYABLE", "Only ARIES's own captures under %s can be inspected" % CAPTURES)
    data = path.read_bytes()
    frame = _load(path)
    try:
        pixels, _buffer, _stride = _view(frame)
        return {"path": str(path), "width": int(pixels.shape[1]), "height": int(pixels.shape[0]),
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "content": content(pixels), "observed_at": now()}
    finally:
        _release(frame)


# ── text ────────────────────────────────────────────────────────────────────

def _tesseract(language):
    """The tesseract C API over ctypes, plus the language data it needs.

    Raises with the exact command to fix it rather than returning nothing: OCR
    that silently produces an empty string is worse than no OCR at all, because
    an empty screen and an unreadable one look identical to the caller.
    """
    global _tesseract_library
    if language not in LANGUAGES:
        raise ScreenError("NON_RETRYABLE", "Supported OCR languages are " + ", ".join(LANGUAGES))
    wanted = language.split("+")
    with _lock:
        if _tesseract_library is None:
            directories = (*LIBRARY_DIRS, *sorted(Path("/snap").glob(SNAP_LIBRARY_DIRS)))
            found = next((d for d in directories if (d / "libtesseract.so.5").is_file()), None)
            if found is None:
                raise ScreenError("CAPABILITY_UNAVAILABLE",
                                  "libtesseract.so.5 is not on this machine, so ARIES cannot read the screen as "
                                  "text. `sudo apt install tesseract-ocr tesseract-ocr-mkd` installs it; the "
                                  "capture itself works without it.")
            for name in LEPTONICA:
                if (found / name).is_file():
                    ctypes.CDLL(str(found / name), mode=ctypes.RTLD_GLOBAL)
                    break
            try:
                lib = ctypes.CDLL(str(found / "libtesseract.so.5"), mode=ctypes.RTLD_GLOBAL)
            except OSError as exc:
                raise ScreenError("CAPABILITY_UNAVAILABLE", "libtesseract.so.5 was found at %s but could not be "
                                  "loaded: %s" % (found, exc)) from exc
            lib.TessVersion.restype = ctypes.c_char_p
            lib.TessBaseAPICreate.restype = ctypes.c_void_p
            lib.TessBaseAPIInit3.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
            lib.TessBaseAPIInit3.restype = ctypes.c_int
            lib.TessBaseAPISetImage.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 4
            lib.TessBaseAPISetSourceResolution.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.TessBaseAPIGetUTF8Text.argtypes = [ctypes.c_void_p]
            lib.TessBaseAPIGetUTF8Text.restype = ctypes.c_void_p
            lib.TessBaseAPIMeanTextConf.argtypes = [ctypes.c_void_p]
            lib.TessBaseAPIMeanTextConf.restype = ctypes.c_int
            for name in ("TessBaseAPIEnd", "TessBaseAPIDelete", "TessDeleteText"):
                getattr(lib, name).argtypes = [ctypes.c_void_p]
            _tesseract_library = (lib, found, lib.TessVersion().decode("utf-8", "replace"))
    lib, found, version = _tesseract_library
    data = next((d for d in TESSDATA if all((d / (part + ".traineddata")).is_file() for part in wanted)), None)
    if data is None:
        raise ScreenError("CAPABILITY_UNAVAILABLE",
                          "tesseract %s is loadable from %s but has no data for %s. Without root, from the "
                          "project root: %s (5.7 MB, tessdata_fast). With root: `sudo apt install %s`."
                          % (version, found, "+".join(wanted), FETCH_TESSDATA,
                             " ".join("tesseract-ocr-" + p for p in wanted)))
    return lib, data, version


def _text(pixels, buffer, stride, language, ppi=96):
    lib, data, version = _tesseract(language)
    started = time.monotonic()
    height, width, channels = pixels.shape
    api = lib.TessBaseAPICreate()
    if lib.TessBaseAPIInit3(api, os.fsencode(str(data)), language.encode()):
        # Nothing but Delete is safe on a handle that failed Init3; asking it for
        # text segfaults the process, with no Python traceback to show for it.
        lib.TessBaseAPIDelete(api)
        raise ScreenError("CAPABILITY_UNAVAILABLE", "tesseract could not load language data for " + language)
    try:
        lib.TessBaseAPISetImage(api, buffer, width, height, channels, stride)
        # After SetImage, never before: tesseract rejects the other order.
        lib.TessBaseAPISetSourceResolution(api, ppi)
        pointer = lib.TessBaseAPIGetUTF8Text(api)
        if not pointer:
            raise ScreenError("NON_RETRYABLE", "tesseract returned no result for this frame")
        try:
            raw = ctypes.cast(pointer, ctypes.c_char_p).value.decode("utf-8", "replace")
        finally:
            lib.TessDeleteText(pointer)
        confidence = lib.TessBaseAPIMeanTextConf(api)
    finally:
        lib.TessBaseAPIEnd(api)
        lib.TessBaseAPIDelete(api)
    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    text = "\n".join(lines)
    return {"text": text[:20000], "truncated": len(text) > 20000, "characters": len(text), "lines": len(lines),
            "words": len(text.split()), "mean_confidence": int(confidence), "language": language,
            "cyrillic_characters": sum(1 for ch in text if "Ѐ" <= ch <= "ӿ"),
            "engine": "tesseract " + version, "ocr_seconds": round(time.monotonic() - started, 3)}


def read(window_id=None, language="eng+mkd"):
    """Capture, then read. The OCR stack is checked first, on purpose: there is
    no reason to write a picture of somebody's screen that nothing can read."""
    _tesseract(language)
    shot = capture(window_id)
    # Re-open the stored file rather than keeping the frame in memory, so the
    # text is provably the text of the artifact the result points at.
    frame = _load(shot["path"])
    try:
        pixels, buffer, stride = _view(frame)
        recognised = _text(pixels, buffer, stride, language)
    finally:
        _release(frame)
    return {**recognised, "capture": shot, "elapsed_seconds": round(shot["elapsed_seconds"] + recognised["ocr_seconds"], 3),
            "observed_at": now()}


def available():
    """What actually works here, each answer measured rather than assumed."""
    state = {"portal": None, "decoder": None, "ocr": None, "screen_blanked": desktop.session_locked(),
             "captures": str(CAPTURES), "observed_at": now()}
    try:
        _pixbuf()
        state["decoder"] = "gdk-pixbuf"
    except ScreenError as exc:
        state["decoder"] = "unavailable: " + str(exc)
    try:
        state["portal"] = "org.freedesktop.portal.Screenshot" if _call(
            DBusAddress("/org/freedesktop/portal/desktop", bus_name="org.freedesktop.portal.Desktop",
                        interface="org.freedesktop.DBus.Peer"), "Ping") == () else "unexpected portal reply"
    except ScreenError as exc:
        state["portal"] = "unavailable: " + str(exc)
    try:
        _lib, data, version = _tesseract("eng+mkd")
        state["ocr"] = "tesseract %s, data %s" % (version, data)
    except ScreenError as exc:
        state["ocr"] = "unavailable: " + str(exc)
    return state


# ── capabilities ────────────────────────────────────────────────────────────

async def capture_screen(args, ctx):
    return await asyncio.to_thread(capture, args.get("window_id"))


async def read_screen(args, ctx):
    return await asyncio.to_thread(read, args.get("window_id"), args.get("language", "eng+mkd"))


def _titles_found(text):
    """Cross-check: do the window titles Mutter reports appear in the text?

    Independent of the capture path, which is the point — it is the one check
    here that a blank-frame guard and a byte count cannot fake between them. It
    is evidence and not a verdict, because a title can be elided in its own
    title bar or hidden behind another window.
    """
    windows, why, _shell = desktop.read_windows()
    if windows is None:
        return {"checked": False, "reason": why}
    words = {word for w in windows for word in w.title.split() if len(word) >= 4}
    if not words:
        return {"checked": False, "reason": "no observed window title has a word long enough to look for"}
    lowered = text.casefold()
    seen = sorted(word for word in words if word.casefold() in lowered)
    return {"checked": True, "title_words": len(words), "found": len(seen), "examples": seen[:8]}


async def _reinspect(path):
    """A capture that retention has already reclaimed is unverifiable, not verified."""
    try:
        return await asyncio.to_thread(inspect, path)
    except (OSError, ScreenError) as exc:
        return {"path": str(path), "content": {"uniform": True}, "sha256": "", "width": 0, "height": 0,
                "bytes": 0, "unavailable": str(exc), "observed_at": now()}


async def verify_capture(args, result, ctx):
    fresh = await _reinspect(result["path"])
    met = (not fresh["content"]["uniform"] and fresh["sha256"] == result["sha256"]
           and (fresh["width"], fresh["height"], fresh["bytes"]) == (result["width"], result["height"], result["bytes"]))
    return {"met": met, "type": "screen_capture",
            "data": {**fresh, "scope": result.get("scope"), "region": result.get("region"),
                     "method": "the stored PNG re-read and re-decoded, independently of the capture"}}


async def verify_read(args, result, ctx):
    fresh = await _reinspect(result["capture"]["path"])
    titles = await asyncio.to_thread(_titles_found, result["text"])
    # Confidence is reported by tesseract and is 0 or below when it recognised
    # nothing; measured 72-78 on real desktop frames here.
    met = bool(not fresh["content"]["uniform"] and result["characters"] and result["mean_confidence"] > 0)
    return {"met": met, "type": "screen_text",
            "data": {**fresh, "characters": result["characters"], "words": result["words"],
                     "mean_confidence": result["mean_confidence"], "language": result["language"],
                     "window_titles": titles,
                     "method": "the stored PNG re-read and re-decoded; recovered text cross-checked "
                               "against observed window titles where the desktop bridge is available"}}


def register(registry):
    for name in ("capture", "screenshot"):
        registry.register(Capability(
            "screen." + name,
            "See the screen: capture the whole screen, or the area one observed window ID occupies, to an "
            "ARIES-owned PNG. A blanked screen or a uniform frame is an error, never a result.",
            CaptureInput, capture_screen, verify_capture, risk_level="medium", timeout_seconds=30))
    registry.register(Capability(
        "screen.read",
        "Read what is on the screen: capture it and recover its text with local OCR in Macedonian and English. "
        "Use this to answer questions about what is displayed; refuses with instructions if OCR data is missing.",
        ReadInput, read_screen, verify_read, risk_level="medium", timeout_seconds=60))
