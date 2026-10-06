"""Running a task now — the one code path the API, the scheduler, a trigger
and the assistant all call, so they can never drift from each other
(the marketing rule: the chat calls the same handler the dashboard button does).
"""
from __future__ import annotations

import logging

from agentic_core.database.base import async_session
from agentic_core.database.models import Task
from agentic_core.orchestrator.lifecycle import LifecyclePolicy, run_cycle
from agentic_core.orchestrator.states import TaskState, advance_task

logger = logging.getLogger(__name__)

# Applications register how a task KIND is executed: kind → (workflow name | executor factory).
_HANDLERS: dict[str, dict] = {}


def register_kind(kind: str, *, workflow: str | None = None, executor=None, evaluators=None,
                  judge=None, replanner=None, policy: LifecyclePolicy | None = None, notify=None) -> None:
    _HANDLERS[kind] = {"workflow": workflow, "executor": executor, "evaluators": evaluators or [],
                       "judge": judge, "replanner": replanner, "policy": policy, "notify": notify}


def handler_for(kind: str) -> dict | None:
    return _HANDLERS.get(kind) or _HANDLERS.get("*")


def kinds() -> list[str]:
    return sorted(_HANDLERS)


async def run_task_now(task_id: int, kind: str = "initial", *, trigger: str = "manual") -> dict:
    """Execute one task through its handler + the lifecycle. Returns the
    scheduler contract: {attempted, success, deferred, details, outcome}."""
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if task is None:
            return {"attempted": False, "success": False, "deferred": None, "details": "no such task"}
        h = handler_for(task.kind)
        if h is None:
            return {"attempted": False, "success": False, "deferred": "no_handler",
                    "details": f"no handler registered for kind '{task.kind}'"}
        from agentic_core.orchestrator.service import dependencies_met
        ok, blocking = await dependencies_met(db, task)
        if not ok:
            return {"attempted": False, "success": False, "deferred": "dependencies",
                    "details": f"waiting on tasks {blocking}"}
        if task.status in ("draft", "validation_failed", "failed", "rejected", "approved", "scheduled", "completed_unverified"):
            # (re)entering the lifecycle is a legal move from each of these
            try:
                task.status = advance_task(task.status, TaskState.PLANNING) if task.status in ("draft", "failed", "rejected", "validation_failed") else task.status
                if task.status == "planning":
                    task.status = advance_task(task.status, TaskState.DRAFT)
            except Exception:
                pass
        executor = h["executor"]
        if executor is None and h["workflow"]:
            from agentic_core.workflows import engine, spec as wf_spec
            wf = wf_spec.get(h["workflow"])
            if wf is None:
                return {"attempted": False, "success": False, "deferred": None, "details": f"unknown workflow {h['workflow']}"}
            executor = engine.as_executor(wf)
        ctx = {"db": db, "workflow": h["workflow"], "brief": task.brief or task.title}
        try:
            import json
            ctx.update({"input": json.loads(task.input) if task.input else {}})
        except ValueError:
            pass
        outcome = await run_cycle(db, task, executor=executor, evaluators=h["evaluators"], judge=h["judge"],
                                  replanner=h["replanner"], policy=h["policy"], trigger=trigger, ctx=ctx,
                                  notify=h["notify"])
        return {"attempted": True, "success": outcome.verdict == "pass", "deferred": None,
                "details": outcome.verdict, "outcome": outcome.as_dict()}
