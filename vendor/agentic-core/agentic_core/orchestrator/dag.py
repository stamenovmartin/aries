"""The multi-step executor: a plan that resumes, never restarts.
Lifted from backend/app/execution/dag.py.

Called again with the same plan_key it skips every succeeded step and picks up
at the first incomplete one. Each step's external work is guarded by its own
ExecutionOperation; a step that was SENT but whose outcome is unknown blocks
the plan ('reconcile') instead of re-sending. Progress is committed after every
step. Steps run sequentially in topological order.

A step function is `async (ctx) -> dict` where ctx maps completed step names
to their outputs, and the result is {"success", "output", "uncertain", "details"}.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.models import ExecutionPlan, ExecutionStep
from agentic_core.orchestrator import operations

logger = logging.getLogger(__name__)

StepFn = Callable[[dict], Awaitable[dict]]


@dataclass
class StepSpec:
    name: str
    run: StepFn
    depends_on: list[str] = field(default_factory=list)


async def _get_or_create_plan(db, *, plan_key, plan_type, task_id, target_ref, specs):
    plan = (await db.execute(select(ExecutionPlan)
            .where(ExecutionPlan.plan_key == plan_key))).scalars().first()
    if plan is not None:
        return plan
    plan = ExecutionPlan(plan_key=plan_key, plan_type=plan_type, task_id=task_id,
                         target_ref=target_ref, state="pending")
    db.add(plan)
    await db.flush()
    for i, spec in enumerate(specs):
        db.add(ExecutionStep(plan_id=plan.id, name=spec.name, step_index=i,
                             depends_on=json.dumps(spec.depends_on) if spec.depends_on else None,
                             state="pending"))
    await db.flush()
    return plan


def _report(plan: ExecutionPlan, steps: list[ExecutionStep]) -> dict:
    return {"plan_key": plan.plan_key, "state": plan.state,
            "steps": [{"name": s.name, "state": s.state,
                       "output": json.loads(s.result) if s.result else None,
                       "error": s.error} for s in steps]}


async def run_plan(db: AsyncSession, *, plan_key: str, plan_type: str,
                   specs: list[StepSpec], task_id: int | None = None,
                   target_ref: str | None = None) -> dict:
    """Run (or resume) a multi-step plan. Idempotent by plan_key."""
    plan = await _get_or_create_plan(db, plan_key=plan_key, plan_type=plan_type,
                                     task_id=task_id, target_ref=target_ref, specs=specs)
    steps = (await db.execute(select(ExecutionStep).where(ExecutionStep.plan_id == plan.id)
             .order_by(ExecutionStep.step_index))).scalars().all()
    by_name = {s.name: s for s in steps}
    spec_by_name = {sp.name: sp for sp in specs}

    plan.state = "running"
    await db.commit()

    ctx: dict = {s.name: (json.loads(s.result) if s.result else None)
                 for s in steps if s.state == "succeeded"}

    for step in steps:
        if step.state == "succeeded":
            continue
        deps = json.loads(step.depends_on) if step.depends_on else []
        if any(by_name.get(d) is None or by_name[d].state != "succeeded" for d in deps):
            plan.state = "blocked"
            await db.commit()
            return _report(plan, steps)

        key = f"{plan_key}:{step.name}"
        op, action = await operations.begin(db, key=key, operation_type=plan_type,
                                            task_id=task_id, target_ref=target_ref or step.name)
        if action == "reconcile":
            step.state = "uncertain"
            step.error = "A prior attempt was sent; outcome unknown — reconcile before retrying."
            step.error_class = "uncertain"
            plan.state = "blocked"
            await db.commit()
            return _report(plan, steps)
        if action == "done":
            step.state = "succeeded"
            step.result = step.result or json.dumps(
                {"external_id": op.external_id, "external_url": op.external_url})
            ctx[step.name] = json.loads(step.result)
            await db.commit()
            continue

        await operations.mark_sent(db, op)
        await db.commit()
        try:
            result = await spec_by_name[step.name].run(ctx)
        except Exception as e:
            logger.exception("Step %s of plan %s raised", step.name, plan_key)
            result = {"success": False, "details": f"Unexpected error: {e}"}

        await operations.record(db, op, result)
        if result.get("success"):
            step.state = "succeeded"
            step.result = json.dumps(result.get("output") or {}, ensure_ascii=False)
            step.error = None
            ctx[step.name] = result.get("output") or {}
        elif result.get("uncertain"):
            step.state = "uncertain"
            step.error = (result.get("details") or "")[:2000]
            step.error_class = "uncertain"
            plan.state = "blocked"
            await db.commit()
            return _report(plan, steps)
        else:
            step.state = "failed"
            step.error = (result.get("details") or "")[:2000]
            step.error_class = op.error_class
            plan.state = "failed"
            await db.commit()
            return _report(plan, steps)
        await db.commit()

    plan.state = "succeeded" if all(s.state == "succeeded" for s in steps) else plan.state
    await db.commit()
    return _report(plan, steps)


async def reconcile_step(db: AsyncSession, *, plan_key: str, step_name: str,
                         found: bool, external_id: str | None = None) -> dict:
    """The one honest route out of 'uncertain': evidence from the outside world.
    `found=True` marks the step (and its operation) succeeded; `found=False`
    marks it failed-retriable so the next run_plan re-sends it."""
    plan = (await db.execute(select(ExecutionPlan).where(ExecutionPlan.plan_key == plan_key))).scalars().first()
    if plan is None:
        return {"ok": False, "reason": "no such plan"}
    step = (await db.execute(select(ExecutionStep).where(ExecutionStep.plan_id == plan.id,
                                                          ExecutionStep.name == step_name))).scalars().first()
    if step is None:
        return {"ok": False, "reason": "no such step"}
    op, _ = await operations.begin(db, key=f"{plan_key}:{step_name}", operation_type=plan.plan_type)
    if found:
        op.state, op.external_id, op.last_error, op.error_class = "succeeded", external_id, None, None
        step.state, step.error = "succeeded", None
        step.result = step.result or json.dumps({"external_id": external_id, "reconciled": True})
    else:
        op.state, op.error_class = "failed", "transient"
        step.state, step.error_class = "failed", "transient"
    plan.state = "pending"
    await db.commit()
    return {"ok": True, "step": step_name, "state": step.state}
