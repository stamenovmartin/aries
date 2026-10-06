"""What the user cares about — §25's Personal Interest Profile, as a table.

Like a source and unlike a setting, an interest is something the user INVENTS at
runtime ("follow LLM agents", "never show me cryptocurrency"), so it is a row
with full CRUD rather than a declaration in code.

The column split is the same one this project has now used three times, because
the same rule keeps applying:

    WHAT THE USER SAID      topic · synonyms · stance · weight ·
                            source preference · notification threshold
    WHAT ARIES OBSERVED     learned_weight · confidence · rationale ·
                            times shown · engaged · dismissed

§25 permits ARIES to learn interest weights from behaviour, and then requires
that "the user must always be able to inspect and override them" and that
"explicit user configuration has higher priority than inferred preferences".
Keeping the two in separate columns is what makes that structural rather than
procedural: `weight` is written only by the user, `learned_weight` only by the
learning loop, and `effective_weight` picks between them in one place, always
the same way. There is no merge step where the rule could quietly be violated.

STANCE, not a negative weight
-----------------------------
"Topics I do not care about" is its own category in §25, and it is modelled as a
stance rather than as weight 0 or a negative number. The user means "not this",
not "this, but less" — an avoided topic disqualifies an item outright, and no
accumulation of positive matches can outvote it. A weight of 0 would merely make
it contribute nothing, which is a different and weaker statement.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

WANT = "want"
AVOID = "avoid"
STANCES = (WANT, AVOID)


class AriesInterest(Base):
    """One topic the user cares about, or has asked never to see."""

    __tablename__ = "aries_interests"
    __table_args__ = (UniqueConstraint("topic", "scope", name="uq_aries_interest"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The canonical spelling, normalised: "llm agents". Synonyms carry the rest.
    topic: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(160), default="")     # as the user typed it
    synonyms_json: Mapped[str] = mapped_column(Text, default="[]")
    stance: Mapped[str] = mapped_column(String(10), default=WANT, index=True)
    scope: Mapped[str] = mapped_column(String(120), default="", index=True)

    # ── what the user said ──────────────────────────────────────────────────
    # None means "the user has not set a weight" — distinct from 0.0, which
    # would mean "they set it to nothing". The learned weight then decides.
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Source ids to prefer for this topic (§25's "source preference").
    preferred_sources_json: Mapped[str] = mapped_column(Text, default="[]")
    # Per-topic override of notifications.minimum_level, when the user wants to
    # hear about one subject more or less urgently than everything else (§25/§26).
    notification_level: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── what ARIES observed ─────────────────────────────────────────────────
    learned_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    learned_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    learned_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    times_shown: Mapped[int] = mapped_column(Integer, default=0)
    times_engaged: Mapped[int] = mapped_column(Integer, default=0)
    times_dismissed: Mapped[int] = mapped_column(Integer, default=0)

    created_by: Mapped[str] = mapped_column(String(120), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # ── derived ─────────────────────────────────────────────────────────────
    @property
    def synonyms(self) -> list[str]:
        try:
            return list(json.loads(self.synonyms_json or "[]"))
        except ValueError:
            return []

    @property
    def preferred_sources(self) -> list[str]:
        try:
            return list(json.loads(self.preferred_sources_json or "[]"))
        except ValueError:
            return []

    @property
    def avoid(self) -> bool:
        return self.stance == AVOID

    def effective_weight(self, default: float) -> float:
        """§25's precedence, in one place: the user first, then what ARIES
        inferred, then the default."""
        if self.weight is not None:
            return self.weight
        if self.learned_weight is not None:
            return self.learned_weight
        return default

    def weight_source(self) -> str:
        if self.weight is not None:
            return "user"
        if self.learned_weight is not None:
            return "learned"
        return "default"

    @property
    def engagement_rate(self) -> float | None:
        """Share of times the user acted on an item matching this topic.

        None until something has actually been shown — a topic nobody has been
        offered yet has an unknown engagement rate, not a rate of zero. The same
        honesty rule as source useful rates and automation success rates.
        """
        return round(self.times_engaged / self.times_shown, 3) if self.times_shown else None

    def as_dict(self, *, default_weight: float = 0.6) -> dict:
        return {
            "topic": self.topic, "label": self.label or self.topic,
            "synonyms": self.synonyms, "stance": self.stance, "scope": self.scope or None,
            "weight": self.effective_weight(default_weight),
            "weight_source": self.weight_source(),
            "user_weight": self.weight,
            "learned": None if self.learned_weight is None else {
                "weight": self.learned_weight, "confidence": self.learned_confidence,
                "rationale": self.learned_rationale,
                "shadowed": self.weight is not None},
            "preferred_sources": self.preferred_sources,
            "notification_level": self.notification_level,
            "engagement": {"shown": self.times_shown, "engaged": self.times_engaged,
                           "dismissed": self.times_dismissed, "rate": self.engagement_rate,
                           "means": "rate is null until items have actually been shown"},
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
