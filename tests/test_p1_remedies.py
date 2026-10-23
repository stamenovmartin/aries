"""The remedy designed after P1 (experiments/thesis-p1-performance/diagnosis.json), behind its own flag.

ARIES_PLAN_CONTEXT_FIT  context_engine.planner_context: when the records added after the memory loop push the
                        planner context back over its budget, the lowest-ranked memories are dropped until it
                        fits, instead of failing the goal before its first planner call.

No model, no database: planner_context is a pure function of the historical sections and the packet.
"""
import json
import os
import random
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import check, run_module

BUDGET = 2500


def case(rng):
    memories = [{'id': f'm:{i}', 'source': 'memory', 'text': 'x' * rng.randint(150, 450), 'data_class': 'personal',
                 'authority': 'user_statement', 'observed_at': 0.0, 'expires_at': None, 'relevance': 1.0 - i / 10,
                 'sha256': '0' * 64} for i in range(rng.randint(2, 6))]
    packet = {'items': memories, 'required_sources': [], 'missing_sources': [], 'token_method': 'chars/4'}
    historical = {'reviews': [], 'preferences': [{'rule': 'y' * rng.randint(40, 120)} for _ in range(rng.randint(0, 12))],
                  'working_context': {'note': 'z' * rng.randint(0, 500)},
                  'worked_before': {'examples': ['w' * rng.randint(0, 400)]}}
    return historical, packet


def outcome(historical, packet):
    from aries.workspace.context_engine import planner_context
    try:
        return planner_context(json.loads(json.dumps(historical)), json.loads(json.dumps(packet)), max_chars=BUDGET)
    except ValueError:
        return None


def flags(**on):
    names = ('ARIES_PLAN_DISPATCH_FIX', 'ARIES_PLAN_CONTEXT_FIT')
    return patch.dict(os.environ, {n: '1' if on.get(n, False) else '0' for n in names})


async def test_the_defect_exists_and_the_flag_removes_it():
    rng = random.Random(20261023)
    cases = [case(rng) for _ in range(400)]
    with flags(ARIES_PLAN_DISPATCH_FIX=True):
        failed_before = sum(outcome(h, p) is None for h, p in cases)
    with flags(ARIES_PLAN_DISPATCH_FIX=True, ARIES_PLAN_CONTEXT_FIT=True):
        results = [outcome(h, p) for h, p in cases]
    check(f'with ARIES_PLAN_DISPATCH_FIX alone some contexts still fail ({failed_before} of {len(cases)})',
          failed_before > 0)
    check('with ARIES_PLAN_CONTEXT_FIT every one of them fits', all(r is not None for r in results))
    check('and every result is within the budget',
          all(len(json.dumps(r, ensure_ascii=False)) <= BUDGET for r in results))


async def test_off_is_unchanged():
    rng = random.Random(7)
    cases = [case(rng) for _ in range(200)]
    with flags(ARIES_PLAN_DISPATCH_FIX=True):
        a = [outcome(h, p) for h, p in cases]
    with flags(ARIES_PLAN_DISPATCH_FIX=True, ARIES_PLAN_CONTEXT_FIT=False):
        b = [outcome(h, p) for h, p in cases]
    check('flag off gives the same result as before, case by case', a == b)


async def test_only_memories_are_dropped_and_the_drop_is_recorded():
    rng = random.Random(11)
    with flags(ARIES_PLAN_DISPATCH_FIX=True):
        failing = [(h, p) for h, p in (case(rng) for _ in range(400)) if outcome(h, p) is None]
    with flags(ARIES_PLAN_DISPATCH_FIX=True, ARIES_PLAN_CONTEXT_FIT=True):
        fixed = [(p, outcome(h, p)) for h, p in failing]
    check('a context that needed the fit records how many memories it dropped',
          all(r['context_coverage'].get('fit_dropped_memories', 0) >= 1 for _, r in fixed))
    check('the kept memories are the highest-ranked ones, in order',
          all(r['memories'] == p['items'][:len(r['memories'])] for p, r in fixed))


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
