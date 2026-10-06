#!/usr/bin/env python3
"""Чесните бројки за верификација, со именители што издржуваат проверка.

Постои затоа што трудот ги наведува 325/381 = 85.3% и 0/325 како бројки за работата
на системот, а тие се подвижен примерок од 500 најнови цели врз 8.025, па:

  * процентот се движи со денот (85.3% на 4 октомври, 76.9% на 6 октомври)
  * противречностите изгледаат нула само затоа што двете што постојат се надвор од
    примерокот
  * „верификувано“ брои и чекори чиј верификатор структурно не може да падне

Сè овде се чита само за читање од дневникот и се пресметува врз СИТЕ цели.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sqlite3
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = f'file:{ROOT}/var/aries.db?mode=ro'


def wilson(k: int, n: int, z: float = 1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def main() -> int:
    classes = {}
    path = HERE / 'raw/review_verifier_integrity.json'
    if path.exists():
        classes = {c['name']: c['verifier_class']
                   for c in json.loads(path.read_text())['capabilities']}

    c = sqlite3.connect(DB, uri=True)
    goals = c.execute('select count(*) from aries_workspace_goals').fetchone()[0]
    per_class = collections.defaultdict(collections.Counter)
    status = collections.Counter()
    steps = 0
    for (rj,) in c.execute('select result_json from aries_workspace_goals '
                           'where result_json is not null'):
        try:
            d = json.loads(rj)
        except Exception:
            continue
        for s in d.get('steps') or []:
            steps += 1
            vs = s.get('verification_status')
            if vs:
                status[vs] += 1
            if vs in ('verified', 'verification_failed'):
                per_class[classes.get(s.get('capability'), 'OUTSIDE_REGISTRY')][vs] += 1

    verified = status['verified']
    failed = status['verification_failed']
    reached = verified + failed
    falsifiable = {'INDEPENDENT', 'PLANNER_SUPPLIED'}
    can_fail = sum(v['verified'] + v['verification_failed']
                   for k, v in per_class.items() if k in falsifiable)
    cannot_fail = sum(v['verified'] + v['verification_failed']
                      for k, v in per_class.items() if k in ('TRIVIAL', 'SELF_REPORT'))

    commit = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    out = {
      'generated_from': 'experiments/product/independent-acceptance/verification_truth.py',
      'commit': commit,
      'scope': 'EVERY goal in the ledger, not a capped sample',
      'why_this_file_exists':
        'aries/analytics takes the newest Window.goal_scan=500 goals within the window '
        '(RECENT_GOALS ... LIMIT :cap). With 8,025 goals that is 6.2%. The two verification '
        'metrics do not emit the `truncated` flag the Window docstring promises; only '
        'analytics/outcomes.py:135 does. So the published figures are a moving sample '
        'reported as a total.',
      'totals': {'goals': goals, 'steps': steps,
                 'steps_by_verification_status': dict(status)},
      'verification': {
        'reached_a_verifier': reached,
        'verified': verified,
        'contradicted': failed,
        'contradiction_rate': {'numerator': failed, 'denominator': reached,
                               'value': round(failed / reached, 5) if reached else None,
                               'wilson_95': wilson(failed, reached),
                               'of': 'steps whose verifier returned a verdict'},
      },
      'by_verifier_class': {
        k: {'verified': v['verified'], 'contradicted': v['verification_failed'],
            'total': v['verified'] + v['verification_failed'],
            'contradiction_rate': round(v['verification_failed'] /
                                        (v['verified'] + v['verification_failed']), 5)
                                  if (v['verified'] + v['verification_failed']) else None}
        for k, v in sorted(per_class.items())},
      'the_number_that_should_be_quoted': {
        'statement': 'Of steps whose verifier could structurally return a negative verdict, '
                     'this share were contradicted.',
        'falsifiable_steps': can_fail,
        'unfalsifiable_steps': cannot_fail,
        'outside_the_m14_registry': sum(v['verified'] + v['verification_failed']
                                        for k, v in per_class.items()
                                        if k == 'OUTSIDE_REGISTRY'),
        'caution': 'OUTSIDE_REGISTRY steps ran through the older deterministic vocabulary and '
                   'were NOT classified. No claim is made about them in either direction.'},
      'drift_observed': {'2026-10-04': '325/381 = 85.3%', '2026-10-06': '290/377 = 76.9%',
                         'note': 'same endpoint, same window parameter, two days apart'},
    }
    (HERE / 'raw/verification_truth.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"цели {goals}  чекори {steps}")
    print(f"стигнале до верификатор: {reached}   верификувани {verified}   противречни {failed}")
    r = out['verification']['contradiction_rate']
    print(f"стапка на противречност: {r['numerator']}/{r['denominator']} = "
          f"{r['value']:.5f}  Wilson95 {r['wilson_95']}")
    print()
    print(f"{'класа':22s} {'верификувани':>12s} {'противречни':>12s} {'стапка':>9s}")
    for k, v in out['by_verifier_class'].items():
        rate = '—' if v['contradiction_rate'] is None else f"{v['contradiction_rate']:.5f}"
        print(f"{k:22s} {v['verified']:12d} {v['contradicted']:12d} {rate:>9s}")
    print()
    print(f"оборливи чекори   : {can_fail}")
    print(f"необорливи чекори : {cannot_fail}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
