#!/usr/bin/env python3
"""H8 analysis of one run folder (baseline or hardened), per the registered definitions.

Primary: killed = verdict not met. A mutant with a harness error or whose verifier called the mutated
executor entry is INVALID: it is reported, and it is neither killed nor survived. Kill rates are computed
over valid mutants, and the mean kill rate is the mean of the per-capability rates. Intervals are exact
Clopper-Pearson 95%. Secondary: survived with the false value in the evidence, vs survived harmless.
Writes <run>/summary.json.

    python3 -I experiments/thesis-followup-20261012/h8/analyze.py <run-folder> [<baseline-folder> for McNemar]
"""
import collections
import json
import sys
from math import comb
from pathlib import Path


def beta_ppf(q, a, b):
    """Inverse regularised incomplete beta by bisection (no SciPy needed)."""
    def cdf(x):
        # P(Beta(a,b) <= x) for integer a, b = P(Binomial(a+b-1, x) >= a)
        n = a + b - 1
        return sum(comb(n, j) * x ** j * (1 - x) ** (n - j) for j in range(a, n + 1))
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) < q else (lo, mid)
    return (lo + hi) / 2


def clopper_pearson(k, n):
    if n == 0:
        return None
    lo = 0.0 if k == 0 else beta_ppf(0.025, k, n - k + 1)
    hi = 1.0 if k == n else beta_ppf(0.975, k + 1, n - k)
    return [round(lo, 4), round(hi, 4)]


def rate(k, n):
    return {'k': k, 'n': n, 'rate': round(k / n, 4) if n else None, 'ci95': clopper_pearson(k, n)}


def mcnemar_one_sided(b, c):
    n = b + c
    return sum(comb(n, i) for i in range(b, n + 1)) / 2 ** n if n else 1.0


def main(run, base=None):
    rows = [json.loads(l) for l in (Path(run) / 'records.jsonl').read_text().splitlines()]
    mut = [r for r in rows if r['operator'] != 'clean']
    clean = [r for r in rows if r['operator'] == 'clean']
    invalid = [r for r in mut if r.get('error') or r.get('verifier_called_mutated_entry')]
    valid = [r for r in mut if r not in invalid]
    by = lambda key: {k: rate(sum(r['killed'] for r in g), len(g)) for k, g in sorted(
        collections.defaultdict(list, {k: [r for r in valid if r[key] == k] for k in {r[key] for r in valid}}).items())}
    per_cap = {}
    for cap in sorted({r['capability'] for r in mut}):
        g = [r for r in valid if r['capability'] == cap]
        per_cap[cap] = {'killed': sum(r['killed'] for r in g), 'valid': len(g),
                        'invalid': sum(1 for r in invalid if r['capability'] == cap),
                        'rate': round(sum(r['killed'] for r in g) / len(g), 4) if g else None,
                        'verifier_class': next(r['verifier_class'] for r in mut if r['capability'] == cap),
                        'survived': sorted(r['operator'] for r in g if not r['killed'])}
    rated = [v['rate'] for v in per_cap.values() if v['rate'] is not None]
    noop = [r for r in valid if r['operator'] == 'noop_success']
    survived = [r for r in valid if not r['killed']]
    clean_valid = [r for r in clean if not r.get('error')]
    out = {
        'run': str(run), 'mutants': len(mut), 'valid_mutants': len(valid), 'invalid_mutants': len(invalid),
        'invalid': [{'id': r['id'], 'error': r.get('error'), 'mutated_entry_called': r.get('verifier_called_mutated_entry')}
                    for r in invalid],
        'killed_overall': rate(sum(r['killed'] for r in valid), len(valid)),
        'kill_rate_by_verifier_class': by('verifier_class'),
        'kill_rate_by_operator': by('operator'),
        'mean_kill_rate_over_capabilities': round(sum(rated) / len(rated), 4) if rated else None,
        'capabilities_rated': len(rated),
        'criterion_1_mean_kill_rate_ge_0_80': (sum(rated) / len(rated) >= 0.80) if rated else None,
        'noop_survivors': sorted(r['capability'] for r in noop if not r['killed']),
        'criterion_2_no_noop_survivor': not any(not r['killed'] for r in noop),
        'clean_replays': len(clean), 'clean_errors': [r['id'] for r in clean if r.get('error')],
        'false_alarms': rate(sum(r['false_alarm'] for r in clean_valid), len(clean_valid)),
        'false_alarm_ids': sorted(r['id'] for r in clean_valid if r['false_alarm']),
        'criterion_3_false_alarms_le_2pct': (sum(r['false_alarm'] for r in clean_valid) <= 0.02 * len(clean_valid))
        if clean_valid else None,
        'secondary_survived_with_false_value_in_evidence': sum(bool(r.get('false_value_in_evidence')) for r in survived),
        'secondary_survived_harmless': sum(not r.get('false_value_in_evidence') for r in survived),
        'per_capability': per_cap,
    }
    if base:
        brows = {json.loads(l)['id']: json.loads(l) for l in (Path(base) / 'records.jsonl').read_text().splitlines()}
        pairs = [(brows[r['id']], r) for r in valid if r['id'] in brows and brows[r['id']]['killed'] is not None]
        b = sum(1 for o, n in pairs if n['killed'] and not o['killed'])
        c = sum(1 for o, n in pairs if o['killed'] and not n['killed'])
        out['primary_mcnemar_vs_baseline'] = {'b_killed_now_not_before': b, 'c_killed_before_not_now': c,
                                              'pairs': len(pairs), 'p_one_sided': mcnemar_one_sided(b, c)}
    (Path(run) / 'summary.json').write_text(json.dumps(out, indent=1) + '\n')
    return out


if __name__ == '__main__':
    o = main(*sys.argv[1:])
    print(json.dumps({k: v for k, v in o.items() if k not in ('per_capability', 'invalid')}, indent=1))
