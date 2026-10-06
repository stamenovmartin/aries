"""The routes. Each one is thin: it calls the same service function the
workers and the assistant call."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.base import get_db
from agentic_core.database.models import (ActionProposal, AuditEvent, AutomationLog, EvalCase, EvalResult,
                                          EvalRun, ExecutionOperation, ExecutionPlan, ExecutionStep,
                                          ScheduledTask, Task)

router = APIRouter()


# ── health / observability ───────────────────────────────────────────────────

@router.get("/health", tags=["health"])
async def health(request: Request):
    from agentic_core.api.health import collect, summarise
    components = await collect(request)
    by = {c["component"]: c for c in components}
    ok = by.get("database", {}).get("status") == "ok"
    return {"status": "healthy" if ok else "degraded", "status_means": "'healthy' means only that the database answers.",
            "components": components, "summary": summarise(components)}


@router.get("/observability/metrics", tags=["observability"])
async def read_metrics():
    from agentic_core.llm import telemetry
    from agentic_core.observability import metrics
    snap = metrics.snapshot()
    snap["ai_telemetry"] = telemetry.snapshot()
    return snap


@router.get("/observability/workers", tags=["observability"])
async def workers_status():
    from agentic_core.scheduler import registry
    return {"workers": registry.status()}


@router.post("/observability/workers/{name}/run", tags=["observability"])
async def run_worker(name: str):
    from agentic_core.scheduler import registry
    w = registry.get(name)
    if w is None:
        raise HTTPException(404, "no such worker")
    return {"worker": name, "result": await w.run_once()}


@router.get("/logs", tags=["observability"])
async def logs(action: str | None = None, source: str | None = None, status: str | None = None, limit: int = 50,
               db: AsyncSession = Depends(get_db)):
    q = select(AutomationLog).order_by(AutomationLog.id.desc())
    if action:
        q = q.where(AutomationLog.action.startswith(action))
    if source:
        q = q.where(AutomationLog.source == source)
    if status:
        q = q.where(AutomationLog.status == status)
    rows = (await db.execute(q.limit(max(1, min(limit, 500))))).scalars().all()
    return [{"id": r.id, "action": r.action, "source": r.source, "status": r.status, "details": r.details,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@router.get("/audit", tags=["observability"])
async def audit_list(action: str | None = None, entity_type: str | None = None, entity_id: str | None = None,
                     actor: str | None = None, correlation_id: str | None = None, since: datetime | None = None,
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    conds = []
    if action:
        conds.append(AuditEvent.action.startswith(action))
    if entity_type:
        conds.append(AuditEvent.entity_type == entity_type)
    if entity_id:
        conds.append(AuditEvent.entity_id == str(entity_id))
    if actor:
        conds.append(AuditEvent.actor.ilike(f"%{actor}%"))
    if correlation_id:
        conds.append(AuditEvent.correlation_id == correlation_id)
    if since:
        conds.append(AuditEvent.at >= since)
    total = (await db.execute(select(func.count(AuditEvent.id)).where(*conds))).scalar_one()
    rows = (await db.execute(select(AuditEvent).where(*conds).order_by(AuditEvent.at.desc(), AuditEvent.id.desc())
                             .limit(limit).offset(offset))).scalars().all()

    def _l(raw):
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return raw
    return {"total": total, "items": [{"id": e.id, "at": e.at.isoformat() if e.at else None, "actor_type": e.actor_type,
                                       "actor": e.actor, "action": e.action, "entity_type": e.entity_type,
                                       "entity_id": e.entity_id, "permission": e.permission,
                                       "correlation_id": e.correlation_id, "detail": _l(e.detail),
                                       "before": _l(e.before_state), "after": _l(e.after_state)} for e in rows]}


# ── environment / runtime switches ───────────────────────────────────────────

@router.get("/environment", tags=["environment"])
async def environment():
    from agentic_core.config import runtime
    from agentic_core.llm import providers
    from agentic_core.security import crypto, environments
    live = [t.strip() for t in (runtime.get_live_tools() or "").split(",") if t.strip()]
    return {"app_env": environments.describe(), "dry_run": runtime.get_dry_run(), "live_tools": live,
            "executing_live": (not runtime.get_dry_run()) and bool(live), "provider": providers.describe(),
            "autopilot": runtime.get_autopilot(), "credentials": crypto.describe(),
            "note": "'executing_live' is true only when dry-run is off AND at least one tool is named in live_tools."}


class GoLive(BaseModel):
    dry_run: bool | None = None
    live_tools: str | None = None
    ai_provider: str | None = None
    require_ai: bool | None = None
    autopilot: bool | None = None
    operator_prompt: str | None = None


@router.post("/environment/go-live", tags=["environment"])
async def go_live(body: GoLive):
    from agentic_core.config import runtime
    out = {}
    if body.dry_run is not None:
        out["dry_run"] = runtime.set_dry_run(body.dry_run)
    if body.live_tools is not None:
        out["live_tools"] = runtime.set_live_tools(body.live_tools)
    if body.ai_provider is not None:
        try:
            out["ai_provider"] = runtime.set_ai_provider(body.ai_provider)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if body.require_ai is not None:
        out["require_ai"] = runtime.set_require_ai(body.require_ai)
    if body.autopilot is not None:
        out["autopilot"] = runtime.set_autopilot(body.autopilot)
    if body.operator_prompt is not None:
        out["operator_prompt"] = runtime.set_operator_prompt(body.operator_prompt)
    return out


# ── roster: agents, tools, workflows, routing ────────────────────────────────

@router.get("/agents", tags=["agents"])
async def agents():
    from agentic_core.agents import registry
    return {"agents": registry.describe_all()}


@router.get("/tools", tags=["tools"])
async def tools():
    from agentic_core.tools import connectors, registry
    return {"tools": registry.describe_all(), "connectors": connectors.all_capabilities()}


@router.get("/workflows", tags=["workflows"])
async def workflows():
    from agentic_core.scheduler.queue import kinds
    from agentic_core.workflows import spec
    return {"workflows": [w.describe() for w in spec.all_workflows()], "task_kinds": kinds()}


class RouteBody(BaseModel):
    task: str
    kind: str | None = None


@router.post("/route", tags=["routing"])
async def route_task(body: RouteBody):
    from agentic_core.router.router import route
    if not body.task.strip():
        raise HTTPException(400, "empty task")
    return await route(body.task, kind=body.kind)


@router.get("/orchestration/plan", tags=["orchestration"])
async def orchestration_plan(workflow: str = "plan_execute_verify", has_brief: bool = True, review_errors: bool = False):
    """The Director's dry decision for a hypothetical context — routing you can poke at."""
    from agentic_core.orchestrator.graph import Director
    from agentic_core.workflows import engine, spec
    wf = spec.get(workflow)
    if wf is None:
        raise HTTPException(404, "unknown workflow")
    ctx = {"brief": "x" if has_brief else None, "review_hard_errors": review_errors, "caller": {}}
    nodes = engine.to_nodes(None, wf, None, {"id": None})
    return {"workflow": workflow, "decisions": [d.as_dict() for d in Director().plan(nodes, ctx)]}


# ── tasks ────────────────────────────────────────────────────────────────────

class TaskIn(BaseModel):
    kind: str = "generic"
    title: str
    brief: str | None = None
    input: dict | None = None
    priority: int = 2
    parent_id: int | None = None
    depends_on: list[int] | None = None
    run_now: bool = False


@router.post("/tasks", tags=["tasks"], status_code=201)
async def create_task(body: TaskIn, db: AsyncSession = Depends(get_db)):
    from agentic_core.orchestrator.service import create_task as _create, serialize
    from agentic_core.security import principal
    p = principal.current()
    task = await _create(db, kind=body.kind, title=body.title, brief=body.brief, input=body.input,
                         priority=body.priority, parent_id=body.parent_id, depends_on=body.depends_on,
                         created_by=(p.describe() if p else "api"))
    out = serialize(task)
    if body.run_now:
        from agentic_core.scheduler.queue import run_task_now
        run = await run_task_now(task.id, trigger="api")
        await db.refresh(task)
        out = {**serialize(task), "run": run}
    return out


@router.get("/tasks", tags=["tasks"])
async def list_tasks(status: str | None = None, kind: str | None = None, limit: int = 50, db: AsyncSession = Depends(get_db)):
    from agentic_core.orchestrator.service import serialize
    q = select(Task).order_by(Task.id.desc())
    if status:
        q = q.where(Task.status == status)
    if kind:
        q = q.where(Task.kind == kind)
    return [serialize(t) for t in (await db.execute(q.limit(max(1, min(limit, 200))))).scalars().all()]


@router.get("/tasks/{task_id}", tags=["tasks"])
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    from agentic_core.observability import trace
    from agentic_core.orchestrator.service import serialize
    t = await db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "no such task")
    return {**serialize(t), "runs": await trace.for_task(db, task_id)}


@router.post("/tasks/{task_id}/run", tags=["tasks"])
async def run_task(task_id: int, db: AsyncSession = Depends(get_db)):
    from agentic_core.scheduler.queue import run_task_now
    if await db.get(Task, task_id) is None:
        raise HTTPException(404, "no such task")
    return await run_task_now(task_id, trigger="api")


class Decision(BaseModel):
    by: str = "api"
    reason: str | None = None


@router.post("/tasks/{task_id}/approve", tags=["tasks"])
async def approve(task_id: int, body: Decision, db: AsyncSession = Depends(get_db)):
    from agentic_core.orchestrator.service import approve_task, serialize
    from agentic_core.orchestrator.states import IllegalTransition
    t = await db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "no such task")
    try:
        return serialize(await approve_task(db, t, by=body.by))
    except IllegalTransition as e:
        raise HTTPException(409, str(e))


@router.post("/tasks/{task_id}/reject", tags=["tasks"])
async def reject(task_id: int, body: Decision, db: AsyncSession = Depends(get_db)):
    from agentic_core.orchestrator.service import reject_task, serialize
    from agentic_core.orchestrator.states import IllegalTransition
    t = await db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "no such task")
    try:
        return serialize(await reject_task(db, t, by=body.by, reason=body.reason))
    except IllegalTransition as e:
        raise HTTPException(409, str(e))


@router.post("/tasks/{task_id}/cancel", tags=["tasks"])
async def cancel(task_id: int, body: Decision, db: AsyncSession = Depends(get_db)):
    from agentic_core.orchestrator.service import cancel_task, serialize
    from agentic_core.orchestrator.states import IllegalTransition
    t = await db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "no such task")
    try:
        return serialize(await cancel_task(db, t, by=body.by))
    except IllegalTransition as e:
        raise HTTPException(409, str(e))


# ── proposals / approvals ────────────────────────────────────────────────────

@router.get("/proposals", tags=["approvals"])
async def proposals(status: str = "proposed", limit: int = 50, db: AsyncSession = Depends(get_db)):
    from agentic_core.security.approvals import serialize
    q = select(ActionProposal).order_by(ActionProposal.id.desc()).limit(limit)
    if status != "all":
        q = q.where(ActionProposal.status == status)
    return [serialize(p) for p in (await db.execute(q)).scalars().all()]


@router.post("/proposals/{proposal_id}/approve", tags=["approvals"])
async def approve_proposal(proposal_id: int, body: Decision, db: AsyncSession = Depends(get_db)):
    from agentic_core.security import approvals
    p = await approvals.approve(db, proposal_id, decided_by=body.by, note=body.reason, channel="api")
    if p is None:
        raise HTTPException(404, "no such proposal")
    await db.commit()
    return approvals.serialize(p)


@router.post("/proposals/{proposal_id}/reject", tags=["approvals"])
async def reject_proposal(proposal_id: int, body: Decision, db: AsyncSession = Depends(get_db)):
    from agentic_core.security import approvals
    p = await approvals.reject(db, proposal_id, decided_by=body.by, note=body.reason, channel="api")
    if p is None:
        raise HTTPException(404, "no such proposal")
    await db.commit()
    return approvals.serialize(p)


class ExecuteBody(BaseModel):
    tool: str
    payload: dict = {}
    task_id: int | None = None
    approved_proposal_id: int | None = None


@router.post("/execution/tool", tags=["execution"])
async def execute_tool(body: ExecuteBody, db: AsyncSession = Depends(get_db)):
    """Call a tool through every gate (dry-run, live, policy, approval, idempotency)."""
    from agentic_core.security import principal
    from agentic_core.tools.calling import call_tool
    p = principal.current()
    return await call_tool(db, body.tool, body.payload, task_id=body.task_id,
                           approved_proposal_id=body.approved_proposal_id, actor=(p.describe() if p else "api"))


@router.get("/execution/recent", tags=["execution"])
async def execution_recent(limit: int = 40, db: AsyncSession = Depends(get_db)):
    ops = (await db.execute(select(ExecutionOperation).order_by(ExecutionOperation.id.desc()).limit(limit))).scalars().all()
    plans = (await db.execute(select(ExecutionPlan).order_by(ExecutionPlan.id.desc()).limit(limit))).scalars().all()
    plan_out = []
    for p in plans:
        steps = (await db.execute(select(ExecutionStep).where(ExecutionStep.plan_id == p.id).order_by(ExecutionStep.step_index))).scalars().all()
        plan_out.append({"plan_key": p.plan_key, "plan_type": p.plan_type, "state": p.state, "task_id": p.task_id,
                         "steps": [{"name": s.name, "state": s.state, "error": s.error} for s in steps]})
    by_state: dict[str, int] = {}
    for o in ops:
        by_state[o.state] = by_state.get(o.state, 0) + 1
    return {"summary": by_state,
            "operations": [{"id": o.id, "type": o.operation_type, "tool": o.tool, "state": o.state, "attempts": o.attempts,
                            "external_id": o.external_id, "error_class": o.error_class,
                            "last_error": (o.last_error or "")[:160] or None, "target_ref": o.target_ref,
                            "task_id": o.task_id, "created_at": o.created_at.isoformat() if o.created_at else None} for o in ops],
            "plans": plan_out}


class ReconcileBody(BaseModel):
    found: bool
    external_id: str | None = None


@router.post("/execution/plans/{plan_key}/steps/{step}/reconcile", tags=["execution"])
async def reconcile(plan_key: str, step: str, body: ReconcileBody, db: AsyncSession = Depends(get_db)):
    from agentic_core.orchestrator.dag import reconcile_step
    return await reconcile_step(db, plan_key=plan_key, step_name=step, found=body.found, external_id=body.external_id)


# ── scheduler ────────────────────────────────────────────────────────────────

class ScheduleBody(BaseModel):
    run_at: datetime | None = None
    in_minutes: int | None = None
    kind: str = "initial"


@router.post("/scheduler/tasks/{task_id}", tags=["scheduler"])
async def schedule_task(task_id: int, body: ScheduleBody, db: AsyncSession = Depends(get_db)):
    from datetime import timedelta
    from agentic_core.scheduler.scheduled import schedule, serialize
    if await db.get(Task, task_id) is None:
        raise HTTPException(404, "no such task")
    run_at = body.run_at or (datetime.utcnow() + timedelta(minutes=body.in_minutes or 0))
    return serialize(await schedule(db, task_id, run_at, kind=body.kind))


@router.get("/scheduler", tags=["scheduler"])
async def list_scheduled(status: str | None = None, limit: int = 100, db: AsyncSession = Depends(get_db)):
    from agentic_core.scheduler.scheduled import serialize
    q = select(ScheduledTask).order_by(ScheduledTask.run_at)
    if status:
        q = q.where(ScheduledTask.status == status)
    return [serialize(r) for r in (await db.execute(q.limit(limit))).scalars().all()]


@router.delete("/scheduler/{scheduled_id}", tags=["scheduler"])
async def cancel_scheduled(scheduled_id: int, db: AsyncSession = Depends(get_db)):
    from agentic_core.scheduler.scheduled import serialize
    sp = await db.get(ScheduledTask, scheduled_id)
    if sp is None:
        raise HTTPException(404, "no such schedule")
    if sp.status in ("done", "executing"):
        raise HTTPException(409, f"cannot cancel a '{sp.status}' schedule")
    sp.status = "canceled"
    await db.commit()
    return serialize(sp)


@router.post("/scheduler/tick", tags=["scheduler"])
async def tick(now: str | None = None, db: AsyncSession = Depends(get_db)):
    from agentic_core.scheduler.scheduled import process_due
    ref = None
    if now:
        try:
            ref = datetime.fromisoformat(now)
        except ValueError:
            ref = None
    outcomes = await process_due(db, now=ref)
    return {"processed": len(outcomes), "outcomes": outcomes}


class EventBody(BaseModel):
    kind: str
    subject: str
    data: dict = {}


@router.post("/events", tags=["scheduler"])
async def post_event(body: EventBody, db: AsyncSession = Depends(get_db)):
    from agentic_core.scheduler import triggers
    row = await triggers.record(db, body.kind, body.subject, body.data, source="api")
    await db.commit()
    return {"event_id": row.id}


@router.post("/events/propose", tags=["scheduler"])
async def propose_from_events(dry_run: bool = False, db: AsyncSession = Depends(get_db)):
    from agentic_core.scheduler import triggers
    return await triggers.propose(db, dry_run=dry_run)


# ── memory / learning ────────────────────────────────────────────────────────

@router.get("/context", tags=["memory"])
async def context_listing():
    from agentic_core.memory import context_layer
    return {"modules": context_layer.listing(), "digest": context_layer.digest()}


@router.get("/context/{module}/{name}", tags=["memory"])
async def context_doc(module: str, name: str):
    from agentic_core.memory import context_layer
    try:
        doc = context_layer.read(module, name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if doc is None:
        raise HTTPException(404, "no such document")
    doc["data"] = context_layer.read_data(module, name)
    return doc


class MemoryIn(BaseModel):
    kind: str = "fact"
    title: str
    content: str


@router.post("/memory", tags=["memory"])
async def memory_add(body: MemoryIn, db: AsyncSession = Depends(get_db)):
    from agentic_core.memory.vector import remember
    row = await remember(db, kind=body.kind, title=body.title, content=body.content)
    return {"id": row.id, "backend": row.backend, "dim": row.dim}


@router.get("/memory/recall", tags=["memory"])
async def memory_recall(q: str, top_k: int = 5, db: AsyncSession = Depends(get_db)):
    from agentic_core.memory.vector import recall
    return [{"id": m.id, "kind": m.kind, "title": m.title, "content": m.content[:300], "score": round(s, 3)}
            for m, s in await recall(db, q, top_k=top_k)]


@router.post("/memory/ask", tags=["memory"])
async def memory_ask(q: str, db: AsyncSession = Depends(get_db)):
    from agentic_core.memory.vector import ask
    return await ask(db, q)


@router.post("/learning/distill", tags=["memory"])
async def distill(db: AsyncSession = Depends(get_db)):
    from agentic_core.memory.feedback import distill as _distill
    return await _distill(db)


@router.get("/learning/rules", tags=["memory"])
async def rules(db: AsyncSession = Depends(get_db)):
    from agentic_core.memory.feedback import rules_snapshot
    return await rules_snapshot(db)


class FeedbackIn(BaseModel):
    task_id: int | None = None
    scope: str | None = None
    kind: str = "edit"
    before: str = ""
    after: str = ""
    instruction: str | None = None
    sender: str = "api"


@router.post("/feedback", tags=["memory"])
async def feedback(body: FeedbackIn, db: AsyncSession = Depends(get_db)):
    from agentic_core.memory import feedback as fb
    if body.kind == "reject":
        row = await fb.capture_reject(db, task_id=body.task_id, scope=body.scope, reason=body.instruction or body.after, sender=body.sender)
    else:
        row = await fb.capture_edit(db, task_id=body.task_id, scope=body.scope, before=body.before, after=body.after,
                                    instruction=body.instruction, sender=body.sender)
    await db.commit()
    return {"id": row.id if row else None, "captured": row is not None}


# ── evals ────────────────────────────────────────────────────────────────────

class EvalCaseIn(BaseModel):
    name: str
    agent: str = "executor"
    input: dict = {}
    expected: dict = {}
    tags: list[str] = []


@router.post("/evals/cases", tags=["evals"], status_code=201)
async def add_case(body: EvalCaseIn, db: AsyncSession = Depends(get_db)):
    c = EvalCase(name=body.name, agent=body.agent, input=json.dumps(body.input), expected=json.dumps(body.expected),
                 tags=json.dumps(body.tags))
    db.add(c)
    await db.commit()
    return {"id": c.id}


@router.get("/evals/cases", tags=["evals"])
async def list_cases(db: AsyncSession = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "agent": c.agent, "input": json.loads(c.input or "{}"),
             "expected": json.loads(c.expected or "{}"), "tags": json.loads(c.tags or "[]"), "active": c.active}
            for c in (await db.execute(select(EvalCase).order_by(EvalCase.id))).scalars().all()]


@router.post("/evals/run", tags=["evals"])
async def run_evals(label: str | None = None, judge: bool = False, agent: str = "executor", db: AsyncSession = Depends(get_db)):
    from agentic_core.agents import registry
    from agentic_core.agents.runtime import run_agent
    from agentic_core.evaluators.judge import make_judge
    from agentic_core.evaluators.runner import run_suite
    from agentic_core.evaluators.scorers import default_suite
    spec = registry.get(agent)
    if spec is None:
        raise HTTPException(404, "unknown agent")

    async def gen(case):
        ctx = {"brief": case.name, **(json.loads(case.input) if case.input else {})}
        res = await run_agent(spec, ctx, db=db)
        out = res["output"]
        return out.get("content") if isinstance(out, dict) else str(out)
    return await run_suite(db, label=label, generate_fn=gen, suite=default_suite(),
                           judge=make_judge() if judge else None, prompt_version=spec.prompt_version, agent=agent)


@router.get("/evals/runs", tags=["evals"])
async def list_runs(limit: int = 20, db: AsyncSession = Depends(get_db)):
    return [{"id": r.id, "label": r.label, "prompt_version": r.prompt_version, "judged": r.judged, "cases": r.cases,
             "passed": r.passed, "avg_score": r.avg_score, "dimensions": json.loads(r.dimensions) if r.dimensions else {},
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in (await db.execute(select(EvalRun).order_by(EvalRun.id.desc()).limit(limit))).scalars().all()]


@router.get("/evals/runs/{run_id}", tags=["evals"])
async def run_detail(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    results = (await db.execute(select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.id))).scalars().all()
    return {"id": run.id, "label": run.label, "avg_score": run.avg_score, "passed": run.passed, "cases": run.cases,
            "results": [{"case_name": r.case_name, "overall": r.overall, "passed": r.passed,
                         "scores": json.loads(r.scores or "{}"), "notes": json.loads(r.notes or "{}"), "output": r.output}
                        for r in results]}


# ── secrets ──────────────────────────────────────────────────────────────────

@router.get("/settings/credentials", tags=["security"])
async def credentials_state(db: AsyncSession = Depends(get_db)):
    from agentic_core.security import secrets_store
    return {"fields": await secrets_store.state(db)}


class CredentialsIn(BaseModel):
    values: dict[str, str]


@router.post("/settings/credentials", tags=["security"])
async def credentials_save(body: CredentialsIn, db: AsyncSession = Depends(get_db)):
    from agentic_core.security import secrets_store
    return await secrets_store.save(db, body.values)


@router.post("/settings/credentials/{key}/revoke", tags=["security"])
async def credentials_revoke(key: str, db: AsyncSession = Depends(get_db)):
    from agentic_core.security import secrets_store
    return await secrets_store.revoke(db, key)
