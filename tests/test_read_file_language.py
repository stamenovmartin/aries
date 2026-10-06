"""File command words must not become part of a user-supplied path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-read-file-language')
from aries.workspace.capabilities import recognize


def test_file_path_boundaries():
    for prefix in ('read file', 'прочитај фајл', 'прочитај', 'procitaj fajl', 'procitaj'):
        for path in ('/tmp/fajl', '~/Documents/белешки.txt', '/tmp/фајл со празни места.txt'):
            for supplied in (path, '"' + path + '"'):
                actual = recognize(prefix + ' ' + supplied)
                check(prefix + ' ' + supplied,
                      actual == {'capability': 'read_file', 'args': {'path': path}})


def test_screen_and_policy_targets_remain_distinct():
    for text in ('прочитај го екранот', 'procitaj ekranot', 'read screen'):
        check('screen stays screen: ' + text, recognize(text)['capability'] == 'read_screen')
    for prefix in ('прочитај фајл', 'procitaj fajl'):
        check('policy receives the unchanged protected target: ' + prefix,
              recognize(prefix + ' /etc/shadow')['args']['path'] == '/etc/shadow')


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
