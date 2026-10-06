"""Durable breaker behavior under partial failure and recovery."""
import sys
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-breaker-remediation')
from agentic_core.database.base import async_session
from aries.automations import breaker
from aries.automations.genome import AriesAutomationRun
from aries.health.automation import SPEC as HEALTH


async def record(db, statuses, *, automation_id='fixture.partial', now=None):
    now=now or datetime.utcnow()
    for index,status in enumerate(statuses):
        db.add(AriesAutomationRun(automation_id=automation_id,status=status,
            summary=status,started_at=now-timedelta(minutes=len(statuses)-index-1)))
    await db.commit()


async def test_degraded_failures_pause_and_only_success_resets():
    for statuses in (['degraded']*3, ['failed','degraded','failed']):
        await reset_db()
        now=datetime.utcnow()
        async with async_session() as db:
            await record(db,statuses,now=now)
            result=await breaker.state(db,'fixture.partial',threshold=3,cooldown_minutes=30,now=now)
            check('three unsuccessful passes pause', result.state==breaker.OPEN and result.consecutive_failures==3)
            await record(db,['skipped'],now=now)
            check('skips do not clear the breaker',
                  (await breaker.state(db,'fixture.partial',threshold=3,now=now)).state==breaker.OPEN)
            await record(db,['ok'],now=now)
            check('verified successful pass closes breaker',
                  (await breaker.state(db,'fixture.partial',threshold=3,now=now)).state==breaker.CLOSED)


async def test_failed_half_open_trial_starts_a_fresh_cooldown():
    await reset_db()
    now=datetime.utcnow()
    async with async_session() as db:
        await record(db,['failed']*3,now=now-timedelta(minutes=60))
        check('old failures permit a trial after cooldown',
              (await breaker.state(db,'fixture.partial',threshold=3,now=now)).state==breaker.HALF_OPEN)
        await record(db,['degraded'],now=now)
        result=await breaker.state(db,'fixture.partial',threshold=3,cooldown_minutes=30,now=now)
        check('unsuccessful trial reopens', result.state==breaker.OPEN)
        check('retry deadline uses latest attempt, not oldest failure', result.retry_at==now+timedelta(minutes=30))
        check('trial becomes available only at new deadline',
              (await breaker.state(db,'fixture.partial',threshold=3,cooldown_minutes=30,
                                   now=now+timedelta(minutes=30))).state==breaker.HALF_OPEN)


async def test_diagnostic_partial_passes_are_neutral_and_policy_is_visible():
    await reset_db()
    now=datetime.utcnow()
    async with async_session() as db:
        await record(db,['degraded']*15,automation_id=HEALTH.automation_id,now=now)
        result=await breaker.state(db,HEALTH.automation_id,threshold=3,now=now)
        check('missing optional sensor cannot disable health diagnostics',result.state==breaker.CLOSED)
        check('workflow describes its explicit exception',HEALTH.describe()['breaker_on_degraded'] is False)
        await record(db,['failed','degraded','failed','degraded','failed'],automation_id=HEALTH.automation_id,now=now)
        result=await breaker.state(db,HEALTH.automation_id,threshold=3,now=now)
        check('partial diagnostics do not erase actual failures',result.state==breaker.OPEN)
        result=await breaker.state(db,HEALTH.automation_id,threshold=0,now=now)
        check('explicit user setting disabling breaker remains respected',result.state==breaker.CLOSED)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
