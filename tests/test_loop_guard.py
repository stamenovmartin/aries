"""ARIES_LOOP_GUARD: a planner that keeps proposing the same action is stopped.

The defect (docs/AUDIT.md section 4b): the planner proposes the same capability and
arguments again, `agent.py` rejects it as a duplicate, the rejected step still
consumes the step budget, and the loop replans until the budget is gone (138 of 242
steps in the held-out run). Under the flag the fingerprint of every proposal is the
capability plus the canonical JSON of its arguments; on the SECOND duplicate of a
fingerprint in one goal the agent stops planning and ends the goal through the same
terminal machinery as budget exhaustion (partial if anything was verified, else
failed), with stop_reason REPEATED_ACTION and the fingerprint and count recorded.
Off, the loop is the frozen one.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_agent_execution import setup, run_goal, execute
from tests._bootstrap import check, run_module

# The goal asks for the file, so the write is authorised; automatic contract finish
# is held off so that only the repeating stub planner decides what happens next.
def goal(directory):
    return f'Create a file called scratch.txt in {directory} containing:\nsame\nThen read it back.'


ENV = {'ARIES_CONTRACT_FINISH': '0'}


def test_flag_is_registered_and_off_by_default():
    from aries import flags
    check('registered', 'ARIES_LOOP_GUARD' in flags.FLAGS)
    check('default off', flags.FLAGS['ARIES_LOOP_GUARD'][0] is False)


def test_fingerprint_is_canonical():
    from aries.workspace import loop_guard
    a = loop_guard.fingerprint('file.write', {'path': '/tmp/a', 'content': 'x'})
    b = loop_guard.fingerprint('file.write', {'content': 'x', 'path': '/tmp/a'})
    c = loop_guard.fingerprint('file.write', {'content': 'y', 'path': '/tmp/a'})
    check('argument order does not matter', a == b)
    check('a different argument is a different action', a != c)
    check('a different capability is a different action',
          a != loop_guard.fingerprint('file.edit', {'path': '/tmp/a', 'content': 'x'}))


async def test_repeating_planner_is_stopped_on_the_second_duplicate():
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path = str(Path(directory) / 'scratch.txt')
        repeat = [execute('file.write', path=path, content='same')]
        await setup(limit=8)
        with patch.dict('os.environ', {**ENV, 'ARIES_LOOP_GUARD': '1'}):
            result = await run_goal(goal(directory), repeat)
        agent = result['agent']
        check('stopped with a typed reason', agent.get('stop_reason') == 'REPEATED_ACTION')
        check('same terminal state as budget exhaustion (partial: the first write verified)',
              result['state'] == 'partial')
        check('three proposals, two of them duplicates: stopped at the third planner call',
              agent['metrics']['planner_calls'] == 3)
        check('the second duplicate is not executed (two steps)', len(result['steps']) == 2)
        check('first duplicate still rejected as before',
              (result['steps'][1].get('error') or {}).get('code') == 'NON_RETRYABLE')
        record = agent.get('repeated_action') or {}
        check('fingerprint recorded', record.get('capability') == 'file.write'
              and record.get('arguments') == {'path': path, 'content': 'same'}
              and isinstance(record.get('fingerprint'), str))
        check('count recorded (proposals of this fingerprint, duplicates)',
              record.get('count') == 3 and record.get('duplicates') == 2)
        check('earlier steps of the fingerprint named',
              record.get('step_ids') == [s['step_id'] for s in result['steps']])
        check('decision event carries the typed error',
              (agent['decisions'][-1].get('error') or {}).get('code') == 'REPEATED_ACTION')
        check('summary says why', 'REPEATED_ACTION' in agent.get('summary', ''))


async def test_off_keeps_the_old_loop():
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path = str(Path(directory) / 'scratch.txt')
        await setup(limit=8)
        with patch.dict('os.environ', {**ENV, 'ARIES_LOOP_GUARD': '0'}):
            result = await run_goal(goal(directory), [execute('file.write', path=path, content='same')])
        agent = result['agent']
        check('off: no stop reason', 'stop_reason' not in agent and 'repeated_action' not in agent)
        check('off: duplicates consume the whole step budget', len(result['steps']) == 8)
        check('off: budget exhaustion message', 'Action budget exhausted' in agent.get('summary', ''))
        check('off: same terminal state', result['state'] == 'partial')


async def test_changing_arguments_is_not_a_loop():
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path = str(Path(directory) / 'scratch.txt')
        seq = [execute('file.write', path=path, content='v' + str(i)) for i in range(4)]
        seq.append({'action': 'fail', 'reason': 'done writing'})
        await setup(limit=8)
        with patch.dict('os.environ', {**ENV, 'ARIES_LOOP_GUARD': '1'}):
            result = await run_goal(goal(directory), seq)
        check('distinct actions are not stopped', result['agent'].get('stop_reason') is None
              and len(result['steps']) == 4)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
