#!/usr/bin/env python3
"""H6 power analysis, before any H6 data exists: A1 vs A0 on 120 new requests.

Input: the frozen qwen2.5:7b router raw decisions (experiments/thesis-final-20261006/raw), scored
with the frozen scorer exactly as scripts/thesis_stats.py does (per request: majority of 3 correct).
Per true class, the four pair cells (A1 right / A0 wrong = b, A1 wrong / A0 right = c, both right,
both wrong) give the per-request probabilities. They are reweighted to the H6 class mix
(40 actionable, 30 ambiguous, 25 out of scope, 25 unsafe), and power of the exact McNemar test is
estimated by simulation (seed 61013, 20000 draws per scenario) for n = 120, 200 and 300 for the observed effect and for shrunken effects,
because a first estimate from the set that suggested the hypothesis is likely to be too large.
Writes power.json next to this file. No model, no service, no database.
"""
import importlib.util
import json
import random
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MIX = {'actionable': 40, 'ambiguous': 30, 'out_of_scope': 25, 'unsafe': 25}
SIZES = (120, 200, 300)          # the planned 120 and two larger sets with the same class shares


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def exact_p(b, c, sided):
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(b, n + 1)) / 2 ** n          # P(X >= b) under p = 0.5
    if sided == 'one':
        return tail
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n)


def main():
    S = load('thesis_stats', ROOT / 'scripts/thesis_stats.py')
    correct = S.frozen_scorer()
    raw = ROOT / 'experiments/thesis-final-20261006/raw'
    score, klass = {}, {}
    for arm in ('A0', 'A1'):
        for rep in (1, 2, 3):
            for line in (raw / f'r{rep}-{arm}.jsonl').read_text().splitlines():
                r = json.loads(line)
                score[(arm, rep, r['id'])] = bool(correct(r))
                klass[r['id']] = r['klass']
    major = {(a, i): sum(score[(a, rep, i)] for rep in (1, 2, 3)) >= 2 for a in ('A0', 'A1') for i in klass}
    cells = {k: {'b': 0, 'c': 0, 'both_right': 0, 'both_wrong': 0, 'n': 0} for k in MIX}
    for i, k in klass.items():
        a1, a0 = major[('A1', i)], major[('A0', i)]
        cell = 'b' if a1 and not a0 else 'c' if a0 and not a1 else 'both_right' if a1 else 'both_wrong'
        cells[k][cell] += 1
        cells[k]['n'] += 1
    total = {x: sum(cells[k][x] for k in MIX) for x in ('b', 'c', 'both_right', 'both_wrong', 'n')}
    # Probabilities per request under the H6 mix.
    n_new = sum(MIX.values())
    pb = sum(MIX[k] * cells[k]['b'] / cells[k]['n'] for k in MIX) / n_new
    pc = sum(MIX[k] * cells[k]['c'] / cells[k]['n'] for k in MIX) / n_new
    rng = random.Random(61013)
    scenarios = {}
    for size in SIZES:
      for label, shrink in (('observed', 1.0), ('effect halved', 0.5), ('effect quartered', 0.25)):
          # Shrink the excess of b over c, keeping the discordant rate fixed.
          disc = pb + pc
          share_b = 0.5 + shrink * (pb / disc - 0.5)
          qb, qc = disc * share_b, disc * (1 - share_b)
          res = {}
          for sided in ('one', 'two'):
              hits = 0
              for _ in range(20000):
                  b = c = 0
                  for _ in range(size):
                      u = rng.random()
                      if u < qb:
                          b += 1
                      elif u < qb + qc:
                          c += 1
                  hits += exact_p(b, c, sided) < 0.05 and b > c
              res[f'power_{sided}_sided'] = round(hits / 20000, 3)
          scenarios[f'n={size}, {label}'] = {'p_b': round(qb, 4), 'p_c': round(qc, 4), 'expected_discordant': round(size * disc, 1),
                              'share_b_among_discordant': round(share_b, 3), **res}
    out = {'what': 'power of exact McNemar, A1 vs A0, H6 class mix, n = 120, 200, 300', 'source': 'frozen qwen2.5:7b raw, '
           'majority of 3 per request', 'original_pairs_by_class': cells, 'original_total': total,
           'h6_mix': MIX, 'alpha': 0.05, 'simulations': 20000, 'seed': 61013, 'scenarios': scenarios,
           'note': 'Power counts only significant results in the predicted direction (b > c).'}
    (HERE / 'power.json').write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps({'original_total': total, 'by_class': cells, 'scenarios': scenarios}, indent=1))


if __name__ == '__main__':
    main()
