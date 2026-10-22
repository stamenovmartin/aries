"""ARIES_READ_PATH_STRICT: the legacy read_file route takes only the path token.

The defect (docs/AUDIT.md section 4a, goal dev-a-04): `(.+)$` after the verb took the
rest of the sentence as the path, the Macedonian words before it and the sentence
period after it included, so the goal failed at prepare with "is not an absolute
path" and the planner was never asked.

The rule under the flag, as tested here:
  * the path starts at the first `/` or `~/` in the capture; with no such token the
    route declines (recognize returns None) and the goal goes to the planner;
  * words before it are allowed only when they are filler ("ми го", "the", "file");
    anything else ("the summary in /dir") is a request ABOUT the path, so it declines;
  * the path ends at the longest prefix that exists, else at the first component that
    has an extension, else at the first whitespace;
  * a trailing . , ? ! ; : or ... is stripped only when the path with it does not exist
    and the path without it has an extension in its final component or exists;
  * a quoted path is taken verbatim.
Off, recognize is the frozen function.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-read-path-strict')
from aries.workspace.capabilities import recognize

FLAG = 'ARIES_READ_PATH_STRICT'


class flag:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.previous = os.environ.get(FLAG)
        os.environ[FLAG] = self.value

    def __exit__(self, *exc):
        if self.previous is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = self.previous


def path_of(text):
    found = recognize(text)
    if not found or found['capability'] != 'read_file':
        return None
    return found['args']['path']


DEV_A_04 = 'Прочитај ми го резимето во /home/stamenovmartin/Documents/ARIES-CIA-01/dev-a-04.'


def test_flag_is_registered_and_off_by_default():
    from aries import flags
    check('registered', FLAG in flags.FLAGS)
    check('default off', flags.FLAGS[FLAG][0] is False)


def test_off_keeps_the_frozen_capture():
    with flag('0'):
        check('dev-a-04 keeps words and period (old behaviour)',
              path_of(DEV_A_04) == 'ми го резимето во /home/stamenovmartin/Documents/ARIES-CIA-01/dev-a-04.')
        check('english trailing period kept (old behaviour)',
              path_of('Read file /tmp/x/notes.txt.') == '/tmp/x/notes.txt.')
        check('trailing words kept (old behaviour)',
              path_of('read file /tmp/x/notes.txt and tell me what it says')
              == '/tmp/x/notes.txt and tell me what it says')


def test_sentence_period_is_stripped():
    with flag('1'):
        check('english period', path_of('Read file /tmp/x/notes.txt.') == '/tmp/x/notes.txt')
        check('english question mark', path_of('read file /tmp/x/notes.txt?') == '/tmp/x/notes.txt')
        check('english comma', path_of('read file /tmp/x/notes.txt,') == '/tmp/x/notes.txt')
        check('macedonian period', path_of('Прочитај /tmp/x/белешки.txt.') == '/tmp/x/белешки.txt')
        check('macedonian with filler', path_of('Прочитај ми го /tmp/x/белешки.txt.') == '/tmp/x/белешки.txt')
        check('macedonian фајл', path_of('прочитај фајл ~/Documents/белешки.txt?') == '~/Documents/белешки.txt')
        check('latin macedonian', path_of('procitaj fajl /tmp/x/beleski.md.') == '/tmp/x/beleski.md')


def test_trailing_words_are_dropped():
    with flag('1'):
        check('english', path_of('read file /tmp/x/notes.txt and tell me what it says.') == '/tmp/x/notes.txt')
        check('macedonian', path_of('прочитај /tmp/x/белешки.txt и кажи ми што пишува') == '/tmp/x/белешки.txt')


def test_a_request_about_a_folder_goes_to_the_planner():
    with flag('1'):
        check('dev-a-04 declines', recognize(DEV_A_04) is None)
        check('english equivalent declines', recognize('read the summary in /tmp/x/dir.') is None
              or recognize('read the summary in /tmp/x/dir.')['capability'] != 'read_file')
        check('no path token declines', recognize('прочитај ја книгата') is None)
        from aries.workspace.service import plan
        steps = plan(DEV_A_04)
        check('service.plan routes dev-a-04 to agent_task',
              len(steps) == 1 and steps[0]['capability'] == 'agent_task')


def test_a_period_that_belongs_to_an_existing_name_stays():
    with flag('1'), tempfile.TemporaryDirectory() as tmp:
        dotted = os.path.join(tmp, 'archive.')
        Path(dotted).write_text('x')
        check('existing name ending in a period is kept', path_of('read file ' + dotted) == dotted)
        check('and with a sentence period after it, only that one goes',
              path_of('read file ' + dotted + '.') == dotted)
        bare = os.path.join(tmp, 'README')
        check('no extension, nothing exists: period kept', path_of('read file ' + bare + '.') == bare + '.')
        Path(bare).write_text('x')
        check('no extension, stripped name exists: period stripped', path_of('read file ' + bare + '.') == bare)
        spaced = os.path.join(tmp, 'my notes')
        Path(spaced).write_text('x')
        check('existing name with a space is kept whole', path_of('read file ' + spaced + '.') == spaced)


def test_existing_boundaries_still_hold_under_the_flag():
    with flag('1'):
        for prefix in ('read file', 'прочитај фајл', 'прочитај', 'procitaj fajl', 'procitaj'):
            for path in ('/tmp/fajl', '~/Documents/белешки.txt', '/tmp/фајл со празни места.txt'):
                for supplied in (path, '"' + path + '"'):
                    check(prefix + ' ' + supplied, path_of(prefix + ' ' + supplied) == path)
        check('protected target unchanged', path_of('прочитај фајл /etc/shadow') == '/etc/shadow')
        check('screen stays screen', recognize('прочитај го екранот')['capability'] == 'read_screen')


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
