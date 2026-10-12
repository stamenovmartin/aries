#!/usr/bin/env python3
"""Validate an H4 scenario file before any measurement. Prints PASS/FAIL, never the scenarios.

Two gates, both must pass:

1. Structure (H4-specific): required fields, unique ids, the set's expected outcome, the
   standard check ids each set must carry, no `requires`, no example rows, and, for a
   real set, exactly 10 rows whose `template_id`s pair one-to-one with the other set.
2. Discrimination: every case's oracle is executed against a record in which ARIES did
   nothing, using the UNCHANGED logic of
   experiments/product/independent-acceptance/validate_oracles.py. Only its input file and
   output folder are redirected, so its reported raw/oracle_validation.json is not touched.
   A case passes only if it is DISCRIMINATING and setup violates no forbidden state.

Nothing is submitted to ARIES, no database is opened, and no service is touched.
Output: <out>/raw/oracle_validation.json (per-case verdicts) and <out>/validation.json.

    python3 -I validate_oracles.py set_a.jsonl --pair set_c.jsonl --out <dir>
    python3 -I validate_oracles.py example_pair.jsonl --example --out <dir>
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ORIGINAL = HERE.parents[1] / 'product/independent-acceptance/validate_oracles.py'
EXPECTED = {'A': ('h4_ambiguous', 'ask'), 'C': ('h4_control', 'pass')}
REQUIRED_CHECKS = {'A': {'planner_question', 'sandbox_unchanged', 'not_reported_complete'},
                   'C': {'target_read_verified', 'no_question', 'sandbox_unchanged'}}
REQUIRED_FORBIDDEN = {'A': {'no_candidate_read'}, 'C': set()}
FIELDS = ('id', 'set', 'template_id', 'class', 'expected_outcome', 'held_out', 'goal', 'setup',
          'teardown', 'independent_oracle', 'budget_seconds', 'requires', 'surface', 'author', 'written_at')
GOAL_ROOT = '/home/stamenovmartin/Documents/ARIES-CIA-01/'


def structure(rows, *, example, pair_rows):
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
        s = r['set']
        if s not in EXPECTED:
            problems.append(f'{rid}: set must be A or C')
            continue
        if (r['class'], r['expected_outcome']) != EXPECTED[s]:
            problems.append(f'{rid}: set {s} needs class/expected_outcome {EXPECTED[s]}')
        if bool(r.get('example')) != example:
            problems.append(f'{rid}: example rows are only allowed in the example file')
        if r['requires']:
            problems.append(f'{rid}: requires must be empty for H4')
        if r['held_out'] is not True:
            problems.append(f'{rid}: held_out must be true')
        if r['surface'] != 'api':
            problems.append(f'{rid}: surface must be api')
        if GOAL_ROOT + rid not in r['goal']:
            problems.append(f'{rid}: goal must name its own case folder {GOAL_ROOT}<id>')
        oracle = r['independent_oracle']
        have = {c.get('id') for c in oracle.get('checks') or []}
        forb = {c.get('id') for c in oracle.get('forbidden_state') or []}
        if not REQUIRED_CHECKS[s] <= have:
            problems.append(f'{rid}: missing standard checks {sorted(REQUIRED_CHECKS[s] - have)}')
        if not REQUIRED_FORBIDDEN[s] <= forb:
            problems.append(f'{rid}: missing standard forbidden_state {sorted(REQUIRED_FORBIDDEN[s] - forb)}')
    if not example:
        if len(rows) != 10:
            problems.append(f'expected 10 scenarios, found {len(rows)}')
        if len({r.get('set') for r in rows}) > 1:
            problems.append('a set file must contain one set only')
        if pair_rows is not None:
            mine = sorted(r.get('template_id') for r in rows)
            theirs = sorted(r.get('template_id') for r in pair_rows)
            if mine != theirs or len(set(mine)) != len(mine):
                problems.append('template_ids do not pair one-to-one with the other set')
    return problems


def discrimination(path, out):
    spec = importlib.util.spec_from_file_location('ia_validate_oracles', ORIGINAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FIXTURES = pathlib.Path(path)
    module.HERE = pathlib.Path(out)          # output goes to <out>/raw/oracle_validation.json
    (pathlib.Path(out) / 'raw').mkdir(parents=True, exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):   # its printout names cases; keep it quiet
        module.main()
    cases = json.loads((pathlib.Path(out) / 'raw/oracle_validation.json').read_text())['cases']
    bad = [c['id'] for c in cases
           if c['verdict'] != 'DISCRIMINATING' or c.get('forbidden_violated_by_setup')]
    tally = {}
    for c in cases:
        tally[c['verdict']] = tally.get(c['verdict'], 0) + 1
    return tally, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scenarios')
    ap.add_argument('--pair', help='the matched other set, for the template pairing check')
    ap.add_argument('--example', action='store_true', help='validate the worked example file')
    ap.add_argument('--out', required=True)
    cli = ap.parse_args()
    raw = pathlib.Path(cli.scenarios).read_bytes()
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    pair_rows = None
    if cli.pair:
        pair_rows = [json.loads(l) for l in pathlib.Path(cli.pair).read_text().splitlines() if l.strip()]
    problems = structure(rows, example=cli.example, pair_rows=pair_rows)
    tally, bad = discrimination(cli.scenarios, cli.out) if rows else ({}, [])
    ok = not problems and not bad and bool(rows)
    report = {'file': cli.scenarios, 'sha256': hashlib.sha256(raw).hexdigest(), 'rows': len(rows),
              'example_mode': cli.example, 'structure_problems': problems,
              'discrimination_tally': tally, 'not_discriminating_ids': bad,
              'result': 'PASS' if ok else 'FAIL'}
    pathlib.Path(cli.out).mkdir(parents=True, exist_ok=True)
    (pathlib.Path(cli.out) / 'validation.json').write_text(json.dumps(report, indent=1))
    # Only the verdict and counts are printed; the scenarios themselves are not shown.
    print(f"{report['result']}  rows={len(rows)}  structure_problems={len(problems)}  "
          f"discrimination={tally}  not_discriminating={len(bad)}  sha256={report['sha256'][:16]}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
