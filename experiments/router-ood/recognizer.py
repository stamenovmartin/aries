"""The cheapest half of the abstention question, with no model in the loop.

`capabilities.recognize()` is a pure function and it runs BEFORE any planner. If
it matches, the request never reaches a layer that could ask a question — so
whatever it matches, it has already decided to act on. Running the fixture
through it therefore measures something the router cannot: how often ARIES
commits to an action on an utterance that does not name one.

Deterministic, no database, no GPU, no network. Run it as often as you like.
"""
import json, pathlib, sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
for p in (ROOT / 'vendor' / 'agentic-core', ROOT / 'vendor', ROOT):
    sys.path.insert(0, str(p))
from aries.workspace import capabilities                      # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
rows = [json.loads(line) for line in (HERE / 'fixture.jsonl').open() if line.strip()]

out, counts = [], Counter()
for row in rows:
    match = capabilities.recognize(row['utterance'])
    record = dict(row, matched=bool(match),
                  capability=(match or {}).get('capability'),
                  args=(match or {}).get('args'))
    out.append(record)
    counts[(row['klass'], bool(match))] += 1

print(f'{"class":14s} {"n":>4s} {"commits to an action":>22s}')
for klass in ('actionable', 'ambiguous', 'out_of_scope', 'unsafe'):
    yes, no = counts[(klass, True)], counts[(klass, False)]
    if yes + no:
        print(f'{klass:14s} {yes+no:4d} {yes:12d} / {yes+no:<4d} ({yes/(yes+no)*100:3.0f}%)')

# A pronoun is not an argument. These are the cases where the regex captured a
# clitic or a determiner and handed it on as an application name, a file path or
# a search query — the request never reaches anything that could ask which one.
PRONOUNS = {'го', 'ја', 'ги', 'ме', 'ми', 'му', 'им', 'се', 'тоа', 'тој', 'таа', 'тие',
            'овој', 'оваа', 'ова', 'онаа', 'оној', 'она', 'другата', 'другиот', 'другото',
            'двете', 'обата', 'нешто', 'сето', 'тука', 'таму', 'it', 'that', 'this',
            'one', 'both', 'them', 'something', 'anything', 'the', 'other', 'same', 'all'}


def only_pronouns(value):
    words = [w for w in str(value).casefold().replace('.', ' ').split() if w]
    return bool(words) and all(w in PRONOUNS for w in words)


print('\nAn argument made entirely of pronouns or determiners:')
bad = 0
for record in out:
    for name, value in (record['args'] or {}).items():
        if only_pronouns(value):
            bad += 1
            print(f'  [{record["klass"]:12s}] {record["utterance"]!r}'
                  f'  ->  {record["capability"]}({name}={value!r})')
            break
print(f'\n{bad} of {len(rows)} utterances have an action committed on a pronoun.')
(HERE / 'recognizer.json').write_text(json.dumps(
    {'n': len(out), 'pronoun_arguments': bad, 'results': out}, ensure_ascii=False, indent=2))
print(f'written {HERE / "recognizer.json"}')
