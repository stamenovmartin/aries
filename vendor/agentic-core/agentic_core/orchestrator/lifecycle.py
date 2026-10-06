"""TASK → EXECUTION → RESULT → EVALUATION → PASS/FAIL → RETRY / REPLAN / ESCALATE.

This is the generalisation of what the marketing pipeline does in
backend/app/services/agent/__init__.py (copy → review → gate_and_repair) and
backend/app/services/posting/__init__.py (publish → classify → skip/fail):

  1. EXECUTE     the executor produces a result (an agent, a tool, a plan).
  2. EVALUATE    every deterministic evaluator runs; an optional LLM judge adds
                 a second opinion that can lower but never override honesty.
  3. VERDICT     pass  → optional approval gate → done
                 fail  → classify the failure:
                    transient   → RETRY the same executor (bounded, with the
                                  evaluator's issues as a corrective note —
                                  the gate_and_repair pattern)
                    validation  → REPLAN: hand the issues to the planner and
                                  run again (bounded)
                    policy /
                    unknown /
                    exhausted   → ESCALATE: an ActionProposal for a human,
                                  notified on the approval channel
                    uncertain   → RECONCILE: never re-run; ask a human/probe.

Everything is recorded: a TaskRun with the decisions, an AgentStep per phase,
an AutomationLog line per verdict, an AuditEvent for the escalation.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.models import AutomationLog, Task, TaskRun
from agentic_core.evaluators.base import Verdict, evaluate_all
from agentic_core.observability import audit, metrics, trace
from agentic_core.orchestrator.errors import ErrorClass, classify
from agentic_core.orchestrator.states import TaskState, advance_task

logger = logging.getLogger(__name__)

# executor(task, ctx) -> result dict; ctx carries {"attempt", "issues", "plan", ...}
Executor = Callable[[Task, dict], Awaitable[dict]]
# replanner(task, ctx) -> new plan dict merged into ctx["plan"]
Replanner = Callable[[Task, dict], Awaitable[dict]]


@dataclass
class LifecyclePolicy:
    max_retries: int = 2          # same executor, corrective note
    max_replans: int = 1          # planner re-run on validation failures
    require_approval: bool = False  # PASS still waits for a human
    pass_threshold: float = 0.7
    escalate_on_uncertain: bool = True


@dataclass
class Outcome:
    verdict: str                  # pass | retry_exhausted | replan_exhausted | escalated | reconcile
    run_id: int
    result: dict | None
    evaluation: dict | None
    attempts: int
    replans: int
    proposal_id: int | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "run_id": self.run_id, "result": self.result,
                "evaluation": self.evaluation, "attempts": self.attempts, "replans": self.replans,
                "proposal_id": self.proposal_id, "notes": self.notes}


def _decide(v: Verdict, err_cls: ErrorClass | None) -> str:
    """Map an evaluation + optional failure class to the next move."""
    if v.passed:
        return "pass"
    if err_cls is ErrorClass.UNCERTAIN:
        return "reconcile"
    if err_cls in (ErrorClass.POLICY, ErrorClass.AUTH, ErrorClass.CAPABILITY):
        return "escalate"
    if err_cls is ErrorClass.VALIDATION or v.needs_replan:
        return "replan"
    if err_cls is ErrorClass.TRANSIENT or v.hard_errors:
        return "retry"
    return "escalate"


async def run_cycle(db: AsyncSession, task: Task, *, executor: Executor,
                    evaluators: list, judge=None, replanner: Replanner | None = None,
                    policy: LifecyclePolicy | None = None, trigger: str = "manual",
                    ctx: dict | None = None, notify=None) -> Outcome:
    """One full lifecycle for a task. Commits. Never raises for a task failure —
    a failure is an Outcome, an exception here is a bug."""
    from agentic_core.observability import correlation
    from agentic_core.security import approvals

    policy = policy or LifecyclePolicy()
    ctx = dict(ctx or {})
    run = TaskRun(task_id=task.id, trigger=trigger, workflow=ctx.get("workflow"),
                  correlation_id=correlation.current(), status="running")
    db.add(run)
    await db.flush()
    task.status = advance_task(task.status, TaskState.RUNNING)
    await db.commit()

    attempts, replans = 0, 0
    result: dict | None = None
    verdict: Verdict | None = None
    err_cls: ErrorClass | None = None
    notes: list[str] = []

    while True:
        attempts += 1
        ctx["attempt"] = attempts
        # Trace and verdict rows from the previous attempt must be durable before
        # another executor reads settings and awaits external I/O. Otherwise that
        # read autoflushes them and holds SQLite's writer lock throughout the wait.
        await db.commit()
        t0 = time.monotonic()
        # ── EXECUTION ──────────────────────────────────────────────────────
        try:
            result = await executor(task, ctx)
            err_cls = None
            if isinstance(result, dict) and result.get("uncertain"):
                err_cls = ErrorClass.UNCERTAIN
            elif isinstance(result, dict) and result.get("success") is False:
                err_cls = classify(str(result.get("details") or result.get("error") or "")).cls
        except Exception as e:
            logger.exception("Executor raised on task %s attempt %d", task.id, attempts)
            result = {"success": False, "details": f"{type(e).__name__}: {e}"}
            err_cls = classify(str(e)).cls
        ms = int((time.monotonic() - t0) * 1000)
        await trace.record(db, run.id, "executor", summary=_summ(result), detail=result,
                           ok=bool(result and result.get("success", True)), duration_ms=ms)
        await db.commit()

        # ── EVALUATION ─────────────────────────────────────────────────────
        verdict = await evaluate_all(evaluators, result, task, ctx, judge=judge,
                                     pass_threshold=policy.pass_threshold)
        metrics.record_validation(task.kind, verdict.passed)
        await trace.record(db, run.id, "evaluator", summary=verdict.summary(), detail=verdict.as_dict(),
                           ok=verdict.passed, confidence=verdict.score)
        move = _decide(verdict, err_cls)
        db.add(AutomationLog(action=f"lifecycle.{move}", source=f"task:{task.id}",
                             details=f"attempt {attempts}: {verdict.summary()[:400]}",
                             status="success" if move == "pass" else "failure"))

        # ── VERDICT ────────────────────────────────────────────────────────
        if move == "pass":
            break
        if move == "retry" and attempts <= policy.max_retries:
            ctx["issues"] = verdict.issues
            ctx["corrective_note"] = verdict.corrective_note()
            metrics.record_retry(f"task:{task.kind}")
            notes.append(f"retry {attempts}: {verdict.summary()[:120]}")
            continue
        if move == "replan" and replanner is not None and replans < policy.max_replans:
            replans += 1
            ctx["issues"] = verdict.issues
            await db.commit()
            try:
                new_plan = await replanner(task, ctx)
                ctx["plan"] = new_plan
                await trace.record(db, run.id, "planner", summary="replanned", detail=new_plan, ok=True)
                notes.append(f"replan {replans}: {verdict.summary()[:120]}")
                task.status = advance_task(task.status, TaskState.PLANNING)
                task.status = advance_task(task.status, TaskState.RUNNING)
                continue
            except Exception as e:
                logger.exception("Replanner failed for task %s", task.id)
                notes.append(f"replan failed: {e}")
                move = "escalate"
        if move == "reconcile" and not policy.escalate_on_uncertain:
            break
        # retry/replan exhausted, reconcile, or escalate → a human.
        break

    # ── OUTCOME ────────────────────────────────────────────────────────────
    run.decisions = json.dumps(ctx.get("decisions") or [], ensure_ascii=False, default=str)
    run.evaluation = json.dumps(verdict.as_dict(), ensure_ascii=False, default=str) if verdict else None
    task.attempts = (task.attempts or 0) + attempts
    proposal_id = None
    notification = None

    if move == "pass":
        task.result = json.dumps(result, ensure_ascii=False, default=str)
        task.last_error, task.error_class = None, None
        if policy.require_approval or (result or {}).get("requires_approval"):
            task.status = advance_task(task.status, TaskState.AWAITING_APPROVAL)
            p = await approvals.propose(db, kind=(result or {}).get("proposal_kind") or f"complete:{task.kind}",
                                        task_id=task.id, run_id=run.id, title=task.title,
                                        payload=result, rationale="Evaluation passed; consequential — needs a human.",
                                        confidence=verdict.score if verdict else None,
                                        evidence=verdict.as_dict() if verdict else None,
                                        risk=(result or {}).get("risk") or "medium")
            proposal_id = p.id
            if notify:
                notification = (p, "awaiting approval")
        else:
            task.status = advance_task(task.status, TaskState.COMPLETED_UNVERIFIED)
            task.status = advance_task(task.status, TaskState.DONE)
        run.status, run.verdict, final = "done", "pass", "pass"
    else:
        task.last_error = (verdict.summary() if verdict else "")[:2000]
        task.error_class = err_cls.value if err_cls else "validation"
        if move == "reconcile":
            task.status = advance_task(task.status, TaskState.FAILED)
            final = "reconcile"
        elif move == "replan":
            task.status = advance_task(task.status, TaskState.VALIDATION_FAILED)
            final = "replan_exhausted"
        elif move == "retry":
            task.status = advance_task(task.status, TaskState.VALIDATION_FAILED)
            final = "retry_exhausted"
        else:
            task.status = advance_task(task.status, TaskState.FAILED)
            final = "escalated"
        # Every non-pass ends in a human's queue. The proposal is the escalation.
        p = await approvals.propose(db, kind=f"escalation:{final}", task_id=task.id, run_id=run.id,
                                    title=f"[{final}] {task.title}",
                                    payload={"result": result, "issues": verdict.issues if verdict else [],
                                             "error_class": task.error_class},
                                    rationale=f"{final}: {task.last_error}",
                                    confidence=verdict.score if verdict else None,
                                    evidence=verdict.as_dict() if verdict else None,
                                    risk="high" if move in ("escalate", "reconcile") else "medium",
                                    created_by="lifecycle")
        proposal_id = p.id
        metrics.record_escalation(final)
        await audit.log_event(db, actor_type="system", actor="lifecycle", action=f"task.{final}",
                              entity_type="task", entity_id=task.id,
                              detail={"attempts": attempts, "replans": replans, "error_class": task.error_class})
        run.status, run.verdict = "failed", final
        if notify:
            notification = (p, final)

    run.finished_at = datetime.utcnow()
    await db.commit()
    # A notification can call a remote service. Persist its proposal and release
    # the writer first, so unrelated goals and worker heartbeats can still save.
    if notification:
        await _notify(notify, task, *notification)
    await db.refresh(task)
    return Outcome(verdict=final, run_id=run.id, result=result,
                   evaluation=verdict.as_dict() if verdict else None,
                   attempts=attempts, replans=replans, proposal_id=proposal_id, notes=notes)


def _summ(result) -> str:
    if not isinstance(result, dict):
        return str(result)[:300]
    return (result.get("summary") or result.get("details") or json.dumps(result, default=str))[:300]


async def _notify(notify, task, proposal, what: str) -> None:
    try:
        await notify(task, proposal, what)
    except Exception:
        logger.exception("Notification failed for task %s", task.id)
