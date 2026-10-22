"""ARIES_VERIFY_SCOPE: a differential side-effect check on the independent verifiers.

The gap (docs/AUDIT.md section 4e; H8 side_effect_outside_scope, 0 of 14 killed): every
independent verifier re-reads the requested TARGET, and nothing compares what lies
next to it, so an executor that does the honest thing plus one change elsewhere is
verified. Under the flag, for the 14 capabilities that H8 operator targets, the
registry wraps the executor so that it snapshots the declared scope first (the parent
folder of every path argument; the other windows; the notification table), and wraps
the verifier so that, after the frozen verifier ran, it snapshots again and fails the
verdict when anything in that scope other than the declared target changed. A scope
that cannot be read is UNVERIFIED, not met. Off, the registry holds the frozen
function objects. Designed after H8: exploratory, not part of the confirmatory test.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-verify-scope')

ROOT = Path(__file__).resolve().parents[1]


def wrapped(name, executor, verifier, effect='file_mutation'):
    from aries.workspace import scope_verifiers
    from aries.workspace.capability_types import Capability, Input
    cap = Capability(name, 'test', Input, executor, verifier, effect=effect)
    return scope_verifiers.wrap(cap)


async def honest_verifier(args, result, ctx):
    return {'met': True, 'type': 'file_state', 'data': {'path': args.get('path')}}


async def run(cap, args):
    ctx = {}
    result = await cap.executor(args, ctx)
    return await cap.verifier(args, result, ctx)


def test_flag_is_registered_and_off_by_default():
    from aries import flags
    check('registered', 'ARIES_VERIFY_SCOPE' in flags.FLAGS)
    check('default off', flags.FLAGS['ARIES_VERIFY_SCOPE'][0] is False)


def test_the_scoped_set_is_the_h8_side_effect_set():
    from aries.workspace import scope_verifiers
    check('14 capabilities', len(scope_verifiers.SCOPED) == 14)
    check('file, desktop and notify classes', set(scope_verifiers.SCOPED.values()) == {'files', 'windows', 'notifications'})


async def test_file_write_with_a_stray_file_fails():
    with tempfile.TemporaryDirectory() as tmp:
        target, stray = Path(tmp, 'new.txt'), Path(tmp, 'outside.txt')

        async def writes_target_and_stray(args, ctx):
            target.write_text('content')
            stray.write_text('side effect')
            return {'path': str(target)}
        verdict = await run(wrapped('file.write', writes_target_and_stray, honest_verifier, 'create'),
                            {'path': str(target), 'content': 'content'})
        check('stray file in the target folder fails verification', verdict['met'] is False)
        check('the change is named', any(c['name'] == 'outside.txt' and c['change'] == 'added'
                                         for c in verdict['scope']['changes']))
        check('marked as a scope failure', verdict['scope']['status'] == 'OUTSIDE_SCOPE_CHANGED')
        check('the frozen verdict is kept for the record', verdict['scope']['frozen_met'] is True)


async def test_file_write_without_a_stray_file_passes():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, 'existing.txt').write_text('untouched')
        target = Path(tmp, 'new.txt')

        async def writes_target(args, ctx):
            target.write_text('content')
            return {'path': str(target)}
        verdict = await run(wrapped('file.write', writes_target, honest_verifier, 'create'),
                            {'path': str(target), 'content': 'content'})
        check('only the declared target changed: met', verdict['met'] is True)
        check('scope recorded as checked', verdict['scope']['status'] == 'IN_SCOPE')


async def test_move_declares_source_and_destination_and_catches_a_modified_neighbour():
    with tempfile.TemporaryDirectory() as tmp:
        src_dir, dst_dir = Path(tmp, 'docs'), Path(tmp, 'out')
        src_dir.mkdir()
        dst_dir.mkdir()
        src, dst, neighbour = src_dir / 'a.txt', dst_dir / 'a.txt', src_dir / 'b.txt'
        src.write_text('a')
        neighbour.write_text('b')

        async def honest_move(args, ctx):
            os.rename(src, dst)
            return {'path': str(src), 'destination': str(dst)}

        async def move_and_touch(args, ctx):
            os.rename(src, dst)
            neighbour.write_text('b changed, longer')
            return {'path': str(src), 'destination': str(dst)}
        args = {'path': str(src), 'destination': str(dst), 'expected_sha256': '0' * 64}
        verdict = await run(wrapped('file.move', honest_move, honest_verifier), args)
        check('honest move: source removal and destination creation are both in scope', verdict['met'] is True)
        dst.rename(src)
        verdict = await run(wrapped('file.move', move_and_touch, honest_verifier), args)
        check('a modified neighbour of the source fails', verdict['met'] is False
              and any(c['name'] == 'b.txt' and c['change'] == 'modified' for c in verdict['scope']['changes']))


async def test_copy_that_changes_its_source_fails():
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp, 'a.txt'), Path(tmp, 'a-copy.txt')
        src.write_text('a')

        async def copy_and_damage_source(args, ctx):
            dst.write_text('a')
            src.write_text('a but different')
            return {'path': str(src), 'destination': str(dst)}
        verdict = await run(wrapped('file.copy', copy_and_damage_source, honest_verifier),
                            {'path': str(src), 'destination': str(dst), 'expected_sha256': '0' * 64})
        check('copy: only the destination is declared, a changed source fails', verdict['met'] is False)


async def test_a_failed_frozen_verdict_stays_failed():
    with tempfile.TemporaryDirectory() as tmp:
        async def nothing(args, ctx):
            return {}

        async def says_no(args, result, ctx):
            return {'met': False, 'type': 'file_state', 'data': {}}
        verdict = await run(wrapped('file.write', nothing, says_no, 'create'), {'path': str(Path(tmp, 'x.txt')), 'content': 'x'})
        check('not met stays not met', verdict['met'] is False)


async def test_no_pre_execution_snapshot_leaves_the_verdict_alone():
    async def fresh_recheck():
        cap = wrapped('file.write', None, honest_verifier, 'create')
        return await cap.verifier({'path': '/tmp/x.txt', 'content': 'x'}, {}, {})
    verdict = await fresh_recheck()
    check('a recheck without a snapshot keeps the frozen verdict', verdict['met'] is True)
    check('and says the scope was not checked', verdict['scope']['status'] == 'NOT_CHECKED')


async def test_an_unreadable_scope_is_unverified():
    from aries.workspace import scope_verifiers

    async def writes(args, ctx):
        return {}
    cap = wrapped('file.write', writes, honest_verifier, 'create')
    with patch.object(scope_verifiers, '_listing', side_effect=OSError('denied')):
        verdict = await run(cap, {'path': '/tmp/aries-scope-x.txt', 'content': 'x'})
    check('snapshot failure: not met', verdict['met'] is False)
    check('snapshot failure: UNVERIFIED', verdict.get('status') == 'UNVERIFIED'
          and verdict['scope']['status'] == 'UNVERIFIED')


def windows(*rows):
    return [{'window_id': i, 'app_id': a, 'geometry': dict(g), 'minimized': m, 'maximized': False,
             'focused': f, 'title': 't' + i} for i, a, g, m, f in rows]


async def test_desktop_action_that_moves_another_window_fails():
    from aries.workspace import scope_verifiers
    g1, g2 = {'x': 0, 'y': 0, 'width': 100, 'height': 100}, {'x': 500, 'y': 0, 'width': 100, 'height': 100}
    world = {'w': windows(('101', 'calc', g1, False, True), ('102', 'files', g2, False, False))}

    async def fake_windows(ctx):
        return [dict(w, geometry=dict(w['geometry'])) for w in world['w']]

    async def minimize_and_nudge(args, ctx):
        world['w'][0]['minimized'] = True
        world['w'][1]['geometry']['x'] += 37
        world['w'][1]['focused'] = True
        return {}

    async def minimize_only(args, ctx):
        world['w'][0]['minimized'] = True
        world['w'][0]['focused'] = False
        world['w'][1]['focused'] = True
        return {}

    async def verified(args, result, ctx):
        return {'met': True, 'type': 'desktop_state', 'data': {}}
    args = {'window_id': '101', 'app_id': 'calc'}
    with patch.object(scope_verifiers, '_windows', side_effect=fake_windows):
        verdict = await run(wrapped('desktop.minimize', minimize_and_nudge, verified, 'desktop'), args)
        check('another window moved: fails', verdict['met'] is False
              and any(c['window_id'] == '102' for c in verdict['scope']['changes']))
        world['w'] = windows(('101', 'calc', g1, False, True), ('102', 'files', g2, False, False))
        verdict = await run(wrapped('desktop.minimize', minimize_only, verified, 'desktop'), args)
        check('focus moving to another window is not a side effect', verdict['met'] is True)


async def test_an_extra_notification_fails():
    await reset_db()
    from agentic_core.database.base import async_session
    from aries.notify import emit
    from aries.health.findings import Severity
    from aries.workspace import registry as reg

    async def send_and_extra(args, ctx):
        result = await reg.notification(args, ctx)
        await emit(ctx['db'], key='stray', title='side effect', severity=Severity.NOTICE, source='test', body='x')
        await ctx['db'].commit()
        return result

    for executor, expect in ((reg.notification, True), (send_and_extra, False)):
        async with async_session() as db:
            cap = wrapped('notification.send', executor, reg.verify_notification, 'notify')
            ctx = {'db': db, 'task_id': 'scope-test'}
            args = {'title': 'hello', 'body': 'world'}
            result = await cap.executor(args, ctx)
            verdict = await cap.verifier(args, result, ctx)
        check(('exactly one new notification: met' if expect else 'an extra notification row: fails'),
              verdict['met'] is expect)


def _registry_identity(flag):
    code = ("import sys;sys.path[:0]=%r\n"
            "from tests._bootstrap import bootstrap;bootstrap('aries-verify-scope-registry')\n"
            "from aries.workspace import registry as r, desktop_capabilities as d\n"
            "from aries.workspace import scope_verifiers as s\n"
            "items=r.registry._items\n"
            "frozen=items['file.write'].verifier is r.verify_write and items['file.write'].executor is r.write_file "
            "and items['notification.send'].verifier is r.verify_notification\n"
            "scoped=all(getattr(items[n].verifier,'scope_kind',None)==k for n,k in s.SCOPED.items())\n"
            "others=all(not hasattr(items[n].verifier,'scope_kind') for n in items if n not in s.SCOPED)\n"
            "print(frozen,scoped,others)\n") % ([str(ROOT / 'vendor/agentic-core'), str(ROOT / 'vendor'), str(ROOT)],)
    env = {**os.environ, 'ARIES_VERIFY_SCOPE': flag, 'ARIES_FLAG_FILE': '/nonexistent/aries-flags.env'}
    out = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=120)
    return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-400:]


def test_registry_off_holds_the_frozen_functions_and_on_wraps_exactly_the_scoped_set():
    check('off: frozen function objects, nothing wrapped', _registry_identity('0') == 'True False True')
    check('on: the 14 are wrapped, nothing else', _registry_identity('1') == 'False True True')


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
