"""What ARIES saw, what it thought of it, and whether it said anything.

Every item is stored, including the ones judged irrelevant and the ones
suppressed as duplicates. That is deliberate and it is what §29 requires: the
user must be able to ask "why didn't you show me this?" and get an answer. An
item ARIES discarded silently is an item nobody can audit.

It is also what makes the learning loop possible. "Shown and ignored" and "never
shown" are completely different signals about a topic's weight, and a table that
only keeps what was delivered cannot tell them apart.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base


def fingerprint(*parts: str) -> str:
    """A stable id for an item. Used for 'have I seen this before?', so it must
    depend only on the item's identity, never on when it was fetched."""
    joined = "\x1f".join((p or "").strip().lower() for p in parts)
    return hashlib.sha256(joined.encode("utf-8", errors="replace")).hexdigest()[:32]


class AriesNewsItem(Base):
    """One item from one source, with the judgement ARIES made about it."""

    __tablename__ = "aries_news_items"
    __table_args__ = (UniqueConstraint("item_id", name="uq_aries_news_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[str] = mapped_column(String(120), index=True)

    title: Mapped[str] = mapped_column(String(500))
    link: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # ── the judgement ───────────────────────────────────────────────────────
    relevance: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    matched_json: Mapped[str] = mapped_column(Text, default="[]")
    excluded_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")

    # Items telling the same story share a cluster; one of them is the
    # representative and the rest are duplicates of it.
    cluster_id: Mapped[str] = mapped_column(String(40), index=True, default="")
    is_representative: Mapped[bool] = mapped_column(Boolean, default=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ── what happened to it ─────────────────────────────────────────────────
    # delivered | held | below_threshold | excluded | duplicate
    disposition: Mapped[str] = mapped_column(String(30), default="", index=True)
    engaged: Mapped[bool] = mapped_column(Boolean, default=False)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    @property
    def matched(self) -> list[dict]:
        try:
            return list(json.loads(self.matched_json or "[]"))
        except ValueError:
            return []

    @property
    def topics(self) -> list[str]:
        return [m.get("topic", "") for m in self.matched if m.get("topic")]

    def as_dict(self) -> dict:
        return {"item_id": self.item_id, "source_id": self.source_id, "title": self.title,
                "link": self.link, "summary": self.summary[:600], "author": self.author,
                "published": self.published_at.isoformat() if self.published_at else None,
                "relevance": round(self.relevance, 3), "topics": self.topics,
                "matched": self.matched, "excluded_by": self.excluded_by,
                "explanation": self.explanation, "cluster_id": self.cluster_id,
                "is_representative": self.is_representative, "duplicate_of": self.duplicate_of,
                "disposition": self.disposition, "engaged": self.engaged,
                "dismissed": self.dismissed,
                "first_seen": self.first_seen_at.isoformat() if self.first_seen_at else None}
