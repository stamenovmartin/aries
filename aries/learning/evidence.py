"""Evidence, sliced finely enough to tell five different things apart.

Entry 008's `gather()` produced one number per topic: how many items were shown
and how many were opened. That is enough to decide whether a preference should
rise, and not nearly enough to decide whether an ESTABLISHED preference should be
reversed — because five very different situations produce the same overall rate:

    NOISE        a few contradictory observations in an otherwise steady record
    TEMPORARY    a real dip that has not lasted
    SUSTAINED    a genuine change of mind, holding across the whole window
    CONTEXTUAL   engagement collapsed for one source but not the others
    FATIGUE      steadily declining interest rather than a switch flipping

Reversing on the first two is how a system becomes unreliable. Refusing to
reverse on the third is how it becomes stubborn. Treating the fourth as a topic
change loses the actual finding — it is the *source* that stopped being useful.
Treating the fifth as a reversal overshoots, because interest is decaying and not
inverted.

So evidence is sliced three ways:

  * the WHOLE window, which says what is true overall;
  * the RECENT slice (the most recent third), which says what is true now;
  * per SOURCE and per time BUCKET, which say whether "overall" is uniform.

Each slice carries a Wilson interval rather than a rate, for the reason Entry 008
gives: a rate computed from four observations is not a rate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aries.learning.statistics import Interval, wilson
from aries.news.models import AriesNewsItem

# Number of equal time buckets the window is divided into for trend detection.
# Four is enough to see a monotone decline and few enough that each bucket holds
# a usable number of observations.
BUCKETS = 4


@dataclass
class Slice:
    """One subset of the evidence for a topic."""

    label: str
    shown: int = 0
    engaged: int = 0
    dismissed: int = 0

    @property
    def interval(self) -> Interval:
        return wilson(self.engaged, self.shown)

    @property
    def rate(self) -> float | None:
        return self.engaged / self.shown if self.shown else None

    def as_dict(self) -> dict:
        return {"label": self.label, "shown": self.shown, "engaged": self.engaged,
                "dismissed": self.dismissed, **self.interval.as_dict()}


@dataclass
class TopicEvidence:
    """Everything known about one topic in one window."""

    topic: str
    window_days: int
    overall: Slice
    recent: Slice
    by_source: dict[str, Slice] = field(default_factory=dict)
    buckets: list[Slice] = field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    source_digest: str = ''

    # ── shorthands the rest of the code reads ───────────────────────────────
    @property
    def shown(self) -> int:
        return self.overall.shown

    @property
    def engaged(self) -> int:
        return self.overall.engaged

    @property
    def dismissed(self) -> int:
        return self.overall.dismissed

    @property
    def interval(self) -> Interval:
        return self.overall.interval

    @property
    def trend(self) -> str:
        """monotone_down | monotone_up | flat | mixed, over the populated buckets.

        Only buckets with observations count: an empty bucket means the user saw
        nothing that week, which says nothing about their interest.
        """
        rates = [b.rate for b in self.buckets if b.shown >= 3 and b.rate is not None]
        if len(rates) < 3:
            return "insufficient"
        downs = sum(1 for a, b in zip(rates, rates[1:]) if b < a - 0.05)
        ups = sum(1 for a, b in zip(rates, rates[1:]) if b > a + 0.05)
        if downs and not ups:
            return "monotone_down"
        if ups and not downs:
            return "monotone_up"
        if not ups and not downs:
            return "flat"
        return "mixed"

    def source_spread(self) -> tuple[Slice | None, Slice | None]:
        """The best and worst source, among those with enough observations.

        A wide gap is what distinguishes "this topic stopped being interesting"
        from "one source started producing rubbish about this topic".
        """
        usable = [s for s in self.by_source.values() if s.shown >= 4]
        if len(usable) < 2:
            return None, None
        ordered = sorted(usable, key=lambda s: s.rate or 0.0)
        return ordered[-1], ordered[0]

    def as_dict(self) -> dict:
        best, worst = self.source_spread()
        return {"topic": self.topic, "window_days": self.window_days, "source_digest":self.source_digest,
                "overall": self.overall.as_dict(), "recent": self.recent.as_dict(),
                "trend": self.trend,
                "buckets": [b.as_dict() for b in self.buckets],
                "by_source": {k: v.as_dict() for k, v in self.by_source.items()},
                "best_source": best.as_dict() if best else None,
                "worst_source": worst.as_dict() if worst else None,
                "first_seen": self.first_seen.isoformat() if self.first_seen else None,
                "last_seen": self.last_seen.isoformat() if self.last_seen else None}


async def gather(db: AsyncSession, *, window_days: int = 30,
                 recent_fraction: float = 1 / 3) -> dict[str, TopicEvidence]:
    """Evidence per topic, sliced by time and by source.

    Only items the user had the OPPORTUNITY to see — `delivered` and `held`.
    Items below the threshold stay excluded, for the circularity reason in
    `loop.py`: counting them as "not engaged" would let the system confirm its
    own guesses.
    """
    now = datetime.utcnow()
    start = now - timedelta(days=window_days)
    recent_start = now - timedelta(days=max(1.0, window_days * recent_fraction))
    span = max(timedelta(seconds=1), now - start)

    rows = (await db.execute(
        select(AriesNewsItem).where(
            AriesNewsItem.disposition.in_(("delivered", "held")),
            AriesNewsItem.first_seen_at >= start)
    )).scalars().all()

    out: dict[str, TopicEvidence] = {}
    identities: dict[str,list] = {}
    for row in rows:
        seen_at = row.first_seen_at or now
        idx = min(BUCKETS - 1, int((seen_at - start) / span * BUCKETS))
        for topic in row.topics:
            identities.setdefault(topic,[]).append((row.item_id,row.source_id,row.disposition,
                bool(row.engaged),bool(row.dismissed),seen_at.isoformat()))
            ev = out.get(topic)
            if ev is None:
                ev = out[topic] = TopicEvidence(
                    topic=topic, window_days=window_days,
                    overall=Slice("overall"), recent=Slice("recent"),
                    buckets=[Slice(f"bucket{i}") for i in range(BUCKETS)])
            for target in (ev.overall, ev.buckets[idx],
                           *( (ev.recent,) if seen_at >= recent_start else () ),
                           ev.by_source.setdefault(row.source_id, Slice(row.source_id))):
                target.shown += 1
                if row.engaged:
                    target.engaged += 1
                if row.dismissed:
                    target.dismissed += 1
            ev.first_seen = min(ev.first_seen or seen_at, seen_at)
            ev.last_seen = max(ev.last_seen or seen_at, seen_at)
    for topic,ev in out.items():
        ev.source_digest=hashlib.sha256(json.dumps(sorted(identities[topic]),ensure_ascii=False).encode()).hexdigest()
    return out
