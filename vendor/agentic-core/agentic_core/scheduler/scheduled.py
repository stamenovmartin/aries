"""The due-queue: ScheduledTask rows fired by `process_due`, with the guards a
careful operator would apply. Lifted from backend/app/services/scheduling.py.

  1. quiet hours       — nothing runs in [start, end) local time
  2. approval gate     — never run something a human has not approved; a
                         rejected task cancels its schedule
  3. per-row claim     — an atomic UPDATE so concurrent tickers cannot both
                         fire one row
  4. deferral ≠ outcome — a run that attempted nothing (dry run, held, policy)
                         keeps the row queued; only an attempt retires it
  5. retry w/ backoff  — failures requeue up to max_attempts, then dead-letter
`now` and `run_fn` are injectable, so the whole machine is testable offline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.config.settings import settings
from agentic_core.database.models import ScheduledTask, Task
from agentic_core.observability import metrics

logger = logging.getLogger(__name__)


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.scheduler_timezone)
    except Exception:
        return ZoneInfo("UTC")


def to_local(utc_naive: datetime) -> datetime:
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(_tz()).replace(tzinfo=None)


def to_utc(local_naive: datetime) -> datetime:
    return local_naive.replace(tzinfo=_tz()).astimezone(timezone.utc).replace(tzinfo=None)


def in_quiet_hours(dt: datetime, start: int, end: int) -> bool:
    if start == end:
        return False
    h = dt.hour
    return (start <= h < end) if start < end else (h >= start or h < end)


def next_allowed_slot(dt: datetime, start: int, end: int) -> datetime:
    if not in_quiet_hours(dt, start, end):
        return dt
    candidate = dt.replace(hour=end % 24, minute=0, second=0, microsecond=0)
    if candidate <= dt:
        candidate += timedelta(days=1)
    return candidate


async def schedule(db: AsyncSession, task_id: int, run_at: datetime, *, kind: str = "initial",
                   max_attempts: int | None = None) -> ScheduledTask:
    if run_at.tzinfo is not None:
        run_at = run_at.astimezone(timezone.utc).replace(tzinfo=None)
    sp = ScheduledTask(task_id=task_id, run_at=run_at, status="queued", kind=kind,
                       max_attempts=max_attempts or settings.scheduler_max_attempts)
    db.add(sp)
    await db.commit()
    await db.refresh(sp)
    return sp


async def due(db: AsyncSession, now: datetime) -> list[ScheduledTask]:
    return list((await db.execute(select(ScheduledTask).where(ScheduledTask.status == "queued", ScheduledTask.run_at <= now)
                                  .order_by(ScheduledTask.run_at))).scalars().all())


def _defer(sp, run_at, reason) -> dict:
    sp.run_at, sp.status, sp.reason = run_at, "queued", reason
    return {"id": sp.id, "task_id": sp.task_id, "status": "deferred", "reason": reason}


async def process_due(db: AsyncSession, *, now: datetime | None = None, run_fn=None) -> list[dict]:
    """Fire (or defer) every due row. `run_fn(task_id, kind) -> dict` must return
    {"attempted": bool, "success": bool, "deferred": str|None, "details": str}."""
    if run_fn is None:
        from agentic_core.scheduler.queue import run_task_now as run_fn
    now = now or datetime.utcnow()
    q_start, q_end = settings.quiet_hours_start, settings.quiet_hours_end
    backoff = settings.scheduler_retry_backoff_minutes
    local_now = to_local(now)
    outcomes: list[dict] = []
    rows = await due(db, now)
    metrics.set_queue_depth("scheduled_tasks", len(rows))
    for sp in rows:
        claim = await db.execute(update(ScheduledTask).where(ScheduledTask.id == sp.id, ScheduledTask.status == "queued")
                                 .values(status="processing"))
        await db.commit()
        if claim.rowcount == 0:
            continue
        sp.status = "processing"
        task = await db.get(Task, sp.task_id)
        if not task:
            sp.status, sp.reason = "canceled", "task no longer exists"
            outcomes.append({"id": sp.id, "task_id": sp.task_id, "status": "canceled"}); continue
        if task.status == "rejected" or task.status == "cancelled":
            sp.status, sp.reason = "canceled", f"task is {task.status}"
            outcomes.append({"id": sp.id, "task_id": task.id, "status": "canceled", "reason": sp.reason}); continue
        if task.status in ("draft", "awaiting_approval", "validation_failed"):
            outcomes.append(_defer(sp, now + timedelta(minutes=60), "awaiting approval")); continue
        if in_quiet_hours(local_now, q_start, q_end):
            outcomes.append(_defer(sp, to_utc(next_allowed_slot(local_now, q_start, q_end)), "quiet hours")); continue

        sp.status = "executing"
        await db.commit()
        try:
            result = await run_fn(task.id, sp.kind)
        except Exception as e:
            logger.exception("Scheduled run crashed for task %s", task.id)
            result = {"attempted": True, "success": False, "details": str(e)}

        if result.get("deferred"):
            outcomes.append(_defer(sp, now + timedelta(minutes=60), f"not attempted ({result['deferred']}) — waiting")); continue
        if not result.get("success"):
            sp.attempts = (sp.attempts or 0) + 1
            if sp.attempts >= sp.max_attempts:
                sp.status, sp.reason = "failed", f"failed after {sp.attempts} attempts: {result.get('details', '')[:200]}"
                metrics.record_dead_letter(f"scheduled:{task.kind}")
                outcomes.append({"id": sp.id, "task_id": task.id, "status": "failed"})
            else:
                sp.status, sp.run_at = "queued", now + timedelta(minutes=backoff * sp.attempts)
                sp.reason = f"retry {sp.attempts}/{sp.max_attempts}: {result.get('details', '')[:200]}"
                metrics.record_retry(f"scheduled:{task.kind}")
                outcomes.append({"id": sp.id, "task_id": task.id, "status": "retry"})
        else:
            sp.status, sp.done_at, sp.reason = "done", now, None
            outcomes.append({"id": sp.id, "task_id": task.id, "status": "done"})
    await db.commit()
    return outcomes


def serialize(sp: ScheduledTask) -> dict:
    return {"id": sp.id, "task_id": sp.task_id, "run_at": sp.run_at.isoformat() if sp.run_at else None,
            "status": sp.status, "kind": sp.kind, "reason": sp.reason, "attempts": sp.attempts,
            "max_attempts": sp.max_attempts, "done_at": sp.done_at.isoformat() if sp.done_at else None}
