"""Where sources live. §24's field list, as a table.

Sources are DATA, not declarations. That is the difference between this and the
Settings schema of Entry 002: settings are knobs the system knows about and
declares in code, whereas a source is something the USER invents at runtime —
"follow this feed", "read this folder". So the registry is a table with full
CRUD, not a registry of Python objects, and adding a source never requires a
deploy.

Two groups of columns, and the split is §20's:

  WHAT THE USER SAID     name, type, location, enabled, scope, priority,
                         trust, topics, poll interval, permissions
  WHAT ARIES OBSERVED    last_sync, failures, health, and the counters behind
                         "useful article rate", "duplication rate", "reliability"

§20 allows the observed half to influence ranking over time, but is explicit
that "explicit user source preferences must override learned preferences" — so
the two are stored separately and never merged into one number. `priority` is the
user's word and is never written by anything but the user; `useful_rate` and its
siblings are counted by ARIES and inform ordering only after priority has spoken.
`effective_rank()` in the service is where that ordering is decided, once.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

from aries.sources.types import Priority, Trust

# A source that has failed this many times in a row is reported as failing. Low
# on purpose: three consecutive failures is a broken feed, not bad luck.
FAILING_AFTER = 3


class AriesSource(Base):
    """One place ARIES may get information from."""

    __tablename__ = "aries_sources"
    __table_args__ = (UniqueConstraint("source_id", name="uq_aries_source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # A stable, human-readable slug: "reuters-ai", "docs-research". Used in URLs,
    # in agent prompts and in provenance, so it must survive a rename of `name`.
    source_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(40), index=True)
    # Normalised by safety.check — a resolved absolute path, or the URL as given.
    location: Mapped[str] = mapped_column(Text)
    # Exactly what the user typed, kept so an error message can quote them back.
    location_original: Mapped[str] = mapped_column(Text, default="")

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # "" is global; "project:insomnia" scopes the source to one project.
    scope: Mapped[str] = mapped_column(String(120), default="", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=int(Priority.NORMAL))
    trust: Mapped[int] = mapped_column(Integer, default=int(Trust.NORMAL), index=True)
    topics_json: Mapped[str] = mapped_column(Text, default="[]")
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=120)
    # What ARIES may do with it: read · search · listen. A subset of the type's
    # capabilities, so a user can add a readable source without granting search.
    permissions_json: Mapped[str] = mapped_column(Text, default='["read"]')
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    # ── what ARIES observed ─────────────────────────────────────────────────
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    sync_count: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)

    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_useful: Mapped[int] = mapped_column(Integer, default=0)      # reached the user
    items_duplicate: Mapped[int] = mapped_column(Integer, default=0)   # already had it elsewhere
    engagements: Mapped[int] = mapped_column(Integer, default=0)       # the user acted on it
    corrections: Mapped[int] = mapped_column(Integer, default=0)       # the user said it was wrong

    created_by: Mapped[str] = mapped_column(String(120), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # ── derived ─────────────────────────────────────────────────────────────
    @property
    def topics(self) -> list[str]:
        try:
            return list(json.loads(self.topics_json or "[]"))
        except ValueError:
            return []

    @property
    def permissions(self) -> list[str]:
        try:
            return list(json.loads(self.permissions_json or '["read"]'))
        except ValueError:
            return ["read"]

    @property
    def metadata_dict(self) -> dict:
        try:
            return dict(json.loads(self.metadata_json or "{}"))
        except ValueError:
            return {}

    def rate(self, numerator: int) -> float | None:
        """A rate over items seen, or None when nothing has been seen.

        Honest observability (§13/20): a source that has never been read has an
        *unknown* useful rate, not a useful rate of zero. Reporting 0.0 would
        make a brand-new source look like the worst one in the list, and ranking
        would then bury it before it ever had a chance to prove itself.
        """
        return round(numerator / self.items_seen, 3) if self.items_seen else None

    @property
    def useful_rate(self) -> float | None:
        return self.rate(self.items_useful)

    @property
    def duplicate_rate(self) -> float | None:
        return self.rate(self.items_duplicate)

    @property
    def reliability(self) -> float | None:
        """Share of syncs that succeeded, or None if it has never been synced."""
        total = self.sync_count + self.fail_count
        return round(self.sync_count / total, 3) if total else None

    def health(self, *, now: datetime | None = None) -> dict:
        """What the Sources screen shows in the health column."""
        now = now or datetime.utcnow()
        if not self.enabled:
            return {"state": "disabled", "reason": "turned off by the user"}
        if self.consecutive_failures >= FAILING_AFTER:
            return {"state": "failing",
                    "reason": f"{self.consecutive_failures} consecutive failures — "
                              f"{(self.last_error or 'no reason recorded')[:120]}"}
        if self.consecutive_failures:
            return {"state": "degraded",
                    "reason": f"{self.consecutive_failures} recent failure(s) — "
                              f"{(self.last_error or '')[:120]}"}
        if self.last_sync_at is None:
            return {"state": "unused", "reason": "never read yet"}
        overdue = now - self.last_sync_at > timedelta(minutes=self.poll_interval_minutes * 3)
        if overdue:
            return {"state": "stale",
                    "reason": f"last read {(now - self.last_sync_at).total_seconds() / 3600:.1f}h ago, "
                              f"expected every {self.poll_interval_minutes} min"}
        return {"state": "ok", "reason": None}

    def as_dict(self, *, now: datetime | None = None) -> dict:
        return {
            "source_id": self.source_id, "name": self.name, "type": self.type,
            "location": self.location, "location_original": self.location_original or self.location,
            "enabled": self.enabled, "scope": self.scope or None,
            "priority": Priority(self.priority).label, "trust": Trust(self.trust).label,
            "topics": self.topics, "permissions": self.permissions,
            "poll_interval_minutes": self.poll_interval_minutes,
            "metadata": self.metadata_dict,
            "last_sync": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "last_ok": self.last_ok_at.isoformat() if self.last_ok_at else None,
            "last_error": self.last_error,
            "health": self.health(now=now),
            "performance": {
                "items_seen": self.items_seen, "items_useful": self.items_useful,
                "items_duplicate": self.items_duplicate, "engagements": self.engagements,
                "corrections": self.corrections,
                "useful_rate": self.useful_rate, "duplicate_rate": self.duplicate_rate,
                "reliability": self.reliability,
                "syncs": self.sync_count, "failures": self.fail_count,
                "means": "rates are null until the source has actually been read — a new "
                         "source is unproven, not bad",
            },
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
