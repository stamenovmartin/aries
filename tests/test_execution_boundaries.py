"""Real second-writer probes at lifecycle I/O boundaries, on a scratch DB."""
import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-execution-boundaries')
from sqlalchemy import select, text
from agentic_core.database.base import async_session
from agentic_core.database.models import AutomationLog, Task
from agentic_core.evaluators.base import Evaluator, issue
from agentic_core.orchestrator.lifecycle import run_cycle
from agentic_core.scheduler.worker import Worker
from agentic_core.scheduler import worker as worker_module


async def writer_available(db):
    # A normal ORM settings/context read autoflushes any pending trace rows.
    await db.execute(select(Task.id))
    async with async_session() as other:
        await other.execute(text('PRAGMA busy_timeout=100'))
        other.add(AutomationLog(action='probe', source='test', status='success'))
        try:
            await other.commit()
            return True
        except Exception:
            await other.rollback()
            return False


async def test_lifecycle_releases_writer_before_external_phases():
    for mode in ('retry', 'replan'):
        await reset_db()
        observed = []
        async with async_session() as db:
            task = Task(kind='generic', title='boundary test', status='draft')
            db.add(task)
            await db.commit()

            async def execute(task, ctx):
                observed.append(('executor', await writer_available(db)))
                return {'success': True, 'content': 'done'}

            async def evaluate(result, task, ctx):
                observed.append(('evaluator', await writer_available(db)))
                return [issue('error', 'again', 'another attempt')] if ctx['attempt'] == 1 else []

            async def replan(task, ctx):
                observed.append(('replanner', await writer_available(db)))
                return {'fixed': True}

            async def notify(*args):
                observed.append(('notification', await writer_available(db)))

            from agentic_core.orchestrator.lifecycle import LifecyclePolicy
            out = await run_cycle(db, task, executor=execute,
                evaluators=[Evaluator('check', evaluate, replan_codes={'again'} if mode == 'replan' else set())],
                replanner=replan, notify=notify, policy=LifecyclePolicy(require_approval=True))
            check(f'{mode}: completes two attempts with approval retained',
                  out.verdict == 'pass' and out.attempts == 2 and task.status == 'awaiting_approval')
            for phase in ('executor', 'evaluator', 'notification') + (('replanner',) if mode == 'replan' else ()):
                values = [ok for name, ok in observed if name == phase]
                check(f'{mode}: another connection can write during {phase}', bool(values) and all(values))


async def test_cancelled_worker_is_never_recorded_successful():
    await reset_db()
    entered = asyncio.Event()

    async def body():
        entered.set()
        await asyncio.Future()

    worker = Worker('cancel-probe', body, timedelta(seconds=60))
    task = asyncio.create_task(worker.run_once())
    await entered.wait()
    task.cancel()
    try:
        await task
        cancelled = False
    except asyncio.CancelledError:
        cancelled = True
    check('worker cancellation propagates', cancelled)
    async with async_session() as db:
        rows = (await db.execute(select(AutomationLog).where(AutomationLog.source == 'cancel-probe'))).scalars().all()
        check('cancelled pass has a failure record, never a success heartbeat',
              len(rows) == 1 and rows[0].status == 'failure' and 'interrupted' in rows[0].details)


async def test_worker_lock_log_includes_real_sqlite_result_code():
    await reset_db()

    @asynccontextmanager
    async def short_wait_session():
        async with async_session() as db:
            await db.execute(text('PRAGMA busy_timeout=100'))
            yield db

    async def body():
        return {'result': 'completed'}

    async with async_session() as holder:
        holder.add(AutomationLog(action='hold', source='test', status='success'))
        await holder.flush()
        with patch.object(worker_module, 'async_session', short_wait_session), \
                patch.object(worker_module.logger, 'exception') as log:
            result = await Worker('lock-probe', body, timedelta(seconds=60)).run_once()
        check('checkpoint contention does not replay or falsify the work outcome', result == {'result': 'completed'})
        check('real SQLite writer contention records its extended code and name',
              log.call_count == 1 and log.call_args.args[-2:] == (5, 'SQLITE_BUSY'))
        await holder.rollback()


async def test_second_cancellation_during_recording_is_visible():
    await reset_db()
    entered, recording = asyncio.Event(), asyncio.Event()

    async def body():
        entered.set()
        await asyncio.Future()

    async def mark(*args, **kwargs):
        recording.set()
        await asyncio.Future()

    with patch.object(worker_module.checkpoints, 'mark_run', mark), \
            patch.object(worker_module.logger, 'warning') as log:
        task = asyncio.create_task(Worker('double-cancel', body, timedelta(seconds=60)).run_once())
        await entered.wait()
        task.cancel()
        await recording.wait()
        task.cancel()
        try:
            await task
            cancelled = False
        except asyncio.CancelledError:
            cancelled = True
    check('second cancellation still propagates without hanging shutdown', cancelled)
    check('interrupted recording is visible in the worker log',
          log.call_count == 1 and log.call_args.args[1] == 'double-cancel')


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
