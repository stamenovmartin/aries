"""Recovery after restart. Lifted from backend/app/services/posting/__init__.py
::recover_stuck_publishing and scheduling.py::recover_stuck_scheduled.

A task frozen in EXECUTING by a crash is unrunnable, unapprovable and
unrejectable — so a sweep releases it, at startup AND on every scheduler tick.
In-flight operations become 'uncertain' (the call may have happened), never
'failed' (which auto-retries)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update

from agentic_core.database import writer
from agentic_core.database.models import ExecutionOperation, ExecutionPlan, ScheduledTask, Task, TaskRun

logger = logging.getLogger(__name__)


async def recover_stuck(older_than_minutes: int = 10) -> dict:
    cutoff = datetime.utcnow() - timedelta(minutes=older_than_minutes)
    out = {"tasks": 0, "runs": 0, "operations": 0, "plans": 0, "scheduled": 0}
    async with writer.write_session(name="recover_stuck") as db:
        for t in (await db.execute(select(Task).where(Task.status.in_(("executing", "running")),
                                                       Task.updated_at < cutoff))).scalars().all():
            t.status = "approved" if t.status == "executing" else "failed"
            t.last_error = "Interrupted by a restart mid-run — the action MAY have happened. Check before re-running."
            t.error_class = "uncertain"
            out["tasks"] += 1
        r = await db.execute(update(TaskRun).where(TaskRun.status == "running", TaskRun.started_at < cutoff)
                             .values(status="failed", verdict="interrupted", finished_at=datetime.utcnow()))
        out["runs"] = r.rowcount or 0
        r = await db.execute(update(ExecutionOperation).where(ExecutionOperation.state == "sent",
                                                              ExecutionOperation.updated_at < cutoff)
                             .values(state="uncertain", error_class="uncertain",
                                     last_error="sent before a restart; outcome unknown — reconcile"))
        out["operations"] = r.rowcount or 0
        r = await db.execute(update(ExecutionPlan).where(ExecutionPlan.state == "running", ExecutionPlan.updated_at < cutoff)
                             .values(state="blocked"))
        out["plans"] = r.rowcount or 0
        r = await db.execute(update(ScheduledTask).where(ScheduledTask.status.in_(("processing", "executing")),
                                                         ScheduledTask.updated_at < cutoff)
                             .values(status="failed", reason="interrupted mid-run (restart) — check and requeue"))
        out["scheduled"] = r.rowcount or 0
    if any(out.values()):
        logger.warning("Recovered after restart: %s", out)
    return out
