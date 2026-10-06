"""The medium learning loop — §16.

    task outcomes → evaluate → adjust preferences

Runs over days, not seconds. It reads what actually happened to the items ARIES
delivered, and adjusts two things: how much each topic is worth, and how high the
relevance bar should be.

FOUR RULES IT CANNOT BREAK
--------------------------
1. **It proposes into the learned layer, never the user's.** `interests.learn()`
   and `SettingsService.learn()` physically cannot write a user value. If the
   user has set a weight, the inference is stored, reported as shadowed, and has
   no effect until they clear theirs. This is the same guarantee as Entries 002,
   005 and 006, and this is the component it was built for.

2. **It may weigh topics; it may not invent them.** `learn()` refuses an unknown
   topic. Deciding *what* the user follows is theirs.

3. **It acts on intervals, not rates.** One click out of three is not a 33%
   engagement rate, it is no evidence — see `statistics.py`.

4. **It moves slowly and it can be watched.** Every change is capped per run,
   carries a written rationale, and can be proposed without being applied
   (`learning.apply_changes`), which is §18's observe → measure → propose shape
   in the small.

WHY EVIDENCE COMES FROM THE ITEMS, NOT FROM COUNTERS
----------------------------------------------------
`AriesInterest` carries `times_shown`/`times_engaged` counters, and it would be
convenient to read those. They are a SUMMARY, maintained by several writers, and
a summary that drifts from the facts produces learning that cannot be explained
afterwards. `aries_news_items` holds one durable row per item with its topics and
what became of it, so evidence is recomputed from the record every time. The
counters stay for display; the loop trusts the rows.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aries.interests import service as interests
from aries.learning import history, reversal
from aries.learning.evidence import TopicEvidence, gather
from aries.learning.statistics import Interval, step_toward, wilson
from aries.news.models import AriesNewsItem
from aries.settings import SettingsService

logger = logging.getLogger(__name__)


@dataclass
class Proposal:
    """One change the loop believes the evidence supports."""

    kind: str                    # "topic_weight" | "relevance_threshold"
    target: str                  # the topic, or the settings key
    current: float
    proposed: float
    direction: str               # "up" | "down"
    confidence: float
    rationale: str
    evidence: dict = field(default_factory=dict)
    applied: bool = False
    shadowed: bool = False
    note: str | None = None
    damping: float = 1.0                     # how much this target's step was reduced
    reversals: int = 0                       # times the loop has turned around on it
    scope: str = ""
    classification: str = "ordinary"         # ordinary | fatigue | sustained
    window_days: int = 0
    interval: dict = field(default_factory=dict)
    reversal_id: int | None = None
    control_epoch: int = 0

    def as_dict(self) -> dict:
        return {"kind": self.kind, "target": self.target,
                "current": round(self.current, 3), "proposed": round(self.proposed, 3),
                "direction": self.direction, "confidence": round(self.confidence, 3),
                "rationale": self.rationale, "evidence": self.evidence,
                "applied": self.applied, "shadowed": self.shadowed, "note": self.note,
                "damping": round(self.damping, 4), "reversals": self.reversals,
                "scope": self.scope or None, "classification": self.classification,
                "window_days": self.window_days, "interval": self.interval,
                "reversal_id": self.reversal_id,"control_epoch":self.control_epoch}




async def propose(db: AsyncSession, *, now: datetime | None = None) -> list[Proposal]:
    """What the evidence supports. Writes only the pending-reversal state.

    TWO PATHS, and which one applies is decided by whether there is an
    established position to contradict:

      ORDINARY    no settled learned value, or evidence that agrees with it —
                  the thresholds of Entry 008 decide, and a change is a nudge.
      HYSTERETIC  evidence pointing AWAY from a settled value — the stricter
                  rules of `reversal.py` decide, and most outcomes are "not yet".

    A target may be in only one of them per pass. Running both would let a
    contradiction be refused by the hysteretic path and then applied anyway by
    the ordinary one, which is the failure the hysteresis exists to prevent.
    """
    from aries.learning.controls import LearningControl
    from sqlalchemy import func
    control_epoch=int(await db.scalar(select(func.max(LearningControl.id))) or 0)
    s = SettingsService(db)
    cfg = await s.section("learning")
    min_obs = int(cfg["learning.min_observations"])
    engaged_target = float(cfg["learning.engaged_threshold"])
    ignored_target = float(cfg["learning.ignored_threshold"])
    max_step = float(cfg["learning.max_step"])
    window = int(cfg["learning.window_days"])
    max_reversals = int(cfg["learning.max_reversals"])
    damping_base = float(cfg["learning.damping"])
    required_confirmations = int(cfg["learning.reversal_confirmations"])
    neutral = float(await s.get("interests.default_weight"))

    stability = await history.all_stability(db, max_reversals=max_reversals,
                                            damping_base=damping_base)
    evidence = await gather(db, window_days=window)

    proposals: list[Proposal] = []
    frozen: list[dict] = []
    verdicts: list[dict] = []

    for topic, ev in sorted(evidence.items()):
        row = await interests.get(db, topic)
        if row is None:
            continue                        # rule 2: learning does not invent topics

        # Oscillation guard, before anything else: a target the loop keeps
        # turning around on is handed back to the user rather than argued about.
        stab = stability.get(topic)
        if stab is not None and stab.frozen:
            frozen.append({"target": topic, **stab.as_dict()})
            continue

        # Two different values, and conflating them was a real error.
        #
        #   `established`  what ARIES has CONCLUDED. Hysteresis protects this and
        #                  only this: a reversal is ARIES changing its own mind.
        #                  When nothing has been learned there is no established
        #                  position, so the ordinary path applies.
        #   `base`         where a step starts from. The user's value is a
        #                  reasonable prior for ARIES's first opinion, so it is
        #                  used when nothing has been learned yet.
        #
        # Taking the user's weight as the established position would have meant
        # ARIES applying the stricter reversal rules to a preference it never
        # formed — protecting a value that was never its to change, and refusing
        # to learn anything about topics the user had configured.
        established = row.learned_weight
        base = established if established is not None else row.effective_weight(neutral)
        verdict = (reversal.classify(ev, learned=established, neutral=neutral, cfg=cfg)
                   if established is not None
                   else reversal.Verdict(reversal.NONE,
                                         reason="ARIES has formed no opinion here yet"))
        verdicts.append({"target": topic, "scope": row.scope or None, **verdict.as_dict()})

        # ── the hysteretic path ────────────────────────────────────────────
        # observe() is called for EVERY established target, not only for the
        # contradicting ones. A pending reversal has to be withdrawn the moment
        # the contradiction stops holding — and when the user starts engaging
        # again the verdict becomes NOISE or AGREES, which used to route past
        # this call entirely and leave a stale pending reversal that would be
        # confirmed by the next genuine dip. Alternating evidence would then have
        # reversed after all, which is the exact failure the confirmations exist
        # to prevent.
        applied = None
        if established is not None:
            applied = await reversal.observe(
                db, topic, scope=row.scope or "", verdict=verdict, ev=ev,
                learned=established, required=required_confirmations)

        if verdict.contradicts:

            if verdict.classification == reversal.FATIGUE and verdict.proposed is not None:
                if abs(verdict.proposed - base) >= 0.005:
                    proposals.append(Proposal(
                        kind="topic_weight", target=topic, current=base,
                        proposed=verdict.proposed, direction="down",
                        confidence=verdict.confidence, rationale=verdict.reason,
                        evidence=verdict.evidence, scope=row.scope or "",
                        classification=reversal.FATIGUE, window_days=window,
                        interval=ev.overall.interval.as_dict()))
                continue

            if applied is not None:
                # Confirmed often enough to act. The reversal moves toward the
                # opposite extreme, still bounded by max_step and damping — a
                # reversal is permission to change direction, not to leap.
                damping = stab.damping if stab is not None else 1.0
                target_value = 0.0 if verdict.direction == "down" else 1.0
                proposed = step_toward(base, target_value,
                                       confidence=verdict.confidence,
                                       max_step=max_step * damping)
                if abs(proposed - base) >= 0.005:
                    proposals.append(Proposal(
                        kind="topic_weight", target=topic, current=base,
                        proposed=proposed, direction=verdict.direction,
                        confidence=verdict.confidence,
                        rationale=(f"REVERSAL after {applied.confirmations} consecutive passes: "
                                   f"{verdict.reason}"),
                        evidence=verdict.evidence, scope=row.scope or "",
                        classification=reversal.SUSTAINED, window_days=window,
                        interval=ev.overall.interval.as_dict(), damping=damping,
                        reversals=stab.reversals if stab is not None else 0,
                        reversal_id=applied.id))
            continue

        # ── the ordinary path ──────────────────────────────────────────────
        if ev.shown < min_obs:
            continue
        interval = ev.overall.interval
        if interval.lower >= engaged_target:
            target_value, direction = 1.0, "up"
            confidence = min(1.0, (interval.lower - engaged_target)
                             / max(0.01, 1 - engaged_target))
            reason = (f"you opened {ev.engaged} of {ev.shown} items about '{topic}' — even at the "
                      f"pessimistic end of the interval that is {interval.lower:.0%}, above the "
                      f"{engaged_target:.0%} mark")
        elif interval.upper <= ignored_target:
            target_value, direction = 0.0, "down"
            confidence = min(1.0, (ignored_target - interval.upper) / max(0.01, ignored_target))
            reason = (f"you opened {ev.engaged} of {ev.shown} items about '{topic}' — even at the "
                      f"optimistic end that is {interval.upper:.0%}, below the "
                      f"{ignored_target:.0%} mark")
        else:
            continue                        # the interval is not decisive

        damping = stab.damping if stab is not None else 1.0
        proposed = step_toward(base, target_value, confidence=confidence,
                               max_step=max_step * damping)
        if abs(proposed - base) < 0.005:
            continue
        if damping < 1.0:
            reason += (f"; damped to {damping:.0%} of a full step after "
                       f"{stab.reversals} reversal(s)")
        proposals.append(Proposal(
            kind="topic_weight", target=topic, current=base, proposed=proposed,
            direction=direction, confidence=confidence, rationale=reason,
            evidence=ev.as_dict(), scope=row.scope or "", classification="ordinary",
            window_days=window, interval=interval.as_dict(), damping=damping,
            reversals=stab.reversals if stab is not None else 0))

    threshold = await _propose_threshold(db, evidence, cfg)
    if threshold is not None:
        t_stab = stability.get(threshold.target)
        if t_stab is not None and t_stab.frozen:
            frozen.append({"target": threshold.target, **t_stab.as_dict()})
        else:
            proposals.append(threshold)

    import hashlib,json
    for proposal in proposals:
        proposal.control_epoch=control_epoch
        if proposal.kind=='topic_weight':
            proposal.evidence['source_digest']=evidence[proposal.target].source_digest
        else:
            proposal.evidence['source_digest']=hashlib.sha256(json.dumps(
                sorted((topic,ev.source_digest) for topic,ev in evidence.items())).encode()).hexdigest()
    _CONTEXT[id(proposals)] = {"frozen": frozen, "verdicts": verdicts}
    return proposals


# Context computed during the last `propose` call, keyed by the list it returned.
# A list cannot carry attributes and threading a second return value through
# every caller would be worse than this small map.
_CONTEXT: dict[int, dict] = {}


def frozen_for(proposals: list) -> list[dict]:
    return _CONTEXT.get(id(proposals), {}).get("frozen", [])


def verdicts_for(proposals: list) -> list[dict]:
    return _CONTEXT.get(id(proposals), {}).get("verdicts", [])


async def _propose_threshold(db: AsyncSession, evidence: dict[str, TopicEvidence],
                             cfg: dict) -> Proposal | None:
    """Raise the relevance bar when delivered items are being dismissed.

    Only ever UPWARD. Lowering it would mean showing more, on the basis of
    evidence about things the user never saw — the circular reasoning `gather`
    avoids. If the bar is too high, the user lowers it themselves; the system
    only offers to be quieter, never to be louder.
    """
    s = SettingsService(db)
    shown = sum(e.shown for e in evidence.values())
    dismissed = sum(e.dismissed for e in evidence.values())
    if shown < int(cfg["learning.min_observations"]) * 2:
        return None
    interval = wilson(dismissed, shown)
    noisy_at = float(cfg["learning.noisy_threshold"])
    if interval.lower < noisy_at:
        return None
    current = float(await s.get("news.relevance_threshold"))
    proposed = min(0.95, round(current + float(cfg["learning.max_step"]) / 2, 3))
    if proposed <= current:
        return None
    return Proposal(
        kind="relevance_threshold", target="news.relevance_threshold",
        current=current, proposed=proposed, direction="up",
        confidence=min(1.0, interval.lower),
        rationale=(f"you dismissed {dismissed} of {shown} delivered items — at least "
                   f"{interval.lower:.0%} are unwanted, so the bar is too low"),
        evidence={"shown": shown, "dismissed": dismissed, **interval.as_dict()})


async def apply(db: AsyncSession, proposals: list[Proposal], *, commit: bool = True) -> list[Proposal]:
    """Write the proposals into the LEARNED layer. Never the user's."""
    from aries.learning.evidence_use import EvidenceUse
    from aries.learning.controls import LearningControl
    from sqlalchemy import select,func
    from sqlalchemy.exc import IntegrityError
    s = SettingsService(db)
    for p in proposals:
        p.applied=False
        digest=p.evidence.get('source_digest','')
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            p.note='not applied: source evidence identity is missing'
            continue
        used=await db.scalar(select(EvidenceUse.id).where(EvidenceUse.kind==p.kind,
            EvidenceUse.target==p.target,EvidenceUse.scope==p.scope,EvidenceUse.digest==digest))
        if used:
            p.note='not applied: this exact evidence was already used'
            continue
        try:
            # Receipt, value and history succeed or roll back together. The
            # unique receipt also arbitrates two concurrent copies of a pass.
            async with db.begin_nested():
                db.add(EvidenceUse(kind=p.kind,target=p.target,scope=p.scope,digest=digest))
                await db.flush()
                if int(await db.scalar(select(func.max(LearningControl.id))) or 0)!=p.control_epoch:
                    raise ValueError('Manual learning control changed since proposal')
                if p.kind == "topic_weight":
                    current=await interests.get(db,p.target,scope=p.scope)
                    if current is None:raise ValueError('Topic no longer exists')
                    await db.refresh(current)
                    neutral=float(await s.get('interests.default_weight'))
                    value=current.learned_weight if current.learned_weight is not None else current.effective_weight(neutral)
                    if abs(value-p.current)>1e-9:raise ValueError('Learned value changed since proposal')
                    out = await interests.learn(db, p.target, p.proposed, scope=p.scope, confidence=p.confidence,
                                                rationale=p.rationale, commit=False)
                elif p.kind == "relevance_threshold":
                    scoped=SettingsService(db,scope=p.scope or None)
                    if abs(float(await scoped.get(p.target))-p.current)>1e-9:
                        raise ValueError('Setting changed since proposal')
                    out = await scoped.learn(p.target, p.proposed, confidence=p.confidence,
                                        rationale=p.rationale, scope=p.scope, set_by="learning", commit=False)
                else:
                    raise ValueError('Unknown learning proposal kind')
                p.shadowed = bool(out.get("shadowed"))
                p.note = out.get("note")
                change = await history.record(
                    db, kind=p.kind, target=p.target, previous=p.current, applied=p.proposed,
                    direction=p.direction, confidence=p.confidence, rationale=p.rationale,
                    shadowed=p.shadowed, scope=p.scope, policy_version=reversal.POLICY_VERSION,
                    window_days=p.window_days, interval=p.interval,
                    classification=p.classification)
                if change.reversal:
                    p.note = ((p.note + " ") if p.note else "") + "this reversed the previous change"
            p.applied = True
        except IntegrityError:
            p.note='not applied: a concurrent pass already consumed this evidence'
        except Exception as e:
            logger.exception("Could not apply learning proposal for %s", p.target)
            p.note = f"not applied: {type(e).__name__}: {e}"
    if commit:
        await db.commit()
    return proposals


async def run_pass(ctx: dict) -> dict:
    """One medium-loop pass: gather, propose, and apply if allowed."""
    db = ctx["db"]
    s = SettingsService(db)
    cfg = await s.section("learning")
    proposals = await propose(db)
    frozen = frozen_for(proposals)
    verdicts = verdicts_for(proposals)

    if cfg["learning.apply_changes"]:
        proposals = await apply(db, proposals)
        verb = "applied"
    else:
        verb = "proposed (not applied — learning.apply_changes is off)"
        await db.commit()

    applied = [p for p in proposals if p.applied]
    reported = applied if cfg["learning.apply_changes"] else proposals
    ups = [p for p in reported if p.direction == "up"]
    downs = [p for p in reported if p.direction == "down"]
    shadowed = [p for p in reported if p.shadowed]
    reversed_ = [p for p in reported if p.reversals]
    turned = [p for p in applied if p.classification == reversal.SUSTAINED]
    summary = (f"{len(reported)} change(s) {verb}: {len(ups)} up, {len(downs)} down"
               + (f", {len(shadowed)} shadowed by your own settings" if shadowed else "")
               + (f", {len(reversed_)} damped after earlier reversals" if reversed_ else ""))
    if cfg["learning.apply_changes"] and len(applied)<len(proposals):
        summary += f"; {len(proposals)-len(applied)} proposal(s) not applied"
    if not proposals:
        summary = "no change — the evidence is not yet decisive"
    if turned:
        summary = (f"{len(turned)} REVERSAL(s) applied: "
                   + ", ".join(f"{p.target} {p.current:.2f}→{p.proposed:.2f}" for p in turned)
                   + ("; " + summary if proposals != turned else ""))
    if frozen:
        summary += (f"; {len(frozen)} left to you "
                    f"({', '.join(f['target'] for f in frozen[:3])})")

    return {"success": True, "summary": summary, "details": summary,
            "status": "ok", "proposals": [p.as_dict() for p in proposals],
            "frozen": frozen, "verdicts": verdicts,
            "reversals_applied": [p.as_dict() for p in proposals
                                  if p.classification == reversal.SUSTAINED and p.applied],
            "apply_enabled": cfg["learning.apply_changes"], "applied": bool(applied),
            "applied_count": len(applied)}
