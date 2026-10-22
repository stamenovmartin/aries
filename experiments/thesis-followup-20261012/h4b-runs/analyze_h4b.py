#!/usr/bin/env python3
"""H4b analysis, as registered (docs/preregistration/H4b-clarify-resolver.md, Amendment 2). Written before any H4b run.

    analyze_h4b.py <run folder> x6   ->  h4b-runs/summary-<first run stamp>.json

Exactly 3 treatment and 3 baseline runs, each complete (40 ambiguous + 40 twins), at one commit, with stable model
and code, or the analysis refuses. Per-item outcome = majority over the 3 runs of a condition; a pair is correct
when both of its items are.
- Primary: paired accuracy (pairs correct of 40), treatment against baseline, exact two-sided McNemar on the
  per-pair outcomes. The Holm-adjusted p-value is computed in the family report.
- Secondary 1: over-ask on twins (majority), non-inferiority with margin 10 points: the upper limit of the
  one-sided 95% Newcombe interval (method 10, z = 1.645) for the paired difference treatment minus baseline must
  be below 0.10. Overall, and for t1 and t2 separately.
- Secondary 2: ask rate on the ambiguous items (majority), per condition, Wilson 95%.
- Secondary 3 (treatment, item-runs, descriptive): how often the subset with more than one candidate was
  reached; the raw model decision against the correct one (ambiguous: ask; twin: select the intended file); how
  often code overruled a select, and why; final accuracy there.
- Secondary 4 (descriptive): per-run counts, terminal states, how often the resolver applied and its candidate
  buckets (0, 1, 2-5, >5), latency and model calls per item.
"""
import json
import sys
from collections import Counter
from math import comb, sqrt
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARGIN = 0.10


def wilson(k, n, z=1.959964):
    if not n:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [max(0.0, centre - half), min(1.0, centre + half)]


def newcombe_paired(a, b, c, d, z=1.645):
    """Newcombe (1998) method 10 for p1 - p2 on paired data. a = both yes, b = only 1, c = only 2, d = neither."""
    n = a + b + c + d
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n, z)
    l2, u2 = wilson(a + c, n, z)
    den = (a + b) * (c + d) * (a + c) * (b + d)
    phi = (a * d - b * c) / sqrt(den) if den else 0.0
    delta = p1 - p2
    lower = delta - sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    upper = delta + sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return delta, lower, upper


def mcnemar_two_sided(b, c):
    m = b + c
    if not m:
        return 1.0
    return min(1.0, 2 * sum(comb(m, i) for i in range(0, min(b, c) + 1)) / 2 ** m)


def rate(k, n):
    ci = wilson(k, n)
    return {'k': k, 'n': n, 'rate': round(k / n, 4) if n else None, 'wilson95': [round(x, 4) for x in ci] if ci else None}


def majority(runs, key):
    items = {}
    for res in runs:
        for x in res:
            items.setdefault(x['id'], []).append(bool(key(x)))
    return {i: sum(v) >= 2 for i, v in items.items()}


def non_inferiority(over, pairs, twin_ids):
    a = sum(over['treatment'][t] and over['baseline'][t] for t in twin_ids)
    b = sum(over['treatment'][t] and not over['baseline'][t] for t in twin_ids)
    c = sum(over['baseline'][t] and not over['treatment'][t] for t in twin_ids)
    d = len(twin_ids) - a - b - c
    if not twin_ids:
        return {'n_twins': 0}
    delta, lower, upper = newcombe_paired(a, b, c, d)
    return {'n_twins': len(twin_ids), 'over_ask_treatment': a + b, 'over_ask_baseline': a + c,
            'only_treatment': b, 'only_baseline': c, 'difference': round(delta, 4),
            'one_sided_95_upper': round(upper, 4), 'two_sided_90_interval': [round(lower, 4), round(upper, 4)],
            'margin': MARGIN, 'non_inferior': upper < MARGIN}


def main(folders):
    runs = [json.loads((Path(f) / 'results.json').read_text()) for f in folders]
    refused = []
    by = {'treatment': [], 'baseline': []}
    for f, r in zip(folders, runs):
        meta, res = r['run'], r['results']
        counts = Counter(x['kind'] for x in res)
        if dict(counts) != {'ambiguous': 40, 'twin': 40} or not meta.get('finished_at') or meta.get('sets') != 'h4b':
            refused.append(f'{f}: incomplete {dict(counts)}')
        if not meta.get('model_stable') or not meta.get('code_stable'):
            refused.append(f'{f}: model or code changed during the run')
        by[meta['condition']].append(res)
    commits = {r['run']['preflight']['commit'] for r in runs}
    if len(by['treatment']) != 3 or len(by['baseline']) != 3 or len(commits) != 1:
        refused.append(f'need 3 + 3 runs at one commit; got {len(by["treatment"])} + {len(by["baseline"])} at {commits}')
    if refused:
        print(json.dumps({'refused': refused}, indent=1))
        return 1

    first = by['treatment'][0]
    pair_of = {x['id']: x['pair_id'] for x in first}
    kind = {x['id']: x['kind'] for x in first}
    twin_type = {x['id']: x.get('twin_type') for x in first}
    pairs = sorted(set(pair_of.values()))
    correct = {c: majority(by[c], lambda x: x['h4b']['correct']) for c in by}
    over = {c: majority([[x for x in res if x['kind'] == 'twin'] for res in by[c]], lambda x: x['h4b']['over_ask'])
            for c in by}
    asked = {c: majority([[x for x in res if x['kind'] == 'ambiguous'] for res in by[c]],
                         lambda x: x['terminal_state'] == 'needs_clarification') for c in by}
    pair_ok = {c: {p: all(correct[c][i] for i in pair_of if pair_of[i] == p) for p in pairs} for c in by}
    b = sum(pair_ok['treatment'][p] and not pair_ok['baseline'][p] for p in pairs)
    c = sum(pair_ok['baseline'][p] and not pair_ok['treatment'][p] for p in pairs)
    primary = {'pairs': len(pairs), 'paired_accuracy': {k: sum(v.values()) for k, v in pair_ok.items()},
               'b_treatment_only': b, 'c_baseline_only': c, 'p_two_sided_exact': mcnemar_two_sided(b, c),
               'holm_adjusted_p': 'in the family report'}
    twins = [i for i in kind if kind[i] == 'twin']
    secondary = {
        'over_ask_non_inferiority': {
            'all': non_inferiority(over, pairs, twins),
            't1': non_inferiority(over, pairs, [t for t in twins if twin_type[t] == 't1']),
            't2': non_inferiority(over, pairs, [t for t in twins if twin_type[t] == 't2'])},
        'ask_rate_ambiguous': {k: rate(sum(v.values()), len(v)) for k, v in asked.items()},
        'item_correct_majority': {k: {'ambiguous': sum(v[i] for i in v if kind[i] == 'ambiguous'),
                                      'twin': sum(v[i] for i in v if kind[i] == 'twin')} for k, v in correct.items()},
    }
    # Secondary 3: the treatment's model decision on the subset with more than one candidate (item-runs).
    reached = [x for res in by['treatment'] for x in res
               if (x.get('resolver') or {}).get('n_candidates') is not None and x['resolver']['n_candidates'] > 1]
    decided = [x for x in reached if x['resolver'].get('model_decision') is not None]

    def model_right(x):
        r = x['resolver']
        if x['kind'] == 'ambiguous':
            return r['model_decision'] == 'ask'
        return r['model_decision'] == 'select' and r.get('selected_index') is not None and \
            (r.get('selected') or '').endswith('/' + str(x.get('intended_file', '')))
    secondary['resolver_subset_treatment_item_runs'] = {
        'reached': len(reached), 'of_item_runs': sum(len(res) for res in by['treatment']),
        'reached_by_kind': dict(Counter(x['kind'] + (':' + x['twin_type'] if x.get('twin_type') else '') for x in reached)),
        'model_called': len(decided),
        'raw_model_decision_by_kind': {k: dict(Counter(x['resolver']['model_decision'] for x in decided
                                                       if x['kind'] == k)) for k in ('ambiguous', 'twin')},
        'select_overruled_by_code': sum(x['resolver']['model_decision'] == 'select' and not x['resolver']['accepted']
                                        for x in decided),
        'select_overruled_why': dict(Counter(x['resolver']['why'] for x in decided
                                             if x['resolver']['model_decision'] == 'select'
                                             and not x['resolver']['accepted'])),
        'raw_model_decision_right': rate(sum(model_right(x) for x in decided), len(decided)),
        'raw_model_decision_right_definition': 'ask on an ambiguous item; a select of the intended file on a twin',
        'final_correct_after_code': rate(sum(bool(x['h4b']['correct']) for x in reached), len(reached)),
    }
    secondary['descriptive'] = {}
    for cond, results in by.items():
        flat = [x for res in results for x in res]
        secondary['descriptive'][cond] = {
            'per_run': [dict(Counter(f"{x['kind']}:{'correct' if x['h4b']['correct'] else 'not'}" for x in res))
                        for res in results],
            'terminal_states': {k: dict(Counter(x.get('terminal_state') for x in flat if x['kind'] == k))
                                for k in ('ambiguous', 'twin')},
            'question_source': dict(Counter(x['h4b'].get('question_source') for x in flat if x['h4b'].get('question_source'))),
            'verdicts': dict(Counter(x['verdict'] for x in flat)),
            'resolver_applied': sum(bool((x.get('resolver') or {}).get('applies')) for x in flat),
            'candidate_buckets': dict(Counter((x.get('resolver') or {}).get('candidate_bucket') for x in flat
                                              if (x.get('resolver') or {}).get('applies'))),
            'mean_seconds_per_item': round(sum(x.get('seconds', 0) for x in flat) / len(flat), 2),
            'mean_model_calls_per_item': round(sum(sum((x.get('model_calls') or {}).values()) for x in flat) / len(flat), 3),
            'resolver_model_calls': sum((x.get('model_calls') or {}).get('resolver_model_calls', 0) for x in flat),
        }
    out = {'runs': [str(f) for f in folders], 'commit': commits.pop(), 'primary': primary, 'secondary': secondary,
           'label': 'confirmatory (Holm family H4b/H5/H6/H8); secondary descriptive except the registered '
                    'non-inferiority test',
           'limitation': 'items written by OpenAI Codex (gpt-6-astra), not a person (H4b Amendment 1)'}
    dest = HERE / f'summary-{Path(folders[0]).name[:16]}.json'
    if dest.exists():
        raise SystemExit(f'REFUSED: {dest} exists')
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'primary': primary, 'over_ask_non_inferiority': secondary['over_ask_non_inferiority']['all']},
                     indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
