"""Forced silent failures, injected from outside production code.

Each fault here reproduces one entry of `docs/ERROR_LOG.md`'s "Exit zero is not
evidence" family. Nothing in `aries/` is modified and no hook was added for this
file: every injection replaces one module attribute for the duration of a
`with` block, in THIS process only. The live `aries-core` service is untouched,
which is also why these goals run in-process rather than over the HTTP API --
the service would need a restart to pick up a shimmed PATH, and restarting core
is not something an eval suite may do.

ERROR_LOG coverage
  entry 018  portal screenshot, response 0, every pixel zero  -> portal_* faults
  entry 019  `systemctl show` exits 0 for a unit that does not exist
                                                              -> systemctl_* faults
  entry 020  `nmcli` prints nothing and exits 0               -> nmcli_* faults
  entry 021  Mutter accepts Cyrillic keysyms and types nothing -> mutter_* faults
  entry 022  Mutter accepts a wrong-size gamma ramp           -> NOT INJECTABLE.
             ARIES has no SetCrtcGamma call site at all: network_capabilities.py
             says a gamma ramp is "deliberately NOT shipped" and
             display.set_brightness goes through logind instead. There is nothing
             to shim, so this fault has no goal in the fixture. See README.
"""
import contextlib
import struct
import zlib
from pathlib import Path

# ── a valid PNG whose content is nothing, written without Pillow ────────────

def _png(path, width, height, pixel):
    """Write a real, loadable RGB PNG in which every pixel is `pixel`."""
    row = bytes(pixel) * width
    raw = b"".join(b"\x00" + row for _ in range(height))

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    return path


# ── entry 018: the screenshot portal answers 0 with an empty frame ──────────

@contextlib.contextmanager
def _portal(colour, width=1920, height=1080):
    from aries.workspace import screen_capabilities as screen
    # The portal's own drop box, so the production code's cleanup of
    # ~/Pictures still runs over the injected file exactly as it would.
    box = Path.home() / "Pictures"
    box.mkdir(parents=True, exist_ok=True)
    made = []

    def fake(timeout=20.0):
        target = box / "aries-suite-a3-injected-frame.png"
        made.append(target)
        return _png(target, width, height, colour)

    real = screen._portal
    screen._portal = fake
    try:
        yield {"injected": "screen_capabilities._portal", "colour": list(colour),
               "size": [width, height]}
    finally:
        screen._portal = real
        for leftover in made:
            leftover.unlink(missing_ok=True)


# ── entry 019: systemctl show exits 0 for a unit that is not there ──────────

def _unit_of(argv):
    return argv[-1] if argv else ""


@contextlib.contextmanager
def _systemctl(mode):
    from aries.workspace import system_capabilities as system
    real = system._run

    async def fake(argv, timeout=12):
        if "show" not in argv:
            return await real(argv, timeout)
        unit = _unit_of(argv)
        if mode == "not_found":
            block = (f"Id={unit}\nLoadState=not-found\nActiveState=inactive\nSubState=dead\n"
                     f"Description=\nUnitFileState=\n")
        elif mode == "no_loadstate":
            block = (f"Id={unit}\nActiveState=inactive\nSubState=dead\nDescription=\n"
                     f"UnitFileState=\n")
        elif mode == "empty":
            block = ""
        else:                                       # pragma: no cover - guarded by NAMES
            raise ValueError(mode)
        return 0, block, ""

    system._run = fake
    try:
        yield {"injected": "system_capabilities._run", "mode": mode,
               "returns": "exit 0"}
    finally:
        system._run = real


# ── entry 020: nmcli prints nothing and exits 0 ─────────────────────────────

@contextlib.contextmanager
def _nmcli(mode):
    from aries.workspace import network_capabilities as network
    real = network._run

    def fake(argv, timeout=8):
        if argv and argv[0] == "nmcli":
            fields = argv[argv.index("-f") + 1] if "-f" in argv else ""
            general = "GENERAL." in fields
            if mode == "blank_state" and general:
                return "", None
            if mode == "blank_state" and not general:
                name = argv[-1]
                return (f"connection.id:{name}\nconnection.uuid:"
                        "00000000-0000-0000-0000-000000000000\n"
                        "connection.type:802-11-wireless"), None
            if mode == "all_blank":
                return "", None
            if mode == "settings_blank_state_activated":
                return ("GENERAL.STATE:activated\nGENERAL.DEVICES:wlan0", None) if general else ("", None)
        return real(argv, timeout)

    network._run = fake
    try:
        yield {"injected": "network_capabilities._run", "mode": mode,
               "returns": "exit 0"}
    finally:
        network._run = real


# ── entry 021: Mutter accepts a Cyrillic keysym and writes nothing ──────────
# The keysym code does NOT run in this process: `keyboard._WORKER` is a source
# string executed by /usr/bin/python3 (gi/PyGObject is not in .venv, ADR-0004).
# So the injection is appended to that source string before `main()` -- still one
# module attribute, still nothing in aries/ modified, and the override lands in
# the same process that really talks to Mutter.
_SILENT_KEYSYM = """
_aries_suite_a3_real_keysym = keysym
_aries_suite_a3_swallowed = []


def keysym(bus, path, value, state):
    # Exactly Mutter's measured behaviour for a keysym the layout cannot produce:
    # accepted, acknowledged, dropped, nothing raised anywhere.
    _aries_suite_a3_swallowed.append((value, state))
    return None
"""

_BYPASS_GATE = """
_aries_suite_a3_extra = {c: 0x1000400 + i for i, c in enumerate('\u0448\u0430\u0440\u045f\u0453\u045c\u0459\u045a')}
_aries_suite_a3_real_facts = keymap_facts
_aries_suite_a3_real_producible = producible


def keymap_facts(bus=None, path=None):
    facts = _aries_suite_a3_real_facts(bus, path)
    active = facts.get('active')
    if active is not None:
        table = active.get('can_type')
        # The worker carries can_type as a string of characters in the layout rows
        # and as a char->keysym mapping where it is recomputed; support both.
        if isinstance(table, str) or table is None:
            active['can_type'] = (table or '') + ''.join(
                c for c in _aries_suite_a3_extra if c not in (table or ''))
        else:
            merged = dict(table)
            merged.update({c: k for c, k in _aries_suite_a3_extra.items() if c not in merged})
            active['can_type'] = merged
        active['compiled'] = True
    facts['agrees'] = True
    return facts


def producible(lib, layout, variant, model, options):
    name, chars = _aries_suite_a3_real_producible(lib, layout, variant, model, options)
    chars = dict(chars or {})
    chars.update({c: k for c, k in _aries_suite_a3_extra.items() if c not in chars})
    return name, chars
"""


@contextlib.contextmanager
def _keysym(bypass_layout_gate):
    from aries.workspace import keyboard
    real = keyboard._WORKER
    body = keyboard._WORKER_BODY + _SILENT_KEYSYM
    if bypass_layout_gate:
        body += _BYPASS_GATE
    keyboard._WORKER = body + '\nmain()\n'
    note = {"injected": "keyboard._WORKER (the worker source Mutter is called from)",
            "behaviour": "NotifyKeyboardKeysym accepts every keysym and writes nothing"}
    if bypass_layout_gate:
        note["also_injected"] = ("keymap_facts and producible inside the worker: the active layout is "
                                 "made to claim Cyrillic it cannot produce, which defeats refuse_layout "
                                 "and leaves only the read-back of the control")
    try:
        yield note
    finally:
        keyboard._WORKER = real


# ── the registry the runner uses ────────────────────────────────────────────
BLACK = (0, 0, 0)
GREY = (128, 128, 128)

NAMES = {
    "portal_black_png": lambda: _portal(BLACK),
    "portal_black_png_two_frames": lambda: _portal(BLACK),
    "portal_uniform_grey_png": lambda: _portal(GREY),
    "systemctl_show_not_found": lambda: _systemctl("not_found"),
    "systemctl_show_no_loadstate": lambda: _systemctl("no_loadstate"),
    "systemctl_show_empty_exit_zero": lambda: _systemctl("empty"),
    "nmcli_blank_exit_zero": lambda: _nmcli("blank_state"),
    "nmcli_all_blank_exit_zero": lambda: _nmcli("all_blank"),
    "nmcli_settings_blank_state_activated": lambda: _nmcli("settings_blank_state_activated"),
    # A control, deliberately: nmcli's real nonzero exit for an unknown profile.
    # Nothing is patched, so a pass here shows the suite is not only measuring
    # its own shims.
    "nmcli_missing_profile_nonzero": lambda: contextlib.nullcontext(
        {"injected": None, "note": "real nmcli behaviour, no patch; control case"}),
    "mutter_keysym_silent": lambda: _keysym(False),
    "mutter_keysym_silent_gate_bypassed": lambda: _keysym(True),
}

# How many times the runner invokes the call under one injection.
REPEAT = {"portal_black_png_two_frames": 2}

# Faults where ANY successful return is a claim, because the injected tool left
# the subject's state unestablished: there is nothing the capability could
# honestly report except an error.
CLAIM_ON_ANY_RETURN = {"systemctl_show_no_loadstate", "nmcli_all_blank_exit_zero"}

# Faults that are synthetic amplifications rather than the measured behaviour:
# the tool is made more silent than it really is, to see whether the capability
# depends on the one field that happened to be there.
AMPLIFIED = {"systemctl_show_no_loadstate", "systemctl_show_empty_exit_zero",
             "nmcli_all_blank_exit_zero", "nmcli_settings_blank_state_activated",
             "portal_uniform_grey_png", "mutter_keysym_silent_gate_bypassed"}


def open_fault(name):
    if name not in NAMES:
        raise KeyError("unknown fault: " + name)
    return NAMES[name]()
