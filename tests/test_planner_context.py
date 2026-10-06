"""What the planner is shown before it plans, and what it is never shown instead.

Measured 2026-10-03: the planner received all 58 capabilities — 7,990 characters of
catalogue — inside a context window of `ai.context_tokens` 8,192 that also had to hold
the instruction and up to 7,000 characters of step history. On 2026-09-30 one task
rendered 22,738 characters and the fixed prompt was the part ollama discarded. It was
also told three facts about the machine (`home`, `demo_directory`, `now`) and nothing
about its current state, so "close it" or "split the screen" had nothing to resolve
against.

These tests fix the behaviour that followed, including the two failures found while
building it: selection with no signal returned the ten shortest names, and the memory
layer label compared against the wrong key prefix.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-planner-context')

from aries import flags
from aries.workspace import agent_planner
from aries.workspace.registry import registry
from aries.workspace.state_snapshot import recent_actions, snapshot

EMPTY = {'agent': {'contract': {'requirements': []}, 'environment': {'home': '/home/x'}}, 'steps': []}


def with_flags(**values):
    """Set flags for one call and restore, so order cannot change a result."""
    previous = {k: os.environ.get(k) for k in values}
    os.environ.update({k: v for k, v in values.items()})
    try:
        return agent_planner.context('split the screen left and right', EMPTY, 8)
    finally:
        for key, old in previous.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


async def test_selection_shortens_the_prompt_without_losing_the_right_tool():
    allowed = registry.describe_allowed()
    off = with_flags(ARIES_CAP_TOPK='0', ARIES_STATE_SNAPSHOT='0')
    on = with_flags(ARIES_CAP_TOPK='1', ARIES_STATE_SNAPSHOT='0')
    before = len(json.dumps(off, ensure_ascii=False))
    after = len(json.dumps(on, ensure_ascii=False))
    check(f'the prompt gets shorter ({before} -> {after} chars)', after < before * 0.6)
    check('and says how many of how many it is showing',
          'of %d' % len(allowed) in (on.get('capabilities_shown') or ''))
    first = agent_planner.relevant(allowed, 'split the screen left and right', EMPTY)[0]['name']
    check(f'the right tool is ranked first, not merely included (got {first})',
          first == 'desktop.tile')
    check('maximise wins for a fullscreen request',
          agent_planner.relevant(allowed, 'make firefox fullscreen', EMPTY)[0]['name'] == 'desktop.maximize')
    check('reading the clipboard wins for a clipboard question',
          agent_planner.relevant(allowed, 'what is on the clipboard', EMPTY)[0]['name'] == 'input.clipboard_read')


async def test_no_signal_shows_everything_rather_than_an_arbitrary_ten():
    """The failure this guards: 'turn the volume down' matched nothing — the planner
    registry has no volume tool — and the tie-break returned the ten shortest names,
    all `file.*`. Ten wrong options read as a capability surface; everything reads as
    what it is."""
    allowed = registry.describe_allowed()
    for goal in ('turn the volume down', 'install vlc', 'xyzzy plugh'):
        chosen = agent_planner.relevant(allowed, goal, EMPTY)
        check(f'no lexical signal shows all {len(allowed)}: {goal!r}', len(chosen) == len(allowed))


async def test_a_capability_already_used_is_never_dropped():
    allowed = registry.describe_allowed()
    data = {'agent': {'contract': {'requirements': []}, 'environment': {}},
            'steps': [{'capability': 'input.clipboard_write', 'state': 'done'}]}
    names = [c['name'] for c in agent_planner.relevant(allowed, 'read file notes.txt', data)]
    check('a half-finished route can still be continued or corrected',
          'input.clipboard_write' in names)


async def test_the_snapshot_reports_what_it_could_not_read():
    taken = snapshot()
    check('it always carries a clock', 'now' in taken)
    check('it is bounded and says how long it took',
          isinstance(taken.get('snapshot_ms'), int) and taken['snapshot_ms'] < 4000)
    for section in ('windows', 'audio'):
        value = taken[section]
        check(f'{section} is either a reading or a stated reason',
              isinstance(value, dict) and (value.get('unavailable') or len(value) > 0))
    if any(isinstance(v, dict) and v.get('unavailable') for v in taken.values()):
        check('an unreadable section is announced, so absent is not read as empty',
              'Absent is not empty' in (taken.get('note') or ''))


async def test_recent_actions_carry_the_verdict_not_just_the_attempt():
    data = {'steps': [
        {'capability': 'file.write', 'execution_status': 'done',
         'verification': {'met': True, 'evidence': 'file exists'}},
        {'capability': 'research', 'execution_status': 'done',
         'verification': {'met': None, 'unverifiable': True}},
        {'capability': 'desktop.tile', 'execution_status': 'failed',
         'error': {'code': 'TARGET_NOT_FOUND'}}]}
    seen = recent_actions(data)
    check('a verified action is marked verified', seen[0]['verified'] is True)
    check('an unverifiable one is marked unverifiable, not failed',
          seen[1]['unverifiable'] and seen[1]['verified'] is None)
    check('a typed error code survives into the observation',
          seen[2]['error'] == 'TARGET_NOT_FOUND')


async def test_every_flag_is_readable_and_enumerable():
    described = flags.describe()
    for name in ('ARIES_CAP_TOPK', 'ARIES_STATE_SNAPSHOT', 'ARIES_PLAN_MEMORY'):
        check(f'{name} is enumerable for an ablation', name in described['flags'])
        check(f'{name} reports where its value came from',
              described['flags'][name]['source'] in {'default', 'environment'}
              or described['flags'][name]['source'].startswith('file '))
    check('an unknown flag raises instead of reading False',
          _raises(lambda: flags.enabled('ARIES_NOT_A_FLAG')))


def _raises(call):
    try:
        call()
    except KeyError:
        return True
    return False


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
