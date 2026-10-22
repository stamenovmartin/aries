#!/usr/bin/env python3
"""Validate the H5 item files before any measurement. Prints PASS/FAIL and counts, never the items.

Two gates, both must pass:

1. Structure (H5-specific):
   - 15 goals (h5-g-01..15: 5 read, 5 list, 5 exists);
   - 10 controls (h5-n-01..10), with at least 3 of each type: wrong_file, missing_evidence,
     changed_after_read;
   - a changed_after_read control carries change_after_read {file, command};
   - the standard checks of each kind;
   - English only, no example rows, and the goal names its own case folder.
2. Discrimination: every oracle runs against a record in which ARIES did nothing, using the UNCHANGED
   logic of experiments/product/independent-acceptance/validate_oracles.py. A do-nothing record leaves
   the goal 'queued', so both a goal's reached_done and a control's terminal_not_done must fail on it.

Nothing is submitted to ARIES, no database is opened, and no service is touched.

    python3 -I validate_items.py goals.jsonl controls.jsonl --out <dir>
    python3 -I validate_items.py example_items.jsonl --example --out <dir>
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import re
import sys
import tempfile
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ORIGINAL = HERE.parents[1] / 'product/independent-acceptance/validate_oracles.py'
GOAL_ROOT = '/home/stamenovmartin/Documents/ARIES-CIA-01/'
FIELDS = ('id', 'kind', 'goal_type', 'expected_outcome', 'goal', 'setup', 'teardown', 'independent_oracle',
          'budget_seconds', 'requires', 'surface', 'notes', 'author', 'written_at')
REQUIRED = {'goal': {'reached_done', 'answer_verified', 'sandbox_unchanged'}, 'control': {'terminal_not_done'}}
EXPECTED = {'goal': 'done', 'control': 'not_done'}
CONTROL_TYPES = ('wrong_file', 'missing_evidence', 'changed_after_read')
CYRILLIC = re.compile('[Ѐ-ӿ]')


def structure(rows, *, example):
    problems = []
    ids = [r.get('id') for r in rows]
    if len(set(ids)) != len(ids):
        problems.append('duplicate ids')
    for r in rows:
        rid = r.get('id', '?')
        missing = [f for f in FIELDS if f not in r]
        if missing:
            problems.append(f'{rid}: missing fields {missing}')
            continue
        kind = r['kind']
        if kind not in REQUIRED:
            problems.append(f'{rid}: kind must be goal or control')
            continue
        if bool(r.get('example')) != example:
            problems.append(f'{rid}: example rows are only allowed in the example file')
        pattern = r'h5-g-(0[1-9]|1[0-5])' if kind == 'goal' else r'h5-n-(0[1-9]|10)'
        if not example and not re.fullmatch(pattern, str(rid)):
            problems.append(f'{rid}: id must be h5-g-01..15 (goals) or h5-n-01..10 (controls)')
        if r['goal_type'] not in ('read', 'list', 'exists'):
            problems.append(f'{rid}: goal_type must be read, list or exists')
        if r['expected_outcome'] != EXPECTED[kind]:
            problems.append(f'{rid}: expected_outcome must be {EXPECTED[kind]}')
        if r['requires'] or r['surface'] != 'api':
            problems.append(f'{rid}: requires must be empty and surface api')
        if GOAL_ROOT + rid not in r['goal']:
            problems.append(f'{rid}: goal must name its own case folder {GOAL_ROOT}<id>')
        if CYRILLIC.search(r['goal']):
            problems.append(f'{rid}: goals are English only')
        if kind == 'control':
            t = r.get('control_type')
            if t not in CONTROL_TYPES:
                problems.append(f'{rid}: control_type must be one of {CONTROL_TYPES}')
            change = r.get('change_after_read')
            if t == 'changed_after_read' and not (isinstance(change, dict) and change.get('file') and change.get('command')):
                problems.append(f'{rid}: changed_after_read needs change_after_read {{file, command}}')
            if t != 'changed_after_read' and change:
                problems.append(f'{rid}: change_after_read is only for changed_after_read controls')
        have = {c.get('id') for c in r['independent_oracle'].get('checks') or []}
        if not REQUIRED[kind] <= have:
            problems.append(f'{rid}: missing standard checks {sorted(REQUIRED[kind] - have)}')
    if not example:
        goals = [r for r in rows if r.get('kind') == 'goal']
        controls = [r for r in rows if r.get('kind') == 'control']
        if len(goals) != 15 or len(controls) != 10:
            problems.append(f'expected 15 goals and 10 controls, found {len(goals)} and {len(controls)}')
        types = Counter(r.get('goal_type') for r in goals)
        if any(types.get(t, 0) != 5 for t in ('read', 'list', 'exists')):
            problems.append(f'goals need 5 read, 5 list, 5 exists; found {dict(types)}')
        ctypes = Counter(r.get('control_type') for r in controls)
        if any(ctypes.get(t, 0) < 3 for t in CONTROL_TYPES):
            problems.append(f'controls need at least 3 of each type; found {dict(ctypes)}')
    return problems


def discrimination(rows, out):
    spec = importlib.util.spec_from_file_location('ia_validate_oracles', ORIGINAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as tmp:
        for r in rows:
            tmp.write(json.dumps({**r, 'class': 'h5_' + r['kind'], 'held_out': True}, ensure_ascii=False) + '\n')
    module.FIXTURES = pathlib.Path(tmp.name)
    module.HERE = pathlib.Path(out)
    (pathlib.Path(out) / 'raw').mkdir(parents=True, exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        module.main()
    pathlib.Path(tmp.name).unlink()
    cases = json.loads((pathlib.Path(out) / 'raw/oracle_validation.json').read_text())['cases']
    bad = [c['id'] for c in cases if c['verdict'] != 'DISCRIMINATING' or c.get('forbidden_violated_by_setup')]
    return dict(Counter(c['verdict'] for c in cases)), bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--example', action='store_true')
    ap.add_argument('--out', required=True)
    cli = ap.parse_args()
    raws = [pathlib.Path(f).read_bytes() for f in cli.files]
    rows = [json.loads(l) for raw in raws for l in raw.decode().splitlines() if l.strip()]
    problems = structure(rows, example=cli.example)
    tally, bad = discrimination(rows, cli.out) if rows else ({}, [])
    ok = not problems and not bad and bool(rows)
    report = {'files': {f: hashlib.sha256(r).hexdigest() for f, r in zip(cli.files, raws)}, 'rows': len(rows),
              'example_mode': cli.example, 'structure_problems': problems, 'discrimination_tally': tally,
              'not_discriminating_ids': bad, 'result': 'PASS' if ok else 'FAIL'}
    pathlib.Path(cli.out).mkdir(parents=True, exist_ok=True)
    (pathlib.Path(cli.out) / 'validation.json').write_text(json.dumps(report, indent=1))
    print(f"{report['result']}  rows={len(rows)}  structure_problems={len(problems)}  discrimination={tally}  "
          f"not_discriminating={len(bad)}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
