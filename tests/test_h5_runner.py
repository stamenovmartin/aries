"""The H5 runner's conditions and outcome rules (experiments/thesis-followup-20261012/h5-runs/run_h5.py).

No instance, model or item is used: the runner module is loaded and its pure functions are checked.
"""
import importlib.util
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import check, run_module

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('run_h5', ROOT / 'experiments/thesis-followup-20261012/h5-runs/run_h5.py')
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)


def test_conditions_are_the_registered_ones():
    from aries import flags
    t, c = H.CONDITIONS['treatment'], H.CONDITIONS['control']
    check('every named flag exists', all(k in flags.FLAGS for cond in H.CONDITIONS.values() for k in cond))
    check('treatment: both completion flags on', t['ARIES_COMPLETION_READ_PARAPHRASE'] == t['ARIES_COMPLETION_TYPED_CONTRACT'] == '1')
    check('control: both off', c['ARIES_COMPLETION_READ_PARAPHRASE'] == c['ARIES_COMPLETION_TYPED_CONTRACT'] == '0')
    check('clarify, guard and resolver pinned off in both; the hook on in both',
          all(cond[k] == '0' for cond in (t, c) for k in ('ARIES_PLANNER_CLARIFY', 'ARIES_PLANNER_CLARIFY_GUARD',
                                                          'ARIES_CLARIFY_RESOLVER'))
          and t['ARIES_MEASURE_CHANGE_HOOK'] == c['ARIES_MEASURE_CHANGE_HOOK'] == '1')
    check('the conditions differ only in the two treatment flags',
          {k for k in t if t[k] != c[k]} == {'ARIES_COMPLETION_READ_PARAPHRASE', 'ARIES_COMPLETION_TYPED_CONTRACT'})


def test_outcome_rules():
    done = {'state': 'done', 'agent': {'contract': {'supported': True, 'recognised_by': 'typed'}, 'decisions': [1]}}
    partial = {'state': 'partial', 'agent': {'contract': {'supported': False}, 'decisions': [1],
                                             'completion_checks': [{'met': False}]}}
    check('G: done + PASS is a correct done', H.h5_outcome('G', done, 'PASS')['correct_done'] is True)
    check('G: done + FAIL is a false done, not correct',
          H.h5_outcome('G', done, 'FAIL')['correct_done'] is False and H.h5_outcome('G', done, 'FAIL')['false_done'])
    check('N: any done is a false done', H.h5_outcome('N', done, 'FAIL')['false_done'] is True)
    check('N: not done is not a false done', H.h5_outcome('N', partial, 'PASS')['false_done'] is False)
    check('held-out: no H5 outcome, PASS counted separately', H.h5_outcome('heldout', done, 'PASS')['correct_done'] is None)
    check('contract source and end path are recorded',
          H.h5_outcome('G', done, 'PASS')['contract_source'] == 'typed step'
          and H.h5_outcome('G', partial, 'FAIL')['end_path'] == 'finish rejected'
          and H.end_path({'state': 'failed', 'agent': {'decisions': []}}) == 'never planned')


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
