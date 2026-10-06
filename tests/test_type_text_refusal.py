"""Every way `input.type_text` could lose characters quietly, turned into a refusal.

WHY THIS FILE IS SEPARATE FROM tests/test_input_capabilities.py
---------------------------------------------------------------
That file proves the guards that decide WHETHER to write: identity, focus,
editability, password fields. This one is about what happens AFTER the write is
accepted, which is a different failure and the one that had been reported as a
success. Wayland gives ARIES no global synthetic input, so typing is AT-SPI
`EditableText` or nothing; and `Atspi.EditableText.insert_text` returns TRUE in
every one of the cases below while the characters are not in the control
afterwards. Measured relatives of the same defect are already written down in
`aries/workspace/keyboard.py`: Mutter accepts a Cyrillic keysym on a Latin
layout, writes nothing, and reports no error.

No test here opens a window or touches the real accessibility bus. A test suite
that steals the keyboard focus eats whatever the person was typing, so the real
worker body is executed against a fake AT-SPI tree — the same technique
tests/test_input_capabilities.py and tests/test_accessibility.py use.

The flag is ARIES_TYPE_STRICT, default on. The last test here runs with it off
and shows the old shape returning, so the Part B ablation has something to
compare against.
"""
import asyncio
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module

bootstrap('aries-type-text-refusal')
from aries import flags
from aries.workspace import input_capabilities as ic


# --- just enough fake AT-SPI to run the real worker ---------------------------

class States:
    def __init__(self, flags_):
        self.flags = set(flags_)

    def contains(self, flag):
        return flag in self.flags


class Node:
    def __init__(self, name, role='application', children=(), states=(), pid=4242,
                 text=None, editable=True, selections=0, caret=0):
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
    """An honest toolkit: it stores exactly what it was given."""

    @staticmethod
    def set_text_contents(node, text):
        node.text = text
        return True

    @staticmethod
    def insert_text(node, position, text, length):
        node.text = node.text[:position] + text + node.text[position:]
        return True


class StateType:
    EDITABLE, FOCUSED, ACTIVE, SENSITIVE, SHOWING, VISIBLE = (
        'EDITABLE', 'FOCUSED', 'ACTIVE', 'SENSITIVE', 'SHOWING', 'VISIBLE')


class FakeAtspi:
    StateType, Text, EditableText = StateType, Text, Editable

    def __init__(self, desktop):
        self.desktop = desktop

    def get_desktop(self, index):
        return self.desktop

    @staticmethod
    def set_timeout(a, b):
        return None


LIVE ={'EDITABLE', 'FOCUSED', 'SENSITIVE', 'SHOWING', 'VISIBLE'}


def one_app(**entry):
    fields = dict(role='text', states=LIVE, text='', editable=True)
    fields.update(entry)
    control = Node('Message body', **fields)
    window = Node('Compose', role='frame', states={'ACTIVE'}, children=[control])
    return Node('desktop', children=[Node('python3', children=[window])]), control


def reviewed(**overrides):
    payload = {'app': 'python3', 'node': '0/0/0', 'pid': 4242, 'role': 'text',
               'name': 'Message body', 'text': 'hello', 'mode': 'insert', 'strict': True}
    payload.update(overrides)
    return payload


def worker_with(desktop, editable=None):
    """The real worker source, wired to a fake tree and an optional hostile toolkit."""
    namespace = {}
    exec(compile(ic._WORKER_BODY, '<worker>', 'exec'), namespace)
    fake = type('A', (FakeAtspi,), {'EditableText': editable} if editable else {})(desktop)
    namespace['atspi'] = lambda: fake
    return namespace


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


# --- refused BEFORE anything is written --------------------------------------

def test_text_that_cannot_survive_the_write_is_refused_before_the_write():
    """Each of these is a measured or structural silent loss, so none of them is
    allowed to begin. "Nothing was typed" has to be true, and is checked."""
    cases = [
        ('a\x00b', 'text', 'NUL', 'InsertText is a C call on a NUL-terminated string'),
        ('line\x07one', 'text', 'a C0 control character', 'a text buffer discards it'),
        ('first\nsecond', 'entry', 'a line break into a single-line entry', 'GtkEntry drops it'),
        ('first\rsecond', 'search box', 'a carriage return into a search box', 'same mechanism'),
    ]
    for text, role, what, because in cases:
        desktop, control = one_app(role=role, text='before')
        result = worker_with(desktop)['type_text'](reviewed(text=text, role=role))
        check('refused before writing: %s (%s)' % (what, because),
              result.get('ok') is False and result.get('code') == 'TEXT_NOT_TYPEABLE')
        check('  and the control was genuinely left alone', control.text == 'before')
        check('  and the refusal says why in a sentence a person can act on',
              len(result.get('message', '')) > 40 and 'Nothing was typed' in result['message'])
        check('  and the refusal never quotes the text back',
              text.strip() not in result.get('message', ''))

    desktop, control = one_app(role='text', text='before')
    ok = worker_with(desktop)['type_text'](reviewed(text='two\nlines', role='text'))
    check('a line break into a MULTI-line control is still allowed — the rule is '
          'about what the control drops, not about newlines',
          ok.get('ok') is True and control.text == 'two\nlinesbefore')


# --- refused AFTER a write the toolkit accepted ------------------------------

def test_a_write_the_toolkit_accepted_but_did_not_keep_is_a_refusal():
    """The realistic failure: an application filters or truncates its own input
    and AT-SPI still returns True. This is the case that used to come back as
    {'ok': True, 'landed': False} — a success report for text nobody received."""

    class Filtering:
        @staticmethod
        def insert_text(node, position, text, length):
            node.text = node.text[:position] + ''.join(c for c in text if c.isascii()) + node.text[position:]
            return True

        @staticmethod
        def set_text_contents(node, text):
            node.text = text
            return True

    desktop, control = one_app(text='')
    result = worker_with(desktop, editable=Filtering)['type_text'](reviewed(text='café naïve'))
    check('a partially filtered insert is refused, not reported as done',
          result.get('ok') is False and result.get('code') == 'TEXT_NOT_LANDED')
    check('the refusal carries the arithmetic: characters sent, held before, held after',
          all(piece in result['message'] for piece in ['12 characters were sent', 'from 0 to 10']))
    check('the refusal states that the control WAS modified and not restored',
          'WAS modified and ARIES did not restore it' in result['message'])
    check('the observation travels with the refusal rather than being replaced by it',
          result['accepted'] is True and result['landed'] is False
          and result['characters_before'] == 0 and result['characters_after'] == 10
          and result['expected_sha256'] != result['observed_sha256'])
    check('neither the old nor the new text appears anywhere in the refusal',
          'cafe' not in result['message'] and 'naive' not in result['message'])

    class Dropping:
        @staticmethod
        def insert_text(node, position, text, length):
            return True                       # accepted, stored nothing

        @staticmethod
        def set_text_contents(node, text):
            return True

    desktop, control = one_app(text='unchanged')
    result = worker_with(desktop, editable=Dropping)['type_text'](reviewed(text='dropped'))
    check('a write that landed nothing at all is refused',
          result.get('ok') is False and result.get('code') == 'TEXT_NOT_LANDED')
    check('and it says the control was NOT modified, which is a different situation',
          'The control was NOT modified.' in result['message'] and control.text == 'unchanged')

    class Refusing:
        @staticmethod
        def insert_text(node, position, text, length):
            return False

        @staticmethod
        def set_text_contents(node, text):
            return False

    desktop, control = one_app(text='unchanged')
    result = worker_with(desktop, editable=Refusing)['type_text'](reviewed(text='x'))
    check('a toolkit that returns false is a refusal with its own code, not a generic one',
          result.get('ok') is False and result.get('code') == 'TEXT_REJECTED'
          and control.text == 'unchanged')


def test_replace_is_held_to_the_same_standard_as_insert():
    class Truncating:
        @staticmethod
        def set_text_contents(node, text):
            node.text = text[:4]
            return True

        @staticmethod
        def insert_text(node, position, text, length):
            return True

    desktop, control = one_app(text='old', selections=1)
    result = worker_with(desktop, editable=Truncating)['type_text'](
        reviewed(mode='replace', text='a much longer replacement'))
    check('a replace that was truncated is refused',
          result.get('ok') is False and result.get('code') == 'TEXT_NOT_LANDED'
          and result['mode'] == 'replace')
    check('the truncation is reported as a number, not as a mood',
          '25 characters were sent' in result['message'] and 'from 3 to 4' in result['message'])


def test_a_write_that_landed_exactly_is_still_a_success():
    """A refusal rule that cannot say yes is useless. This is the control case."""
    desktop, control = one_app(text='Dear Ana,\n\nSincerely', caret=11)
    result = worker_with(desktop)['type_text'](reviewed(text='ARIES was here'))
    expected = 'Dear Ana,\n\nARIES was hereSincerely'
    check('an exact landing is ok=True with landed=True', result.get('ok') is True and result['landed'])
    check('and the digest it publishes is of what is really in the control',
          control.text == expected and result['observed_sha256'] == sha(expected)
          and result['expected_sha256'] == sha(expected))
    check('the previous contents are reported as a digest, never as text',
          result['before_sha256'] == sha('Dear Ana,\n\nSincerely') and 'Sincerely' not in str(result))


# --- the parent process: refusal, not silence, and not a half-measure ---------

def test_the_capability_raises_a_coded_refusal_rather_than_returning_a_flag():
    """`type_into` is what the registry and the spoken surface call. A refusal
    has to arrive there as an exception with a code, because a returned dict
    carrying landed=False is exactly what the planner then reports as done."""
    calls = []

    async def fake_worker(mode, payload, *, timeout=10):
        calls.append(payload)
        row = {'ok': False, 'code': 'TEXT_NOT_LANDED', 'message': 'the application filtered it',
               'landed': False, 'accepted': True}
        raise ic.InputCapabilityError(row['code'], row['message'])

    original = ic.worker
    ic.worker = fake_worker
    try:
        args = {'app': 'gedit', 'node': '0/1/2', 'pid': 42, 'role': 'text', 'name': 'Body',
                'text': 'hello', 'mode': 'insert'}
        try:
            asyncio.run(ic.type_into(dict(args), {}))
            check('a refusal from the worker reaches the capability as an error', False)
        except ic.InputCapabilityError as error:
            check('a refusal from the worker reaches the capability as an error',
                  error.code == 'TEXT_NOT_LANDED' and error.retryable is False)
        check('the capability tells the worker which rule is in force, because the '
              'worker runs under /usr/bin/python3 -I and cannot read the flag itself',
              calls and calls[0]['strict'] is True)

        # The spoken path builds its own arguments and so was never bounded by
        # MAX_TYPE_CHARS. An over-long dictation is now a refusal with a number.
        calls.clear()
        try:
            asyncio.run(ic.type_into({**args, 'text': 'x' * (ic.MAX_TYPE_CHARS + 1)}, {}))
            check('text past the %d-character bound is refused' % ic.MAX_TYPE_CHARS, False)
        except ic.InputCapabilityError as error:
            check('text past the %d-character bound is refused before a worker is spawned'
                  % ic.MAX_TYPE_CHARS,
                  error.code == 'TEXT_NOT_TYPEABLE' and not calls)
    finally:
        ic.worker = original


def test_the_spoken_surface_reports_a_refusal_as_a_refusal():
    """`voice_type_text` is the voice and typed-command surface. Its states are
    done / unconfirmed / failed / held, and a lost write must be `failed` with
    the reason in the summary — never `done`."""
    async def scenario():
        async def survey(args, ctx):
            return {'app': 'gedit', 'matched': 1, 'scanned': 1, 'truncated': False, 'errors': 0,
                    'protected_skipped': 0,
                    'targets': [{'node': '0/1/2', 'pid': 42, 'role': 'text', 'name': 'Body',
                                 'window': 'Untitled', 'window_active': True, 'focused': True,
                                 'enabled': True, 'characters': 0, 'selections': 0, 'typeable': True}]}

        async def refusing_worker(mode, payload, *, timeout=10):
            if mode == 'targets':
                return await survey({}, {})
            raise ic.InputCapabilityError(
                'TEXT_NOT_LANDED', 'The insert was accepted but the control does not hold what was '
                                   'requested: 5 characters were sent, the control went from 0 to 2.')

        original_targets, original_worker = ic.editable_targets, ic.worker
        ic.editable_targets, ic.worker = survey, refusing_worker
        try:
            return await ic.voice_type_text('gedit', '0/1/2', 'insert', 'hello')
        finally:
            ic.editable_targets, ic.worker = original_targets, original_worker

    outcome = asyncio.run(scenario())
    check('a lost write is state=failed on the spoken surface, not done',
          outcome['state'] == 'failed')
    check('and the reason, with its numbers, is what the person is told',
          '5 characters were sent' in outcome['summary'])
    check('no verification is claimed for a write that was refused', 'verification' not in outcome)


# --- the flag ----------------------------------------------------------------

def test_the_flag_is_registered_and_turning_it_off_restores_the_old_shape():
    check('ARIES_TYPE_STRICT is in the one flag registry, default on',
          'ARIES_TYPE_STRICT' in flags.FLAGS and flags.FLAGS['ARIES_TYPE_STRICT'][0] is True
          and flags.describe()['flags']['ARIES_TYPE_STRICT']['on'] is True)

    class Dropping:
        @staticmethod
        def insert_text(node, position, text, length):
            return True

        @staticmethod
        def set_text_contents(node, text):
            return True

    desktop, _ = one_app(text='')
    loose = worker_with(desktop, editable=Dropping)['type_text'](reviewed(text='dropped', strict=False))
    check('with the flag off the worker returns the pre-A10 shape, so Part B can '
          'measure both sides of the change',
          loose.get('ok') is True and loose['accepted'] is True and loose['landed'] is False)

    previous = os.environ.get('ARIES_TYPE_STRICT')
    os.environ['ARIES_TYPE_STRICT'] = '0'
    try:
        check('and the capability reads the flag from aries.flags rather than its own literal',
              ic.strict_typing() is False)
    finally:
        if previous is None:
            os.environ.pop('ARIES_TYPE_STRICT')
        else:
            os.environ['ARIES_TYPE_STRICT'] = previous
    check('restored to on', ic.strict_typing() is True)


if __name__ == '__main__':
    raise SystemExit(run_module(sys.modules[__name__]))
