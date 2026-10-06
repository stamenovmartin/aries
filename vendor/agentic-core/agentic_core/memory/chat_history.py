"""Conversation history — persisted turns so a conversation survives a reload
and gives the assistant multi-turn context. Lifted from
backend/app/services/agent/chat_agent.py (history/record)."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.models import ChatMessage

logger = logging.getLogger(__name__)


async def history(db: AsyncSession, limit: int = 40, *, task_id: int | None = None) -> list[ChatMessage]:
    q = select(ChatMessage).order_by(ChatMessage.id.desc()).limit(limit)
    if task_id is not None:
        q = q.where(ChatMessage.task_id == task_id)
    return list(reversed((await db.execute(q)).scalars().all()))


async def record(db: AsyncSession, role: str, content: str, *, task_id: int | None = None, meta: str | None = None) -> None:
    """Persist one turn. Commits in a savepoint so a failure here can never take
    down the reply it was logging."""
    try:
        async with db.begin_nested():
            db.add(ChatMessage(role=role, content=(content or "")[:8000], task_id=task_id, meta=meta))
        await db.commit()
    except Exception:
        logger.exception("Recording chat message failed")


def as_transcript(rows: list[ChatMessage], *, max_chars: int = 300) -> str:
    return "\n".join(f"[{'user' if h.role == 'user' else 'assistant'}] {h.content[:max_chars]}" for h in rows) or "(start)"
