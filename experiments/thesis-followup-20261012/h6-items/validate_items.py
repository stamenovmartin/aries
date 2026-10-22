#!/usr/bin/env python3
"""Validate the H6 request file before any measurement. Prints PASS/FAIL and counts, never the requests.

Checks:
- every row has exactly the fields id, utterance, klass, lang, author, written_at;
- ids are h6-0001 .. h6-0300, each used once;
- class counts are 100 actionable, 75 ambiguous, 62 out_of_scope, 63 unsafe;
- in every class, English and Macedonian each make up 40-60%;
- Macedonian rows contain Cyrillic and English rows contain none;
- no example rows;
- no utterance appears twice (case, spacing and final punctuation ignored);
- no utterance repeats one of the 225 requests of the frozen ARIES-FINAL-20261006 fixture.

Problems are reported by line number and kind only.

    python3 -I validate_items.py h6_requests.jsonl [--out validation.json]
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN_LABELS = HERE.parents[1] / 'thesis-final-20261006/semantic_labels.json'
FIELDS = {'id', 'utterance', 'klass', 'lang', 'author', 'written_at'}
COUNTS = {'actionable': 100, 'ambiguous': 75, 'out_of_scope': 62, 'unsafe': 63}
CYRILLIC = re.compile('[Ѐ-ӿ]')


def norm(text):
    return re.sub(r'\s+', ' ', str(text)).strip().rstrip('.!?…').casefold()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--out')
    cli = ap.parse_args()
    raw = Path(cli.file).read_bytes()
    problems, rows = [], []
    for n, line in enumerate(raw.decode('utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f'line {n}: not valid JSON')
            continue
        if not isinstance(row, dict):
            problems.append(f'line {n}: not a JSON object')
            continue
        row['_line'] = n
        rows.append(row)
        if row.get('example'):
            problems.append(f'line {n}: example row')
        if set(row) - {'_line'} != FIELDS:
            problems.append(f'line {n}: fields differ from {sorted(FIELDS)}')
        if row.get('klass') not in COUNTS:
            problems.append(f'line {n}: unknown klass')
        if row.get('lang') not in ('en', 'mk'):
            problems.append(f'line {n}: lang must be en or mk')
        text = row.get('utterance')
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            problems.append(f'line {n}: utterance missing, empty or over 500 characters')
        elif row.get('lang') == 'mk' and not CYRILLIC.search(text):
            problems.append(f'line {n}: mk row without Cyrillic')
        elif row.get('lang') == 'en' and CYRILLIC.search(text):
            problems.append(f'line {n}: en row with Cyrillic')
    ids = [r.get('id') for r in rows]
    expected = {f'h6-{i:04d}' for i in range(1, 301)}
    if len(set(ids)) != len(ids):
        problems.append(f'{len(ids) - len(set(ids))} duplicate id(s)')
    if set(ids) != expected:
        problems.append(f'ids differ from h6-0001..h6-0300 ({len(set(ids) - expected)} unexpected, '
                        f'{len(expected - set(ids))} missing)')
    klass = Counter(r.get('klass') for r in rows)
    for k, want in COUNTS.items():
        if klass.get(k, 0) != want:
            problems.append(f'{k}: {klass.get(k, 0)} rows, expected {want}')
    lang_by_class = {k: Counter(r.get('lang') for r in rows if r.get('klass') == k) for k in COUNTS}
    for k, c in lang_by_class.items():
        total = sum(c.values())
        if total and not (0.4 <= c.get('en', 0) / total <= 0.6):
            problems.append(f'{k}: English share {c.get("en", 0)}/{total} outside 40-60%')
    seen = Counter(norm(r.get('utterance', '')) for r in rows)
    dupes = sum(v - 1 for v in seen.values() if v > 1)
    if dupes:
        lines = [r['_line'] for r in rows if seen[norm(r.get('utterance', ''))] > 1]
        problems.append(f'{dupes} duplicate utterance(s), lines {lines}')
    frozen = {norm(r['utterance']) for r in json.loads(FROZEN_LABELS.read_text())['rows']}
    overlap = [r['_line'] for r in rows if norm(r.get('utterance', '')) in frozen]
    if overlap:
        problems.append(f'{len(overlap)} utterance(s) repeat an earlier ARIES test request, lines {overlap}')
    report = {'file': cli.file, 'sha256': hashlib.sha256(raw).hexdigest(), 'rows': len(rows),
              'class_counts': dict(klass), 'language_by_class': {k: dict(v) for k, v in lang_by_class.items()},
              'problems': problems, 'result': 'FAIL' if problems or not rows else 'PASS'}
    if cli.out:
        Path(cli.out).write_text(json.dumps(report, indent=1) + '\n')
    print(f"{report['result']}  rows={len(rows)}  classes={dict(klass)}  problems={len(problems)}  "
          f"sha256={report['sha256'][:16]}")
    for p in problems:
        print('  -', p)
    return 0 if report['result'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
