"""Briefs are kept, not just printed.

A brief the user missed is worse than useless if it is gone — the whole point of
holding items back for the morning is that they will be seen then. Keeping them
also makes the evolution §13/01 asks for possible: "learn preferred length" and
"learn preferred structure" need a record of what was produced and what happened
to it, not just what was printed once to a terminal.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base


class AriesBrief(Base):
    """One produced brief."""

    __tablename__ = "aries_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), default="morning", index=True)
    length: Mapped[str] = mapped_column(String(20), default="standard")
    headline: Mapped[str] = mapped_column(String(500), default="")
    sections_json: Mapped[str] = mapped_column(Text, default="[]")
    rendered: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="info")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # Whether the user actually looked at it — the signal "learn preferred
    # length" would eventually need.
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    @property
    def sections(self) -> list[dict]:
        try:
            return list(json.loads(self.sections_json or "[]"))
        except ValueError:
            return []

    def as_dict(self, *, include_rendered: bool = True) -> dict:
        out = {"id": self.id, "kind": self.kind, "length": self.length,
               "headline": self.headline, "severity": self.severity,
               "item_count": self.item_count, "duration_ms": self.duration_ms,
               "seen": self.seen, "sections": self.sections,
               "created_at": self.created_at.isoformat() if self.created_at else None}
        if include_rendered:
            out["rendered"] = self.rendered
        return out
