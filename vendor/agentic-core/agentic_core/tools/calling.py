"""The guarded tool call — every gate the marketing publish path runs, in the
order it runs them (backend/app/services/posting/__init__.py::publish_campaign):

  1. the tool exists and the caller holds its permission
  2. the payload validates against the input schema
  3. DRY RUN  — a side-effecting tool is simulated, never executed
  4. LIVE GATE — past dry-run, a side-effecting tool runs only if named in
                 live_tools (credentials are not consent; the list is)
  5. POLICY   — the deterministic policy engine may block or demand approval
  6. APPROVAL — high-risk / requires_approval tools need an approved proposal
  7. IDEMPOTENCY — begin/mark_sent BEFORE the call, record AFTER; a prior
                 'sent' with unknown outcome reconciles rather than re-runs
  8. the call, with timeout; exceptions become a classified failure result
  9. audit + metrics + trace

A refusal is a first-class result in the same shape as a success:
{"success": False, "skipped": True, "details": "<why>", "gate": "<which>"}.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.config import runtime
from agentic_core.observability import audit, metrics
from agentic_core.observability.logging_setup import log_context
from agentic_core.orchestrator import operations
from agentic_core.orchestrator.errors import classify
from agentic_core.security import approvals, policy, principal
from agentic_core.tools import registry
from agentic_core.tools.base import validate_payload

logger = logging.getLogger(__name__)


def _live(name: str) -> bool:
    live = {t.strip().lower() for t in (runtime.get_live_tools() or "").split(",") if t.strip()}
    return bool(live) and (name.lower() in live or "*" in live)


def _refuse(gate: str, why: str) -> dict:
    return {"success": False, "skipped": True, "gate": gate, "details": why}


def _key(name: str, payload: dict, task_id: int | None) -> str:
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]
    return f"tool:{name}:{task_id or 0}:{h}"


async def call_tool(db: AsyncSession, name: str, payload: dict, *, ctx: dict | None = None,
                    task_id: int | None = None, approved_proposal_id: int | None = None,
                    actor: str = "agent") -> dict:
    ctx = dict(ctx or {})
    spec = registry.get(name)
    if spec is None:
        return _refuse("registry", f"no tool named '{name}'")

    # 1. permission (only when a principal is in context — workers run as system)
    p = principal.current()
    if p is not None and not p.can(spec.permission):
        return _refuse("permission", f"role '{p.role.value}' lacks '{spec.permission.value}'")

    # 2. schema
    problems = validate_payload(spec, payload)
    if problems:
        return _refuse("schema", "invalid payload: " + "; ".join(problems))

    with log_context(tool=name, task_id=task_id):
        if spec.side_effect:
            # 3. dry run
            if runtime.get_dry_run():
                await _journal(db, name, payload, "skipped", "[DRY RUN] simulated", task_id)
                return {"success": True, "dry_run": True, "skipped": False,
                        "details": f"[DRY RUN] {name} would run with {json.dumps(payload, default=str)[:300]}"}
            # 4. live gate
            if not _live(name):
                await _journal(db, name, payload, "skipped", "[HELD] not in LIVE_TOOLS", task_id)
                return _refuse("live_gate", f"'{name}' is not in live_tools — held, not executed")
            # 5. policy
            decision = await policy.evaluate(db, {"tool": name, "payload": payload, "risk": spec.risk})
            if not decision.allowed:
                await _journal(db, name, payload, "skipped", f"[POLICY] {decision.summary}", task_id)
                return _refuse("policy", decision.summary)
            # 6. approval
            if spec.requires_approval or decision.requires_approval or spec.risk == "high":
                ok = await _has_approval(db, approved_proposal_id)
                if not ok:
                    prop = await approvals.propose(db, kind="execute_tool", tool=name, task_id=task_id,
                                                   title=f"{name}: {json.dumps(payload, default=str)[:120]}",
                                                   payload=payload, rationale=decision.summary,
                                                   risk=spec.risk, created_by=actor)
                    await db.commit()
                    return {**_refuse("approval", f"'{name}' needs a human's approval (proposal #{prop.id})"),
                            "proposal_id": prop.id, "requires_approval": True}
            # 7. idempotency
            key = _key(name, payload, task_id)
            if not spec.idempotent:
                key = f"{key}:r{await operations.count_for_prefix(db, key)}"
            op, action = await operations.begin(db, key=key, operation_type="tool", task_id=task_id, tool=name,
                                                target_ref=str(payload.get("target") or "")[:120] or None)
            if action == "done":
                await db.commit()
                return operations.recorded_result(op)
            if action == "reconcile":
                await db.commit()
                return {"success": False, "skipped": True, "uncertain": True, "gate": "reconcile",
                        "details": "a prior attempt was sent and its outcome is unknown — reconcile before retrying"}
            await operations.mark_sent(db, op)
            await db.commit()
        else:
            op = None

        # 8. the call
        t0 = time.monotonic()
        try:
            coro = spec.run(payload, ctx)
            result = await (asyncio.wait_for(coro, timeout=spec.timeout_s) if spec.timeout_s else coro)
            if not isinstance(result, dict):
                result = {"success": True, "output": result}
            result.setdefault("success", True)
        except asyncio.TimeoutError:
            # Timed out after the call started: uncertain if it had side effects.
            result = {"success": False, "uncertain": bool(spec.side_effect),
                      "details": f"tool '{name}' timed out after {spec.timeout_s}s"}
        except Exception as e:
            logger.exception("Tool %s raised", name)
            v = classify(str(e))
            result = {"success": False, "details": f"{type(e).__name__}: {e}", "error_class": v.cls.value,
                      "action": v.action}
        ms = int((time.monotonic() - t0) * 1000)
        result["duration_ms"] = ms

        # 9. record
        if op is not None:
            await operations.record(db, op, result)
            if approved_proposal_id and result.get("success"):
                await approvals.mark_executed(db, approved_proposal_id, result=result)
        metrics.record_tool_call(name, bool(result.get("success")))
        if not result.get("success"):
            metrics.record_error(result.get("error_class") or "unknown", where=f"tool:{name}")
        await audit.log_event(db, actor_type="agent" if actor == "agent" else "human", actor=actor,
                              action="tool.executed" if result.get("success") else "tool.failed",
                              entity_type="tool", entity_id=name,
                              detail={"task_id": task_id, "risk": spec.risk, "side_effect": spec.side_effect,
                                      "details": str(result.get("details") or "")[:300], "ms": ms})
        await _journal(db, name, payload, "success" if result.get("success") else "failure",
                       str(result.get("details") or "")[:300], task_id)
        await db.commit()
        return result


async def _has_approval(db, proposal_id: int | None) -> bool:
    if not proposal_id:
        return False
    from agentic_core.database.models import ActionProposal
    p = await db.get(ActionProposal, proposal_id)
    return bool(p and p.status == "approved")


async def _journal(db, name, payload, status, details, task_id):
    from agentic_core.database.models import AutomationLog
    db.add(AutomationLog(action=f"tool.{name}", source=f"task:{task_id}" if task_id else "tools",
                         details=f"{details} :: {json.dumps(payload, default=str)[:200]}", status=status))
