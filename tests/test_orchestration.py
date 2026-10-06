"""Concurrency and re-routing, measured rather than asserted.

Two things are deliberately kept apart here, because reporting them as one would
be the dishonesty the module is written against:

  * the ROUTING ENGINE is exercised end to end against capabilities registered by
    this test, so a typed failure is deterministic and happens on demand;
  * the FIVE PRODUCTION ALTERNATIVES are checked structurally — they exist, their
    argument mappings validate against the alternative's own schema, and none
    widens authority — and are NOT executed, because executing `desktop.launch`
    or `screen.capture` would open windows on the person's desktop.
"""
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap('aries-orchestration')

from sqlalchemy import select
from agentic_core.database.base import async_session
from aries.workspace import orchestration as orc
from aries.workspace.capability_types import Capability, Input
from aries.workspace.models import WorkspaceGoal
from aries.workspace.registry import registry

SLOW_S = 0.35            # long enough that four of them serially is unmistakable
_calls: dict[str, int] = {}


class Empty(Input):
    pass


def _reset_calls():
    _calls.clear()


async def _slow(args, ctx):
    await asyncio.sleep(SLOW_S)
    _calls['slow'] = _calls.get('slow', 0) + 1
    return {'slept': SLOW_S, 'at': time.time()}


async def _missing(args, ctx):
    # Exactly how screen/network/input capabilities signal a missing mechanism.
    raise RuntimeError('CAPABILITY_UNAVAILABLE: the primary mechanism is not installed here')


async def _flaky(args, ctx):
    _calls['flaky'] = _calls.get('flaky', 0) + 1
    raise TimeoutError('TRANSIENT: busy')


async def _standin(args, ctx):
    _calls['standin'] = _calls.get('standin', 0) + 1
    return {'by': 'the alternative'}


async def _weak(args, ctx):
    _calls['weak'] = _calls.get('weak', 0) + 1
    raise RuntimeError('CAPABILITY_UNAVAILABLE: only a weaker alternative is available')


async def _ok(args, result, ctx):
    return {'met': True, 'type': 'test_state', 'data': {'observed': result}}


for _name, _executor in (('test.slow', _slow), ('test.missing', _missing), ('test.flaky', _flaky),
                         ('test.standin', _standin), ('test.weak', _weak)):
    registry.register(Capability(_name, 'Test capability: ' + _name, Empty, _executor, _ok,
                                 timeout_seconds=30))

# The public declaration path, the same one production uses.
orc.declare('test.missing', 'test.standin', lambda a: {}, 'the stand-in mechanism is present')
orc.declare('test.flaky', 'test.standin', lambda a: {}, 'stop poking the flaky road')
orc.declare('test.weak', 'test.standin', lambda a: {}, 'weaker but real', degraded=True)


async def _queue_children(parent_id, capability, count, *, request='concurrent sub-goal'):
    ids = []
    async with async_session() as db:
        for index in range(count):
            subgoal = {'capability': capability, 'args': {}, 'request': f'{request} {index}',
                       'index': index}
            row = WorkspaceGoal(id=f'{parent_id}-c{index}', request=subgoal['request'], state='queued',
                                result_json=json.dumps({
                                    'steps': [], 'evidence': [], 'cards': [], 'gaps': [],
                                    'orchestration': {'role': 'child', 'parent_id': parent_id,
                                                      'subgoal': subgoal}}))
            # created_at is defaulted per row; stagger it so FIFO order is defined.
            row.created_at = datetime.utcnow() + timedelta(milliseconds=index)
            db.add(row)
            ids.append(row.id)
        db.add(WorkspaceGoal(id=parent_id, request='several goals at once', state='running',
                            result_json=json.dumps({
                                'steps': [], 'evidence': [], 'cards': [], 'gaps': [],
                                'orchestration': {'role': 'parent', 'children': ids,
                                                  'width': len(ids)}})))
        await db.commit()
    return ids


async def _rows(ids):
    async with async_session() as db:
        found = (await db.execute(select(WorkspaceGoal).where(WorkspaceGoal.id.in_(ids)))).scalars().all()
    return {r.id: (r.state, json.loads(r.result_json)) for r in found}


def _overlap(intervals):
    """The largest number of sub-goals that were provably running at one instant."""
    edges = sorted([(a, 1) for a, _ in intervals] + [(b, -1) for _, b in intervals])
    live = peak = 0
    for _, delta in edges:
        live += delta
        peak = max(peak, live)
    return peak


# ── 1. how many: the governor, not a constant ───────────────────────────────

async def test_capacity_is_read_out_of_the_resource_policy():
    await reset_db()
    from aries.power import governor
    from unittest.mock import patch

    async def snapshot(_db, *, cpu=None, status='allowed', why='within limits'):
        return {'limits': {'cpu_pct': 70, 'temperature_celsius': 80},
                'measurement': {'cpu_pct': cpu, 'cpu_unavailable': None if cpu is not None else '/proc/stat unreadable'},
                'classes': [{'name': 'heavy_cpu', 'status': status, 'why': why}]}

    async with async_session() as db:
        real = await orc.capacity(db)
        check(f'the live machine reports {real.slots} slot(s): {real.reason}',
              1 <= real.slots <= orc.CEILING and 'governor' in real.as_dict()['source'])
        with patch.object(governor, 'snapshot', lambda d: snapshot(d, cpu=5)):
            idle = await orc.capacity(db)
        with patch.object(governor, 'snapshot', lambda d: snapshot(d, cpu=65)):
            busy = await orc.capacity(db)
        with patch.object(governor, 'snapshot', lambda d: snapshot(d, cpu=95, status='deferred',
                                                                  why='the GPU is at 91 %')):
            hot = await orc.capacity(db)
        with patch.object(governor, 'snapshot', lambda d: snapshot(d, cpu=None)):
            blind = await orc.capacity(db)
    check(f'an idle processor affords more goals ({idle.slots}) than a busy one ({busy.slots})',
          idle.slots > busy.slots)
    check('a machine the governor has deferred runs one at a time, and says why',
          hot.slots == 1 and 'GPU is at 91' in hot.reason)
    check('capacity is never zero, so a queued goal is never unreachable',
          min(idle.slots, busy.slots, hot.slots, blind.slots) >= 1)
    check('an unreadable processor is one at a time, not a guess',
          blind.slots == 1 and 'cannot be measured' in blind.reason)
    check('the ceiling bounds the arithmetic and is never exceeded',
          max(idle.slots, busy.slots) <= orc.CEILING)


async def test_capacity_writes_nothing_because_it_runs_on_a_two_second_poll():
    # governor.may_run records every refusal. Called per tick it would write a row
    # per empty pass, which is the 2026-09-29 automation_logs bug exactly.
    await reset_db()
    from aries.power.governor import AriesResourceEvent
    async with async_session() as db:
        before = len((await db.execute(select(AriesResourceEvent.id))).all())
        for _ in range(5):
            await orc.capacity(db)
        after = len((await db.execute(select(AriesResourceEvent.id))).all())
    check(f'five capacity reads wrote no resource-policy rows ({before} -> {after})', before == after)


# ── 2. who goes next: aging beats starvation ────────────────────────────────

async def test_aging_stops_a_younger_goal_starving_an_older_one():
    for goal in list(orc._deferred):
        orc.release(goal)
    old, young = 'older-goal', 'younger-goal'
    # The desktop lane is held by a long runner; the older goal wants it.
    for _ in range(orc.AGING_DEFERRALS):
        check('the older goal is passed over while the lane is busy',
              orc.admit(old, {'desktop'}, {'desktop'}) is False)
    check(f'after {orc.AGING_DEFERRALS} deferrals it reserves what it waits for',
          orc.deferrals()[old]['reserving'] and 'desktop' in orc.reserved(young))
    check('a younger goal may not take the reserved lane even though it is free',
          orc.admit(young, {'desktop'}, set()) is False)
    check('a younger goal wanting a different lane still runs — the machine stays busy',
          orc.admit('other-goal', {'files'}, set()) is True)
    check('the starved goal itself does not reserve against itself',
          orc.admit(old, {'desktop'}, set()) is True)
    check('admission clears the record', old not in orc.deferrals())
    for goal in list(orc._deferred):
        orc.release(goal)


async def test_reads_take_no_lane_so_questions_are_actually_parallel():
    check('a read-only capability reserves nothing', orc.lanes_for('system.status') == frozenset())
    check('typing is scoped to the focused window, which is a singleton',
          orc.lanes_for('input.type_text') == frozenset({'desktop'}))
    check('a browser action takes the browser lane', orc.lanes_for('browser.navigate') == frozenset({'browser'}))
    check('only genuine singletons are exclusive', orc.EXCLUSIVE == frozenset({'desktop', 'local-model'}))


# ── 3. what to try next: the typed code ─────────────────────────────────────

async def test_every_typed_code_has_one_decision_and_a_reason():
    from aries.workspace import agent
    codes = ('TRANSIENT', 'TARGET_NOT_FOUND', 'CAPABILITY_UNAVAILABLE', 'PERMISSION_REQUIRED',
             'AUTH_REQUIRED', 'AMBIGUOUS', 'NETWORK_ERROR', 'VERIFICATION_FAILED', 'NON_RETRYABLE')
    check('every code agent.error can produce is routed', set(codes) <= set(orc.ROUTE))
    check('TRANSIENT and NETWORK_ERROR retry the same road',
          all(orc.ROUTE[c][0] == 'retry' for c in ('TRANSIENT', 'NETWORK_ERROR')))
    check('CAPABILITY_UNAVAILABLE and PERMISSION_REQUIRED look for a different road',
          all(orc.ROUTE[c][0] == 'reroute' for c in ('CAPABILITY_UNAVAILABLE', 'PERMISSION_REQUIRED')))
    check('NON_RETRYABLE, AMBIGUOUS, AUTH_REQUIRED and VERIFICATION_FAILED stop',
          all(orc.ROUTE[c][0] == 'stop' for c in ('NON_RETRYABLE', 'AMBIGUOUS', 'AUTH_REQUIRED',
                                                  'VERIFICATION_FAILED')))
    check('an unrecognised code stops rather than improvising',
          orc.route('SOMETHING_NEW', 'test.missing', [], {}).action == 'stop')
    unmapped = orc.route('SOMETHING_NEW', 'test.missing', [], {})
    check('and says which code it did not recognise', 'SOMETHING_NEW' in unmapped.why)


async def test_routing_is_bounded_in_all_three_directions():
    trail = [{'capability': 'test.flaky', 'strategy': {}}]
    check('a transient failure retries the same capability',
          orc.route('TRANSIENT', 'test.flaky', trail, {}).capability == 'test.flaky')
    repeats = [{'capability': 'test.flaky', 'strategy': {}} for _ in range(orc.RETRY_CAP + 1)]
    rerouted = orc.route('TRANSIENT', 'test.flaky', repeats, {})
    check(f'the same road is not retried past {orc.RETRY_CAP} repeats',
          rerouted.action == 'reroute' and rerouted.capability == 'test.standin'
          and str(orc.RETRY_CAP) in rerouted.why)
    no_alternative = [{'capability': 'test.standin', 'strategy': {}}
                      for _ in range(orc.RETRY_CAP + 1)]
    stopped = orc.route('TRANSIENT', 'test.standin', no_alternative, {})
    check('retry exhaustion without a declared alternative still stops',
          stopped.action == 'stop' and str(orc.RETRY_CAP) in stopped.why)
    used = [{'capability': f'test.alt{i}', 'strategy': {'alternative_of': 'test.missing'}}
            for i in range(orc.ALTERNATIVE_CAP)]
    check(f'at most {orc.ALTERNATIVE_CAP} different approaches are tried',
          orc.route('CAPABILITY_UNAVAILABLE', 'test.missing', used, {}).action == 'stop')
    full = [{'capability': 'test.flaky', 'strategy': {}} for _ in range(orc.ATTEMPT_CAP)]
    exhausted = orc.route('TRANSIENT', 'test.flaky', full, {})
    check(f'{orc.ATTEMPT_CAP} attempts is the hard budget for one sub-goal',
          exhausted.action == 'stop' and 'budget' in exhausted.why)
    check('a code with no declared alternative stops and says so',
          orc.route('CAPABILITY_UNAVAILABLE', 'file.read', [], {'path': '/tmp/x'}).action == 'stop')


async def test_an_alternative_can_never_be_a_way_round_a_gate():
    failed = []
    for primary, alternative, why in (
            ('file.read', 'file.copy', 'approval the original did not need'),
            ('file.read', 'file.write', 'mutating where the original only read'),
            ('system.status', 'input.clipboard_write', 'both at once')):
        try:
            orc.declare(primary, alternative, lambda a: {}, why)
            failed.append(f'{primary} -> {alternative} was accepted')
        except ValueError:
            pass
    check('an alternative that needs approval the original did not is refused at declaration',
          not failed)
    check('re-registering the same alternative twice is refused',
          _raises(lambda: orc.declare('test.missing', 'test.standin', lambda a: {}, 'again')))
    check('an alternative naming a capability that does not exist is refused',
          _raises(lambda: orc.declare('test.missing', 'test.nonexistent', lambda a: {}, 'nope')))


async def test_repeated_alternative_counts_as_one_distinct_approach():
    trail = [{'capability': 'test.missing', 'strategy': {}}] + [
        {'capability': 'test.flaky', 'strategy': {'alternative_of': 'test.missing'}}
        for _ in range(2)]
    decision = orc.route('CAPABILITY_UNAVAILABLE', 'test.flaky', trail, {})
    check('retrying one alternative does not consume two distinct alternative slots',
          decision.action == 'reroute' and decision.capability == 'test.standin')


async def test_uncertain_mutation_is_not_repeated_or_rerouted():
    for code in ('TRANSIENT', 'NETWORK_ERROR'):
        decision = orc.route(code, 'file.write',
                             [{'capability': 'file.write', 'strategy': {}}],
                             {'path': '/tmp/aries-uncertain-write', 'content': 'example'})
        check(f'{code} after a mutation needs verification, not another effect',
              decision.action == 'stop' and 'verification' in decision.why)


def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


async def test_the_five_production_alternatives_are_real_and_do_not_widen_authority():
    samples = {'desktop.focus': {'app': 'firefox'}, 'desktop.launch': {'app': 'firefox'},
               'file.search': {'path': str(Path.home()), 'query': 'notes'},
               'screen.read': {'window_id': None, 'language': 'eng+mkd'},
               'input.type_text': {'app': 'gedit', 'node': '0/1/2', 'pid': 1234, 'role': 'text',
                                   'name': 'Document', 'text': 'Здраво', 'mode': 'insert'}}
    production = {p: a for p, a in orc.ALTERNATIVES.items() if not p.startswith('test.')}
    problems = []
    for primary, entries in production.items():
        original = registry.get(primary)
        for entry in entries:
            alternative = registry.get(entry.capability)
            if alternative.requires_approval and not original.requires_approval:
                problems.append(f'{primary} -> {entry.capability} escalates approval')
            if original.effect == 'read' and alternative.effect != 'read':
                problems.append(f'{primary} -> {entry.capability} mutates where {primary} reads')
            if entry.capability == primary:
                problems.append(f'{primary} is its own alternative')
            try:
                registry.validate(entry.capability, entry.argmap(samples[primary]))
            except Exception as exc:
                problems.append(f'{primary} -> {entry.capability} argmap: {type(exc).__name__}: {exc}')
    check(f'{sum(len(v) for v in production.values())} declared alternatives over '
          f'{len(production)} capabilities', sum(len(v) for v in production.values()) >= 5)
    check('every one maps arguments its alternative actually accepts: ' + ('; '.join(problems) or 'none'),
          not problems)
    check('a weaker route is marked degraded so it can never report done',
          all(e.degraded for e in orc.ALTERNATIVES['screen.read'])
          and all(e.degraded for e in orc.ALTERNATIVES['input.type_text']))
    check('launch and focus are alternatives of each other',
          orc.ALTERNATIVES['desktop.focus'][0].capability == 'desktop.launch'
          and orc.ALTERNATIVES['desktop.launch'][0].capability == 'desktop.focus')


async def test_a_real_registry_failure_produces_a_real_typed_decision():
    """No mocks: a real capability, a real exception, agent.error's real code."""
    await reset_db()
    from aries.settings import SettingsService
    from aries.workspace.agent import error
    async with async_session() as db:
        await SettingsService(db).set('operator.enabled', True, set_by='user')
        await db.commit()
    missing = str(Path.home() / 'Documents' / 'no-such-file-aries-orchestration-test.txt')
    check('the probe path really does not exist', not Path(missing).exists())
    async with async_session() as db:
        cap = registry.get('file.read')
        try:
            await cap.executor({'path': missing}, {'db': db, 'goal': 'read it', 'task_id': 'x'})
            detail = None
        except Exception as exc:
            detail = error(exc)
    check(f"a missing file is typed TARGET_NOT_FOUND, not a guess: {detail}",
          detail and detail['code'] == 'TARGET_NOT_FOUND' and detail['retryable'] is False)
    decision = orc.route(detail['code'], 'file.read', [], {'path': missing})
    check('and with nothing declared for file.read it stops and names the code',
          decision.action == 'stop' and 'TARGET_NOT_FOUND' in decision.why)


# ── 4. a real re-route, executed ────────────────────────────────────────────

async def test_a_failed_capability_is_rerouted_to_a_declared_alternative():
    await reset_db()
    _reset_calls()
    ids = await _queue_children('reroute-parent', 'test.missing', 1)
    await orc.tick(wait=True)
    rows = await _rows(ids)
    state, data = rows[ids[0]]
    trail = data['steps']
    outcome = data['orchestration']['outcome']
    check('the primary mechanism was tried first', trail[0]['capability'] == 'test.missing')
    check('its failure was typed CAPABILITY_UNAVAILABLE',
          trail[0]['error']['code'] == 'CAPABILITY_UNAVAILABLE')
    check('the declared alternative was tried second', trail[1]['capability'] == 'test.standin')
    check('the alternative really ran', _calls.get('standin') == 1)
    check('and the record says which capability it stood in for',
          trail[1]['strategy']['alternative_of'] == 'test.missing')
    check('the reason a person reads names the code and the mechanism: '
          + trail[0]['strategy']['decision']['why'],
          'CAPABILITY_UNAVAILABLE' in trail[0]['strategy']['decision']['why']
          and 'stand-in' in trail[0]['strategy']['decision']['why'])
    check(f'the sub-goal is done ({state})', state == 'done')
    check('and it does NOT claim a clean first attempt: ' + outcome['summary'],
          'strategy 2 of 2' in outcome['summary'] and 'test.missing' in outcome['summary']
          and 'first attempt' not in outcome['summary'])
    single = orc.report('test.standin', [dict(trail[1], strategy={'index': 1, 'alternative_of': None})])
    check('a genuine first-attempt success does say so', 'first attempt' in single['summary'])


async def test_a_transient_failure_retries_the_same_road_then_changes_it():
    await reset_db()
    _reset_calls()
    ids = await _queue_children('retry-parent', 'test.flaky', 1)
    started = time.monotonic()
    await orc.tick(wait=True)
    elapsed = time.monotonic() - started
    state, data = (await _rows(ids))[ids[0]]
    tried = [s['capability'] for s in data['steps']]
    check(f'the flaky road was retried, not abandoned: {tried}',
          tried.count('test.flaky') == orc.RETRY_CAP + 1)
    check(f'it really ran that many times ({_calls.get("flaky")})', _calls.get('flaky') == orc.RETRY_CAP + 1)
    check('the backoff was actually waited', elapsed >= sum(orc.RETRY_BACKOFF_S[:2]))
    check('then the different road was taken within the attempt budget',
          tried[-1] == 'test.standin' and len(tried) <= orc.ATTEMPT_CAP)
    check(f'and the sub-goal ends done ({state})', state == 'done')
    check('the trail records every decision in order, for a person to read afterwards',
          [s['strategy'].get('decision', {}).get('action') for s in data['steps'][:-1]]
          == ['retry', 'retry', 'reroute'])


async def test_a_weaker_route_is_partial_and_never_done():
    await reset_db()
    _reset_calls()
    ids = await _queue_children('degraded-parent', 'test.weak', 1)
    await orc.tick(wait=True)
    state, data = (await _rows(ids))[ids[0]]
    check('the weaker alternative really ran after the primary failed',
          [s['capability'] for s in data['steps']] == ['test.weak', 'test.standin']
          and _calls.get('standin') == 1)
    check('the weaker route verified, so the row is not failed', state != 'failed')
    check(f'but a weaker end is partial, never done ({state})', state == 'partial')
    check('and the summary says the end is weaker than the one asked for: '
          + data['orchestration']['outcome']['summary'],
          'weaker' in data['orchestration']['outcome']['summary'])


async def test_a_policy_freeze_is_never_rerouted():
    await reset_db()
    from aries.settings import SettingsService
    async with async_session() as db:
        # notification.send requires approval; policy returns False, not an error.
        await SettingsService(db).set('operator.enabled', True, set_by='user')
        await db.commit()
    async with async_session() as db:
        db.add(WorkspaceGoal(id='freeze-child', request='tell me', state='running',
                             result_json=json.dumps({'steps': [], 'evidence': [], 'cards': [], 'gaps': []})))
        await db.commit()
    data = {'steps': [], 'evidence': [], 'cards': [], 'gaps': []}
    verdict = await orc.attempt('freeze-child', 'send me a notice',
                                {'capability': 'notification.send',
                                 'args': {'title': 'Hello', 'body': 'Frozen for review'}}, data)
    check(f'an unapproved action freezes rather than failing ({verdict["state"]})',
          verdict['state'] == 'proposed')
    check('exactly one strategy was recorded — no alternative was sought',
          verdict['strategies'] == 1 and not verdict['alternatives_used'])
    check('nothing was executed', data['steps'][0]['execution_status'] == 'planned')


# ── 5. several goals at once, measured ──────────────────────────────────────

async def test_four_sub_goals_really_run_at_the_same_time():
    await reset_db()
    _reset_calls()
    from aries.power import governor
    from unittest.mock import patch

    async def idle_machine(_db):
        return {'limits': {'cpu_pct': 70}, 'measurement': {'cpu_pct': 1.0, 'cpu_unavailable': None},
                'classes': [{'name': 'heavy_cpu', 'status': 'allowed', 'why': 'within limits'}]}

    width = orc.CEILING
    ids = await _queue_children('concurrent-parent', 'test.slow', width)
    started = time.monotonic()
    with patch.object(governor, 'snapshot', idle_machine):
        result = await orc.tick(wait=True)
    wall = time.monotonic() - started
    rows = await _rows(ids)
    serial = width * SLOW_S
    spans = []
    for goal_id in ids:
        state, data = rows[goal_id]
        step = data['steps'][0]
        spans.append((datetime.fromisoformat(step['started_at']),
                      datetime.fromisoformat(step['finished_at'])))
    peak = _overlap(spans)
    check(f'the governor gave {result["capacity"]["slots"]} slots: {result["capacity"]["reason"]}',
          result['capacity']['slots'] == width)
    check(f'all {width} sub-goals were launched in one pass', result['orchestrated'] == width)
    check(f'all {width} executed ({_calls.get("slow")} calls)', _calls.get('slow') == width)
    check(f'{peak} of {width} were provably running at one instant, from their own durable rows',
          peak == width)
    check(f'wall clock {wall:.2f}s against {serial:.2f}s serial — concurrency is real, not claimed',
          wall < serial * 0.6)
    check('every sub-goal reached done', all(rows[i][0] == 'done' for i in ids))
    check('each keeps its OWN evidence, with no id shared between them',
          len({e['evidence_id'] for i in ids for e in rows[i][1]['evidence']})
          == sum(len(rows[i][1]['evidence']) for i in ids))
    check('and its own row, steps and audit trail',
          all(len(rows[i][1]['steps']) == 1 and rows[i][1]['steps'][0]['task_id'] == i for i in ids))


async def test_concurrent_writers_do_not_hit_database_is_locked():
    """The obvious trap: four goals persisting a trail each, into one sqlite file."""
    await reset_db()
    _reset_calls()
    from aries.power import governor
    from unittest.mock import patch

    async def idle_machine(_db):
        return {'limits': {'cpu_pct': 70}, 'measurement': {'cpu_pct': 1.0, 'cpu_unavailable': None},
                'classes': [{'name': 'heavy_cpu', 'status': 'allowed', 'why': 'within limits'}]}

    ids = await _queue_children('lock-parent', 'test.flaky', orc.CEILING)
    started = time.monotonic()
    with patch.object(governor, 'snapshot', idle_machine):
        await orc.tick(wait=True)
    wall = time.monotonic() - started
    rows = await _rows(ids)
    writes = sum(len(rows[i][1]['steps']) for i in ids)
    locked = [str(g) for i in ids for g in rows[i][1]['gaps'] if 'locked' in str(g).lower()]
    check(f'{orc.CEILING} goals each wrote a {orc.ATTEMPT_CAP}-strategy trail '
          f'({writes} steps, {wall:.2f}s)', writes == orc.CEILING * orc.ATTEMPT_CAP)
    check('no sub-goal recorded a database lock: ' + (', '.join(locked) or 'none'), not locked)
    check('each reached a final state rather than dying mid-write',
          all(rows[i][0] in {'done', 'partial', 'failed'} for i in ids))
    async with async_session() as db:
        from sqlalchemy import text
        mode = (await db.execute(text('PRAGMA journal_mode'))).scalar()
        wait = (await db.execute(text('PRAGMA busy_timeout'))).scalar()
    check(f'measured against WAL and a {int(wait)} ms busy timeout, which is what production runs',
          str(mode).lower() == 'wal' and int(wait) >= 10000)


# ── 6. honest roll-up ───────────────────────────────────────────────────────

async def test_partial_across_sub_goals_is_never_done():
    check('all done is done', orc.combine(['done', 'done']) == 'done')
    check('one failure makes the whole thing partial', orc.combine(['done', 'failed']) == 'partial')
    check('a degraded sub-goal makes it partial', orc.combine(['done', 'partial']) == 'partial')
    check('nothing succeeded is failed', orc.combine(['failed', 'interrupted']) == 'failed')
    check('a pending approval surfaces as proposed', orc.combine(['done', 'proposed']) == 'proposed')
    check('no sub-goals at all is failed, not done', orc.combine([]) == 'failed')


async def test_the_parent_reports_which_strategies_were_needed():
    await reset_db()
    _reset_calls()
    parent = 'mixed-parent'
    async with async_session() as db:
        ids = []
        for index, capability in enumerate(('test.missing', 'test.flaky', 'test.slow')):
            subgoal = {'capability': capability, 'args': {}, 'request': 'sub ' + capability, 'index': index}
            row = WorkspaceGoal(id=f'{parent}-c{index}', request=subgoal['request'], state='queued',
                                result_json=json.dumps({'steps': [], 'evidence': [], 'cards': [], 'gaps': [],
                                                        'orchestration': {'role': 'child', 'parent_id': parent,
                                                                          'subgoal': subgoal}}))
            row.created_at = datetime.utcnow() + timedelta(milliseconds=index)
            db.add(row)
            ids.append(row.id)
        db.add(WorkspaceGoal(id=parent, request='three things at once', state='running',
                             result_json=json.dumps({'steps': [], 'evidence': [], 'cards': [], 'gaps': [],
                                                     'orchestration': {'role': 'parent', 'children': ids,
                                                                       'width': 3}})))
        await db.commit()
    # Break one sub-goal's alternative so the whole request is genuinely partial.
    broken = orc.ALTERNATIVES['test.flaky']
    orc.ALTERNATIVES['test.flaky'] = ()
    try:
        for _ in range(4):
            await orc.tick(wait=True)
            if (await _rows([parent]))[parent][0] != 'running':
                break
    finally:
        orc.ALTERNATIVES['test.flaky'] = broken
    state, data = (await _rows([parent]))[parent]
    outcomes = {o['id']: o for o in data['orchestration']['outcomes']}
    check(f'two of three sub-goals verified and one did not, so the request is partial ({state})',
          state == 'partial')
    check('the parent card counts them honestly: ' + data['cards'][0]['text'],
          '2 of 3 sub-goals verified' in data['cards'][0]['text'])
    check('and names the sub-goal that needed a different strategy',
          'test.missing' in data['cards'][0]['text'] and 'strategies' in data['cards'][0]['text'])
    check('the failure is carried into gaps rather than swallowed',
          any('test.flaky' in g for g in data['gaps']))
    check('every sub-goal is still addressable by its own row id',
          set(outcomes) == set(f'{parent}-c{i}' for i in range(3)))


# ── 7. concurrency is not a way round the guards ────────────────────────────

async def test_fan_out_asks_the_loop_guard_once_and_caps_its_width():
    await reset_db()
    from aries.workspace import runaway
    runaway.resume()
    async with async_session() as db:
        wide = [{'capability': 'test.slow', 'args': {}} for _ in range(orc.MAX_SUBGOALS + 1)]
        check(f'more than {orc.MAX_SUBGOALS} sub-goals in one request is refused',
              await _araises(orc.fan_out(db, 'too much at once', wide)))
        out = await orc.fan_out(db, 'two things', [{'capability': 'test.slow', 'args': {}},
                                                  {'capability': 'test.slow', 'args': {}}],
                               source='voice')
    check('a fan-out creates one parent row and one child row per sub-goal',
          out['width'] == 2 and len(out['children']) == 2)
    rows = await _rows([out['id'], *out['children']])
    check('the parent is running and each child is queued on the one goal table',
          rows[out['id']][0] == 'running' and all(rows[c][0] == 'queued' for c in out['children']))
    # The guard trips on the 3rd identical voice request in two minutes.
    async with async_session() as db:
        for _ in range(2):
            try:
                await orc.fan_out(db, 'two things', [{'capability': 'test.slow', 'args': {}}], source='voice')
            except ValueError:
                pass
        refused = await _araises(orc.fan_out(db, 'two things',
                                            [{'capability': 'test.slow', 'args': {}}], source='voice'))
    check('a repeated spoken request is refused by the existing loop guard, not by a new one',
          refused and 'voice' in runaway.status())
    async with async_session() as db:
        after = (await db.execute(select(WorkspaceGoal.id))).all()
    check('and the refused fan-out created no rows at all',
          len(after) == 1 + 2 + 2)   # the first parent, its 2 children, 2 single-child fan-outs
    runaway.resume()


async def test_a_cancelled_parent_does_not_leave_children_running():
    await reset_db()
    ids = await _queue_children('cancel-parent', 'test.slow', 2)
    async with async_session() as db:
        parent = await db.get(WorkspaceGoal, 'cancel-parent')
        parent.state = 'cancelled'
        await db.commit()
        await orc.roll_up(db, 'cancel-parent')
    rows = await _rows(ids)
    check('cancelling the request cancels its queued sub-goals',
          all(rows[i][0] == 'cancelled' for i in ids))


async def test_parent_cancellation_stops_an_inflight_child():
    await reset_db()
    from aries.workspace import service
    started, completed = asyncio.Event(), asyncio.Event()

    async def waiting(args, ctx):
        started.set()
        await asyncio.sleep(30)
        completed.set()
        return {'completed': True}

    registry.register(Capability('test.cancellable', 'Cancellation probe', Empty,
                                 waiting, _ok, timeout_seconds=40))
    ids = await _queue_children('inflight-parent', 'test.cancellable', 1)
    async with service._lock:
        async with async_session() as db:
            await orc.claim(db, 1)
    supervisor = service._supervisors[ids[0]]
    try:
        await asyncio.wait_for(started.wait(), 3)
        async with async_session() as db:
            await service.cancel(db, 'inflight-parent')
            await orc.roll_up(db, 'inflight-parent')
        await asyncio.wait_for(asyncio.shield(supervisor), 3)
        state, _ = (await _rows(ids))[ids[0]]
        check('cancelling the parent stops the child that already started',
              state == 'cancelled' and not completed.is_set())
        check('cancelled child releases its task and resource reservations',
              ids[0] not in service._tasks and ids[0] not in service._supervisors
              and ids[0] not in service._resources)
    finally:
        if not supervisor.done():
            supervisor.cancel()
            await asyncio.gather(supervisor, return_exceptions=True)


async def test_an_interrupted_sub_goal_is_not_replayed():
    await reset_db()
    _reset_calls()
    async with async_session() as db:
        subgoal = {'capability': 'test.slow', 'args': {}, 'request': 'half-done', 'index': 0}
        db.add(WorkspaceGoal(id='interrupted-child', request='half-done', state='running',
                             result_json=json.dumps({
                                 'steps': [{'step_id': 'abc', 'capability': 'test.slow', 'args': {},
                                            'execution_status': 'executing', 'verification_status': 'pending',
                                            'evidence_refs': []}],
                                 'evidence': [], 'cards': [], 'gaps': [],
                                 'orchestration': {'role': 'child', 'subgoal': subgoal}})))
        await db.commit()
    await orc._drive('interrupted-child', 'half-done', subgoal)
    state, data = (await _rows(['interrupted-child']))['interrupted-child']
    check(f'an effect whose verification never happened is not repeated ({state})',
          state == 'interrupted' and not _calls.get('slow'))
    check('and the uncertainty is on the record',
          data['steps'][0]['verification_status'] == 'interrupted'
          and any('not be replayed' in g for g in data['gaps']))


async def _araises(coro):
    try:
        await coro
        return False
    except Exception:
        return True


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
