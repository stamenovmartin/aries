"""Event-driven triggers: a task because something happened.
Lifted from backend/app/services/triggers.py (catalogue-change triggers).

Two halves, deliberately separate:
  record()   writes the event down; cheap, decides nothing.
  propose()  turns some events into tasks, conservatively: a per-run cap so the
             approval queue is never flooded, a cooldown per subject, and an
             age window so stale events are not acted on.
Applications register `Trigger`s: a predicate over an event + a task factory."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.models import AutomationLog, Task

logger = logging.getLogger(__name__)
EVENT_ACTION = "event"
MAX_PROPOSALS = 2
SUBJECT_COOLDOWN_HOURS = 24
MAX_AGE_HOURS = 72


@dataclass
class Trigger:
    name: str
    matches: Callable[[dict], bool]                        # event → worth acting on?
    make_task: Callable[[dict], Awaitable[dict]]           # event → {kind, title, brief, input}
    cooldown_hours: int = SUBJECT_COOLDOWN_HOURS
    subject_key: str = "subject"


_TRIGGERS: dict[str, Trigger] = {}
_TASKS_BY_LOG: dict[str, dict] = field(default_factory=dict)


def register(t: Trigger) -> Trigger:
    _TRIGGERS[t.name] = t
    return t


def all_triggers() -> list[Trigger]:
    return [_TRIGGERS[k] for k in sorted(_TRIGGERS)]


async def record(db: AsyncSession, kind: str, subject: str, data: dict | None = None, *, source: str = "system") -> AutomationLog:
    """Log one event. Caller commits. The event is evidence whether or not a
    task is ever made from it."""
    row = AutomationLog(action=EVENT_ACTION, source=source, status="success",
                        details=json.dumps({"kind": kind, "subject": subject, "data": data or {}, "handled": False},
                                           ensure_ascii=False, default=str))
    db.add(row)
    await db.flush()
    return row


async def pending(db: AsyncSession, *, limit: int = 50) -> list[tuple[AutomationLog, dict]]:
    cutoff = datetime.utcnow() - timedelta(hours=MAX_AGE_HOURS)
    rows = (await db.execute(select(AutomationLog).where(AutomationLog.action == EVENT_ACTION,
                                                         AutomationLog.created_at >= cutoff)
                             .order_by(AutomationLog.id.desc()).limit(limit * 3))).scalars().all()
    out = []
    for r in rows:
        try:
            d = json.loads(r.details or "{}")
        except ValueError:
            continue
        if not d.get("handled"):
            out.append((r, d))
    return out[:limit]


async def _recently_tasked(db, subject: str, hours: int) -> bool:
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    n = (await db.execute(select(func.count(Task.id)).where(Task.brief.like(f"%{subject}%"), Task.created_at >= cutoff))).scalar() or 0
    return n > 0


async def propose(db: AsyncSession, *, limit: int = MAX_PROPOSALS, dry_run: bool = False) -> dict:
    """Turn the strongest recent events into tasks. Nothing executes here — a
    trigger produces what a human request produces: a task in the queue."""
    from agentic_core.orchestrator.service import create_task
    made, skipped = [], []
    for row, ev in await pending(db, limit=limit * 4):
        if len(made) >= limit:
            break
        trig = next((t for t in all_triggers() if _safe(t.matches, ev)), None)
        if trig is None:
            continue
        subject = str(ev.get(trig.subject_key) or ev.get("subject") or "")
        if subject and await _recently_tasked(db, subject, trig.cooldown_hours):
            skipped.append({"event": row.id, "why": "subject had a task recently"})
            ev["handled"] = True; row.details = json.dumps(ev, ensure_ascii=False, default=str); continue
        spec = await trig.make_task(ev)
        if dry_run:
            made.append({"event": row.id, "trigger": trig.name, "task": spec, "task_id": None}); continue
        try:
            task = await create_task(db, kind=spec["kind"], title=spec["title"], brief=spec.get("brief"),
                                     input=spec.get("input"), created_by=f"trigger:{trig.name}")
        except Exception:
            logger.exception("Trigger task creation failed for event %s", row.id)
            skipped.append({"event": row.id, "why": "task creation failed"}); continue
        ev["handled"], ev["task_id"] = True, task.id
        row.details = json.dumps(ev, ensure_ascii=False, default=str)
        made.append({"event": row.id, "trigger": trig.name, "task_id": task.id})
    if not dry_run:
        await db.commit()
    return {"proposed": made, "skipped": skipped, "pending": len(await pending(db, limit=100))}


def _safe(fn, ev) -> bool:
    try:
        return bool(fn(ev))
    except Exception:
        return False
