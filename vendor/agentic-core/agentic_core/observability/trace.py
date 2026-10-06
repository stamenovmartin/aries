"""Which agent contributed what, for one task run.
Lifted from backend/app/services/agent/trace.py (AutomationLog notes) and
merged with the formal AgentStep row (confidence + evidence) the spec asks for.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.models import AgentStep, TaskRun

logger = logging.getLogger(__name__)


async def record(db: AsyncSession, run_id: int, agent: str, *, summary: str,
                 detail=None, ok: bool = True, confidence: float | None = None,
                 evidence=None, label: str | None = None, duration_ms: int | None = None) -> None:
    """Note one agent's contribution. Never raises."""
    try:
        db.add(AgentStep(run_id=run_id, agent=agent, label=label or agent,
                         summary=(summary or "")[:2000],
                         output=json.dumps(detail, ensure_ascii=False, default=str)[:20000] if detail is not None else None,
                         confidence=confidence,
                         evidence=json.dumps(evidence, ensure_ascii=False, default=str)[:20000] if evidence is not None else None,
                         ok=ok, duration_ms=duration_ms))
    except Exception:
        logger.exception("Could not record the %s step", agent)


async def for_run(db: AsyncSession, run_id: int) -> list[dict]:
    rows = (await db.execute(select(AgentStep).where(AgentStep.run_id == run_id)
                             .order_by(AgentStep.id))).scalars().all()
    out = []
    for r in rows:
        out.append({"agent": r.agent, "label": r.label, "summary": r.summary, "ok": r.ok,
                    "confidence": r.confidence, "duration_ms": r.duration_ms,
                    "output": _loads(r.output), "evidence": _loads(r.evidence),
                    "at": r.at.isoformat() if r.at else None})
    return out


async def for_task(db: AsyncSession, task_id: int) -> list[dict]:
    runs = (await db.execute(select(TaskRun).where(TaskRun.task_id == task_id)
                             .order_by(TaskRun.id))).scalars().all()
    return [{"run_id": r.id, "trigger": r.trigger, "status": r.status, "verdict": r.verdict,
             "decisions": _loads(r.decisions), "evaluation": _loads(r.evaluation),
             "steps": await for_run(db, r.id)} for r in runs]


def _loads(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw
