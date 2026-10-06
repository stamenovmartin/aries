"""Durable, idempotent external operations. Lifted from
backend/app/execution/operations.py.

`begin` answers one of three things for an idempotency key:
  execute   — new, or a prior attempt failed retriably: go.
  done      — already SUCCEEDED: never send again, return the recorded result.
  reconcile — a prior attempt was sent and its outcome is unknown: never
              blind-retry; reconcile first.
`mark_sent` is persisted BEFORE the call leaves the machine.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.models import ExecutionOperation
from agentic_core.orchestrator.errors import ErrorClass, classify

logger = logging.getLogger(__name__)


async def begin(db: AsyncSession, *, key: str, operation_type: str,
                task_id: int | None = None, tool: str | None = None,
                target_ref: str | None = None) -> tuple[ExecutionOperation, str]:
    op = (await db.execute(select(ExecutionOperation)
          .where(ExecutionOperation.idempotency_key == key))).scalars().first()
    if op is None:
        op = ExecutionOperation(idempotency_key=key, operation_type=operation_type,
                                task_id=task_id, tool=tool, target_ref=target_ref,
                                state="pending")
        db.add(op)
        await db.flush()
        return op, "execute"
    if op.state == "succeeded":
        return op, "done"
    if op.state in ("sent", "uncertain"):
        return op, "reconcile"
    return op, "execute"


async def count_for_prefix(db: AsyncSession, prefix: str) -> int:
    """Make a deliberate re-run a NEW operation instead of colliding with the first."""
    return int((await db.execute(
        select(func.count()).select_from(ExecutionOperation)
        .where(ExecutionOperation.idempotency_key.like(f"{prefix}%")))).scalar() or 0)


async def mark_sent(db: AsyncSession, op: ExecutionOperation) -> None:
    op.state = "sent"
    op.attempts = (op.attempts or 0) + 1


async def record(db: AsyncSession, op: ExecutionOperation, result: dict) -> None:
    """Map a tool result dict {success, uncertain?, skipped?, details, external_id?}
    to a terminal state. A genuine failure is classified so the state itself
    says whether a retry is safe."""
    if result.get("success"):
        op.state = "succeeded"
        op.external_id = result.get("external_id")
        op.external_url = result.get("external_url")
        op.last_error = None
        op.error_class = None
    elif result.get("uncertain"):
        op.state = "uncertain"
        op.last_error = (result.get("details") or "")[:2000]
        op.error_class = ErrorClass.UNCERTAIN.value
    elif result.get("skipped"):
        op.state = "skipped"
        op.last_error = (result.get("details") or "")[:2000]
    else:
        v = classify(result.get("details") or "", sent=True, got_response=True)
        op.state = "uncertain" if v.cls is ErrorClass.UNCERTAIN else "failed"
        op.error_class = v.cls.value
        op.last_error = (result.get("details") or "")[:2000]


def recorded_result(op: ExecutionOperation) -> dict:
    return {"success": True, "external_id": op.external_id,
            "external_url": op.external_url, "skipped": False,
            "details": "Already done (idempotent — not executed again)."}
