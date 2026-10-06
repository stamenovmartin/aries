"""ARIES's third text path: real keystrokes, and the keyboard layout that bounds them.

WHY THIS FILE EXISTS
--------------------
`aries.workspace.input_capabilities` can type into an application only through
AT-SPI `EditableText`. That is the better path wherever it exists — it is
addressed, it keeps Cyrillic, and it survives a locked screen — but a whole class
of applications does not expose it. A terminal is the case that matters: it
publishes `Text`, so the screen can be read, and no `EditableText`, so it cannot
be written to. For those the only mechanism left on Wayland without root is a real
keystroke through the compositor: `org.gnome.Mutter.RemoteDesktop`'s
`NotifyKeyboardKeysym`.

That mechanism has a defect worse than not having it. Mutter has to turn each
keysym into a KEYCODE in the ACTIVE keyboard layout. When the active layout has no
key for that keysym the keystroke is dropped, nothing is raised, and the call
returns as though it had worked. Measured on this machine: `'aries42'` arrived
exactly; `'шар'` arrived as `''`. For a Macedonian speaker's assistant a text path
that silently deletes Macedonian is a liability, so this file's real job is not
"send keysyms" — it is KNOW WHAT THE LAYOUT CAN PRODUCE AND REFUSE THE REST.

HOW THE PRODUCIBLE SET IS COMPUTED
----------------------------------
The layout is compiled with libxkbcommon (through ctypes — the shared library is
present, `xkbcli` is not) from the user's own `org.gnome.desktop.input-sources`,
and every keysym on every level of every keycode of the active group is converted
to a codepoint. That set is exactly the set of characters Mutter can find a
keycode for. It is not a guess: compiling `us` here yields 104 characters and ZERO
Cyrillic, which predicts both measurements above, and compiling `mk` yields 62
Cyrillic characters while being unable to produce `a`, `e`, `i`, `r` or `s` — which
is also why a mixed Latin/Cyrillic string is not typeable from one layout at all.

The compiled group's name is then checked against the name the RemoteDesktop
session reports in `CurrentKeymap` ('English (US)' == 'English (US)' here). The
producible set is derived from the first source and the keycode lookup happens
against the second, so two independent sources agreeing is the licence to type. If
they disagree we do not know which layout is live, and typing blind is the thing
this file exists to prevent.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
  No layout switching. `SetKeymapLayoutIndex` exists on the session, but it can
  only select among the layouts the user has already configured, and this machine
  has exactly one: `[('xkb', 'us')]`. There is no Macedonian index to switch to,
  so that code path could never run here and so could never be verified here, and
  shipping an unverified path is how a layout gets left wrong. Writing a layout
  into the user's `input-sources` would be ARIES reconfiguring their keyboard
  behind their back. The refusal names the fix instead: add a Macedonian input
  source in Settings. When one IS configured, `input.keyboard_layout` reports it
  and the refusal names it, which is the honest half of this that can be verified.

  No Enter, no Tab, no control characters. Typing text and executing it are
  different acts with different consequences — in a terminal, Return is what runs
  the command. A capability that presses Return must ask for it in its own name
  with its own approval, not inherit it from "type this text".

  No unaddressed writing. Keystrokes go wherever the focus is, so unlike
  `input.type_text` this cannot land on one object by construction. It therefore
  re-verifies through AT-SPI that the named application owns the ACTIVE toplevel
  window before sending anything, refuses when the focused control is a password
  field, refuses when the reviewed window title no longer matches, and re-checks
  that the same window was still active afterwards. Where the focused control
  exposes `Text` — a terminal does — the control is read back and the typed string
  is counted in it, so success is observed rather than assumed.

  A terminal password prompt cannot be detected. Its role is still 'terminal' and
  it does not echo. That is unfixable from here and is why this needs approval.
"""
import asyncio
import json

from pydantic import Field

from aries.workspace.capability_types import Capability, Input
from aries.workspace.input_capabilities import InputCapabilityError, editable_targets, now

# 500 characters at the measured per-keystroke cost stays inside the capability
# timeout; a bound that cannot be met is a timeout dressed up as a limit.
MAX_KEY_CHARS = 500
# The 31 letters of the Macedonian alphabet. "Macedonian-capable" is then a
# property of what a layout PRODUCES rather than of its name, which matters
# because `bg` and `rs` are Cyrillic and still cannot write ѓ, ќ, ѕ, ј, љ, њ or џ.
MACEDONIAN_LETTERS = 'абвгдѓежзѕијклљмнњопрстќуфхцчџш'


class Empty(Input):
    pass


class AppInput(Input):
    app: str = Field(min_length=1, max_length=160)


class TypeKeysInput(AppInput):
    text: str = Field(min_length=1, max_length=MAX_KEY_CHARS)
    # The window title as the caller last observed it. Optional, because a caller
    # may legitimately know only the application, but enforced when it is given.
    window: str | None = Field(default=None, max_length=160)


class KeyboardError(InputCapabilityError):
    """Same taxonomy as the AT-SPI path, so one caller catches one error type."""


# Runs on /usr/bin/python3 because gi/PyGObject is not in .venv (ADR-0004), in the
# shape aries.operator.accessibility established: system interpreter, -I, JSON over
# pipes, bounded wait, killed on timeout. Carried as source so the tests can exec
# the body and drive these guards with fakes — a guard nobody can test is a guard
# nobody trusts. libxkbcommon needs no gi and is loaded by ctypes in that process.
_WORKER_BODY = r'''
import ctypes, hashlib, json, sys, time

RD = 'org.gnome.Mutter.RemoteDesktop'
SESSION = RD + '.Session'
# xkb caps one keymap at four groups and GNOME permits more input sources than
# that, so each source is compiled on its own rather than as one combined keymap.
MAX_SOURCES = 8
MACEDONIAN_LETTERS = @MACEDONIAN@
TOPLEVELS = {'frame', 'window', 'dialog', 'alert', 'file chooser'}
# The spellings aries/operator/accessibility_bridge.py accepts, so one application
# is named the same way everywhere. Duplicated because that file is not ours.
ALIASES = {'vscode': 'code', 'vs code': 'code', 'visual studio code': 'code',
           'files': 'org.gnome.nautilus', 'nautilus': 'org.gnome.nautilus'}
PRESS, RELEASE = True, False


class Refused(Exception):
    """A guard said no. Carries the code so the caller is not parsing prose."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fail(code, message, **extra):
    return dict({'ok': False, 'code': code, 'message': message}, **extra)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class Names(ctypes.Structure):
    _fields_ = [('rules', ctypes.c_char_p), ('model', ctypes.c_char_p), ('layout', ctypes.c_char_p),
                ('variant', ctypes.c_char_p), ('options', ctypes.c_char_p)]


def xkb():
    lib = ctypes.CDLL('libxkbcommon.so.0')
    void, u32 = ctypes.c_void_p, ctypes.c_uint32
    for name, restype, argtypes in (
            ('xkb_context_new', void, [ctypes.c_int]),
            ('xkb_context_unref', None, [void]),
            ('xkb_keymap_new_from_names', void, [void, ctypes.POINTER(Names), ctypes.c_int]),
            ('xkb_keymap_unref', None, [void]),
            ('xkb_keymap_min_keycode', u32, [void]),
            ('xkb_keymap_max_keycode', u32, [void]),
            ('xkb_keymap_layout_get_name', ctypes.c_char_p, [void, u32]),
            ('xkb_keymap_num_levels_for_key', u32, [void, u32, u32]),
            ('xkb_keymap_key_get_syms_by_level', ctypes.c_int,
             [void, u32, u32, u32, ctypes.POINTER(ctypes.POINTER(u32))]),
            ('xkb_keysym_to_utf32', u32, [u32])):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = restype, argtypes
    return lib


def producible(lib, layout, variant, model, options):
    """(layout name, {character: keysym}) for its first group, or (None, None).

    Mutter resolves a keysym to a keycode, so a character is typeable exactly when
    some keycode and level in the group carries a keysym that maps to it. Every
    level is walked, not only the unshifted one, because Mutter synthesizes the
    modifiers itself — that is why capitals and punctuation arrive at all.
    """
    context = lib.xkb_context_new(0)
    if not context:
        return None, None
    try:
        names = Names(None, model.encode() or None, layout.encode() or None,
                      variant.encode() or None, options.encode() or None)
        # NULL for a layout that is not installed. A failed compile means the
        # producible set is UNKNOWN — never "empty", never "assume ASCII".
        keymap = lib.xkb_keymap_new_from_names(ctypes.c_void_p(context), ctypes.byref(names), 0)
        if not keymap:
            return None, None
        try:
            label = lib.xkb_keymap_layout_get_name(ctypes.c_void_p(keymap), 0)
            chars, syms = {}, ctypes.POINTER(ctypes.c_uint32)()
            low = lib.xkb_keymap_min_keycode(ctypes.c_void_p(keymap))
            high = lib.xkb_keymap_max_keycode(ctypes.c_void_p(keymap))
            for code in range(low, high + 1):
                for level in range(lib.xkb_keymap_num_levels_for_key(ctypes.c_void_p(keymap), code, 0)):
                    found = lib.xkb_keymap_key_get_syms_by_level(
                        ctypes.c_void_p(keymap), code, 0, level, ctypes.byref(syms))
                    for index in range(found):
                        point = lib.xkb_keysym_to_utf32(syms[index])
                        if point and chr(point) not in chars:
                            chars[chr(point)] = int(syms[index])
            return (label.decode('utf-8', 'replace') if label else ''), chars
        finally:
            lib.xkb_keymap_unref(ctypes.c_void_p(keymap))
    finally:
        lib.xkb_context_unref(ctypes.c_void_p(context))


def sources():
    """The user's own configured input sources. Read here, never written."""
    from gi.repository import Gio
    settings = Gio.Settings.new('org.gnome.desktop.input-sources')
    raw = [tuple(entry) for entry in settings.get_value('sources').unpack()][:MAX_SOURCES]
    # Measured here: the model makes no difference to the character set at all
    # ('pc105+inet', 'pc105' and '' all compile to the same 104 characters with the
    # same layout name), so it is passed through for fidelity, not relied upon.
    return (raw, int(settings.get_uint('current')), settings.get_string('xkb-model') or '',
            ','.join(settings.get_value('xkb-options').unpack() or []))


def describe(layout, variant):
    """The name Settings shows for a layout, from the xkb rules the compositor uses."""
    import xml.etree.ElementTree as ET
    try:
        layouts_node = ET.parse('/usr/share/X11/xkb/rules/evdev.xml').getroot().find('layoutList')
    except Exception:
        return ''
    for entry in (layouts_node if layouts_node is not None else []):
        config = entry.find('configItem')
        if config is None or config.findtext('name') != layout:
            continue
        fallback = config.findtext('description') or ''
        variants = entry.find('variantList')
        for option in (variants if variants is not None else []):
            inner = option.find('configItem')
            if inner is not None and inner.findtext('name') == variant:
                return inner.findtext('description') or fallback
        return fallback
    return ''


def layouts():
    """Every configured layout, what each can type, and which one is live now."""
    lib, rows = xkb(), []
    configured, current, model, options = sources()
    for index, entry in enumerate(configured):
        kind, ident = (tuple(entry) + ('', ''))[:2]
        layout, _, variant = str(ident).partition('+')
        row = {'index': index, 'type': str(kind), 'id': str(ident), 'layout': layout, 'variant': variant,
               'settings_name': describe(layout, variant), 'active': index == current, 'can_type': ''}
        if str(kind) != 'xkb':
            # An input method (ibus, m17n) composes characters from keystrokes in
            # its own way; the keysym a layout would need is not knowable here.
            row.update({'compiled': False, 'name': '', 'characters': 0, 'cyrillic': 0, 'macedonian': False,
                        'why': 'not an xkb layout, so what a keysym produces is not predictable'})
        else:
            name, chars = producible(lib, layout, variant, model, options)
            row.update({'compiled': chars is not None, 'name': name or '', 'characters': len(chars or ()),
                        'can_type': ''.join(sorted(chars or ())),
                        'cyrillic': sum('Ѐ' <= c <= 'ӿ' for c in (chars or ())),
                        'macedonian': bool(chars) and all(c in chars and c.upper() in chars
                                                          for c in MACEDONIAN_LETTERS),
                        'why': '' if chars is not None else 'this layout is not installed in the xkb data'})
        rows.append(row)
    return rows, current, model, options


def prop(bus, path, name):
    from gi.repository import Gio, GLib
    return bus.call_sync(RD, path, 'org.freedesktop.DBus.Properties', 'Get',
                         GLib.Variant('(ss)', (SESSION, name)), GLib.VariantType('(v)'),
                         Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]


def session():
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    path = bus.call_sync(RD, '/org/gnome/Mutter/RemoteDesktop', RD, 'CreateSession', None,
                         GLib.VariantType('(o)'), Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    bus.call_sync(RD, path, SESSION, 'Start', None, None, Gio.DBusCallFlags.NONE, 5000, None)
    return bus, path


def stop(bus, path):
    from gi.repository import Gio
    bus.call_sync(RD, path, SESSION, 'Stop', None, None, Gio.DBusCallFlags.NONE, 5000, None)


def keysym(bus, path, value, state):
    from gi.repository import Gio, GLib
    bus.call_sync(RD, path, SESSION, 'NotifyKeyboardKeysym', GLib.Variant('(ub)', (value, state)),
                  None, Gio.DBusCallFlags.NONE, 5000, None)


def loaded_keymap(bus, path):
    """What the compositor itself says is loaded, independently of gsettings."""
    facts = {'session_keymap': '', 'keymap_source': -1, 'keymap_capabilities': {}, 'session_available': False}
    try:
        keymap = prop(bus, path, 'CurrentKeymap')
        facts.update({'session_keymap': str(keymap.get('name', '')),
                      'keymap_source': int(keymap.get('source', -1)),
                      'keymap_capabilities': {str(k): str(v) for k, v in prop(bus, path, 'KeymapCapabilities').items()},
                      'session_available': True})
    except Exception as exc:
        facts['session_error'] = type(exc).__name__
    return facts


def keymap_facts(bus=None, path=None):
    rows, current, model, options = layouts()
    active = next((row for row in rows if row['active']), None)
    facts = {'layouts': rows, 'active_index': current, 'active': active,
             'xkb_model': model, 'xkb_options': options,
             'session_keymap': '', 'keymap_capabilities': {}, 'session_available': False}
    if bus is not None:
        facts.update(loaded_keymap(bus, path))
    # gsettings says which layout SHOULD be live, the session says which IS. They
    # must agree before a keystroke is sent: the producible set came from the first
    # and the keycode lookup will happen against the second.
    facts['agrees'] = bool(active and active.get('compiled') and facts['session_available']
                           and active['name'] == facts['session_keymap'])
    return facts


def atspi():
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    Atspi.set_timeout(400, 900)
    return Atspi


def focus_target(Atspi, app_name):
    """The active toplevel of one application and the focused control inside it.

    Keystrokes are not addressed at an object, so this is the only way to know what
    is about to receive them. Returns (window title, focused node, focused role).
    """
    from collections import deque
    want = ALIASES.get(app_name.strip().casefold(), app_name.strip().casefold())
    desktop = Atspi.get_desktop(0)
    windows = []
    for index in range(min(desktop.get_child_count(), 100)):
        try:
            app = desktop.get_child_at_index(index)
            if app is None or app.get_name().casefold() != want:
                continue
        except Exception:
            continue
        for child in range(min(app.get_child_count(), 60)):
            try:
                node = app.get_child_at_index(child)
                if node is None or node.get_role_name() not in TOPLEVELS:
                    continue
                if node.get_state_set().contains(Atspi.StateType.ACTIVE):
                    windows.append(node)
            except Exception:
                continue
    if not windows:
        raise Refused('WINDOW_NOT_ACTIVE',
                      'No active window belongs to that application, so it is not what keystrokes would '
                      'reach right now. Focus it first; keystrokes go to the focus, not to an address.')
    if len(windows) > 1:
        raise Refused('AMBIGUOUS', 'That application reports more than one active window, so which one '
                                   'would receive the keystrokes is ambiguous')
    window, focused, seen = windows[0], None, 0
    queue = deque([(window, 0)])
    while queue and seen < 400:
        node, depth = queue.popleft()
        seen += 1
        try:
            if node.get_state_set().contains(Atspi.StateType.FOCUSED):
                focused = node
            if depth >= 18:
                continue
            for index in range(min(node.get_child_count(), 60)):
                child = node.get_child_at_index(index)
                if child is not None:
                    queue.append((child, depth + 1))
        except Exception:
            continue
    role = ''
    if focused is not None:
        role = focused.get_role_name()
        if 'password' in role.casefold():
            raise Refused('PASSWORD_FIELD', 'The focused control is a password field; ARIES does not type '
                                            'into one')
    return window.get_name()[:160], focused, role


def readable(Atspi, node):
    """The focused control's text, when it exposes AT-SPI Text. A terminal does."""
    if node is None:
        return None
    try:
        if node.get_text_iface() is None:
            return None
        return Atspi.Text.get_text(node, 0, Atspi.Text.get_character_count(node))
    except Exception:
        return None


def resolve_text(text, chars):
    """(keysym per character, []) or (None, the characters that have no key)."""
    missing = sorted({c for c in text if c not in chars})
    return (None, missing) if missing else ([chars[c] for c in text], [])


def control_characters(text):
    return sorted({c for c in text if ord(c) < 0x20 or 0x7f <= ord(c) < 0xa0})


def refuse_layout(text):
    """The layout gate, answered WITHOUT a compositor session.

    Deliberately session-free: the Cyrillic refusal is the common answer on this
    machine, it must not cost a RemoteDesktop session, and it must still be
    available while the screen is locked — when no session can be created at all.
    Returns (failure or None, facts).
    """
    facts = keymap_facts()
    active = facts['active']
    if active is None:
        return fail('LAYOUT_UNKNOWN', 'No input source is configured at the active index, so which keyboard '
                                      'layout is live cannot be established', **facts), facts
    if not active['compiled']:
        return fail('LAYOUT_UNKNOWN', 'The active input source %s could not be compiled (%s), so the '
                                      'characters it can type are unknown and typing would be a guess'
                    % (active['id'], active['why'] or 'unknown reason'), **facts), facts
    missing = sorted({c for c in text if c not in active['can_type']})
    if missing:
        capable = [row for row in facts['layouts'] if row.get('macedonian')]
        configured = '; '.join('%s (%s)' % (row['id'], row['settings_name'] or row['name'] or '?')
                               for row in facts['layouts']) or 'none'
        advice = ('A Macedonian layout IS configured (%s); make it the active input source and ask again.'
                  % ', '.join(row['id'] for row in capable) if capable else
                  'No configured layout can write Macedonian. Add a Macedonian input source in '
                  'Settings → Keyboard → Input Sources, then ask again.')
        return fail('LAYOUT_CANNOT_TYPE',
                    'The active keyboard layout %r has no key for %s. Mutter would drop exactly those '
                    'characters and type the rest, so nothing was typed at all. Configured input sources: '
                    '%s. %s' % (active['name'], ' '.join(missing), configured, advice),
                    untypeable=missing, configured=[row['id'] for row in facts['layouts']],
                    macedonian_available=[row['id'] for row in capable],
                    active_layout=active['name'], **facts), facts
    return None, facts


def layout_report(payload=None):
    bus = path = None
    try:
        bus, path = session()
    except Exception:
        # A locked session still answers the layout question; it just cannot add
        # the compositor's own account of which keymap is loaded.
        bus = path = None
    try:
        facts = keymap_facts(bus, path)
    finally:
        if bus is not None:
            try:
                stop(bus, path)
            except Exception:
                pass
    facts['ok'] = True
    return facts


def type_keys(payload):
    """Send one whole string as keystrokes, or send nothing at all.

    Gate order is deliberate, cheapest and most certain first: control characters
    (no I/O), then the layout (gsettings and xkb, still no session), then the
    compositor's own keymap, then focus — which is last because it is the answer
    most likely to have changed since the caller looked.
    """
    text = payload['text']
    control = control_characters(text)
    if control:
        return fail('CONTROL_CHARACTER',
                    'Refusing the control characters %s. Typing text and running it are different acts: in '
                    'a terminal Return executes the command, so pressing it has to be asked for by name.'
                    % ' '.join('U+%04X' % ord(c) for c in control))
    refusal, facts = refuse_layout(text)
    if refusal is not None:
        return refusal
    Atspi = atspi()
    bus, path = session()
    try:
        facts = keymap_facts(bus, path)
        active = facts['active']
        if not facts['agrees']:
            return fail('LAYOUT_UNVERIFIED',
                        'GNOME lists %r as the active input source but the compositor reports %r as the '
                        'loaded keymap. Until they agree, which layout a keystroke resolves against is '
                        'unknown, so nothing was typed.' % ((active or {}).get('name'), facts['session_keymap']),
                        **facts)
        # Recomputed here rather than carried across the process boundary: the
        # table that types is the table compiled in the process that types.
        name, chars = producible(xkb(), active['layout'], active['variant'],
                                 facts['xkb_model'], facts['xkb_options'])
        codes, missing = resolve_text(text, chars or {})
        if missing:
            return fail('LAYOUT_CANNOT_TYPE', 'The active layout changed while this was being prepared and '
                                              'can no longer type %s; nothing was typed' % ' '.join(missing),
                        untypeable=missing)
        window, focused, role = focus_target(Atspi, payload['app'])
        if payload.get('window') and payload['window'] != window:
            raise Refused('WINDOW_CHANGED', 'The active window is now %r, not the %r that was reviewed'
                          % (window, payload['window']))
        before = readable(Atspi, focused)
        started = time.monotonic()
        for code in codes:
            keysym(bus, path, code, PRESS)
            keysym(bus, path, code, RELEASE)
        elapsed = (time.monotonic() - started) * 1000
        # Let the application process the stream before reading it back; an
        # immediate read would report a failure the application had not made.
        time.sleep(0.25)
        try:
            after_window, after_focused, _ = focus_target(Atspi, payload['app'])
        except Refused:
            after_window, after_focused = '', None
        after = readable(Atspi, after_focused)
        readback = before is not None and after is not None
        return {'ok': True, 'typed': len(codes), 'window': window, 'focused_role': role,
                'focus_held': after_window == window, 'window_after': after_window,
                'milliseconds': round(elapsed, 1), 'layout': active['name'], 'layout_id': active['id'],
                'text_sha256': sha(text), 'readback': readback,
                # Strictly MORE occurrences than before, so text that was already
                # on a terminal's screen cannot be mistaken for text we just typed.
                'contains_typed': bool(readback and after.count(text) > before.count(text)),
                'characters_before': None if before is None else len(before),
                'characters_after': None if after is None else len(after)}
    except Refused as refused:
        return fail(refused.code, str(refused))
    finally:
        try:
            stop(bus, path)
        except Exception:
            pass


def main():
    modes = {'layout': layout_report, 'type': type_keys}
    try:
        payload = json.loads(sys.stdin.read(200000) or '{}')
        result = modes[sys.argv[1]](payload)
    except Exception as exc:
        detail = str(exc)
        if 'inhibited' in detail:
            # Mutter refuses a session while the lock shield is up. That is a state
            # of the machine, not a fault, and a caller must tell them apart.
            result = fail('SESSION_LOCKED', 'The desktop session is locked; keystrokes cannot be sent until '
                                            'it is unlocked')
        elif isinstance(exc, Refused):
            result = fail(exc.code, detail[:300])
        elif isinstance(exc, ValueError):
            result = fail('TARGET_NOT_FOUND', detail[:300])
        elif isinstance(exc, (ImportError, OSError, KeyError, IndexError)):
            result = fail('CAPABILITY_UNAVAILABLE', type(exc).__name__ + ': ' + detail[:200])
        else:
            result = fail('NON_RETRYABLE', type(exc).__name__ + ': ' + detail[:300])
    sys.stdout.write(json.dumps(result))
'''.replace('@MACEDONIAN@', repr(MACEDONIAN_LETTERS))

# The entry call is appended rather than written inline so the tests can exec the
# body itself, the way tests/test_input_capabilities.py does for the AT-SPI worker.
_WORKER = _WORKER_BODY + '\nmain()\n'


async def worker(mode, payload, *, timeout=15):
    """One bounded system-Python call. The text travels on stdin, never in argv,
    which every process on this machine can read through /proc."""
    proc = await asyncio.create_subprocess_exec(
        '/usr/bin/python3', '-I', '-c', _WORKER, mode,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()), timeout)
    except asyncio.TimeoutError:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise KeyboardError('CAPABILITY_UNAVAILABLE', 'The keyboard ' + mode + ' worker timed out')
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise
    if proc.returncode or not output or len(output) > 400_000:
        raise KeyboardError('CAPABILITY_UNAVAILABLE', 'The keyboard ' + mode + ' worker failed')
    try:
        data = json.loads(output)
    except (ValueError, UnicodeError):
        raise KeyboardError('CAPABILITY_UNAVAILABLE', 'The keyboard ' + mode + ' worker returned invalid output')
    if not isinstance(data, dict) or not data.get('ok'):
        row = data if isinstance(data, dict) else {}
        error = KeyboardError(row.get('code', 'NON_RETRYABLE'), row.get('message', 'The request was refused'))
        # A refusal has to be inspectable, not merely readable: a caller deciding
        # whether to fall back needs the characters, not the sentence.
        error.detail = {key: value for key, value in row.items() if key not in {'ok', 'code', 'message'}}
        raise error
    data.pop('ok', None)
    return data


# --- the pure part: which mechanism reaches a target --------------------------

def mechanism_for(target, layout, text=None):
    """Which text mechanism reaches ONE control, and why. No I/O, so it is testable.

    `target` is a row from `input.editable_targets`, or None meaning the
    application exposed no editable control at all — the terminal case, and the
    whole reason the keysym path exists. `layout` is the active row from
    `input.keyboard_layout`. Passing `text` narrows the keysym verdict from "this
    layout in general" to "this actual string".
    """
    layout = layout or {}
    if target is not None:
        if 'password' in str(target.get('role', '')).casefold():
            return {'mechanism': 'none', 'why': 'a password field is never written to by either path'}
        if target.get('typeable'):
            return {'mechanism': 'atspi',
                    'why': 'it implements AT-SPI EditableText, which is addressed at the control, keeps '
                           'Cyrillic and races no focus change'}
        return {'mechanism': 'atspi', 'blocked': True,
                'why': 'AT-SPI EditableText is the right path for this control but it is not typeable right '
                       'now (focused=%s, window active=%s, enabled=%s, selections=%s)'
                       % (target.get('focused'), target.get('window_active'), target.get('enabled'),
                          target.get('selections'))}
    if not layout.get('compiled'):
        return {'mechanism': 'none',
                'why': 'no editable control is exposed AND the active keyboard layout could not be '
                       'compiled, so keystrokes cannot be resolved either'}
    # A layout really does carry Return, Tab and BackSpace, so `can_type` honestly
    # contains them; input.type_keys refuses them anyway and this must say the same
    # thing, or the advice would disagree with the gate it is advising about.
    control = sorted({c for c in (text or '') if ord(c) < 0x20 or 0x7f <= ord(c) < 0xa0})
    if control:
        return {'mechanism': 'none', 'control_characters': ['U+%04X' % ord(c) for c in control],
                'why': 'input.type_keys refuses control characters: in a terminal Return runs the command, '
                       'so pressing it is a separate act with its own approval'}
    unknown = sorted({c for c in text if c not in layout.get('can_type', '')}) if text else []
    if unknown:
        return {'mechanism': 'none', 'untypeable': unknown,
                'why': 'no editable control is exposed, and the active layout %r has no key for %s, which '
                       'Mutter would drop silently' % (layout.get('name'), ' '.join(unknown))}
    return {'mechanism': 'keysym',
            'why': 'no AT-SPI editable control is exposed (a terminal never is), so compositor keystrokes '
                   'are the only path; bounded to the %d characters %r can produce'
                   % (layout.get('characters', 0), layout.get('name') or 'active layout')}


def active_layout(report):
    """The live layout row out of an input.keyboard_layout result."""
    return next((row for row in report.get('layouts', []) if row.get('active')), None)


# --- capability surface -------------------------------------------------------

async def keyboard_layout(args, ctx):
    data = await worker('layout', {})
    for row in data['layouts']:
        row['macedonian_capable'] = row.pop('macedonian', False)
    return {**data, 'observed_at': now(),
            'source': 'org.gnome.desktop.input-sources compiled with libxkbcommon, cross-checked against '
                      'Mutter RemoteDesktop CurrentKeymap'}


async def verify_keyboard_layout(args, result, ctx):
    fresh = await worker('layout', {})
    met = (fresh.get('active_index') == result.get('active_index')
           and fresh.get('session_keymap') == result.get('session_keymap'))
    # The active layout is one switchable setting. If it moved between the report
    # and this re-read, the producible set already reported is stale.
    return {'met': met, 'type': 'keyboard_layout',
            'data': {'active_index': fresh.get('active_index'), 'session_keymap': fresh.get('session_keymap'),
                     'agrees': fresh.get('agrees'), 'changed_since_report': not met, 'observed_at': now()}}


async def text_mechanisms(args, ctx):
    """For one application: which text mechanism reaches it, control by control."""
    survey = await editable_targets({'app': args['app']}, {})
    report = await keyboard_layout({}, ctx)
    active = active_layout(report)
    rows = [{**{key: target[key] for key in ('node', 'role', 'name', 'window', 'typeable')},
             **mechanism_for(target, active)} for target in survey['targets']]
    if not rows:
        rows = [{'node': '', 'role': '', 'name': '', 'window': '', 'typeable': False,
                 **mechanism_for(None, active)}]
    return {'app': survey['app'], 'matched': survey['matched'], 'targets': rows,
            'active_layout': (active or {}).get('name', ''),
            'active_layout_id': (active or {}).get('id', ''),
            'layout_can_write_macedonian': bool(active and active.get('macedonian_capable')),
            'macedonian_available': [row['id'] for row in report['layouts'] if row.get('macedonian_capable')],
            'keysym_path_available': bool(report.get('agrees')),
            'observed_at': now(), 'source': 'AT-SPI survey plus the compiled active keyboard layout'}


async def verify_text_mechanisms(args, result, ctx):
    # A mechanism report is a claim about a live tree and a live setting, so the
    # evidence is a second independent observation rather than a promise.
    return {'met': True, 'type': 'text_mechanisms', 'data': await text_mechanisms(args, ctx)}


async def type_keys(args, ctx):
    fields = {'app': args['app'], 'text': args['text'], 'window': args.get('window')}
    data = await worker('type', fields, timeout=40)
    return {**data, 'app': args['app'], 'characters_requested': len(args['text']),
            'requested_at': now(), 'source': 'Mutter RemoteDesktop NotifyKeyboardKeysym'}


async def verify_type_keys(args, result, ctx):
    """Keystrokes are unaddressed, so 'sent' proves nothing; the readback does.

    Where the focused control exposes AT-SPI Text — a terminal does — the typed
    string was counted in it before and after. Where it does not, this says so
    rather than claiming a success nobody watched.
    """
    if not result.get('readback'):
        return {'met': False, 'type': 'typed_keys',
                'data': {'window': result.get('window'), 'typed': result.get('typed'),
                         'focus_held': result.get('focus_held'), 'layout': result.get('layout'),
                         'scope': 'the focused control exposes no AT-SPI Text, so what the keystrokes '
                                  'became could not be observed at all',
                         'observed_at': now()}}
    met = bool(result.get('contains_typed')) and bool(result.get('focus_held'))
    return {'met': met, 'type': 'typed_keys',
            'data': {'window': result.get('window'), 'focus_held': result.get('focus_held'),
                     'contains_typed': result.get('contains_typed'), 'typed': result.get('typed'),
                     'layout': result.get('layout'),
                     'scope': 'the focused control was read back over AT-SPI after the keystrokes and the '
                              'typed string occurs in it more often than before',
                     'observed_at': now()}}


def register(registry):
    registry.register(Capability(
        'input.keyboard_layout',
        'Report the configured keyboard layouts, which one is active, and which characters each can type. '
        'Call this before input.type_keys: keystrokes can only produce characters the active layout has a '
        'key for, and Mutter drops the rest without raising anything.',
        Empty, keyboard_layout, verify_keyboard_layout, timeout_seconds=25))
    registry.register(Capability(
        'input.text_mechanisms',
        'Say which text mechanism reaches one application: AT-SPI EditableText per editable control, or '
        'compositor keystrokes when it exposes none, as a terminal does not. Use it to choose between '
        'input.type_text and input.type_keys instead of guessing.',
        AppInput, text_mechanisms, verify_text_mechanisms, timeout_seconds=30))
    registry.register(Capability(
        'input.type_keys',
        'Send text as real keystrokes to the named application\'s active window, for applications with no '
        'AT-SPI EditableText such as terminals. Refused outright unless the active keyboard layout can '
        'produce EVERY character; a partial string is never typed. Control characters including Return are '
        'refused, so this types a command but never runs it. Prefer input.type_text wherever it works.',
        TypeKeysInput, type_keys, verify_type_keys,
        requires_approval=True, effect='input', risk_level='high', timeout_seconds=60))


# --- voice and typed-command surface -----------------------------------------
# These return the result shape aries.workspace.capabilities.execute already
# produces, so its branches stay short and the verification story is unchanged.

def _refusal(error):
    detail = getattr(error, 'detail', {}) or {}
    cards = []
    if detail.get('untypeable'):
        cards.append({'title': 'Cannot be typed on this layout',
                      'text': ' '.join(detail['untypeable']),
                      'evidence': 'These characters have no key in %s, and Mutter drops what it cannot map '
                                  'without reporting it'
                                  % (detail.get('active_layout') or 'the active layout')})
    return {'state': 'held' if error.code == 'SESSION_LOCKED' else 'failed',
            'summary': str(error), 'cards': cards,
            'verification': {'met': False,
                             'evidence': 'Nothing was typed; the refusal was decided before any keystroke '
                                         'was sent'}}


async def voice_keyboard_layout():
    try:
        observed = await keyboard_layout({}, {})
    except InputCapabilityError as error:
        return _refusal(error)
    active, layouts = active_layout(observed), observed['layouts']
    capable = [row['id'] for row in layouts if row.get('macedonian_capable')]
    if (active or {}).get('macedonian_capable'):
        verdict = 'Macedonian can be typed by keystroke.'
    elif capable:
        verdict = 'A Macedonian layout is configured (%s) but is not the active one.' % ', '.join(capable)
    else:
        verdict = ('No configured layout can type Macedonian, so keystroke typing is Latin-only here; add a '
                   'Macedonian input source in Settings → Keyboard.')
    check = await verify_keyboard_layout({}, observed, {})
    return {'state': 'done' if check['met'] else 'unconfirmed',
            'summary': 'Active layout: %s, %d characters typeable. %s'
                       % ((active or {}).get('name') or 'unknown', (active or {}).get('characters', 0), verdict),
            'verification': {'met': check['met'],
                             'evidence': 'Layouts compiled with libxkbcommon and cross-checked against the '
                                         'keymap the compositor reports as loaded'
                                         + ('' if check['met'] else '; the active layout changed in between')},
            'cards': [{'title': (row['settings_name'] or row['id']) + (' — active' if row['active'] else ''),
                       'text': '%d characters, %d Cyrillic; Macedonian: %s'
                               % (row['characters'], row['cyrillic'],
                                  'yes' if row.get('macedonian_capable') else 'no'),
                       'evidence': 'xkb %s compiled from the configured input sources' % row['id']}
                      for row in layouts]}


async def voice_text_mechanisms(app):
    try:
        observed = await text_mechanisms({'app': app}, {})
    except InputCapabilityError as error:
        return _refusal(error)
    counts = {}
    for row in observed['targets']:
        counts[row['mechanism']] = counts.get(row['mechanism'], 0) + 1
    return {'state': 'done',
            'summary': '%s: %s' % (app, ', '.join('%d via %s' % (n, m) for m, n in sorted(counts.items()))),
            'verification': {'met': True,
                             'evidence': 'Read-only AT-SPI survey plus the compiled active layout; no input '
                                         'was sent'},
            'cards': [{'title': row['name'] or row['role'] or 'no editable control exposed',
                       'text': row['why'],
                       'evidence': 'mechanism: %s%s' % (row['mechanism'],
                                                        ' (blocked right now)' if row.get('blocked') else '')}
                      for row in observed['targets']],
            'observation': observed}


async def voice_type_keys(app, text, window=None):
    try:
        result = await type_keys({'app': app, 'text': text, 'window': window}, {})
        check = await verify_type_keys({'app': app, 'text': text}, result, {})
    except InputCapabilityError as error:
        return _refusal(error)
    return {'state': 'done' if check['met'] else 'unconfirmed',
            'summary': ('Typed %d characters into %s' % (result['typed'], result['window'] or app))
                       if check['met'] else
                       'Sent %d keystrokes to %s but could not confirm what they became'
                       % (result['typed'], result['window'] or app),
            'verification': {'met': check['met'], 'evidence': check['data'].get('scope', '')},
            'cards': [{'title': result['window'] or app,
                       'text': '%s · %s' % (result.get('focused_role') or 'focused control',
                                                 result['layout']),
                       'evidence': '%d keysyms in %s ms; focus held: %s'
                                   % (result['typed'], result['milliseconds'], result['focus_held'])}]}
