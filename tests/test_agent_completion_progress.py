"""Focused real-loop regression for rejected completion, using a scripted planner."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_agent_execution import setup, run_goal, execute, finish
from tests._bootstrap import check, run_module


async def test_rejected_finish_is_bounded_and_flag_off_keeps_old_loop():
    await setup(limit=3)
    with patch.dict(os.environ, {"ARIES_COMPLETION_PROGRESS_GUARD": "1", "ARIES_CONTRACT_FINISH": "0"}):
        result = await run_goal('Show system status', [{'action': 'finish', 'evidence_refs': []}])
    check('two rejected finishes stop without false success', result['state'] == 'failed'
          and result['agent']['metrics']['planner_calls'] == 2
          and result['agent']['stop_reason'] == 'COMPLETION_NO_PROGRESS')
    await setup(limit=3)
    with patch.dict(os.environ, {"ARIES_COMPLETION_PROGRESS_GUARD": "0", "ARIES_CONTRACT_FINISH": "0"}):
        baseline = await run_goal('Show system status', [{'action': 'finish', 'evidence_refs': []}])
    check('flag off retains previous call-budget path', baseline['state'] == 'failed'
          and baseline['agent']['metrics']['planner_calls'] == 10
          and 'stop_reason' not in baseline['agent'])


async def test_corrected_reference_can_complete():
    await setup()
    with patch.dict(os.environ, {"ARIES_COMPLETION_PROGRESS_GUARD": "1", "ARIES_CONTRACT_FINISH": "0"}):
        result = await run_goal('Show system status', [execute('system.status'),
            {'action': 'finish', 'evidence_refs': ['unknown']}, finish])
    check('a corrected finish is validated before the guard', result['state'] == 'done'
          and result['agent']['metrics']['planner_calls'] == 3
          and len(result['agent']['completion_checks']) == 2)


async def test_action_after_rejection_can_establish_evidence():
    await setup()
    with patch.dict(os.environ, {"ARIES_COMPLETION_PROGRESS_GUARD": "1", "ARIES_CONTRACT_FINISH": "0"}):
        result = await run_goal('Show system status', [{'action': 'finish', 'evidence_refs': []},
            execute('system.status'), {'action': 'finish', 'evidence_refs': ['wrong']}, finish])
    check('new action gives a fresh correction opportunity', result['state'] == 'done'
          and result['agent']['metrics']['planner_calls'] == 4)


if __name__ == '__main__':
    raise SystemExit(run_module(sys.modules[__name__]))
