"""Task creation, delegation and inspection — the orchestrator's front door.

Composes what the marketing backend spreads over api/agent.py, api/campaigns.py
and services/agent/__init__.py: create a Task, route it to an agent, run it
through a workflow and the lifecycle, and expose the trace.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.models import AutomationLog, Task
from agentic_core.observability import audit
from agentic_core.orchestrator.states import TaskState, advance_task, invalidate_approval

logger = logging.getLogger(__name__)


async def create_task(db: AsyncSession, *, kind: str, title: str, brief: str | None = None,
                      input: dict | None = None, priority: int = 2, parent_id: int | None = None,
                      depends_on: list[int] | None = None, created_by: str = "api",
                      max_attempts: int = 3, route: bool = True) -> Task:
    """Create a task in DRAFT and (optionally) route it. Commits."""
    task = Task(kind=kind, title=title[:255], brief=brief,
                input=json.dumps(input or {}, ensure_ascii=False, default=str),
                priority=priority, parent_id=parent_id,
                depends_on=json.dumps(depends_on) if depends_on else None,
                created_by=created_by, max_attempts=max_attempts, status="draft")
    db.add(task)
    await db.flush()
    if route:
        from agentic_core.router.router import route as route_task
        decision = await route_task(brief or title, kind=kind)
        task.assigned_agent = decision["agent"]
        task.routing = json.dumps(decision, ensure_ascii=False)
    db.add(AutomationLog(action="task.created", source=created_by,
                         details=f"Task {task.id} '{task.title}' ({kind}) → {task.assigned_agent}",
                         status="success"))
    await audit.log_event(db, actor_type="agent" if created_by == "agent" else "human",
                          action="task.created", entity_type="task", entity_id=task.id,
                          detail={"kind": kind, "agent": task.assigned_agent})
    await db.commit()
    await db.refresh(task)
    return task


async def delegate(db: AsyncSession, parent: Task, *, kind: str, title: str, brief: str | None = None,
                   input: dict | None = None, created_by: str = "agent") -> Task:
    """A sub-task an agent hands to another agent. Same table, parent linked."""
    child = await create_task(db, kind=kind, title=title, brief=brief, input=input,
                              parent_id=parent.id, created_by=created_by)
    db.add(AutomationLog(action="task.delegated", source=f"task:{parent.id}",
                         details=f"→ task {child.id} '{title}' ({child.assigned_agent})", status="success"))
    await db.commit()
    return child


async def dependencies_met(db: AsyncSession, task: Task) -> tuple[bool, list[int]]:
    """A task waits on every id in depends_on being DONE."""
    if not task.depends_on:
        return True, []
    ids = json.loads(task.depends_on)
    rows = (await db.execute(select(Task.id, Task.status).where(Task.id.in_(ids)))).all()
    blocking = [i for i, s in rows if s != "done"] + [i for i in ids if i not in {r[0] for r in rows}]
    return not blocking, blocking


async def edit_task(db: AsyncSession, task: Task, *, brief: str | None = None, input: dict | None = None) -> Task:
    """Rule 1: an edit to an approved task revokes the approval."""
    before = task.status
    if brief is not None:
        task.brief = brief
    if input is not None:
        task.input = json.dumps(input, ensure_ascii=False, default=str)
    task.status = invalidate_approval(task.status).value
    if before != task.status:
        db.add(AutomationLog(action="task.approval_invalidated", source="edit",
                             details=f"Task {task.id}: {before} → {task.status}", status="success"))
    await db.commit()
    await db.refresh(task)
    return task


async def cancel_task(db: AsyncSession, task: Task, *, by: str = "human") -> Task:
    task.status = advance_task(task.status, TaskState.CANCELLED)
    await audit.log_event(db, actor_type="human", actor=by, action="task.cancelled",
                          entity_type="task", entity_id=task.id)
    await db.commit()
    await db.refresh(task)
    return task


async def approve_task(db: AsyncSession, task: Task, *, by: str, channel: str = "api") -> Task:
    task.status = advance_task(task.status, TaskState.APPROVED)
    task.approved_by, task.approved_at, task.approval_channel = by, datetime.utcnow(), channel
    task.rejected_reason = None
    await audit.log_event(db, actor_type="human", actor=by, action="task.approved",
                          entity_type="task", entity_id=task.id, detail={"channel": channel})
    await db.commit()
    await db.refresh(task)
    return task


async def reject_task(db: AsyncSession, task: Task, *, by: str, reason: str | None = None,
                      channel: str = "api") -> Task:
    from agentic_core.database.models import Feedback
    task.status = advance_task(task.status, TaskState.REJECTED)
    task.rejected_reason = reason or None
    if reason:
        # A stated reason is a labelled negative — the learning loop's best signal.
        db.add(Feedback(task_id=task.id, scope=task.assigned_agent or "", kind="reject",
                        instruction=reason, sender=by))
    await audit.log_event(db, actor_type="human", actor=by, action="task.rejected",
                          entity_type="task", entity_id=task.id, detail={"reason": reason, "channel": channel})
    await db.commit()
    await db.refresh(task)
    return task


def serialize(task: Task) -> dict:
    return {"id": task.id, "kind": task.kind, "title": task.title, "brief": task.brief,
            "status": task.status, "priority": task.priority, "parent_id": task.parent_id,
            "depends_on": json.loads(task.depends_on) if task.depends_on else [],
            "assigned_agent": task.assigned_agent,
            "routing": json.loads(task.routing) if task.routing else None,
            "input": json.loads(task.input) if task.input else {},
            "result": json.loads(task.result) if task.result else None,
            "attempts": task.attempts, "max_attempts": task.max_attempts,
            "last_error": task.last_error, "error_class": task.error_class,
            "approved_by": task.approved_by, "rejected_reason": task.rejected_reason,
            "created_by": task.created_by,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None}
