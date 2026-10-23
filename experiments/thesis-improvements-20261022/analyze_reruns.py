#!/usr/bin/env python3
"""X1 analysis (docs/preregistration/X1-remedy-reruns.md). Written before any X1 run. Exploratory.

    analyze_reruns.py   ->  outcomes-reruns.json (per item-run outcomes, no item text), summary-reruns.json

Reads the local run folders under h5-reruns/ and h4b-reruns/ (results.json) and the recorded H5 and H4b
outcomes (thesis-followup-20261012/h5-runs/outcomes.json, h4b-runs/outcomes.json). A run that is incomplete
or whose model or code changed is refused. Majority = at least 2 of 3 runs, as in H5 and H4b."""
import json
import sys
from collections import Counter
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
FU = HERE.parent / 'thesis-followup-20261012'
sys.path.insert(0, str(FU / 'h5-runs'))
from analyze_h5 import rate  # noqa: E402  (Clopper-Pearson, as H5)

H5_KEYS = ('id', 'set', 'class', 'goal_type', 'control_type', 'expected_outcome', 'terminal_state', 'verdict',
           'seconds', 'timed_out')
H4B_KEYS = ('id', 'set', 'pair_id', 'kind', 'twin_type', 'n_fitting', 'expected_outcome', 'terminal_state',
            'verdict', 'seconds', 'timed_out')


def mcnemar_two_sided(b, c):
    m = b + c
    return 1.0 if not m else min(1.0, 2 * sum(comb(m, i) for i in range(0, min(b, c) + 1)) / 2 ** m)


def flat_h5(x):
    h = x.get('h5') or {}
    return {**{k: x.get(k) for k in H5_KEYS}, 'correct_done': bool(h.get('correct_done')),
            'false_done': bool(h.get('false_done')), 'contract_source': h.get('contract_source'),
            'end_path': h.get('end_path')}


def flat_h4b(x):
    h = x.get('h4b') or {}
    return {**{k: x.get(k) for k in H4B_KEYS}, 'correct': bool(h.get('correct')), 'over_ask': h.get('over_ask'),
            'question_source': h.get('question_source')}


def new_runs(folder, expect, flat):
    runs, refused = [], []
    for f in sorted(p for p in (HERE / folder).glob('2026*') if (p / 'results.json').exists()):
        r = json.loads((f / 'results.json').read_text())
        meta, res = r['run'], r['results']
        counts = dict(Counter(x['set'] for x in res))
        if counts != expect or not meta.get('finished_at'):
            refused.append(f'{f.name}: incomplete {counts}')
            continue
        if not meta.get('model_stable') or not meta.get('code_stable'):
            refused.append(f'{f.name}: model or code changed during the run')
            continue
        runs.append({'folder': f.name, 'condition': meta['condition'], 'commit': meta['preflight']['commit'],
                     'model_stable': True, 'code_stable': True, 'results': [flat(x) for x in res]})
    return runs, refused


def majority(runs, cond, sets, key):
    items = {}
    for run in runs:
        if run['condition'] == cond:
            for x in run['results']:
                if x['set'] in sets:
                    items.setdefault(x['id'], []).append(bool(key(x)))
    return {i: sum(v) >= 2 for i, v in items.items() if len(v) >= 2}


def h5_summary(runs):
    conds = sorted({r['condition'] for r in runs})
    out = {'runs_per_condition': dict(Counter(r['condition'] for r in runs)), 'by_condition': {}}
    correct = {c: majority(runs, c, ('G',), lambda x: x['correct_done']) for c in conds}
    for c in conds:
        rs = [r for r in runs if r['condition'] == c]
        gn = [x for r in rs for x in r['results'] if x['set'] in ('G', 'N')]
        held = [x for r in rs for x in r['results'] if x['set'] == 'heldout']
        out['by_condition'][c] = {
            'G_correct_done_majority': {'k': sum(correct[c].values()), 'n': len(correct[c])} if correct[c] else None,
            'G_correct_done_item_runs': rate(sum(x['correct_done'] for x in gn if x['set'] == 'G'),
                                             sum(x['set'] == 'G' for x in gn)),
            'false_done_item_runs': rate(sum(x['false_done'] for x in gn), len(gn)),
            'N_done_item_runs': rate(sum(x['terminal_state'] == 'done' for x in gn if x['set'] == 'N'),
                                     sum(x['set'] == 'N' for x in gn)),
            'heldout_pass_item_runs': rate(sum(x['verdict'] == 'PASS' for x in held), len(held)),
            'heldout_done_item_runs': rate(sum(x['terminal_state'] == 'done' for x in held), len(held)),
            'heldout_terminal_states': dict(Counter(x['terminal_state'] for x in held).most_common()),
            'contract_source_G_runs': dict(Counter(str(x['contract_source']).split(' (')[0] for x in gn
                                                   if x['set'] == 'G')),
        }
        if len(rs) >= 2:
            hp = majority(runs, c, ('heldout',), lambda x: x['verdict'] == 'PASS')
            out['by_condition'][c]['heldout_pass_majority'] = {'k': sum(hp.values()), 'n': len(hp)}
    if 'remedies' in correct and 'treatment' in correct:
        ids = sorted(set(correct['remedies']) & set(correct['treatment']))
        b = sum(correct['remedies'][i] and not correct['treatment'][i] for i in ids)
        c = sum(correct['treatment'][i] and not correct['remedies'][i] for i in ids)
        out['remedies_vs_treatment_G'] = {'b_remedies_only': b, 'c_treatment_only': c, 'n': len(ids),
                                          'p_two_sided_exact_orientation_only': mcnemar_two_sided(b, c)}
    return out


def h4b_summary(runs):
    conds = sorted({r['condition'] for r in runs})
    out = {'runs_per_condition': dict(Counter(r['condition'] for r in runs)), 'by_condition': {}}
    pair_ok = {}
    for c in conds:
        correct = majority(runs, c, ('ambiguous', 'twin'), lambda x: x['correct'])
        first = next(r for r in runs if r['condition'] == c)['results']
        pair_of = {x['id']: x['pair_id'] for x in first}
        kind = {x['id']: x['kind'] for x in first}
        pairs = sorted(set(pair_of.values()))
        pair_ok[c] = {p: all(correct.get(i, False) for i in pair_of if pair_of[i] == p) for p in pairs}
        over = majority(runs, c, ('twin',), lambda x: bool(x['over_ask']))
        out['by_condition'][c] = {
            'pairs_correct': {'k': sum(pair_ok[c].values()), 'n': len(pairs)},
            'ambiguous_correct': {'k': sum(v for i, v in correct.items() if kind[i] == 'ambiguous'),
                                  'n': sum(kind[i] == 'ambiguous' for i in correct)},
            'twins_correct': {'k': sum(v for i, v in correct.items() if kind[i] == 'twin'),
                              'n': sum(kind[i] == 'twin' for i in correct)},
            'twins_over_asked': {'k': sum(over.values()), 'n': len(over)},
            'seconds_per_item_mean': round(sum(x['seconds'] or 0 for r in runs if r['condition'] == c
                                               for x in r['results']) /
                                           max(1, sum(len(r['results']) for r in runs if r['condition'] == c)), 2),
        }
    if 'code-select' in pair_ok and 'treatment' in pair_ok:
        ps = sorted(pair_ok['code-select'])
        b = sum(pair_ok['code-select'][p] and not pair_ok['treatment'][p] for p in ps)
        c = sum(pair_ok['treatment'][p] and not pair_ok['code-select'][p] for p in ps)
        out['code_select_vs_treatment_pairs'] = {'b_code_select_only': b, 'c_treatment_only': c, 'n': len(ps),
                                                 'p_two_sided_exact_orientation_only': mcnemar_two_sided(b, c)}
    return out


def main():
    for name in ('outcomes-reruns.json', 'summary-reruns.json'):
        if (HERE / name).exists():
            raise SystemExit(f'REFUSED: {name} exists')
    h5_new, r5 = new_runs('h5-reruns', {'G': 15, 'N': 10, 'heldout': 49}, flat_h5)
    h4_new, r4 = new_runs('h4b-reruns', {'ambiguous': 40, 'twin': 40}, flat_h4b)
    h5_old = json.loads((FU / 'h5-runs/outcomes.json').read_text())['runs']
    h4_old = json.loads((FU / 'h4b-runs/outcomes.json').read_text())['runs']
    (HERE / 'outcomes-reruns.json').write_text(json.dumps(
        {'note': 'X1 per item-run outcomes from the local results.json of each run (no item text).',
         'refused': r5 + r4, 'h5': h5_new, 'h4b': h4_new}, ensure_ascii=False, indent=1) + '\n')
    summary = {'label': 'exploratory (X1): same items as H5 and H4b, remedies designed after their results',
               'refused_runs': r5 + r4, 'commits': sorted({r['commit'] for r in h5_new + h4_new}),
               'h5': h5_summary(h5_old + h5_new), 'h4b': h4b_summary(h4_old + h4_new)}
    (HERE / 'summary-reruns.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(summary, indent=1)[:4000])


if __name__ == '__main__':
    main()
