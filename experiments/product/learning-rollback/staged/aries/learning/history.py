"""Remembering what the loop changed, so it can notice when it keeps changing its mind.

`AriesInterest.learned_weight` holds only the CURRENT inference. That is enough
to act and not enough to judge: a weight of 0.6 looks identical whether the loop
arrived there once and stayed, or has been swinging between 0.4 and 0.8 for a
fortnight. The second is a system chasing noise, and from the outside it looks
like a system with opinions that change for no reason — which is precisely the
failure the Wilson intervals of Entry 008 were meant to avoid, surviving in a
slower form.

So every applied change is recorded, and a REVERSAL is a change whose direction
differs from the previous change to the same target: up after down, or down after
up.

WHAT A REVERSAL MEANS
---------------------
Not that a particular change was wrong. It means the evidence for that target is
sitting near a decision threshold, so ordinary variation is enough to tip it
either way — and the loop will keep tipping, forever, because nothing about its
inputs is going to settle.

Two responses, both borrowed from control systems that face the same problem:

  DAMPING     each reversal halves the step this target is allowed to take, so
              an oscillation decays instead of continuing at full amplitude.
              A target that reverses once moves half as far next time, twice a
              quarter as far. Evidence that is genuinely decisive still wins;
              it simply takes longer, which is the correct trade when the
              system has just demonstrated it cannot tell.

  FREEZING    after `learning.max_reversals`, the loop stops adjusting that
              target at all and says so. This is the important half: a system
              that cannot decide should hand the decision back rather than keep
              performing indecision. The user sees "I kept changing my mind
              about 'programming' — you decide", which is both honest and
              actionable.

A frozen target is not a dead one. Setting the weight explicitly, or clearing the
history, releases it — the freeze records that ARIES could not decide, not that
the topic is settled.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

logger = logging.getLogger(__name__)

# How many recent changes per target are considered. Bounded so the analysis is
# about the loop's current behaviour, not its entire history.
LOOKBACK = 8


class AriesLearningChange(Base):
    """One change the loop applied. Append-only."""

    __tablename__ = "aries_learning_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)      # topic_weight | relevance_threshold
    target: Mapped[str] = mapped_column(String(200), index=True)
    scope: Mapped[str] = mapped_column(String(120), default="", index=True)
    previous: Mapped[float] = mapped_column(Float)
    applied: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(8))              # up | down
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    # True when a user value meant the change had no practical effect. Still
    # recorded: the loop changing its mind is the signal, whether or not the
    # change reached the user.
    shadowed: Mapped[bool] = mapped_column(Integer, default=0)
    # Set when this change reversed the previous one for the same target.
    reversal: Mapped[bool] = mapped_column(Integer, default=0, index=True)
    # Which rules produced this. A learned value with no policy version is a
    # conclusion nobody can reproduce later.
    policy_version: Mapped[str] = mapped_column(String(40), default="reversal-v1")
    # The interval the decision was made from, and over what window.
    window_days: Mapped[int] = mapped_column(Integer, default=0)
    interval_json: Mapped[str] = mapped_column(Text, default="{}")
    classification: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    def as_dict(self) -> dict:
        import json
        return {"id": self.id, "kind": self.kind, "target": self.target,
                "scope": self.scope or None,
                "from": round(self.previous, 3), "to": round(self.applied, 3),
                "direction": self.direction, "confidence": round(self.confidence, 3),
                "rationale": self.rationale, "shadowed": bool(self.shadowed),
                "reversal": bool(self.reversal), "classification": self.classification or None,
                "policy_version": self.policy_version, "window_days": self.window_days,
                "interval": json.loads(self.interval_json or "{}"),
                "at": self.created_at.isoformat() if self.created_at else None}


@dataclass
class TargetStability:
    """How settled the loop is about one target."""

    target: str
    changes: int
    reversals: int
    last_direction: str | None
    frozen: bool
    damping: float
    reason: str = ""

    def as_dict(self) -> dict:
        return {"target": self.target, "changes": self.changes, "reversals": self.reversals,
                "last_direction": self.last_direction, "frozen": self.frozen,
                "damping": round(self.damping, 4), "reason": self.reason}


async def record(db: AsyncSession, *, kind: str, target: str, previous: float, applied: float,
                 direction: str, confidence: float, rationale: str, shadowed: bool,
                 scope: str = "", policy_version: str = "reversal-v1", window_days: int = 0,
                 interval: dict | None = None, classification: str = "",
                 commit: bool = False) -> AriesLearningChange:
    """Write one applied change, marking it as a reversal if it turned around."""
    last = await _last(db, target, scope=scope)
    is_reversal = bool(last is not None and last.direction != direction)
    import json as _json
    row = AriesLearningChange(
        kind=kind, target=target, scope=scope or "", previous=previous, applied=applied,
        direction=direction, confidence=confidence, rationale=rationale[:2000],
        shadowed=int(bool(shadowed)), reversal=int(is_reversal),
        policy_version=policy_version, window_days=window_days,
        interval_json=_json.dumps(interval or {}, default=str),
        classification=classification)
    db.add(row)
    await db.flush()
    if is_reversal:
        logger.info("Learning reversed direction on %s (%s after %s)",
                    target, direction, last.direction)
    if commit:
        await db.commit()
    return row


async def epoch_floor(db,target,scope=''):
    from aries.learning.controls import LearningControl
    floor=await db.scalar(select(LearningControl.history_floor).where(
        LearningControl.label==target,LearningControl.scope==(scope or ''))
        .order_by(LearningControl.id.desc()).limit(1))
    return int(floor or 0)


async def _last(db: AsyncSession, target: str, *, scope: str='') -> AriesLearningChange | None:
    floor=await epoch_floor(db,target,scope)
    return (await db.execute(
        select(AriesLearningChange).where(AriesLearningChange.target == target,
            AriesLearningChange.scope==(scope or ''),AriesLearningChange.id>floor)
        .order_by(AriesLearningChange.id.desc()).limit(1))).scalar_one_or_none()


async def history(db: AsyncSession, target: str | None = None, *,
                  limit: int = 50) -> list[AriesLearningChange]:
    q = select(AriesLearningChange).order_by(AriesLearningChange.id.desc())
    if target:
        q = q.where(AriesLearningChange.target == target)
    return list((await db.execute(q.limit(limit))).scalars().all())


async def stability(db: AsyncSession, target: str, *, max_reversals: int = 3,
                    damping_base: float = 0.5, scope: str='') -> TargetStability:
    """How much the loop should trust itself about this target.

    Damping is `damping_base ** reversals`, so the allowed step halves with each
    time the loop turned around. An oscillation decays geometrically rather than
    continuing at full amplitude.
    """
    floor=await epoch_floor(db,target,scope)
    rows = list(reversed((await db.execute(
        select(AriesLearningChange).where(AriesLearningChange.target == target,
            AriesLearningChange.scope==(scope or ''),AriesLearningChange.id>floor)
        .order_by(AriesLearningChange.id.desc()).limit(LOOKBACK))).scalars().all()))
    if not rows:
        return TargetStability(target, 0, 0, None, False, 1.0)

    reversals = sum(1 for r in rows if r.reversal)
    frozen = reversals >= max_reversals
    damping = damping_base ** reversals
    reason = ""
    if frozen:
        reason = (f"changed direction {reversals} times in the last {len(rows)} adjustments — "
                  f"the evidence is not settled, so ARIES has stopped adjusting this and left "
                  f"it to you")
    elif reversals:
        reason = (f"changed direction {reversals} time(s) recently, so changes to this are "
                  f"damped to {damping:.0%} of a full step")
    return TargetStability(target, len(rows), reversals, rows[-1].direction, frozen,
                           damping, reason)


async def all_stability(db: AsyncSession, *, max_reversals: int = 3,
                        damping_base: float = 0.5) -> dict[str, TargetStability]:
    targets = list((await db.execute(
        select(AriesLearningChange.target).distinct())).scalars().all())
    return {t: await stability(db, t, max_reversals=max_reversals, damping_base=damping_base)
            for t in targets}


async def reversal_rate(db: AsyncSession) -> dict:
    """The automation's declared `reversal_rate` metric — how often the loop
    turns around. Honest about having no data."""
    total = (await db.execute(select(func.count(AriesLearningChange.id)))).scalar() or 0
    reversals = (await db.execute(
        select(func.count(AriesLearningChange.id))
        .where(AriesLearningChange.reversal == 1))).scalar() or 0
    return {"changes": total, "reversals": reversals,
            "rate": round(reversals / total, 3) if total else None,
            "reason": None if total else "no changes recorded yet",
            "means": "how often the loop reversed a previous adjustment — high means it is "
                     "chasing noise rather than learning"}


async def release(db: AsyncSession, target: str, *, commit: bool = True) -> int:
    """Forget a target's history, releasing a freeze.

    Deliberately a deletion rather than a flag: the freeze exists because the
    RECORD says the loop was unstable, so releasing it means agreeing to start
    the record over. Anything else would leave a freeze that cannot be undone
    without the reason for it also being false.
    """
    from sqlalchemy import delete
    res = await db.execute(delete(AriesLearningChange).where(AriesLearningChange.target == target))
    if commit:
        await db.commit()
    return res.rowcount or 0
