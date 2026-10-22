#!/usr/bin/env python3
"""H5 analysis, as registered (docs/preregistration/H5-completion-paraphrase.md). Written before any H5 run.

    analyze_h5.py <run folder> x6   ->  h5-runs/summary-<first run stamp>.json

Exactly 3 treatment and 3 control runs, each complete (15 G, 10 N, 49 held-out results), with stable model
and code, or the analysis refuses. Per-goal outcome = majority over the 3 runs of a condition.
- Criterion 1: with the flags on, at least 10 of 15 G goals end in a correct done (majority).
- Criterion 2: with the flags on, no N goal ends in done in any run (0 of 30 runs).
- Criterion 3: on the 49 held-out goals, the treatment's PASS count (majority) is not lower than the
  control's by more than 2.
- Primary: one-sided exact McNemar on per-goal correct done in G, treatment against control (b = only the
  treatment right). The Holm-adjusted p-value is left to the family report.
Secondary (descriptive): false-done rate with Clopper-Pearson 95% per condition, over G and N item-runs;
results by goal type and control type; contract source; end paths of goals with a contract that did not
reach done; change-hook firing on the changed_after_read controls.
"""
import json
import sys
from collections import Counter
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent


def beta_ppf(q, a, b):
    def cdf(x):
        n = a + b - 1
        return sum(comb(n, j) * x ** j * (1 - x) ** (n - j) for j in range(a, n + 1))
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) < q else (lo, mid)
    return (lo + hi) / 2


def rate(k, n):
    ci = None if not n else [0.0 if k == 0 else round(beta_ppf(0.025, k, n - k + 1), 4),
                             1.0 if k == n else round(beta_ppf(0.975, k + 1, n - k), 4)]
    return {'k': k, 'n': n, 'rate': round(k / n, 4) if n else None, 'ci95': ci}


def mcnemar_one_sided(b, c):
    m = b + c
    return sum(comb(m, i) for i in range(b, m + 1)) / 2 ** m if m else 1.0


def main(folders):
    runs = [json.loads((Path(f) / 'results.json').read_text()) for f in folders]
    refused = []
    by = {'treatment': [], 'control': []}
    for f, r in zip(folders, runs):
        meta, res = r['run'], r['results']
        counts = Counter(x['set'] for x in res)
        if dict(counts) != {'G': 15, 'N': 10, 'heldout': 49} or not meta.get('finished_at'):
            refused.append(f'{f}: incomplete {dict(counts)}')
        if not meta.get('model_stable') or not meta.get('code_stable'):
            refused.append(f'{f}: model or code changed during the run')
        by[meta['condition']].append(res)
    commits = {r['run']['preflight']['commit'] for r in runs}
    if len(by['treatment']) != 3 or len(by['control']) != 3 or len(commits) != 1:
        refused.append(f'need 3 + 3 runs at one commit; got {len(by["treatment"])} + {len(by["control"])} at {commits}')
    if refused:
        print(json.dumps({'refused': refused}, indent=1))
        return 1

    def per_item(cond, label, key):
        items = {}
        for res in by[cond]:
            for x in res:
                if x['set'] == label:
                    items.setdefault(x['id'], []).append(key(x))
        return {i: sum(v) >= 2 for i, v in items.items()}, items

    correct = {c: per_item(c, 'G', lambda x: bool(x['h5']['correct_done']))[0] for c in by}
    held = {c: per_item(c, 'heldout', lambda x: x['verdict'] == 'PASS')[0] for c in by}
    n_done_runs = sum(x['terminal_state'] == 'done' for res in by['treatment'] for x in res if x['set'] == 'N')
    ids = sorted(correct['treatment'])
    b = sum(correct['treatment'][i] and not correct['control'][i] for i in ids)
    c = sum(correct['control'][i] and not correct['treatment'][i] for i in ids)
    criteria = {
        'criterion_1_correct_done_ge_10_of_15': {'treatment': sum(correct['treatment'].values()), 'n': 15,
                                                 'met': sum(correct['treatment'].values()) >= 10},
        'criterion_2_no_N_done_in_any_treatment_run': {'done_runs': n_done_runs, 'n_runs': 30, 'met': n_done_runs == 0},
        'criterion_3_heldout_no_drop_gt_2': {'treatment_pass': sum(held['treatment'].values()),
                                             'control_pass': sum(held['control'].values()), 'n': 49,
                                             'met': sum(held['treatment'].values()) >= sum(held['control'].values()) - 2},
    }
    primary = {'b_treatment_only': b, 'c_control_only': c, 'n_goals': len(ids),
               'correct_done_majority': {k: sum(v.values()) for k, v in correct.items()},
               'p_one_sided_exact': mcnemar_one_sided(b, c), 'holm_adjusted_p': 'in the family report'}
    secondary = {}
    for cond, results in by.items():
        gn = [x for res in results for x in res if x['set'] in ('G', 'N')]
        secondary[cond] = {
            'false_done_item_runs': rate(sum(bool(x['h5']['false_done']) for x in gn), len(gn)),
            'G_correct_done_by_goal_type_runs': {t: rate(sum(bool(x['h5']['correct_done']) for x in gn
                                                             if x['set'] == 'G' and x['goal_type'] == t),
                                                         sum(x['set'] == 'G' and x['goal_type'] == t for x in gn))
                                                 for t in ('read', 'list', 'exists')},
            'N_done_by_control_type_runs': {t: rate(sum(x['terminal_state'] == 'done' for x in gn
                                                        if x['set'] == 'N' and x['control_type'] == t),
                                                    sum(x['set'] == 'N' and x['control_type'] == t for x in gn))
                                            for t in ('wrong_file', 'missing_evidence', 'changed_after_read')},
            'contract_source_G_runs': dict(Counter(x['h5']['contract_source'].split(' (')[0] for x in gn if x['set'] == 'G')),
            'typed_rejections_G_runs': dict(Counter(x['h5']['contract_source'] for x in gn
                                                    if x['set'] == 'G' and 'typed rejected' in x['h5']['contract_source'])),
            'end_path_contract_not_done_G_runs': dict(Counter(x['h5']['end_path'] for x in gn if x['set'] == 'G'
                                                              and not x['h5']['contract_source'].startswith('none')
                                                              and x['terminal_state'] != 'done')),
            'change_hook_fired_runs': dict(Counter(bool((x.get('change_hook') or {}).get('fired')) for x in gn
                                                   if x.get('control_type') == 'changed_after_read')),
            'heldout_pass_majority': sum(held[cond].values()),
            'heldout_label': 'discovered by diagnosis, fixed, measured on the same fixture',
        }
    out = {'runs': [str(f) for f in folders], 'commit': commits.pop(), 'primary': primary, 'criteria': criteria,
           'secondary': secondary, 'label': 'confirmatory (Holm family H4b/H5/H6/H8); secondary descriptive',
           'limitation': 'items written by OpenAI Codex (gpt-6-astra), not a person (H5 Amendment 2)'}
    dest = HERE / f'summary-{Path(folders[0]).name[:16]}.json'
    if dest.exists():
        raise SystemExit(f'REFUSED: {dest} exists')
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'primary': primary, 'criteria': criteria}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
