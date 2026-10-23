#!/usr/bin/env python3
"""P1 Amendment 1: one agent-suite series (three runs), reported as P1-C is (analyze_p1.py's rules).

    analyze_p1_suite.py LABEL   ->  summary-LABEL.json (refuses to overwrite)"""
import json
import sys
from collections import Counter

import analyze_p1 as P


def main(label):
    dest = P.HERE / f'summary-{label}.json'
    if dest.exists():
        raise SystemExit(f'REFUSED: {dest.name} exists')
    ph, ss = P.phases(), P.samples()
    out = {'label': f'P1 Amendment 1, series {label}, exploratory', 'idle': P.resources(
        ss, ph[f'{label}-idle']['start'], ph[f'{label}-idle']['end']), 'agent_suite': {}}
    outcome = {}
    for r in (1, 2, 3):
        d, s = P.suite(f'{label}-run{r}')
        s['resources'] = P.resources(ss, ph[f'{label}-run-{r}']['start'], ph[f'{label}-run-{r}']['end'],
                                     requests=s['counts']['attempted'])
        out['agent_suite'][f'run{r}'] = s
        outcome[r] = {g['id']: g['outcome'] for g in d['goals']}
    ids = sorted(set.intersection(*(set(o) for o in outcome.values())))
    same = [i for i in ids if len({outcome[r][i] for r in outcome}) == 1]
    out['reliability'] = {
        'goals_same_outcome_all_runs': P.A.rate(len(same), len(ids)),
        'goals_pass_all_runs': P.A.rate(sum(all(outcome[r][i] == 'pass' for r in outcome) for i in ids), len(ids)),
        'goals_pass_in_some_but_not_all': sorted(i for i in ids if i not in same and
                                                 any(outcome[r][i] == 'pass' for r in outcome)),
        'outcome_patterns': dict(Counter('/'.join(outcome[r][i] for r in sorted(outcome)) for i in ids))}
    dest.write_text(json.dumps(out, indent=1) + '\n')
    print({r: v['counts'] for r, v in out['agent_suite'].items()}, out['reliability']['goals_same_outcome_all_runs'])


if __name__ == '__main__':
    main(sys.argv[1])
