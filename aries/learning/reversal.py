"""Letting a learned preference be taken back — safely.

Entry 008's loop could only raise a weight or lower one from where it sat. This
module answers the harder question: when the evidence now CONTRADICTS what ARIES
has already concluded, may it change its mind, and how sure must it be?

The answer must be asymmetric. If reversing an established preference were as
easy as forming it, every established preference would be one quiet fortnight
away from being undone, and the user would experience a system whose beliefs
never settle. If reversing were impossible, the first confident conclusion would
be permanent, and a genuine change of interest could never be reflected.

HYSTERESIS
----------
Borrowed from control systems, where the same problem has the same shape: a
thermostat that switched at exactly one temperature would chatter. Continuing in
the direction already established uses the ordinary thresholds. REVERSING one
requires, all at once:

  * a stricter bound          — the interval must clear the threshold by a
                                further `learning.reversal_hysteresis` margin;
  * more observations         — `reversal_min_observations_factor` times as many;
  * agreement over time       — the recent slice and the whole window must BOTH
                                say so, not merely the average of them;
  * repetition                — `reversal_confirmations` consecutive passes must
                                reach the same conclusion before anything moves.

The last is what separates a reversal from a bad fortnight. A pending reversal is
durable state: it is recorded when first suspected, confirmed on later passes,
and ABANDONED the moment the contradiction stops holding. Alternating evidence
therefore never reverses anything — it repeatedly opens a pending reversal and
repeatedly withdraws it, which is visible in the record and costs the user
nothing.

FIVE THINGS THAT LOOK ALIKE
---------------------------
A falling engagement rate has at least five causes, and only one of them is a
reversal:

  NOISE        not decisive even at face value → do nothing
  TEMPORARY    decisive recently, not over the window → wait
  CONTEXTUAL   collapsed for one source, healthy for another → the SOURCE is the
               finding, not the topic; the weight is left alone
  FATIGUE      declining steadily but still positive → decay gently, do not invert
  SUSTAINED    decisive recently AND over the window → a real reversal

Getting this wrong is not a rounding error. Treating CONTEXTUAL as a reversal
throws away a topic the user still cares about because one feed got worse.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

from aries.learning.evidence import TopicEvidence
from aries.learning.statistics import Z_95, wilson

logger = logging.getLogger(__name__)

# Recorded with every decision. When the rules below change, this changes, so a
# stored reversal can always be read against the policy that produced it — §12
# asks for versioned behaviour, and a learned value with no policy version is a
# conclusion nobody can reproduce.
POLICY_VERSION = "reversal-v1"

# The confidence used when REVERSING, at maximum hysteresis. 99.9% — deliberately
# far above the 95% used for ordinary adjustment, so "more sure" has room to mean
# something.
Z_999 = 3.290526731491999

AGREES = "agrees"          # the evidence supports what is already believed
NOISE = "noise"
TEMPORARY = "temporary"
CONTEXTUAL = "contextual"
FATIGUE = "fatigue"
SUSTAINED = "sustained"
NONE = "none"

PENDING, APPLIED, ABANDONED = "pending", "applied", "abandoned"


class AriesReversal(Base):
    """A suspected or applied reversal of a learned preference.

    Durable because a reversal must be CONFIRMED across passes, and because §6 of
    the requirement asks for full provenance: what was believed, what contradicted
    it, how sure, in what window, at what scope, under which policy.
    """

    __tablename__ = "aries_reversals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(200), index=True)
    scope: Mapped[str] = mapped_column(String(120), default="", index=True)
    kind: Mapped[str] = mapped_column(String(40), default="topic_weight")

    established: Mapped[float] = mapped_column(Float)          # what ARIES believed
    proposed: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str] = mapped_column(String(8))          # up | down
    classification: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    window_days: Mapped[int] = mapped_column(Integer, default=30)
    observations: Mapped[int] = mapped_column(Integer, default=0)
    interval_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    reason: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(20), default=PENDING, index=True)
    confirmations: Mapped[int] = mapped_column(Integer, default=1)
    required_confirmations: Mapped[int] = mapped_column(Integer, default=2)
    policy_version: Mapped[str] = mapped_column(String(40), default=POLICY_VERSION)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(),
                                                   onupdate=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def as_dict(self) -> dict:
        return {"id": self.id, "target": self.target, "scope": self.scope or None,
                "kind": self.kind, "established": round(self.established, 3),
                "proposed": None if self.proposed is None else round(self.proposed, 3),
                "direction": self.direction, "classification": self.classification,
                "confidence": round(self.confidence, 3), "window_days": self.window_days,
                "observations": self.observations,
                "interval": json.loads(self.interval_json or "{}"),
                "evidence": json.loads(self.evidence_json or "{}"),
                "reason": self.reason, "status": self.status,
                "confirmations": self.confirmations,
                "required_confirmations": self.required_confirmations,
                "policy_version": self.policy_version,
                "first_seen": self.first_seen_at.isoformat() if self.first_seen_at else None,
                "last_seen": self.last_seen_at.isoformat() if self.last_seen_at else None,
                "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None}


@dataclass
class Verdict:
    """What the evidence says about an established preference."""

    classification: str
    direction: str = "none"
    confidence: float = 0.0
    reason: str = ""
    proposed: float | None = None
    evidence: dict = field(default_factory=dict)

    @property
    def contradicts(self) -> bool:
        return self.classification in (TEMPORARY, CONTEXTUAL, FATIGUE, SUSTAINED)

    @property
    def ordinary(self) -> bool:
        """True when the hysteretic path does not apply and the normal
        thresholds of Entry 008 should decide."""
        return self.classification in (NONE, AGREES)

    def as_dict(self) -> dict:
        return {"classification": self.classification, "direction": self.direction,
                "confidence": round(self.confidence, 3), "reason": self.reason,
                "proposed": None if self.proposed is None else round(self.proposed, 3),
                "evidence": self.evidence}


def _position(learned: float, neutral: float, margin: float) -> str:
    if learned >= neutral + margin:
        return "up"
    if learned <= neutral - margin:
        return "down"
    return "flat"


def classify(ev: TopicEvidence, *, learned: float, neutral: float, cfg: dict) -> Verdict:
    """What kind of contradiction, if any, the evidence presents.

    `learned` is what ARIES currently believes; `neutral` is the value it would
    hold with no opinion. A contradiction is evidence pointing away from the
    established position — not merely evidence that is weak.
    """
    engaged_at = float(cfg["learning.engaged_threshold"])
    ignored_at = float(cfg["learning.ignored_threshold"])
    hysteresis = float(cfg["learning.reversal_hysteresis"])
    min_obs = int(cfg["learning.min_observations"])
    factor = float(cfg["learning.reversal_min_observations_factor"])
    margin = float(cfg["learning.established_margin"])

    position = _position(learned, neutral, margin)
    if position == "flat":
        return Verdict(NONE, reason="no established position to contradict")

    overall, recent = ev.overall.interval, ev.recent.interval

    # HYSTERESIS IS EXPRESSED AS CONFIDENCE, NOT AS A MOVED THRESHOLD.
    #
    # The first attempt tightened the threshold itself (0.10 → 0.06 at a
    # hysteresis of 0.4). That is the wrong currency: because a Wilson bound sits
    # well above the point estimate at realistic sample sizes, it demanded almost
    # literally zero engagement across sixty observations, which no real user
    # would ever produce. The rule was not strict, it was unreachable — and an
    # unreachable rule means reversals never happen, which is the same as not
    # having built them.
    #
    # "Be more certain" is what hysteresis actually means, and a confidence level
    # is where certainty belongs. Reversing evaluates the SAME threshold with a
    # WIDER interval, so it needs more evidence to clear the identical bar.
    z_reverse = Z_95 + (Z_999 - Z_95) * hysteresis
    strong = wilson(ev.engaged, ev.shown, z=z_reverse)

    if position == "up":
        direction = "down"
        # Strength comes from the whole window at the stricter confidence.
        overall_says = strong.upper <= ignored_at
        # The recent slice is a CORROBORATION check, not a second independent
        # test: it is a third of the data, so its interval is far wider and
        # requiring it to clear the bar alone would make the rule unreachable
        # again. It must merely point the same way.
        recent_says = recent.point is not None and recent.point <= ignored_at
        loose_says = overall.upper <= ignored_at
        strict = ignored_at
    else:
        direction = "up"
        overall_says = strong.lower >= engaged_at
        recent_says = recent.point is not None and recent.point >= engaged_at
        loose_says = overall.lower >= engaged_at
        strict = engaged_at

    required_obs = int(min_obs * factor)
    base = {"overall": ev.overall.as_dict(), "recent": ev.recent.as_dict(),
            "trend": ev.trend, "required_observations": required_obs,
            "threshold": round(strict, 3), "position": position,
            "reversal_interval": strong.as_dict(),
            "reversal_confidence_z": round(z_reverse, 3)}

    # ORDER MATTERS, and getting it wrong hid two of the five cases.
    #
    # Contextual collapse and fatigue are DIAGNOSES, not weaker contradictions:
    # neither necessarily looks like a contradiction in the aggregate. A topic
    # read avidly from one source and ignored from another averages out to
    # something unremarkable, and a steady decline from 90% to 25% is still well
    # above the "ignored" line. Both were unreachable while they sat after the
    # "is this even contradictory?" test, because neither ever got that far.
    #
    # So the diagnoses are asked FIRST, and only then the question of whether
    # what remains is strong enough to reverse.

    # 1. Did one source collapse while another held? Then the source changed.
    best, worst = ev.source_spread()
    if best is not None and worst is not None and position == "up":
        healthy = best.interval.lower >= engaged_at
        dead = worst.interval.upper <= ignored_at
        if healthy and dead:
            return Verdict(CONTEXTUAL, direction, confidence=0.6, reason=(
                f"engagement collapsed for '{worst.label}' ({worst.engaged}/{worst.shown}) while "
                f"'{best.label}' held ({best.engaged}/{best.shown}) — the source changed, not "
                f"your interest in '{ev.topic}'"),
                evidence={**base, "best_source": best.as_dict(), "worst_source": worst.as_dict()})

    # 2. Is interest declining steadily rather than gone? Then decay it gently.
    if position == "up" and ev.trend == "monotone_down" and not overall_says:
        step = float(cfg["learning.fatigue_step"])
        rate = overall.point if overall.point is not None else 0.0
        return Verdict(FATIGUE, "down", confidence=0.5, reason=(
            f"interest in '{ev.topic}' is fading rather than gone — engagement has fallen in "
            f"each part of the window but is still {rate:.0%}"),
            proposed=max(0.0, round(learned - step, 3)), evidence=base)

    # 3. Does the evidence still SUPPORT what is believed? Then this is not the
    #    hysteretic path at all; the ordinary thresholds decide.
    supports = (overall.lower >= engaged_at) if position == "up" else (overall.upper <= ignored_at)
    if supports:
        return Verdict(AGREES, position, confidence=0.5, reason=(
            f"the evidence continues to support a '{position}' preference"), evidence=base)

    # 4. Is there a contradiction at all?
    if not (overall_says or recent_says or loose_says):
        return Verdict(NOISE, direction, reason=(
            f"the evidence does not contradict a '{position}' preference — "
            f"the interval is [{overall.lower:.0%}, {overall.upper:.0%}]"), evidence=base)

    # 5. Is there enough of it to reverse something established?
    if ev.shown < required_obs:
        return Verdict(TEMPORARY, direction, confidence=0.3, reason=(
            f"{ev.shown} observations is not enough to reverse an established preference — "
            f"reversing needs {required_obs}"), evidence=base)

    # 6. Does it hold at the higher confidence reversing demands, with the recent
    #    slice agreeing?
    if overall_says and recent_says:
        bound = strong.upper if position == "up" else strong.lower
        conf = min(1.0, 0.5 + abs(strict - bound) / max(0.05, strict) * 0.5)
        return Verdict(SUSTAINED, direction, confidence=conf, reason=(
            f"you engaged with {ev.engaged} of {ev.shown} '{ev.topic}' items over "
            f"{ev.window_days} days, and {ev.recent.engaged} of {ev.recent.shown} recently — "
            f"the whole window clears {strict:.0%} even at the higher confidence reversing "
            f"requires, and the recent slice agrees"),
            evidence=base)

    return Verdict(TEMPORARY, direction, confidence=0.4, reason=(
        "the recent slice and the whole window disagree, so this has not lasted long enough "
        "to be a change of mind"), evidence=base)


# ── the pending-reversal state machine ──────────────────────────────────────

async def observe(db: AsyncSession, target: str, *, scope: str, verdict: Verdict,
                  ev: TopicEvidence, learned: float, required: int,
                  commit: bool = False) -> AriesReversal | None:
    """Record what this pass concluded, and say whether a reversal is now due.

    Returns the row when it has just reached APPLIED, so the caller applies it
    exactly once.
    """
    row = (await db.execute(
        select(AriesReversal).where(AriesReversal.target == target,
                                    AriesReversal.scope == (scope or ""),
                                    AriesReversal.status == PENDING)
        .order_by(AriesReversal.id.desc()).limit(1))).scalar_one_or_none()

    if verdict.classification != SUSTAINED:
        # The contradiction did not hold. A pending reversal is withdrawn, and the
        # withdrawal is recorded — alternating evidence should leave a visible
        # trail of ARIES declining to act, not silence.
        if row is not None:
            row.status = ABANDONED
            row.resolved_at = datetime.utcnow()
            row.reason = (f"withdrawn: {verdict.reason}")[:2000]
            row.classification = verdict.classification
            await db.flush()
            if commit:
                await db.commit()
        return None

    if row is None:
        row = AriesReversal(
            target=target, scope=scope or "", established=learned,
            proposed=verdict.proposed, direction=verdict.direction,
            classification=SUSTAINED, confidence=verdict.confidence,
            window_days=ev.window_days, observations=ev.shown,
            interval_json=json.dumps(ev.overall.interval.as_dict()),
            evidence_json=json.dumps(verdict.evidence, default=str),
            reason=verdict.reason[:2000], status=PENDING, confirmations=1,
            required_confirmations=required, policy_version=POLICY_VERSION)
        db.add(row)
    else:
        row.confirmations += 1
        row.confidence = verdict.confidence
        row.observations = ev.shown
        row.interval_json = json.dumps(ev.overall.interval.as_dict())
        row.evidence_json = json.dumps(verdict.evidence, default=str)
        row.reason = verdict.reason[:2000]
        row.last_seen_at = datetime.utcnow()
    await db.flush()

    if row.confirmations >= row.required_confirmations:
        row.status = APPLIED
        row.resolved_at = datetime.utcnow()
        await db.flush()
        if commit:
            await db.commit()
        return row
    if commit:
        await db.commit()
    return None


async def pending(db: AsyncSession, *, status: str | None = None,
                  limit: int = 50) -> list[AriesReversal]:
    q = select(AriesReversal).order_by(AriesReversal.id.desc())
    if status:
        q = q.where(AriesReversal.status == status)
    return list((await db.execute(q.limit(limit))).scalars().all())


async def rate(db: AsyncSession) -> dict:
    """How often a suspected reversal actually held — the honest form of
    `reversal_rate`: many abandonments mean the evidence is noisy, not that the
    loop is wrong."""
    rows = (await db.execute(
        select(AriesReversal.status, func.count(AriesReversal.id))
        .group_by(AriesReversal.status))).all()
    counts = {s: int(n) for s, n in rows}
    total = sum(counts.values())
    return {"total": total, "by_status": counts,
            "applied_rate": round(counts.get(APPLIED, 0) / total, 3) if total else None,
            "reason": None if total else "no reversals suspected yet",
            "means": "a high abandonment rate means contradictions keep appearing and "
                     "withdrawing — the evidence is unsettled, and nothing was changed"}
