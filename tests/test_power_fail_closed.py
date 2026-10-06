"""Resource admission and recovery with synthetic sensors and isolated DB."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-power-fail-closed')
from agentic_core.database.base import async_session
from aries.power import governor, workload

LIMITS = {'temperature_celsius': 85, 'cpu_pct': 90, 'gpu_pct': 90,
          'allow_heavy_cpu': True, 'allow_gpu_jobs': True,
          'resume_margin_celsius': 5, 'clear_checks': 2}


async def test_missing_invalid_and_unwatched_sensors():
    await reset_db()
    with patch.object(governor, 'limits', AsyncMock(return_value=LIMITS)), \
         patch.object(governor.state, 'display_state', return_value=('on', 'test')):
        async with async_session() as db:
            for cls, field in [('heavy_cpu', 'cpu_pct'), ('heavy_cpu', 'temperature_c'),
                               ('heavy_gpu', 'gpu_pct'), ('heavy_gpu', 'temperature_c')]:
                for invalid in (None, float('nan'), float('inf'), True):
                    m = governor.Measurement(cpu_pct=5, gpu_pct=5, temperature_c=45)
                    setattr(m, field, invalid)
                    with patch.object(governor, 'measure', AsyncMock(return_value=m)):
                        verdict = await governor.may_run(db, SimpleNamespace(workload=cls), force=True)
                    check(f'{cls} {field}={invalid} cannot pass even with force',
                          not verdict.allowed and verdict.code == 'sensor_unavailable')
                    status, _ = governor._status_of(workload.get(cls), None, m, LIMITS, False)
                    check('panel agrees with admission', status == 'blocked')
            m = governor.Measurement(cpu_pct=5, temperature_c=45, gpu_unavailable='no GPU')
            with patch.object(governor, 'measure', AsyncMock(return_value=m)):
                check('CPU work does not need a GPU',
                      (await governor.may_run(db, SimpleNamespace(workload='heavy_cpu'))).allowed)
                m.temperature_unavailable = 'stale reading'
                check('a numeric but explicitly unavailable reading is rejected',
                      not (await governor.may_run(db, SimpleNamespace(workload='heavy_cpu'))).allowed)
            with patch.object(governor, 'measure', AsyncMock(side_effect=AssertionError('must not sample'))):
                check('health/light work remains available',
                      (await governor.may_run(db, SimpleNamespace(workload='light'))).allowed)


async def test_unknown_declaration_cannot_become_light():
    await reset_db()
    async with async_session() as db:
        for bad in ('heavy_typo', '', [], 42):
            verdict = await governor.may_run(db, SimpleNamespace(workload=bad), force=True)
            check(f'invalid declaration {bad!r} is refused',
                  not verdict.allowed and verdict.code == 'invalid_workload')
        check('missing legacy declaration retains explicit compatibility default',
              (await governor.may_run(db, SimpleNamespace())).allowed)


async def test_hold_survives_blindness_and_unrelated_block_events():
    await reset_db()
    governor._clear_streak.clear()
    with patch.object(governor, 'limits', AsyncMock(return_value=LIMITS)):
        async with async_session() as db:
            await governor._record(db, kind='deferred', cls='heavy_cpu', reason='hot')
            await db.commit()
            cool = governor.Measurement(cpu_pct=5, temperature_c=70)
            check('one cool reading does not release', await governor.release_holds(db, measurement=cool) == [])
            await governor._record(db, kind='blocked', cls='heavy_cpu', reason='permission disabled')
            await db.commit()
            check('unrelated block cannot erase thermal hold', await governor.active_hold(db, 'heavy_cpu') is not None)
            blind = governor.Measurement(cpu_pct=5, temperature_unavailable='disconnected')
            check('blind sensor preserves hold', await governor.release_holds(db, measurement=blind) == [])
            check('blind sample resets consecutive cooling checks', governor._clear_streak['heavy_cpu'] == 0)
            check('recovery requires a new full cool streak', await governor.release_holds(db, measurement=cool) == [])
            check('two actual cool samples release', len(await governor.release_holds(db, measurement=cool)) == 1)
            await db.commit()
            check('release is durable', await governor.active_hold(db, 'heavy_cpu') is None)
    governor._clear_streak.clear()


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
