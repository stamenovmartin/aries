"""Structured proposals — the machine's typed request to do one thing, and the
human's decision on it. Lifted from backend/app/services/proposals/__init__.py.

Approving records consent; it does NOT execute. An executor reads approved
proposals and acts, after the policy engine agrees. Old undecided proposals
expire out loud.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.models import ActionProposal, ApprovalRequest
from agentic_core.observability.audit import log_event

EXPIRE_DAYS = 14


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def propose(db: AsyncSession, *, kind: str, title: str | None = None, task_id: int | None = None,
                  run_id: int | None = None, tool: str | None = None, target_ref: str | None = None,
                  payload: dict | None = None, rationale: str | None = None, confidence: float | None = None,
                  evidence: dict | None = None, risk: str = "medium", created_by: str = "agent") -> ActionProposal:
    p = ActionProposal(kind=kind, title=(title or "")[:200] or None, task_id=task_id, run_id=run_id, tool=tool,
                       target_ref=target_ref, payload=json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
                       rationale=rationale, confidence=confidence,
                       evidence=json.dumps(evidence, ensure_ascii=False, default=str) if evidence else None,
                       risk=risk if risk in ("low", "medium", "high") else "medium",
                       created_by=created_by, status="proposed")
    db.add(p)
    await db.flush()
    await log_event(db, actor_type="agent", actor=created_by, action="proposal.created",
                    entity_type="action_proposal", entity_id=p.id,
                    detail={"kind": kind, "title": title, "tool": tool, "risk": p.risk})
    return p


async def _decide(db, proposal_id, decision, *, decided_by, note, channel):
    p = await db.get(ActionProposal, proposal_id)
    if p is None:
        return None
    if p.status != "proposed":
        return p            # the first decision holds
    p.status = "approved" if decision == "approved" else "rejected"
    p.updated_at = _now()
    db.add(ApprovalRequest(proposal_id=proposal_id, channel=channel, decision=p.status,
                           decided_by=decided_by, note=note, decided_at=_now()))
    await log_event(db, actor_type="human", actor=decided_by, action=f"approval.{p.status}",
                    entity_type="action_proposal", entity_id=proposal_id, detail={"channel": channel, "note": note})
    return p


async def approve(db, proposal_id: int, *, decided_by=None, note=None, channel="screen"):
    return await _decide(db, proposal_id, "approved", decided_by=decided_by, note=note, channel=channel)


async def reject(db, proposal_id: int, *, decided_by=None, note=None, channel="screen"):
    return await _decide(db, proposal_id, "rejected", decided_by=decided_by, note=note, channel=channel)


async def mark_executed(db, proposal_id: int, *, result: dict | None = None) -> ActionProposal | None:
    """Only an APPROVED proposal may become executed."""
    p = await db.get(ActionProposal, proposal_id)
    if p is None or p.status != "approved":
        return p
    p.status, p.updated_at = "executed", _now()
    await log_event(db, actor_type="system", action="proposal.executed", entity_type="action_proposal",
                    entity_id=proposal_id, detail={"result": (result or {}).get("details")})
    return p


async def expire_stale(db, *, days: int = EXPIRE_DAYS) -> int:
    cutoff = _now() - timedelta(days=days)
    rows = (await db.execute(select(ActionProposal).where(ActionProposal.status == "proposed",
                                                          ActionProposal.created_at < cutoff))).scalars().all()
    for p in rows:
        p.status, p.updated_at = "expired", _now()
        await log_event(db, actor_type="system", actor="expiry", action="proposal.expired",
                        entity_type="action_proposal", entity_id=p.id, detail={"after_days": days})
    if rows:
        await db.commit()
    return len(rows)


async def list_open(db, limit: int = 50) -> list[ActionProposal]:
    return list((await db.execute(select(ActionProposal).where(ActionProposal.status == "proposed")
                                  .order_by(ActionProposal.id.desc()).limit(limit))).scalars().all())


def serialize(p: ActionProposal) -> dict:
    def _l(raw):
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return raw
    return {"id": p.id, "kind": p.kind, "title": p.title, "task_id": p.task_id, "run_id": p.run_id,
            "tool": p.tool, "target_ref": p.target_ref, "payload": _l(p.payload), "rationale": p.rationale,
            "confidence": p.confidence, "evidence": _l(p.evidence), "risk": p.risk, "status": p.status,
            "created_by": p.created_by, "created_at": p.created_at.isoformat() if p.created_at else None}
