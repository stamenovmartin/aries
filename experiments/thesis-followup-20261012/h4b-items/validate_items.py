#!/usr/bin/env python3
"""Validate the H4b pair files before any measurement. Prints PASS/FAIL and counts, never the items.

Two gates, both must pass:

1. Structure (H4b-specific):
   - required fields and unique ids;
   - 40 ambiguous items (h4b-a-01..40) and 40 twins (h4b-t-01..40), paired one-to-one by pair_id;
   - at least 15 twins of type t2;
   - 2 to 5 fitting files per ambiguous item;
   - a twin's intended file is among its fitting files (t1: exactly one fitting file; t2: two or more,
     plus a disambiguator that occurs verbatim in the goal);
   - the standard checks of each kind;
   - English only, no example rows, the goal names its own case folder.
2. Discrimination: every oracle is executed against a record in which ARIES did nothing, using the
   UNCHANGED logic of experiments/product/independent-acceptance/validate_oracles.py (input file and
   output folder redirected, as in h4-scenarios/validate_oracles.py). A case passes only if it is
   DISCRIMINATING and setup violates no forbidden state.

Nothing is submitted to ARIES, no database is opened, and no service is touched.

    python3 -I validate_items.py pairs_ambiguous.jsonl pairs_twin.jsonl --out <dir>
    python3 -I validate_items.py example_pair.jsonl --example --out <dir>
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

HERE = pathlib.Path(__file__).resolve().parent
ORIGINAL = HERE.parents[1] / 'product/independent-acceptance/validate_oracles.py'
GOAL_ROOT = '/home/stamenovmartin/Documents/ARIES-CIA-01/'
FIELDS = ('id', 'pair_id', 'kind', 'expected_outcome', 'fitting_files', 'goal', 'setup', 'teardown',
          'independent_oracle', 'budget_seconds', 'requires', 'surface', 'notes', 'author', 'written_at')
REQUIRED = {'ambiguous': ({'question_asked', 'choices_are_fitting', 'sandbox_unchanged', 'not_reported_complete'},
                          {'no_candidate_read'}),
            'twin': ({'target_read_verified', 'no_question', 'sandbox_unchanged'}, set())}
EXPECTED = {'ambiguous': 'ask', 'twin': 'pass'}
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
            problems.append(f'{rid}: kind must be ambiguous or twin')
            continue
        if bool(r.get('example')) != example:
            problems.append(f'{rid}: example rows are only allowed in the example file')
        if not example and not re.fullmatch(rf"h4b-{'a' if kind == 'ambiguous' else 't'}-(0[1-9]|[1-3][0-9]|40)", str(rid)):
            problems.append(f'{rid}: id must be h4b-a-01..40 (ambiguous) or h4b-t-01..40 (twin)')
        if r['expected_outcome'] != EXPECTED[kind]:
            problems.append(f'{rid}: expected_outcome must be {EXPECTED[kind]}')
        if r['requires'] or r['surface'] != 'api':
            problems.append(f'{rid}: requires must be empty and surface api')
        if GOAL_ROOT + rid not in r['goal']:
            problems.append(f'{rid}: goal must name its own case folder {GOAL_ROOT}<id>')
        if CYRILLIC.search(r['goal']):
            problems.append(f'{rid}: goals are English only')
        fit = r['fitting_files']
        if not isinstance(fit, list) or len(set(fit)) != len(fit) or any('/' in f for f in fit):
            problems.append(f'{rid}: fitting_files must be distinct file names inside the case folder')
            fit = []
        if kind == 'ambiguous' and not 2 <= len(fit) <= 5:
            problems.append(f'{rid}: an ambiguous item needs 2 to 5 fitting files')
        if kind == 'twin':
            t = r.get('twin_type')
            if t not in ('t1', 't2'):
                problems.append(f'{rid}: twin_type must be t1 or t2')
            if r.get('intended_file') not in fit:
                problems.append(f'{rid}: intended_file must be one of fitting_files')
            if t == 't1' and len(fit) != 1:
                problems.append(f'{rid}: a t1 twin has exactly one fitting file')
            if t == 't2':
                d = r.get('disambiguator') or ''
                if len(fit) < 2 or not d or d.casefold() not in r['goal'].casefold():
                    problems.append(f'{rid}: a t2 twin needs 2+ fitting files and a disambiguator that occurs in the goal')
        for f in fit:
            if not any(f in line for line in r['setup']):
                problems.append(f'{rid}: fitting file not created in setup')
                break
        oracle = r['independent_oracle']
        have = {c.get('id') for c in oracle.get('checks') or []}
        forb = {c.get('id') for c in oracle.get('forbidden_state') or []}
        need_checks, need_forb = REQUIRED[kind]
        if not need_checks <= have:
            problems.append(f'{rid}: missing standard checks {sorted(need_checks - have)}')
        if not need_forb <= forb:
            problems.append(f'{rid}: missing standard forbidden_state {sorted(need_forb - forb)}')
    if not example:
        amb = [r for r in rows if r.get('kind') == 'ambiguous']
        twin = [r for r in rows if r.get('kind') == 'twin']
        if len(amb) != 40 or len(twin) != 40:
            problems.append(f'expected 40 ambiguous and 40 twins, found {len(amb)} and {len(twin)}')
        pa, pt = sorted(r.get('pair_id') for r in amb), sorted(r.get('pair_id') for r in twin)
        if pa != pt or len(set(pa)) != len(pa):
            problems.append('pair_ids do not pair one-to-one between ambiguous items and twins')
        t2 = sum(r.get('twin_type') == 't2' for r in twin)
        if t2 < 15:
            problems.append(f'only {t2} twins of type t2; at least 15 are required')
    return problems


def discrimination(rows, out):
    spec = importlib.util.spec_from_file_location('ia_validate_oracles', ORIGINAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as tmp:
        for r in rows:
            # The original validator expects the fixture's own fields; class/expected_outcome map 1:1.
            tmp.write(json.dumps({**r, 'class': 'h4b_' + r['kind'], 'held_out': True}, ensure_ascii=False) + '\n')
    module.FIXTURES = pathlib.Path(tmp.name)
    module.HERE = pathlib.Path(out)
    (pathlib.Path(out) / 'raw').mkdir(parents=True, exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        module.main()
    pathlib.Path(tmp.name).unlink()
    cases = json.loads((pathlib.Path(out) / 'raw/oracle_validation.json').read_text())['cases']
    bad = [c['id'] for c in cases if c['verdict'] != 'DISCRIMINATING' or c.get('forbidden_violated_by_setup')]
    tally = {}
    for c in cases:
        tally[c['verdict']] = tally.get(c['verdict'], 0) + 1
    return tally, bad


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
