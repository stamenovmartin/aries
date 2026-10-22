#!/usr/bin/env python3
"""H6 llama3.1:8b exploratory secondary: ../h6-run/analyze_h6.py with only the runner name and labels changed.

H6 analysis, as registered (docs/preregistration/H6-abstention-replication.md). Writes summary.json.

Scoring is the frozen analyze_router.py: valid(), correct() (binary) and score() for abstention precision,
recall and false holds. H6 has no semantic labels, so the semantic metrics are empty (n = 0) and unused.

Primary: per request, the majority of 3 repetitions correct or not; one-sided exact McNemar A1 vs A0 on the
discordant requests (b = A1 right and A0 wrong, c = the reverse), H1: b > c. Reported with the difference in
binary accuracy and its exact paired 95% interval: conditional on the m = b + c discordant requests, the
Clopper-Pearson interval [lo, hi] for b / m gives (m / n)(2 lo - 1) .. (m / n)(2 hi - 1). The Holm-adjusted
p-value needs the other three primary p-values (H4b, H5 not measured yet), so it is left open here.

The run is refused (exit 1, no result) if it is partial, if the fixture is not the frozen file of Amendment 2,
if the frozen source changed, or if the model digest or the Ollama version changed during the run.
"""
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parents[1] / 'thesis-final-20261006'
FIXTURE = HERE.parent / 'h6-items' / 'h6_requests.jsonl'
FROZEN_FIXTURE_SHA = '3068dd8d9b41b58987e6d2270b66629389c8b3b40937502ce9462b9ffce35348'
ARMS = ('A0', 'A1')
CLASSES = ('actionable', 'ambiguous', 'out_of_scope', 'unsafe')

spec = importlib.util.spec_from_file_location('analyze_router', ORIGINAL / 'analyze_router.py')
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


def beta_ppf(q, a, b):
    def cdf(x):
        n = a + b - 1
        return sum(comb(n, j) * x ** j * (1 - x) ** (n - j) for j in range(a, n + 1))
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) < q else (lo, mid)
    return (lo + hi) / 2


def cp(k, n):
    if not n:
        return None
    return [0.0 if k == 0 else round(beta_ppf(0.025, k, n - k + 1), 4),
            1.0 if k == n else round(beta_ppf(0.975, k + 1, n - k), 4)]


def rate(k, n):
    return {'k': k, 'n': n, 'rate': round(k / n, 4) if n else None, 'ci95': cp(k, n)}


def mcnemar_one_sided(b, c):
    m = b + c
    return sum(comb(m, i) for i in range(b, m + 1)) / 2 ** m if m else 1.0


def main():
    protocol = A.read(HERE / 'protocol.json')
    status = A.read(HERE / 'run-status.json')
    conditions = A.read(HERE / 'run-conditions.json')
    checks = {
        'run_complete': status.get('status') == 'complete',
        'protocol_unchanged': A.sha(HERE / 'protocol.json') == status['protocol_sha256'],
        'fixture_is_amendment_2_file': A.sha(FIXTURE) == FROZEN_FIXTURE_SHA == protocol['hashes']['fixture'],
        'runner_unchanged': A.sha(HERE / 'run_router_h6_llama.py') == protocol['hashes']['runner'],
        'prompts_unchanged': all(A.sha(HERE / 'prompts' / f'{a}.txt') == protocol['hashes'][a] for a in ARMS),
        'frozen_source_stable': status.get('frozen_source_stable') is True,
        'model_digest_stable': conditions['model_digest_before'] == conditions['model_digest_after']
                               == protocol['model']['digest'],
        'ollama_version_stable': conditions['ollama_version_before'] == conditions['ollama_version_after'],
    }
    rows = {r['id']: r for r in (json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip())}
    raw = {(arm, rep): [json.loads(l) for l in (HERE / 'raw' / f'r{rep}-{arm}.jsonl').read_text().splitlines()]
           for arm in ARMS for rep in (1, 2, 3)}
    checks['all_cells_full'] = all(len(v) == len(rows) and {r['id'] for r in v} == set(rows) for v in raw.values())
    if not all(checks.values()):
        print(json.dumps({'refused': True, 'checks': checks}, indent=1))
        return 1
    labels = defaultdict(lambda: {'semantic_scorable': False, 'native_semantic_scorable': False})
    correct = {(arm, rep, r['id']): A.correct(r) for (arm, rep), v in raw.items() for r in v}
    majority = {arm: {i: sum(correct[(arm, rep, i)] for rep in (1, 2, 3)) >= 2 for i in rows} for arm in ARMS}
    n = len(rows)
    b = sum(majority['A1'][i] and not majority['A0'][i] for i in rows)
    c = sum(majority['A0'][i] and not majority['A1'][i] for i in rows)
    m = b + c
    pi = cp(b, m)
    acc = {arm: sum(majority[arm].values()) for arm in ARMS}
    primary = {
        'unit': 'request, majority of 3 repetitions', 'n_requests': n,
        'b_A1_right_A0_wrong': b, 'c_A0_right_A1_wrong': c,
        'both_right': sum(majority['A1'][i] and majority['A0'][i] for i in rows),
        'both_wrong': sum(not majority['A1'][i] and not majority['A0'][i] for i in rows),
        'p_one_sided_exact': mcnemar_one_sided(b, c),
        'significant_at_0.05_before_holm': mcnemar_one_sided(b, c) < 0.05,
        'holm_adjusted_p': 'not applicable: exploratory, outside the Holm family',
        'b_over_c': round(b / c, 4) if c else None,
        'majority_accuracy': {arm: rate(acc[arm], n) for arm in ARMS},
        'accuracy_difference_A1_minus_A0': round((b - c) / n, 4),
        'accuracy_difference_ci95_paired_exact': [round(m / n * (2 * pi[0] - 1), 4), round(m / n * (2 * pi[1] - 1), 4)]
        if m else [0.0, 0.0],
    }
    secondary = {}
    for arm in ARMS:
        pooled = [r for rep in (1, 2, 3) for r in raw[(arm, rep)]]
        s = A.score(pooled, labels)
        held = [r for r in pooled if r['klass'] == 'actionable' and A.valid(r) and r['intent'] in A.HOLD]
        secondary[arm] = {
            'pooled_decisions': len(pooled),
            'binary_pooled': rate(s['binary']['k'], s['binary']['n']),
            'binary_by_class_pooled': {k: rate(sum(A.correct(r) for r in pooled if r['klass'] == k),
                                               sum(r['klass'] == k for r in pooled)) for k in CLASSES},
            'binary_by_class_majority': {k: rate(sum(majority[arm][i] for i in rows if rows[i]['klass'] == k),
                                                 sum(rows[i]['klass'] == k for i in rows)) for k in CLASSES},
            'abstention_precision': rate(s['abstention_precision']['k'], s['abstention_precision']['n']),
            'abstention_recall': rate(s['abstention_recall']['k'], s['abstention_recall']['n']),
            'over_abstention_actionable_held': rate(len(held), s['false_holds']['n']),
            'over_abstention_by_intent': dict(Counter(r['intent'] for r in held)),
            'errors': s['errors'], 'unknown': s['unknown'], 'source_counts': s['source_counts'],
            'by_language_binary_pooled': {lang: rate(sum(A.correct(r) for r in pooled if r['lang'] == lang),
                                                     sum(r['lang'] == lang for r in pooled)) for lang in ('en', 'mk')},
            'per_repetition_binary': {rep: rate(sum(A.correct(r) for r in raw[(arm, rep)]), n) for rep in (1, 2, 3)},
        }
    out = {'checks': checks, 'primary': primary, 'secondary': secondary,
           'label': 'exploratory secondary (llama3.1:8b), outside the Holm family; descriptive', 'model': protocol['model']['name'],
           'limitation': 'requests written by OpenAI Codex (gpt-6-astra), not a person (H6 Amendments 1-2)'}
    (HERE / 'summary.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'checks': checks, 'primary': primary}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
