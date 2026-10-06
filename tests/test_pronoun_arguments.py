"""A pronoun is not an argument.

Measured on 2026-10-03 over `experiments/router-ood/fixture.jsonl` (225 utterances):
past the two gates that exist in `service.py` — the four hardcoded clarification
phrasings and the open/read reference resolver — the deterministic vocabulary
committed to an action on 23 requests it should not have, and ten of those carried
an argument that named nothing at all. `'отвори го'` became `open_app(app='го')`,
an application named after the Macedonian accusative clitic.

Succeeding is what makes this dangerous: a match here stops the request ever
reaching a layer that could ask which one was meant.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-pronoun-arguments')

from aries.workspace import capabilities


async def test_an_argument_made_only_of_pronouns_is_declined():
    for request in ('отвори го', 'избриши го', 'прочитај ми го', 'инсталирај го',
                    'отвори ги двете', 'пушти ја другата',
                    'open that one', 'install it', 'open both'):
        check('declined so it can be asked about: ' + request,
              capabilities.recognize(request) is None)


async def test_a_demonstrative_plus_a_common_noun_names_nothing():
    for request in ('пушти ја онаа песна', 'отвори ја таа папка'):
        check('declined: ' + request, capabilities.recognize(request) is None)
    # Two words at most, and only because a longer phrase does identify something.
    found = capabilities.recognize('пушти ја таа песна од Лозано')
    check('a demonstrative with real content still resolves',
          bool(found) and found['capability'] == 'play_music'
          and 'Лозано' in found['args']['query'])


async def test_the_guard_costs_nothing_that_names_something():
    """The same 100 actionable utterances matched 49 times before the guard and 49
    after. These are the shapes most at risk of being caught by mistake."""
    cases = {
        'open the calculator': 'open_app',          # the English article is not a demonstrative
        'вклучи го firefox': 'open_app',            # clitic beside the verb, real target after
        'отвори го youtube': 'open_url',
        'прочитај го фајлот ~/Documents/proba.txt': 'read_file',
        'намали го звукот': 'set_volume',
        'избриши ја папката ~/Documents': 'trash_file',
    }
    for request, expected in cases.items():
        found = capabilities.recognize(request)
        check(f'{request!r} still recognised as {expected}',
              bool(found) and found['capability'] == expected)


async def test_free_text_arguments_are_left_alone():
    """`content` and `task` are not names. "create file note.txt :: it" is a
    perfectly good instruction and must not be declined for containing a pronoun."""
    found = capabilities.recognize('create file ~/Documents/aries-pronoun.txt :: it')
    check('file content may be a pronoun',
          bool(found) and found['capability'] == 'create_file' and found['args']['content'] == 'it')


async def test_the_judgement_is_about_naming_not_about_word_lists():
    check('an empty argument is not a pronoun argument', not capabilities.names_nothing(''))
    check('a path is not a pronoun argument', not capabilities.names_nothing('~/Documents/x.txt'))
    check('a bare clitic is', capabilities.names_nothing('го'))
    check('two clitics are', capabilities.names_nothing('ми го'))
    check('a demonstrative and a common noun are', capabilities.names_nothing('таа папка'))
    check('three words are not caught by the demonstrative clause',
          not capabilities.names_nothing('таа папка Documents'))
    check('digits and punctuation alone do not qualify', not capabilities.names_nothing('42'))


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
