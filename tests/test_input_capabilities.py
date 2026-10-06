"""Clipboard round trips, and the guards that stop ARIES typing into the wrong thing.

No test here needs a particular application to be open, and none spawns a window:
a test suite that steals the keyboard focus is a test suite that eats whatever the
person was typing. The guard logic is therefore driven with fake AT-SPI nodes, the
way tests/test_accessibility.py drives the read-only bridge, and the live clipboard
path saves the real clipboard and puts it back.
"""
import asyncio
import hashlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-input-capabilities')
from aries.workspace import input_capabilities as ic
from aries.workspace.registry import Registry


# --- fake AT-SPI, enough of it to run the real guards --------------------------

class States:
    def __init__(self, flags):
        self.flags = set(flags)

    def contains(self, flag):
        return flag in self.flags


class Node:
    def __init__(self, name, role='application', children=(), states=(), pid=4242,
                 text=None, editable=False, selections=0, caret=0):
        self.name, self.role, self.children, self.states, self.pid = name, role, list(children), states, pid
        self.text, self.editable, self.selections, self.caret = text, editable, selections, caret

    def get_name(self):
        return self.name

    def get_role_name(self):
        return self.role

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index] if 0 <= index < len(self.children) else None

    def get_process_id(self):
        return self.pid

    def get_state_set(self):
        return States(self.states)

    def get_text_iface(self):
        return self if self.text is not None else None

    def get_editable_text_iface(self):
        return self if self.editable else None


class Text:
    @staticmethod
    def get_character_count(node):
        return len(node.text)

    @staticmethod
    def get_text(node, start, end):
        return node.text[start:end]

    @staticmethod
    def get_caret_offset(node):
        return node.caret

    @staticmethod
    def get_n_selections(node):
        return node.selections


class Editable:
    @staticmethod
    def set_text_contents(node, text):
        node.text = text
        return True

    @staticmethod
    def insert_text(node, position, text, length):
        node.text = node.text[:position] + text + node.text[position:]
        return True


class StateType:
    EDITABLE, FOCUSED, ACTIVE, SENSITIVE, SHOWING, VISIBLE = 'EDITABLE', 'FOCUSED', 'ACTIVE', 'SENSITIVE', 'SHOWING', 'VISIBLE'


class FakeAtspi:
    StateType, Text, EditableText = StateType, Text, Editable

    def __init__(self, desktop):
        self.desktop = desktop

    def get_desktop(self, index):
        return self.desktop


def worker_with(desktop):
    """The real worker body, wired to a fake accessibility tree."""
    namespace = {}
    exec(compile(ic._WORKER_BODY, '<worker>', 'exec'), namespace)
    namespace['atspi'] = lambda: FakeAtspi(desktop)
    return namespace


LIVE = {'EDITABLE', 'FOCUSED', 'SENSITIVE', 'SHOWING', 'VISIBLE'}


def one_app(**entry):
    """A desktop holding one app, one active window and one text control at 0/0/0."""
    fields = dict(role='text', states=LIVE, text='', editable=True)
    fields.update(entry)
    control = Node('Message body', **fields)
    window = Node('Compose', role='frame', states={'ACTIVE'}, children=[control])
    return Node('desktop', children=[Node('python3', children=[window])]), control


def reviewed(**overrides):
    payload = {'app': 'python3', 'node': '0/0/0', 'pid': 4242, 'role': 'text',
               'name': 'Message body', 'text': 'здраво', 'mode': 'insert'}
    payload.update(overrides)
    return payload


# --- contract -----------------------------------------------------------------

def test_registration_contract():
    registry = Registry()
    ic.register(registry)
    names = {'input.clipboard_read', 'input.clipboard_write', 'input.editable_targets', 'input.type_text'}
    check('all four capabilities register', {c['name'] for c in registry.describe_allowed()} == names)
    reads = [registry.get(n) for n in ('input.clipboard_read', 'input.editable_targets')]
    check('observations are read-effect and need no approval',
          all(c.effect == 'read' and not c.requires_approval for c in reads))
    writes = [registry.get(n) for n in ('input.clipboard_write', 'input.type_text')]
    check('both mutations require approval and declare an input effect',
          all(c.requires_approval and c.effect == 'input' for c in writes))
    check('typing is the highest risk level of the set',
          registry.get('input.type_text').risk_level == 'high')
    check('every capability publishes a JSON schema',
          all(isinstance(c['input_schema'], dict) for c in registry.describe_allowed()))
    check('registering twice is refused rather than silently shadowing',
          _raises(lambda: ic.register(registry), ValueError))


def _raises(call, kind):
    try:
        call()
    except kind:
        return True
    except Exception:
        return False
    return False


def test_input_validation():
    good = ic.TypeInput.model_validate(reviewed())
    check('a reviewed target validates and defaults are explicit', good.mode == 'insert')
    for bad, why in [({'node': ''}, 'empty node'), ({'node': 'a/b'}, 'non-numeric node'),
                     ({'node': '1//2'}, 'empty path element'),
                     ({'node': '/'.join(['1'] * 21)}, 'path deeper than twenty'),
                     ({'mode': 'overwrite'}, 'unknown mode'), ({'text': ''}, 'empty text'),
                     ({'text': 'x' * (ic.MAX_TYPE_CHARS + 1)}, 'text past the bound'),
                     ({'pid': 0}, 'impossible pid')]:
        check('rejected: ' + why, _raises(lambda b=bad: ic.TypeInput.model_validate(reviewed(**b)), Exception))
    check('unexpected arguments are forbidden, not ignored',
          _raises(lambda: ic.TypeInput.model_validate(reviewed(force=True)), Exception))
    check('clipboard text is bounded',
          _raises(lambda: ic.ClipboardWriteInput.model_validate({'text': 'x' * (ic.MAX_CLIPBOARD_BYTES + 1)}), Exception))


# --- the guards, on the real worker code --------------------------------------

def test_reviewed_identity_must_still_hold():
    desktop, _ = one_app()
    resolve = worker_with(desktop)['resolve']
    Atspi = FakeAtspi(desktop)
    check('an unchanged target resolves', resolve(Atspi, reviewed())[1] == 'text')
    for bad, why in [({'app': 'ptyxis'}, 'another application now at that position'),
                     ({'pid': 9999}, 'the process changed after review'),
                     ({'role': 'entry'}, 'the role changed after review'),
                     ({'name': 'Subject'}, 'the accessible name changed after review'),
                     ({'node': '0/0/7'}, 'the control no longer exists'),
                     ({'node': '/'.join(['0'] * 21)}, 'an over-long path')]:
        check('refused: ' + why, _raises(lambda b=bad: resolve(Atspi, reviewed(**b)), ValueError))
    check('the accessible name is NOT re-checked on a read-back, because some '
          'controls derive it from their value',
          resolve(Atspi, reviewed(name='changed by the write'), check_name=False)[1] == 'text')


def test_never_types_into_a_password_field():
    secret = Node('Password', role='password text', states=LIVE, text='', editable=True)
    window = Node('Unlock', role='frame', states={'ACTIVE'}, children=[secret])
    desktop = Node('desktop', children=[Node('python3', children=[window])])
    namespace = worker_with(desktop)
    check('a password control is refused even when fully addressed',
          _raises(lambda: namespace['resolve'](FakeAtspi(desktop), reviewed(role='password text', name='Password')),
                  ValueError))
    listed = namespace['targets']({'app': 'python3'})
    check('a password control is never listed, so it can never be chosen',
          listed['targets'] == [] and listed['protected_skipped'] == 1)
    check('its name never leaves the worker', 'Password' not in str(listed['targets']))


def test_typing_refuses_every_unsafe_control():
    for entry, window_states, code, why in [
            ({'editable': False}, {'ACTIVE'}, 'NOT_EDITABLE', 'no EditableText interface, as on a terminal'),
            ({'text': None}, {'ACTIVE'}, 'NOT_EDITABLE', 'no Text interface to read the result back from'),
            ({'states': LIVE - {'EDITABLE'}}, {'ACTIVE'}, 'NOT_EDITABLE', 'a label rather than a field'),
            ({'states': LIVE - {'SENSITIVE'}}, {'ACTIVE'}, 'NOT_EDITABLE', 'a disabled field'),
            ({'states': LIVE - {'FOCUSED'}}, {'ACTIVE'}, 'NOT_FOCUSED', 'not the control being worked in'),
            ({}, set(), 'WINDOW_NOT_ACTIVE', 'a background window'),
            ({'selections': 1}, {'ACTIVE'}, 'AMBIGUOUS', 'a live selection an insert would not replace')]:
        desktop, _ = one_app(**entry)
        desktop.children[0].children[0].states = window_states
        result = worker_with(desktop)['type_text'](reviewed())
        check('refused (%s): %s' % (code, why), result.get('code') == code and not result.get('ok'))


def test_insert_goes_to_the_caret_and_reports_a_checkable_digest():
    desktop, control = one_app(text='Dear Ana,\n\nSincerely', caret=11)
    result = worker_with(desktop)['type_text'](reviewed(text='ARIES beше тука'))
    expected = 'Dear Ana,\n\nARIES beше тукаSincerely'
    check('the text is inserted at the caret, not appended', control.text == expected)
    check('the reported digest is of the expected result',
          result['expected_sha256'] == hashlib.sha256(expected.encode()).hexdigest())
    check('what was observed immediately after is reported separately from what was accepted',
          result['accepted'] is True and result['landed'] is True
          and result['observed_sha256'] == result['expected_sha256'])
    check('the previous contents are reported as a digest, never as text',
          result['before_sha256'] == hashlib.sha256('Dear Ana,\n\nSincerely'.encode()).hexdigest()
          and 'Sincerely' not in str(result))
    desktop, control = one_app(text='old', selections=1)
    replaced = worker_with(desktop)['type_text'](reviewed(mode='replace', text='нов текст'))
    check('replace is allowed with a selection and overwrites everything',
          control.text == 'нов текст' and replaced['landed'] is True)


def test_a_write_that_did_not_land_is_not_reported_as_success():
    desktop, control = one_app(text='')
    namespace = worker_with(desktop)
    # An application that quietly filters or truncates input is the realistic
    # failure: the AT-SPI call still returns True.
    namespace['atspi'] = lambda: type('A', (FakeAtspi,), {
        'EditableText': type('E', (), {'set_text_contents': staticmethod(lambda n, t: True),
                                       'insert_text': staticmethod(lambda n, p, t, l: True)})})(desktop)
    result = namespace['type_text'](reviewed(text='dropped'))
    check('accepted is reported, landed is not', result['accepted'] is True and result['landed'] is False)
    check('the observed digest differs from the expected one',
          result['observed_sha256'] != result['expected_sha256'])


def test_targets_reports_what_makes_a_control_typeable():
    desktop, _ = one_app(text='abc')
    listed = worker_with(desktop)['targets']({'app': 'python3'})
    row = listed['targets'][0]
    check('one editable control is found with its full reviewable identity',
          listed['matched'] == 1 and row['node'] == '0/0/0' and row['pid'] == 4242 and row['role'] == 'text')
    check('the window it belongs to and whether that window is active are reported',
          row['window'] == 'Compose' and row['window_active'] is True)
    check('typeable is the conjunction the capability actually enforces', row['typeable'] is True)
    desktop, _ = one_app(text='abc', selections=2)
    row = worker_with(desktop)['targets']({'app': 'python3'})['targets'][0]
    check('a control holding a selection is listed but not typeable',
          row['selections'] == 2 and row['typeable'] is False)
    empty = worker_with(Node('desktop', children=[Node('ptyxis')]))['targets']({'app': 'python3'})
    check('an application that is not running yields no targets and no error',
          empty['matched'] == 0 and empty['targets'] == [])
    aliased = worker_with(Node('desktop', children=[Node('code')]))['targets']({'app': 'VS Code'})
    check('the same application aliases the read-only bridge accepts work here too',
          aliased['matched'] == 1)


# --- the live bridge and the live clipboard -----------------------------------

async def test_worker_bridge_surfaces_failure_as_a_refusal():
    if not Path('/usr/bin/python3').exists():
        check('skipped — no system interpreter to bridge to (gi lives there, not in .venv)', True)
        return
    try:
        await ic.worker('no_such_mode', {})
        check('an unknown worker mode raises rather than returning a fake result', False)
    except ic.InputCapabilityError as error:
        check('an unknown worker mode raises InputCapabilityError with a code',
              error.code == 'CAPABILITY_UNAVAILABLE')
    try:
        await ic.worker('type', reviewed(app='no-such-application-is-running'))
        check('typing into an application that is not running is refused', False)
    except ic.InputCapabilityError as error:
        check('typing into an application that is not running is refused',
              error.code in {'TARGET_NOT_FOUND', 'CAPABILITY_UNAVAILABLE'})


async def test_editable_targets_never_invents_a_target():
    try:
        observed = await ic.editable_targets({'app': 'no-such-application-is-running'}, {})
    except ic.InputCapabilityError as error:
        check('skipped — accessibility unavailable: ' + error.code, True)
        return
    check('no match means no targets, reported as such',
          observed['matched'] == 0 and observed['targets'] == [] and 'observed_at' in observed)
    refusal = await ic.voice_type_text('no-such-application-is-running', '0/0/0', 'insert', 'x')
    check('the spoken form refuses a node it did not just survey', refusal['state'] == 'failed')


async def test_clipboard_round_trip_and_the_users_clipboard_is_put_back():
    """Read, write, verify by reading back, then restore — in that order, always."""
    try:
        original = await ic.clipboard_read({}, {})
    except ic.InputCapabilityError as error:
        # Mutter refuses a RemoteDesktop session while the lock shield is up.
        check('skipped — GNOME clipboard unavailable (' + error.code + ')', True)
        return
    check('a clipboard read reports its size, type and digest together',
          original['sha256'] == hashlib.sha256(original['text'].encode()).hexdigest()
          and original['bytes'] <= ic.MAX_CLIPBOARD_BYTES)
    probe = 'ARIES clipboard проба — 42\nsecond line'
    restored = None
    try:
        written = await ic.clipboard_write({'text': probe}, {})
        verdict = await ic.verify_clipboard_write({'text': probe}, written, {})
        check('Mutter asked for the offered bytes, so the value is cached and outlives the writer',
              bool(written['served_mime_types']))
        check('the write is verified by reading it back from a fresh session', verdict['met'] is True)
        check('the read-back text is exactly what was written, Cyrillic and newline included',
              verdict['data']['text'] == probe)
        check('what was destroyed is reported as a digest and a length, never as text',
              written['replaced']['sha256'] == original['sha256'] and probe not in str(written['replaced']))
    finally:
        if original['has_text']:
            back = await ic.clipboard_write({'text': original['text']}, {})
            restored = await ic.verify_clipboard_write({'text': original['text']}, back, {})
    if original['has_text']:
        check("the user's own clipboard is back, byte for byte",
              restored is not None and restored['met'] and restored['data']['sha256'] == original['sha256'])
    else:
        check('skipped — the clipboard held no text to restore', True)


async def test_clipboard_read_will_not_vouch_for_a_stale_observation():
    try:
        await ic.clipboard_read({}, {})
    except ic.InputCapabilityError as error:
        check('skipped — GNOME clipboard unavailable (' + error.code + ')', True)
        return
    stale = {'sha256': hashlib.sha256(b'something nobody copied').hexdigest()}
    verdict = await ic.verify_clipboard_read({}, stale, {})
    check('a digest that no longer matches the clipboard is reported unmet, not smoothed over',
          verdict['met'] is False and verdict['data']['changed_since_read'] is True)
    check('the verifier returns a fresh independent observation as its evidence',
          verdict['type'] == 'clipboard_state' and 'observed_at' in verdict['data'])


def test_the_text_never_travels_in_argv():
    # argv is world-readable through /proc, so a clipboard payload or a dictated
    # sentence must not be an argument to the worker process.
    check('the worker takes only a mode on the command line',
          "'-I', '-c', _WORKER, mode" in Path(ic.__file__).read_text())
    check('payloads are written to the worker on stdin',
          'proc.communicate(json.dumps(payload).encode())' in Path(ic.__file__).read_text())


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
