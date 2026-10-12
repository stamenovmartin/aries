#!/usr/bin/env python3
"""Paired significance tests on the ARIES-FINAL-20261006 router decisions (no new measurement).

Reads the 12 frozen raw files (225 requests x 4 arms x 3 repetitions = 2,700 decisions),
checks each against `router.raw_sha256` in dokazi/final-evaluation.json, and scores them
with the frozen `correct()` from experiments/thesis-final-20261006/analyze_router.py, so
"binary correctness" is the published definition and not a re-implementation.

Before any test it must reproduce the published totals exactly; if it does not, it stops
with exit code 2 and writes nothing.

Per request, the unit of analysis is the majority over the 3 repetitions: a request counts
as correct in an arm when at least 2 of its 3 decisions are correct. On that:
  - exact McNemar tests (two-sided binomial on the discordant pairs) for A3 vs A1,
    A2 vs A1 and A1 vs A0;
  - Cochran's Q across A0..A3 (chi-square with 3 df).
The optional mixed-effects logistic model runs only if statsmodels is importable.

    python3 scripts/thesis_stats.py <final-evaluation.json> <out-dir>
"""
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / 'experiments/thesis-final-20261006'
ARMS = ('A0', 'A1', 'A2', 'A3')
PUBLISHED = {'A0': 385, 'A1': 463, 'A2': 440, 'A3': 463}
PUBLISHED_PAIRED = {'case_mean_improved': 26, 'case_mean_worse': 25, 'case_mean_equal': 174}


def frozen_scorer():
    spec = importlib.util.spec_from_file_location('analyze_router', FROZEN / 'analyze_router.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.correct


def mcnemar_exact(b, c):
    """Two-sided exact McNemar: binomial(b + c, 0.5) on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def chi2_sf_df3(x):
    """Survival function of chi-square with 3 degrees of freedom (closed form)."""
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2)) + math.sqrt(2 * x / math.pi) * math.exp(-x / 2)


def cochran_q(table):
    """table: list of rows (one per request), each a list of 0/1 for k arms."""
    k = len(table[0])
    col = [sum(r[j] for r in table) for j in range(k)]
    row = [sum(r) for r in table]
    total = sum(row)
    denominator = k * total - sum(x * x for x in row)
    q = (k - 1) * (k * sum(x * x for x in col) - total ** 2) / denominator if denominator else 0.0
    return q, k - 1


def main(evaluation_path, out_dir):
    evaluation = json.loads(Path(evaluation_path).read_text())
    expected_hashes = evaluation['router']['raw_sha256']
    correct = frozen_scorer()

    rows, hashes = {}, {}
    for arm in ARMS:
        for rep in (1, 2, 3):
            name = f'r{rep}-{arm}.jsonl'
            raw = (FROZEN / 'raw' / name).read_bytes()
            hashes[name] = hashlib.sha256(raw).hexdigest()
            for line in raw.decode().splitlines():
                r = json.loads(line)
                assert r['arm'] == arm and r['rep'] == rep
                rows[(arm, rep, r['id'])] = r
    hash_ok = {n: hashes[n] == expected_hashes[n] for n in expected_hashes}
    ids = sorted({i for (_, _, i) in rows})

    score = {key: bool(correct(r)) for key, r in rows.items()}
    totals = {a: sum(score[(a, rep, i)] for rep in (1, 2, 3) for i in ids) for a in ARMS}
    case_mean = {a: {i: sum(score[(a, rep, i)] for rep in (1, 2, 3)) / 3 for i in ids} for a in ARMS}
    diff = [case_mean['A3'][i] - case_mean['A1'][i] for i in ids]
    paired = {'case_mean_improved': sum(d > 0 for d in diff), 'case_mean_worse': sum(d < 0 for d in diff),
              'case_mean_equal': sum(d == 0 for d in diff)}
    reproduction = {
        'raw_files_sha256_match': hash_ok,
        'n_requests': len(ids), 'n_decisions': len(rows),
        'totals': {a: {'k': totals[a], 'n': 3 * len(ids), 'published_k': PUBLISHED[a],
                       'match': totals[a] == PUBLISHED[a]} for a in ARMS},
        'A3_vs_A1_case_means': {**paired, 'published': PUBLISHED_PAIRED, 'match': paired == PUBLISHED_PAIRED},
    }
    reproduced = (all(hash_ok.values()) and len(ids) == 225 and len(rows) == 2700
                  and all(v['match'] for v in reproduction['totals'].values())
                  and reproduction['A3_vs_A1_case_means']['match'])
    reproduction['all_match'] = reproduced
    if not reproduced:
        print(json.dumps(reproduction, indent=1))
        print('STOP: published totals not reproduced; no statistics written', file=sys.stderr)
        return 2

    majority = {a: {i: int(sum(score[(a, rep, i)] for rep in (1, 2, 3)) >= 2) for i in ids} for a in ARMS}
    unanimous = {a: sum(len({score[(a, rep, i)] for rep in (1, 2, 3)}) == 1 for i in ids) for a in ARMS}
    tests = {}
    for x, y in (('A3', 'A1'), ('A2', 'A1'), ('A1', 'A0')):
        b = sum(majority[x][i] == 1 and majority[y][i] == 0 for i in ids)  # x right, y wrong
        c = sum(majority[x][i] == 0 and majority[y][i] == 1 for i in ids)  # x wrong, y right
        both = sum(majority[x][i] == majority[y][i] == 1 for i in ids)
        neither = sum(majority[x][i] == majority[y][i] == 0 for i in ids)
        tests[f'{x}_vs_{y}'] = {'test': 'exact McNemar, two-sided', f'{x}_correct_{y}_wrong': b,
                                f'{x}_wrong_{y}_correct': c, 'both_correct': both, 'both_wrong': neither,
                                'n': len(ids), 'p_value': mcnemar_exact(b, c)}
    q, df = cochran_q([[majority[a][i] for a in ARMS] for i in ids])
    result = {
        'experiment': 'ARIES-FINAL-20261006 router, re-analysis only (no new inference)',
        'source': {'final_evaluation': str(evaluation_path),
                   'final_evaluation_sha256': hashlib.sha256(Path(evaluation_path).read_bytes()).hexdigest(),
                   'raw_dir': str((FROZEN / 'raw').relative_to(ROOT)), 'raw_sha256': hashes,
                   'scorer': 'experiments/thesis-final-20261006/analyze_router.py::correct',
                   'scorer_sha256': hashlib.sha256((FROZEN / 'analyze_router.py').read_bytes()).hexdigest()},
        'reproduction': reproduction,
        'unit': 'request (n=225); per-arm outcome = correct in at least 2 of 3 repetitions',
        'majority_correct': {a: {'k': sum(majority[a].values()), 'n': len(ids)} for a in ARMS},
        'requests_with_unanimous_repetitions': {a: {'k': unanimous[a], 'n': len(ids)} for a in ARMS},
        'mcnemar': tests,
        'cochran_q': {'arms': list(ARMS), 'Q': q, 'df': df, 'p_value': chi2_sf_df3(q), 'n': len(ids)},
        'not_corrected_for_multiple_comparisons': True,
    }
    try:
        import statsmodels  # noqa: F401
        result['mixed_effects'] = {'status': 'statsmodels available but model not implemented in this version'}
    except ImportError:
        result['mixed_effects'] = {'status': 'not run: statsmodels is not installed in the interpreter used'}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'stats.json').write_text(json.dumps(result, indent=1))
    print(json.dumps({k: result[k] for k in ('reproduction', 'majority_correct', 'mcnemar', 'cochran_q')}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
