"""Validate fixture.jsonl and print counts. Touches no ARIES code and runs no router."""
import json, pathlib
from collections import Counter

rows = [json.loads(line) for line in
        pathlib.Path(__file__).with_name('fixture.jsonl').read_text().splitlines() if line.strip()]
assert len({r['id'] for r in rows}) == len(rows), 'duplicate id'
assert len({' '.join(r['utterance'].casefold().split()) for r in rows}) == len(rows), 'duplicate utterance'
assert all(set(r) <= {'id', 'klass', 'utterance', 'note'} and r['utterance'].strip() for r in rows)
assert all(r['klass'] in {'actionable', 'ambiguous', 'out_of_scope', 'unsafe'} for r in rows)
print(f'{len(rows)} rows ok, {sum(1 for r in rows if r.get("note"))} noted,', dict(Counter(r['klass'] for r in rows)))
