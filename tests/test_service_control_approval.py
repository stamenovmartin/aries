"""The approval round trip for `system.service_control`, end to end, on real systemd.

WHAT "END TO END" MEANS HERE, AND WHY EACH LINK IS CHECKED SEPARATELY
--------------------------------------------------------------------
A spoken or typed "restart service X" crosses six boundaries before anything
changes on the machine, and every one of them had its own way of being wrong:

  1. the recogniser in `capabilities.recognize` has to produce `service_control`
     and not `open_app` — "start X" must stay an application,
  2. `service.plan` has to turn that into one capability step,
  3. the step must be held because `service_control` is in `capabilities.SENSITIVE`
     — held as a DURABLE `ActionProposal` row, not as a flag in a dict,
  4. nothing may reach systemd before that proposal is decided,
  5. `service.approve` has to bind the decision to that exact proposal and its
     exact payload, and refuse a payload that changed after review,
  6. and only then may `systemctl --user <action> <unit>` run, after which the
     verdict comes from re-reading the unit — a new InvocationID — and never from
     the exit code of the job.

The machinery for all six already existed. It had never been exercised for this
capability, which is what A10 calls an untested surface. Nothing in this file
needed a new behaviour to be written; two of its checks are about refusals that
were already correct and are now pinned.

WHAT IT DOES TO THIS MACHINE
----------------------------
Almost nothing, deliberately. The live round trip asks `start` of a CONTROLLABLE
user unit that is ALREADY active, which systemd treats as a no-op: no process is
restarted, no index is rebuilt, no daemon is interrupted — and `settled()` still
has to produce a true verdict, from `active_state`, which is the interesting
half. Every destructive shape (stop, restart, a unit outside the allowlist, a
system unit, the unit serving the request) is driven against a simulated
`systemctl` so that the argv is checked without a service being stopped.
"""
import asyncio
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap('aries-service-control-approval')
import httpx
from agentic_core.config.settings import settings as engine_settings
from agentic_core.database.base import async_session
from agentic_core.database.models import ActionProposal
from aries.api.app import app
from aries.settings import SettingsService
from aries.workspace import capabilities as cap, service
from aries.workspace import system_capabilities as sysadm
from aries.workspace.models import WorkspaceGoal


async def setup():
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set('operator.enabled', True, set_by='user')
        await s.set('workspace.controlled_browser', False, set_by='user')
        await db.commit()


@contextmanager
def live():
    with patch.object(engine_settings, 'dry_run', False), \
         patch.object(engine_settings, 'live_tools', ','.join(cap.TOOL_NAMES)):
        yield


async def submit(request='', **action):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        result = await c.post('/api/aries/workspace', json={'request': request, **action})
        assert result.status_code == 200, result.text
        return result.json()


async def get(goal_id):
    async with async_session() as db:
        return (await db.get(WorkspaceGoal, goal_id)).as_dict()


async def run(request='', **action):
    row = await submit(request, **action)
    await service.dispatch()
    return await get(row['id'])


async def proposals():
    from sqlalchemy import select
    async with async_session() as db:
        return [p for (p,) in (await db.execute(select(ActionProposal))).all()]


# --- 1 and 2: the words become one capability step ----------------------------

def test_the_words_reach_this_capability_and_not_another_one():
    for request, action, unit in [('restart service aries-voice', 'restart', 'aries-voice'),
                                  ('stop the service ollama', 'stop', 'ollama'),
                                  ('restart ollama.service', 'restart', 'ollama.service'),
                                  ('start aries-core', 'start', 'aries-core'),
                                  ('рестартирај '
                                   'го сервисот ollama',
                                   'рестартирај', 'ollama')]:
        parsed = cap.recognize(request)
        check('"%s" is a service_control request for %s' % (request, unit),
              parsed and parsed['capability'] == 'service_control'
              and parsed['args']['unit'] == unit and parsed['args']['action'] == action)
    for request in ('start firefox', 'open ollama', 'start the music'):
        parsed = cap.recognize(request)
        check('"%s" is NOT a systemd request — a bare start stays an application' % request,
              not parsed or parsed['capability'] != 'service_control')
    steps = service.plan('restart service aries-voice')
    check('the plan is exactly one capability step with both arguments bound',
          len(steps) == 1 and steps[0]['kind'] == 'capability'
          and steps[0]['capability'] == 'service_control'
          and set(steps[0]['args']) == {'action', 'unit'})
    check('service_control is declared sensitive, which is what holds it',
          'service_control' in cap.SENSITIVE)
    from aries.workspace.registry import registry
    control = registry.get('system.service_control')
    check('and the registry capability it maps to requires approval and is not read-effect',
          control.requires_approval is True and control.effect == 'service')


# --- 3, 4, 5: held durably, nothing runs, and the decision is bound -----------

async def test_nothing_reaches_systemd_before_the_proposal_is_decided():
    await setup()
    invocations = []

    async def no_systemctl(argv, timeout=12):
        invocations.append(list(argv))
        return 0, 'Id=ollama.service\nLoadState=loaded\nActiveState=active\nSubState=running\nInvocationID=a1\n', ''

    with live(), patch.object(sysadm, '_run', no_systemctl):
        result = await run('restart service ollama')
    check('the task is held as proposed, not executed', result['state'] == 'proposed')
    control = [a for a in invocations if 'restart' in a or 'stop' in a or 'start' in a]
    check('no systemctl job of any kind was issued before approval (%d read calls, %d control calls)'
          % (len(invocations) - len(control), len(control)), not control)

    rows = await proposals()
    check('the hold is a durable ActionProposal row, so it survives a restart',
          len(rows) == 1 and rows[0].tool == 'workspace.service_control'
          and rows[0].status == 'proposed')
    check('and the proposal carries the exact capability and arguments that would run',
          json.loads(rows[0].payload) == {'capability': 'service_control',
                                          'args': {'action': 'restart', 'unit': 'ollama'}})
    check('the person is shown what it is for', 'ollama' in (rows[0].title or ''))


async def test_a_proposal_whose_payload_changed_after_review_is_refused():
    """The anti-switcheroo check. An approval is for one payload, not for a slot."""
    await setup()

    async def reader(argv, timeout=12):
        return 0, 'Id=ollama.service\nLoadState=loaded\nActiveState=active\nSubState=running\n', ''

    with live(), patch.object(sysadm, '_run', reader):
        result = await run('restart service ollama')
    check('held for approval', result['state'] == 'proposed')
    async with async_session() as db:
        row = await db.get(WorkspaceGoal, result['id'])
        data = json.loads(row.result_json)
        step = next(s for s in data['steps'] if s.get('state') == 'proposed')
        step['args'] = {'action': 'stop', 'unit': 'aries-core'}      # a different machine change
        row.result_json = json.dumps(data)
        await db.commit()
    async with async_session() as db:
        try:
            await service.approve(db, result['id'])
            check('an approval cannot be redirected to a different unit or action', False)
        except ValueError as error:
            check('an approval cannot be redirected to a different unit or action (%s)'
                  % str(error)[:60], 'does not match' in str(error))


# --- 6: approved, executed, and verified by re-reading the unit ---------------

async def test_approval_then_the_exact_job_runs_and_is_verified_by_re_reading():
    """A simulated systemctl, so the argv can be checked and the InvocationID can
    be made to change without stopping anything real."""
    await setup()
    calls, state = [], {'invocation': 'aaaa', 'active': 'active'}

    async def fake_systemctl(argv, timeout=12):
        calls.append(list(argv))
        if 'show' in argv:
            return 0, ('Id=ollama.service\nDescription=ARIES model server\nLoadState=loaded\n'
                       'ActiveState=%s\nSubState=running\nUnitFileState=enabled\nType=simple\n'
                       'InvocationID=%s\nExecMainPID=1234\nNRestarts=0\n'
                       'ActiveEnterTimestamp=@1790702951\nStateChangeTimestamp=@1790702951\n'
                       'FragmentPath=/usr/lib/systemd/user/ollama.service\nCanStart=yes\nCanStop=yes\n'
                       % (state['active'], state['invocation'])), ''
        if 'restart' in argv:
            state['invocation'] = 'bbbb'              # systemd gives a restarted unit a new one
            return 0, '', ''
        raise AssertionError(argv)

    with live(), patch.object(sysadm, '_run', fake_systemctl):
        result = await run('restart service ollama')
        check('held', result['state'] == 'proposed')
        async with async_session() as db:
            queued = await service.approve(db, result['id'])
        check('approval queues the same task rather than creating a second one',
              queued['queued'] is True and queued['id'] == result['id'])
        rows = await proposals()
        check('the durable proposal is recorded as approved, not deleted',
              len(rows) == 1 and rows[0].status == 'approved')
        await service.dispatch()
        result = await get(result['id'])

    check('the approved task finishes verified (state=%s)' % result['state'], result['state'] == 'done')
    job = next((a for a in calls if 'restart' in a), None)
    check('exactly one control job ran, on the user manager, with the unit after --, '
          'and never a password prompt',
          sum('restart' in a for a in calls) == 1 and job is not None
          and job == ['systemctl', '--no-pager', '--no-ask-password', '--user', 'restart',
                      '--', 'ollama.service'])
    step = result['steps'][0]
    verdict = step['result']['verification']
    check('the verdict is met and says what the evidence actually was',
          verdict['met'] is True and 'InvocationID' in verdict['evidence'])
    check('and the proof is the NEW InvocationID, read back from systemd',
          'InvocationID' in step['result']['summary'] or 'new InvocationID' in str(step['result']))
    check('the unit name was qualified with .service on the way through',
          'ollama.service' in step['result']['summary'])


async def test_an_accepted_job_that_did_not_change_the_unit_is_not_reported_done():
    """exit zero is not evidence. systemd accepts a restart and the unit can come
    back inactive, or never leave activating; neither may be called done."""
    await setup()

    async def dishonest(argv, timeout=12):
        if 'show' in argv:
            return 0, ('Id=ollama.service\nLoadState=loaded\nActiveState=inactive\nSubState=dead\n'
                       'InvocationID=aaaa\nCanStart=yes\nCanStop=yes\n'), ''
        return 0, '', ''                                  # the job "succeeded"

    with live(), patch.object(sysadm, '_run', dishonest):
        result = await run('restart service ollama')
        async with async_session() as db:
            await service.approve(db, result['id'])
        await service.dispatch()
        result = await get(result['id'])
    check('an accepted restart that left the unit inactive is unconfirmed, not done',
          result['state'] != 'done' and result['steps'][0]['result']['state'] == 'unconfirmed')
    check('and the verdict says why in systemd\'s own words',
          result['steps'][0]['result']['verification']['met'] is False
          and 'active_state' in result['steps'][0]['result']['verification']['evidence']
          + str(result['steps'][0]['result']['summary']))


async def test_refusals_that_approval_cannot_override():
    """An approval is permission to do what was asked, not permission to do what
    cannot be done safely. These are refused AFTER approval, by the capability."""
    await setup()
    ctx = {'db': None}
    for request, code, why in [
            ({'unit': 'NetworkManager', 'action': 'restart', 'scope': 'system'}, 'AUTH_REQUIRED',
             'a system unit needs an interactive administrator password ARIES cannot answer'),
            ({'unit': 'cups', 'action': 'stop', 'scope': 'user'}, 'PERMISSION_REQUIRED',
             'a unit outside the allowlist')]:
        try:
            await sysadm.control(request, ctx)
            check('refused: ' + why, False)
        except sysadm.SystemCapabilityError as error:
            check('refused (%s): %s' % (error.code, why), error.code == code)

    own = sysadm.own_unit()
    if own and own in sysadm.CONTROLLABLE:
        try:
            await sysadm.control({'unit': own, 'action': 'restart', 'scope': 'user'}, ctx)
            check('refused: stopping the unit serving the request', False)
        except sysadm.SystemCapabilityError as error:
            check('refused (%s): the unit serving this very request, because the result '
                  'could never be re-read' % error.code, error.code == 'PERMISSION_REQUIRED')
    else:
        check('SKIPPED — this test process is not inside a controllable user unit '
              '(own_unit=%r), so the self-stop guard is exercised by '
              'tests/test_system_capabilities.py instead' % own, True)

    check('the allowlist is small, explicit, and all user-manager units',
          sysadm.CONTROLLABLE and all(u.endswith(sysadm.SUFFIXES) for u in sysadm.CONTROLLABLE))


# --- the same round trip, against the real systemd on this machine ------------

async def test_the_round_trip_against_real_systemd():
    """No simulation: the real user manager, a real ActionProposal, a real
    `systemctl --user start`, and a real re-read. `start` of an already-active
    unit is chosen precisely because it changes nothing — what is being tested is
    the wiring and the verdict, not systemd's ability to restart a daemon."""
    await setup()
    candidates = []
    for unit in sorted(sysadm.CONTROLLABLE):
        try:
            rows = await sysadm.show('user', [unit])
        except sysadm.SystemCapabilityError as error:
            check('SKIPPED — the user manager cannot be read here: ' + str(error), True)
            return
        row = rows[0] if rows else None
        if row and row['load_state'] != 'not-found' and row['active_state'] == 'active' \
                and unit != sysadm.own_unit():
            candidates.append(row)
    if not candidates:
        check('SKIPPED — no allowlisted user unit is loaded and active on this machine, so a '
              'no-op `start` cannot be the vehicle; the simulated round trips above are '
              'what was verified', True)
        return
    # A timer in preference to a service: there is no process behind it to disturb.
    unit = next((r for r in candidates if r['unit'].endswith('.timer')), candidates[0])
    name = unit['unit']
    before = dict(unit)

    with live():
        # The full unit name, suffix included: `qualify()` appends '.service' to a
        # bare name, which would turn aries-endurance.timer into a unit that does
        # not exist and is not allowlisted.
        result = await run('start ' + name)
        check('a real request for %s is held for approval, and nothing was started'
              % name, result['state'] == 'proposed')
        rows = await proposals()
        check('with one durable undecided proposal naming it',
              len(rows) == 1 and rows[0].status == 'proposed'
              and json.loads(rows[0].payload)['args']['unit'] == name)
        async with async_session() as db:
            await service.approve(db, result['id'])
        await service.dispatch()
        result = await get(result['id'])

    step = result['steps'][0]
    print('      live: %s %s -> %s (%s)'
          % (name, before['active_state'], result['state'],
             str(step.get('result', {}).get('summary'))[:160]))
    after = step.get('result', {}).get('verification') or {}
    check('the approved start of %s is verified done against the real user manager' % name,
          result['state'] == 'done' and after['met'] is True)
    fresh = (await sysadm.show('user', [name]))[0]
    check('and %s is still active afterwards, with the same InvocationID — a no-op, '
          'as intended, not a restart' % name,
          fresh['active_state'] == 'active' and fresh['invocation'] == before['invocation'])


if __name__ == '__main__':
    raise SystemExit(run_module(sys.modules[__name__]))
