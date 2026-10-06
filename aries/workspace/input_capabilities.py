"""ARIES's hands for text: the clipboard, and typing into a control the user chose.

WHY THERE ARE TWO MECHANISMS HERE, AND WHY THEY ARE NOT INTERCHANGEABLE
----------------------------------------------------------------------
Wayland has no global synthetic input and this machine has no root, so the two
usual tools are dead ends rather than missing packages: `xdotool` only ever sees
XWayland, and `ydotool` needs /dev/uinput, which is `crw------- root root` here
(open() returns EACCES). What remains are two real compositor-blessed paths,
both measured on this machine, and they are good at different things:

  CLIPBOARD  org.gnome.Mutter.RemoteDesktop session selection API. Reading took
             2 ms. A write outlives the writing process because Mutter's own
             clipboard manager fetches the content ~2 ms after ownership changes
             and caches it; 1 MiB came back byte-identical from a fresh session
             after the writer had exited. CreateSession is refused while the
             lock shield is up ("Session creation inhibited"), which is the
             right answer rather than a fault.

  TYPING     AT-SPI EditableText on a node the caller has already observed.
             1-3 ms, keeps Cyrillic, and keeps working while the screen is
             locked, because it is app-to-app over the accessibility bus and
             never touches the compositor.

The same RemoteDesktop session also offers NotifyKeyboardKeysym, and it does
deliver real keystrokes: 'aries42' arrived intact, 69 ms for seven characters.
Typing is still not built on it. Mutter has to find a KEYCODE for each keysym in
the ACTIVE keyboard layout, so on a Latin layout 'шар' arrives as nothing at all
and nothing reports a failure. An assistant whose first language is Macedonian
must not have a text path that silently drops Macedonian, so typing here is
AT-SPI or it is refused.

THE GUARD
---------
Typing into whatever happens to hold focus is a way to destroy someone's work,
so nothing here does that. `input.type_text` writes to ONE object the caller has
already seen through `input.editable_targets`, and before writing it re-checks
that the application name, pid, node role and accessible name are unchanged
since that review — the same anti-TOCTOU check accessibility_bridge.activate
makes — that the node is editable and enabled, that it holds focus inside its
application, that its toplevel window is the ACTIVE one, and that its role is
not a password field. It refuses when the control has a selection, because real
typing would replace the selection and InsertText would not. There is no
keystroke stream to race a focus change: the write is addressed, so it lands on
that one object or it fails.

AND IT SAYS WHICH. ARIES_TYPE_STRICT, default on.
-------------------------------------------------
The guard above decides whether to write. What follows the write is a second
question, and the one this file used to get wrong: `insert_text` returns TRUE and
the characters are not there. A NUL truncates the text inside the toolkit,
because InsertText is a C call on a NUL-terminated string. A C0 control character
is dropped by the text buffer. A line break into a GtkEntry is discarded. An
application that filters or truncates its own input does so after accepting the
call. All of those used to come back as `{'ok': True, 'landed': False}` — a
success report for text the person never received. They are now refusals that
carry the observation with them: the reason, how many characters were sent, how
many the control holds now, and whether it was modified and left that way.
Turning the flag off restores the old shape for an ablation, nothing else.
"""
import asyncio
import hashlib
import json
from datetime import datetime, timezone

from pydantic import Field

from aries.workspace.capability_types import Capability, Input

# Same ceiling aries.workspace.registry.file_snapshot uses for text.
MAX_CLIPBOARD_BYTES = 100_000
MAX_TYPE_CHARS = 4_000


def now():
    return datetime.now(timezone.utc).isoformat()


class Empty(Input):
    pass


class ClipboardWriteInput(Input):
    text: str = Field(min_length=1, max_length=MAX_CLIPBOARD_BYTES)


class TargetsInput(Input):
    app: str = Field(min_length=1, max_length=160)


class TypeInput(TargetsInput):
    # The whole reviewed identity, exactly as input.editable_targets reported it.
    # A node path is a position in a live tree and means nothing on its own.
    node: str = Field(pattern=r'^\d{1,5}(?:/\d{1,5}){0,19}$')
    pid: int = Field(ge=1, le=4_194_304)
    role: str = Field(min_length=1, max_length=80)
    name: str = Field(max_length=160)
    text: str = Field(min_length=1, max_length=MAX_TYPE_CHARS)
    mode: str = Field(default='insert', pattern=r'^(insert|replace)$')


class InputCapabilityError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        # A locked session becomes unlocked by a person, not by trying again.
        self.retryable = False


# The worker below runs on /usr/bin/python3 because gi/PyGObject is not in .venv
# (ADR-0004). It is carried here as source rather than as its own module only
# because this capability set is allowed exactly one file; the bridge shape —
# system interpreter, -I, JSON over pipes, bounded wait, killed on timeout — is
# the one aries.operator.accessibility already established.
_WORKER_BODY = r'''
import hashlib, json, os, select, sys, time

RD = 'org.gnome.Mutter.RemoteDesktop'
SESSION = RD + '.Session'
# Measured here: Mutter serves its own cached copy on text/plain;charset=utf-8
# and answered text/plain empty. UTF8_STRING is kept for selections owned by an
# X11 client through XWayland.
MIMES = ['text/plain;charset=utf-8', 'UTF8_STRING', 'text/plain']
# The spellings aries/operator/accessibility_bridge.py accepts, so one app is
# named the same way in both places. Duplicated because that file is not ours.
ALIASES = {'vscode': 'code', 'vs code': 'code', 'visual studio code': 'code',
           'files': 'org.gnome.nautilus', 'nautilus': 'org.gnome.nautilus'}
TOPLEVELS = {'frame', 'window', 'dialog', 'alert', 'file chooser'}
STATES = ('EDITABLE', 'FOCUSED', 'ACTIVE', 'SENSITIVE', 'SHOWING', 'VISIBLE')


def fail(code, message):
    return {'ok': False, 'code': code, 'message': message}


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def call(bus, path, method, args=None, sig=None, iface=SESSION):
    from gi.repository import Gio, GLib
    return bus.call_with_unix_fd_list_sync(
        RD, path, iface, method, args, GLib.VariantType(sig) if sig else None,
        Gio.DBusCallFlags.NONE, 5000, None, None)


def session():
    from gi.repository import Gio
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    path = call(bus, '/org/gnome/Mutter/RemoteDesktop', 'CreateSession', None, '(o)', RD)[0].unpack()[0]
    call(bus, path, 'Start')
    return bus, path


def offer(values):
    from gi.repository import GLib
    return GLib.Variant('(a{sv})', ({'mime-types': GLib.Variant('as', values)},))


def drain(bus, path, mime, limit, budget=2.0):
    from gi.repository import GLib
    started = time.monotonic()
    reply, fds = call(bus, path, 'SelectionRead', GLib.Variant('(s)', (mime,)), '(h)')
    fd = fds.get(reply.unpack()[0])
    chunks, size = [], 0
    try:
        while True:
            left = budget - (time.monotonic() - started)
            # Mutter hands back a NON-BLOCKING pipe: EAGAIN means "not yet", not
            # "empty", so this polls rather than reading a short result as the end.
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                return b''.join(chunks), 'timeout'
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                return b''.join(chunks), 'complete'
            chunks.append(chunk)
            size += len(chunk)
            if size >= limit:
                return b''.join(chunks)[:limit], 'truncated'
    finally:
        # Leaving a transfer open makes the next SelectionRead fail with
        # LimitsExceeded ("Tried to read in parallel"), so this is not optional.
        os.close(fd)


def clipboard_read(payload):
    from gi.repository import GLib
    limit = max(1, min(int(payload.get('limit') or 100000), 1000000))
    bus, path = session()
    try:
        call(bus, path, 'EnableClipboard', GLib.Variant('(a{sv})', ({},)))
        for mime in MIMES:
            data, state = drain(bus, path, mime, limit)
            if not data:
                continue
            try:
                text, lossless = data.decode('utf-8'), True
            except UnicodeDecodeError:
                text, lossless = data.decode('utf-8', 'replace'), False
            return {'ok': True, 'has_text': True, 'text': text, 'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(), 'mime_type': mime,
                    'truncated': state == 'truncated', 'transfer': state, 'lossless_utf8': lossless}
        return {'ok': True, 'has_text': False, 'text': '', 'bytes': 0, 'mime_type': '',
                'sha256': hashlib.sha256(b'').hexdigest(), 'truncated': False,
                'transfer': 'no text offered', 'lossless_utf8': True}
    finally:
        try:
            call(bus, path, 'Stop')
        except Exception:
            pass


def clipboard_write(payload):
    from gi.repository import Gio, GLib
    data = payload['text'].encode('utf-8')
    bus, path = session()
    served, loop = [], GLib.MainLoop()

    def transfer(conn, sender, obj, iface, signal, params):
        if signal != 'SelectionTransfer':
            return
        mime, serial = params.unpack()
        try:
            reply, fds = call(bus, path, 'SelectionWrite', GLib.Variant('(u)', (serial,)), '(h)')
            with os.fdopen(fds.get(reply.unpack()[0]), 'wb') as sink:
                sink.write(data)
            call(bus, path, 'SelectionWriteDone', GLib.Variant('(ub)', (serial, True)))
            served.append(mime)
        except Exception as exc:
            served.append('failed:' + type(exc).__name__)
        # Linger past the first hand-off so Mutter finishes caching, then leave.
        GLib.timeout_add(250, lambda: loop.quit())

    try:
        call(bus, path, 'EnableClipboard', offer(MIMES))
        bus.signal_subscribe(RD, SESSION, 'SelectionTransfer', path, None, Gio.DBusSignalFlags.NONE, transfer)
        call(bus, path, 'SetSelection', offer(MIMES))
        GLib.timeout_add(1500, lambda: loop.quit())
        loop.run()
    finally:
        try:
            call(bus, path, 'Stop')
        except Exception:
            pass
    good = [m for m in served if not m.startswith('failed:')]
    if not good:
        # Nobody ever asked for the bytes, so Mutter never cached them and the
        # text dies with this process. That is not a write, whatever it returned.
        return fail('CLIPBOARD_NOT_CACHED',
                    'Mutter never requested the offered clipboard content, so nothing was stored')
    return {'ok': True, 'served': served, 'bytes': len(data)}


def atspi():
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    Atspi.set_timeout(400, 900)
    return Atspi


def states(Atspi, node):
    present = node.get_state_set()
    return {name: bool(present.contains(getattr(Atspi.StateType, name)))
            for name in STATES if hasattr(Atspi.StateType, name)}


def iface(node, name):
    try:
        return getattr(node, 'get_%s_iface' % name)()
    except Exception:
        return None


def whole(Atspi, node):
    return Atspi.Text.get_text(node, 0, Atspi.Text.get_character_count(node))


def targets(payload):
    from collections import deque
    Atspi = atspi()
    want = ALIASES.get(payload['app'].strip().casefold(), payload['app'].strip().casefold())
    desktop = Atspi.get_desktop(0)
    deadline = time.monotonic() + 4
    queue, matched = deque(), 0
    for index in range(min(desktop.get_child_count(), 100)):
        try:
            app = desktop.get_child_at_index(index)
            if app and app.get_name().casefold() == want:
                matched += 1
                queue.append((app, [index], '', False, app.get_process_id()))
        except Exception:
            continue
    found, scanned, truncated, protected, errors = [], 0, False, 0, 0
    while queue and len(found) < 40 and time.monotonic() < deadline:
        node, path, window, active, pid = queue.popleft()
        scanned += 1
        if scanned > 400:
            truncated = True
            break
        try:
            role = node.get_role_name()
            if role in TOPLEVELS:
                window = node.get_name()[:160]
                active = bool(node.get_state_set().contains(Atspi.StateType.ACTIVE))
            if 'password' in role.casefold():
                # Never listed, so it can never be chosen as a typing target.
                protected += 1
                continue
            flags = states(Atspi, node)
            if flags.get('EDITABLE') and iface(node, 'editable_text') and iface(node, 'text'):
                found.append({'node': '/'.join(map(str, path)), 'pid': pid, 'role': role[:80],
                              'name': node.get_name()[:160], 'window': window, 'window_active': active,
                              'focused': flags.get('FOCUSED', False), 'enabled': flags.get('SENSITIVE', False),
                              'characters': Atspi.Text.get_character_count(node),
                              'selections': Atspi.Text.get_n_selections(node),
                              'typeable': bool(active and flags.get('FOCUSED') and flags.get('SENSITIVE')
                                               and Atspi.Text.get_n_selections(node) == 0)})
            if len(path) > 18:
                truncated = True
                continue
            count = node.get_child_count()
            truncated = truncated or count > 60
            for child_index in range(min(count, 60)):
                child = node.get_child_at_index(child_index)
                if child:
                    queue.append((child, path + [child_index], window, active, pid))
        except Exception:
            errors += 1
    return {'ok': True, 'app': want, 'matched': matched, 'targets': found, 'scanned': scanned,
            'protected_skipped': protected, 'truncated': truncated or bool(queue), 'errors': errors}


def resolve(Atspi, payload, check_name=True):
    """Re-walk the reviewed path and refuse anything that moved since review."""
    path = [int(part) for part in payload['node'].split('/')]
    if not path or len(path) > 20 or any(index < 0 or index > 99999 for index in path):
        raise ValueError('Invalid control path')
    want = ALIASES.get(payload['app'].strip().casefold(), payload['app'].strip().casefold())
    app = Atspi.get_desktop(0).get_child_at_index(path[0])
    if app is None:
        raise ValueError('The reviewed application is no longer at that position')
    if app.get_name().casefold() != want:
        raise ValueError('A different application now occupies that position')
    if app.get_process_id() != payload['pid']:
        raise ValueError('The application process changed after review')
    node, window, active = app, '', False
    for index in path[1:]:
        node = node.get_child_at_index(index)
        if node is None:
            raise ValueError('The reviewed control no longer exists')
        if node.get_role_name() in TOPLEVELS:
            window = node.get_name()[:160]
            active = bool(node.get_state_set().contains(Atspi.StateType.ACTIVE))
    role = node.get_role_name()
    if role != payload['role'] or (check_name and node.get_name() != payload['name']):
        raise ValueError('The control changed after review')
    if 'password' in role.casefold():
        raise ValueError('ARIES does not type into password fields')
    return node, role, window, active


# A single-line control eats a line break and says nothing. These are the AT-SPI
# role names GTK and Qt publish for one; the list is used to refuse BEFORE the
# write, because a refusal that arrives after half the text is in is not a refusal.
SINGLE_LINE = {'entry', 'password text', 'spin button', 'combo box', 'search box',
               'text field', 'password'}


def untypeable(text, role):
    """Why this exact text cannot reach this exact control intact, or ''.

    Every branch here is a measured or structural SILENT loss: the toolkit
    accepts the call, returns TRUE, and some of the characters are simply not
    there afterwards. Returning a reason is the whole point — the alternative is
    a success report for text the person never got.
    """
    try:
        text.encode('utf-8')
    except UnicodeEncodeError:
        return ('That text is not encodable as UTF-8 (it carries an unpaired surrogate), so it '
                'cannot cross the accessibility bus. Nothing was typed.')
    if '\x00' in text:
        return ('That text contains a NUL. AT-SPI InsertText is a C call on a NUL-terminated '
                'string, so everything after the NUL is dropped inside the toolkit while the '
                'call still reports success. Nothing was typed.')
    bad = sorted({character for character in text if ord(character) < 32 and character not in '\t\n\r'})
    if bad:
        return ('That text contains control characters (%s) that a text buffer discards without '
                'reporting it, so part of the request would vanish. Nothing was typed.'
                % ', '.join('U+%04X' % ord(character) for character in bad))
    if role.casefold() in SINGLE_LINE and ('\n' in text or '\r' in text):
        return ('%s is a single-line control: it drops line breaks silently, so %d break(s) and '
                'everything arranged around them would be lost. Nothing was typed; use a '
                'multi-line control or send one line.'
                % (role, text.count('\n') + text.count('\r')))
    return ''


def type_text(payload):
    Atspi = atspi()
    node, role, window, active = resolve(Atspi, payload)
    flags = states(Atspi, node)
    if not iface(node, 'editable_text') or not iface(node, 'text'):
        return fail('NOT_EDITABLE', 'This control does not implement AT-SPI EditableText, so text cannot be '
                                    'inserted into it and could not be read back if it were. Terminals are '
                                    'the common case: they expose Text without EditableText.')
    if not flags.get('EDITABLE') or not flags.get('SENSITIVE'):
        return fail('NOT_EDITABLE', 'That control is not an enabled editable text field right now')
    if not flags.get('FOCUSED'):
        return fail('NOT_FOCUSED', 'That control does not hold the keyboard focus inside its application')
    if not active:
        return fail('WINDOW_NOT_ACTIVE', 'That window is not the one being worked in; refusing to write into it')
    before = whole(Atspi, node)
    caret = Atspi.Text.get_caret_offset(node)
    selections = Atspi.Text.get_n_selections(node)
    if selections and payload['mode'] == 'insert':
        return fail('AMBIGUOUS', 'The control holds a selection: typing would replace it but an insert would '
                                 'not, so the outcome is ambiguous. Clear the selection or ask for replace.')
    text = payload['text']
    # strict defaults ON. The flag is read in the parent (this worker runs under
    # /usr/bin/python3 -I and cannot import aries.flags) and arrives in the payload.
    strict = payload.get('strict', True)
    if strict:
        why = untypeable(text, role)
        if why:
            return fail('TEXT_NOT_TYPEABLE', why)
    if payload['mode'] == 'replace':
        expected = text
        accepted = bool(Atspi.EditableText.set_text_contents(node, text))
    else:
        caret = caret if 0 <= caret <= len(before) else len(before)
        expected = before[:caret] + text + before[caret:]
        accepted = bool(Atspi.EditableText.insert_text(node, caret, text, len(text)))
    time.sleep(0.12)
    after = whole(Atspi, node)
    # Digests, not the text: this control may be holding the person's own private
    # document, and a persisted task record is not the place to copy it to.
    observed = {'accepted': accepted, 'mode': payload['mode'], 'role': role, 'window': window,
                'caret_before': caret, 'selections_before': selections, 'characters_before': len(before),
                'characters_after': len(after), 'before_sha256': sha(before),
                'expected_sha256': sha(expected), 'observed_sha256': sha(after), 'landed': after == expected}
    if not strict:
        return {'ok': True, **observed}
    # The refusals below CARRY the observation rather than replacing it. The
    # control may have been half written to, and a refusal that hides that is as
    # useless as the success report it replaces.
    if accepted is not True:
        return {**observed, 'ok': False, 'code': 'TEXT_REJECTED',
                'message': ('The control refused the %s: AT-SPI returned false. %d characters were '
                            'requested and the control holds %d. %s'
                            % (payload['mode'], len(text), len(after),
                               'Its text is unchanged.' if after == before else
                               'Its text CHANGED anyway, from %d characters, and ARIES did not '
                               'restore it.' % len(before)))}
    if after != expected:
        delta = len(after) - len(before)
        return {**observed, 'ok': False, 'code': 'TEXT_NOT_LANDED',
                'message': ('The %s was accepted but the control does not hold what was requested: '
                            '%d characters were sent, the control went from %d to %d characters '
                            '(%+d), and its digest is %s where %s was expected. The application '
                            'filtered, reformatted or truncated the text. %s'
                            % (payload['mode'], len(text), len(before), len(after), delta,
                               sha(after)[:12], sha(expected)[:12],
                               'The control was NOT modified.' if after == before else
                               'The control WAS modified and ARIES did not restore it.'))}
    return {'ok': True, **observed}


def read_node(payload):
    # The accessible NAME of some controls is derived from their value, so it
    # legitimately changes when the text does. Identity for a read-back is
    # application, pid, path and role; re-checking the name would fail here for
    # the very controls the write just succeeded on.
    Atspi = atspi()
    node, role, window, active = resolve(Atspi, payload, check_name=False)
    if not iface(node, 'text'):
        return fail('NOT_READABLE', 'This control no longer exposes AT-SPI Text, so it cannot be read back')
    text = whole(Atspi, node)
    return {'ok': True, 'sha256': sha(text), 'characters': len(text), 'role': role,
            'name': node.get_name()[:160], 'window': window, 'window_active': active}


def main():
    modes = {'clipboard_read': clipboard_read, 'clipboard_write': clipboard_write,
             'targets': targets, 'type': type_text, 'read_node': read_node}
    try:
        payload = json.loads(sys.stdin.read(600000) or '{}')
        result = modes[sys.argv[1]](payload)
    except Exception as exc:
        detail = str(exc)
        # Mutter refuses a session while the lock shield is up. That is a state of
        # the machine, not a fault, and the caller has to be able to tell them apart.
        if 'inhibited' in detail:
            result = fail('SESSION_LOCKED', 'The desktop session is locked; the GNOME clipboard is '
                                            'unavailable until it is unlocked')
        elif isinstance(exc, ValueError):
            result = fail('TARGET_NOT_FOUND', detail[:300])
        elif isinstance(exc, (ImportError, KeyError, IndexError)):
            result = fail('CAPABILITY_UNAVAILABLE', type(exc).__name__ + ': ' + detail[:200])
        else:
            result = fail('NON_RETRYABLE', type(exc).__name__ + ': ' + detail[:300])
    sys.stdout.write(json.dumps(result))
'''

# The entry call is appended rather than written inline so the tests can exec the
# body and drive these guards with fake AT-SPI nodes, the way test_accessibility
# does for the read-only bridge. A guard nobody can test is a guard nobody trusts.
_WORKER = _WORKER_BODY + '\nmain()\n'


async def worker(mode, payload, *, timeout=10):
    """One bounded system-Python call. The text travels on stdin, never in argv,
    because argv is readable by every process on the machine through /proc."""
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
        raise InputCapabilityError('CAPABILITY_UNAVAILABLE', 'The ' + mode + ' worker timed out')
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise
    if proc.returncode or not output or len(output) > 400_000:
        raise InputCapabilityError('CAPABILITY_UNAVAILABLE', 'The ' + mode + ' worker failed')
    try:
        data = json.loads(output)
    except (ValueError, UnicodeError):
        raise InputCapabilityError('CAPABILITY_UNAVAILABLE', 'The ' + mode + ' worker returned invalid output')
    if not isinstance(data, dict) or not data.get('ok'):
        row = data if isinstance(data, dict) else {}
        raise InputCapabilityError(row.get('code', 'NON_RETRYABLE'), row.get('message', 'The request was refused'))
    data.pop('ok', None)
    return data


async def clipboard_read(args, ctx):
    data = await worker('clipboard_read', {'limit': MAX_CLIPBOARD_BYTES})
    return {**data, 'observed_at': now(), 'source': 'GNOME/Mutter selection'}


async def verify_clipboard_read(args, result, ctx):
    fresh = await clipboard_read(args, ctx)
    met = fresh['sha256'] == result.get('sha256')
    # A clipboard is one volatile slot. If it changed between the read and this
    # re-read, the text already reported is no longer what is there, and met=True
    # would be vouching for a stale observation.
    return {'met': met, 'type': 'clipboard_state', 'data': {**fresh, 'changed_since_read': not met}}


async def clipboard_write(args, ctx):
    if '\x00' in args['text']:
        raise ValueError('Clipboard text may not contain NUL')
    encoded = args['text'].encode('utf-8')
    if len(encoded) > 2 * MAX_CLIPBOARD_BYTES:
        raise ValueError('Clipboard text is limited to %d UTF-8 bytes' % (2 * MAX_CLIPBOARD_BYTES))
    # Record what is about to be destroyed before destroying it. A clipboard has
    # one slot and no undo, so a length and a digest let the user see that
    # something was lost without copying its plaintext into a task record — it
    # may well have been a password they pasted from a manager.
    try:
        replaced = await worker('clipboard_read', {'limit': MAX_CLIPBOARD_BYTES})
    except InputCapabilityError:
        replaced = {}
    data = await worker('clipboard_write', {'text': args['text']}, timeout=12)
    return {'bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest(),
            'served_mime_types': data.get('served', []),
            'replaced': {'bytes': replaced.get('bytes', 0), 'sha256': replaced.get('sha256', ''),
                         'had_text': bool(replaced.get('has_text'))},
            'requested_at': now(), 'source': 'GNOME/Mutter selection'}


async def verify_clipboard_write(args, result, ctx):
    # A fresh worker and a fresh Mutter session, so this reads what the NEXT
    # application to paste will be handed — not what this process still owns.
    for attempt in range(5):
        fresh = await clipboard_read({}, ctx)
        if fresh['sha256'] == result['sha256']:
            return {'met': True, 'type': 'clipboard_state', 'data': fresh}
        if attempt == 4:
            return {'met': False, 'type': 'clipboard_state',
                    'data': {**fresh, 'expected_sha256': result['sha256']}}
        await asyncio.sleep(0.1)


async def editable_targets(args, ctx):
    data = await worker('targets', {'app': args['app']})
    return {**data, 'observed_at': now(), 'source': 'AT-SPI EditableText survey'}


async def verify_targets(args, result, ctx):
    # A listing is a snapshot of a live tree, so the evidence is a second
    # independent observation rather than a claim that nothing moved.
    return {'met': True, 'type': 'editable_targets', 'data': await editable_targets(args, ctx)}


def strict_typing():
    """Is the refuse-rather-than-lose rule in force? ARIES_TYPE_STRICT, default on."""
    from aries import flags
    return flags.enabled('ARIES_TYPE_STRICT')


async def type_into(args, ctx):
    fields = ('app', 'node', 'pid', 'role', 'name', 'text', 'mode')
    strict = strict_typing()
    if strict:
        # The capability path is validated by the registry; the spoken path
        # (voice_type_text) builds `args` by hand and was not, so MAX_TYPE_CHARS
        # bound nothing there. An over-long dictation is now a refusal with a
        # number in it rather than an unbounded write.
        from pydantic import ValidationError
        try:
            args = TypeInput.model_validate({key: args[key] for key in fields}).model_dump()
        except (ValidationError, KeyError) as error:
            raise InputCapabilityError(
                'TEXT_NOT_TYPEABLE',
                'That request is not a typeable one: %s. Nothing was typed.'
                % str(error).replace('\n', ' ')[:300])
    payload = {key: args[key] for key in fields}
    payload['strict'] = strict
    data = await worker('type', payload, timeout=12)
    return {**data, 'app': args['app'], 'node': args['node'],
            'characters_requested': len(args['text']), 'requested_at': now(),
            'source': 'AT-SPI EditableText'}


async def verify_type(args, result, ctx):
    identity = {key: args[key] for key in ('app', 'node', 'pid', 'role', 'name')}
    for attempt in range(6):
        fresh = await worker('read_node', identity)
        met = fresh['sha256'] == result['expected_sha256']
        if met or attempt == 5:
            return {'met': met, 'type': 'control_text',
                    'data': {**fresh, 'expected_sha256': result['expected_sha256'],
                             'scope': 'the control re-read over a second AT-SPI connection',
                             'observed_at': now()}}
        await asyncio.sleep(0.15)


def register(registry):
    registry.register(Capability(
        'input.clipboard_read',
        'Read the current clipboard as text, bounded to 100 KB. Use it only when the user asks what is on the '
        'clipboard: it returns whatever they last copied, which may be a password, so never call it for context.',
        Empty, clipboard_read, verify_clipboard_read, timeout_seconds=20))
    registry.register(Capability(
        'input.clipboard_write',
        'Replace the clipboard with text and verify it by reading it back from a fresh session. The previous '
        'clipboard is destroyed and cannot be restored, so approval is required.',
        ClipboardWriteInput, clipboard_write, verify_clipboard_write,
        requires_approval=True, effect='input', risk_level='medium', timeout_seconds=30))
    registry.register(Capability(
        'input.editable_targets',
        'List one running application\'s editable text controls with the node identity input.type_text needs. '
        'Password fields are never listed. Call this first; a node path alone is not a target.',
        TargetsInput, editable_targets, verify_targets, timeout_seconds=20))
    registry.register(Capability(
        'input.type_text',
        'Insert text into ONE control previously reported by input.editable_targets, re-verifying its identity '
        'first. Refused unless it is still editable, enabled, focused, in the active window, free of a selection '
        'and not a password field. Terminals do not support this and are refused, not approximated. Any text '
        'that would arrive incomplete is refused with the reason and the observed character counts, never '
        'reported as a success (ARIES_TYPE_STRICT).',
        TypeInput, type_into, verify_type,
        requires_approval=True, effect='input', risk_level='high', timeout_seconds=30))


# ---------------------------------------------------------------------------
# Voice and typed-command surface. These return the result shape
# aries.workspace.capabilities.execute already produces, so its branches stay
# three lines each and the verification story is identical to the M14 one.
# ---------------------------------------------------------------------------

def _refusal(error):
    return {'state': 'held' if error.code == 'SESSION_LOCKED' else 'failed', 'summary': str(error)}


async def voice_clipboard_read():
    try:
        observed = await clipboard_read({}, {})
    except InputCapabilityError as error:
        return _refusal(error)
    if not observed['has_text']:
        return {'state': 'done', 'summary': 'There is no text on the clipboard',
                'verification': {'met': True, 'evidence': 'GNOME offered no text type for the selection'}}
    verdict = await verify_clipboard_read({}, observed, {})
    spoken = ' '.join(observed['text'].split())
    return {'state': 'done' if verdict['met'] else 'unconfirmed',
            'summary': 'Clipboard: ' + spoken[:200] + ('…' if len(spoken) > 200 else ''),
            'verification': {'met': verdict['met'],
                             'evidence': 'Re-read through a second GNOME selection session'
                                         + ('' if verdict['met'] else '; the clipboard changed in between')},
            'cards': [{'title': 'Clipboard', 'text': observed['text'][:4000],
                       'evidence': '%d bytes read from the GNOME selection as %s'
                                   % (observed['bytes'], observed['mime_type'])}]}


async def voice_clipboard_write(text):
    try:
        result = await clipboard_write({'text': text}, {})
        verdict = await verify_clipboard_write({'text': text}, result, {})
    except InputCapabilityError as error:
        return _refusal(error)
    return {'state': 'done' if verdict['met'] else 'unconfirmed',
            'summary': ('Copied %d characters to the clipboard' % len(text)) if verdict['met'] else
                       'The clipboard was offered the text but it could not be read back',
            'verification': {'met': verdict['met'],
                             'evidence': 'Read back from a fresh GNOME selection session after the writer exited'},
            'cards': [{'title': 'Clipboard', 'text': text[:4000],
                       'evidence': 'Replaced %d previous bytes; that content cannot be restored'
                                   % result['replaced']['bytes']}]}


async def voice_type_text(app, node, mode, text):
    """Resolve a reviewed node from a FRESH survey, then type into it.

    The spoken/typed form can only name an app and a node path, so the identity
    the capability requires is recovered here from a current observation — the
    same thing capabilities.prepare does for ui_action — and the write is
    refused outright if that path is not one of the app's editable targets now.
    """
    try:
        survey = await editable_targets({'app': app}, {})
        matches = [row for row in survey['targets'] if row['node'] == node]
        if len(matches) != 1:
            return {'state': 'failed',
                    'summary': 'Survey this application\'s editable controls and choose one of them by node path'}
        target = matches[0]
        if not target['typeable']:
            return {'state': 'failed',
                    'summary': 'That control is not typeable right now: focused=%s, window active=%s, enabled=%s, '
                               'selections=%d' % (target['focused'], target['window_active'],
                                                  target['enabled'], target['selections'])}
        args = {'app': app, 'node': node, 'pid': target['pid'], 'role': target['role'],
                'name': target['name'], 'text': text, 'mode': mode}
        result = await type_into(args, {})
        verdict = await verify_type(args, result, {})
    except InputCapabilityError as error:
        return _refusal(error)
    return {'state': 'done' if verdict['met'] else 'unconfirmed',
            'summary': ('Typed %d characters into %s in %s' % (len(text), target['role'], target['window'] or app))
                       if verdict['met'] else 'The control accepted the text but the change was not confirmed',
            'verification': {'met': verdict['met'],
                             'evidence': 'The control was re-read over a second AT-SPI connection and its text '
                                         'matches the expected result' if verdict['met'] else
                                         'The re-read text does not match what was requested'},
            'cards': [{'title': target['name'] or target['role'],
                       'text': '%s · %s · node %s' % (target['window'] or app, target['role'], node),
                       'evidence': 'AT-SPI EditableText %s; %d characters before, %d after'
                                   % (mode, result['characters_before'], result['characters_after'])}]}
