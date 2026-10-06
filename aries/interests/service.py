"""The Personal Interest Profile — §25.

Two jobs:

  * hold what the user said matters, and what ARIES inferred, without ever
    letting the second overwrite the first;
  * answer the question everything downstream actually asks — *is this item
    worth the user's attention, and why?*

`score_text()` is that answer, and it returns the reasoning with the number.
§25 requires the user be able to inspect and override what ARIES concluded, and
§29 requires that nothing ARIES does be invisible; a bare float satisfies
neither. Every score carries the topics that matched, the term that matched
them, each contribution, and whether the weight came from the user or from
learning.

WHY LEARNING CANNOT REACH THE USER'S COLUMN
-------------------------------------------
Exactly the pattern of Entry 002's settings and Entry 005's sources: the write
path enforces what the read path promises. `learn()` writes `learned_weight` and
physically cannot write `weight`, so "explicit user configuration has higher
priority than inferred preferences" is not a rule someone has to remember — it
is the only thing the code can express. When what it learns is shadowed by a
user weight, it is told so in the return value rather than silently ignored.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.observability import audit

from aries.interests.matching import Matchable, Relevance, normalise
from aries.interests.matching import score as score_terms
from aries.interests.models import AVOID, STANCES, WANT, AriesInterest
from aries.settings import SettingsService

logger = logging.getLogger(__name__)


class InterestError(ValueError):
    """A change to the interest profile that is refused, with a reason."""


async def add(db: AsyncSession, *, topic: str, stance: str = WANT, weight: float | None = None,
              synonyms: list[str] | None = None, scope: str = "",
              preferred_sources: list[str] | None = None, notification_level: str | None = None,
              created_by: str = "user", commit: bool = True) -> AriesInterest:
    """Add a topic to the profile."""
    canonical = normalise(topic)
    if not canonical:
        raise InterestError("a topic is required")
    if stance not in STANCES:
        raise InterestError(f"stance must be one of {list(STANCES)}")
    if weight is not None and not 0.0 <= weight <= 1.0:
        raise InterestError(f"weight must be between 0 and 1, got {weight}")

    settings = SettingsService(db)
    limit = int(await settings.get("interests.max_topics"))
    count = (await db.execute(select(func.count(AriesInterest.id)))).scalar() or 0
    if count >= limit:
        raise InterestError(f"the topic limit of {limit} is reached (raise interests.max_topics)")

    existing = await get(db, canonical, scope=scope)
    if existing is not None:
        raise InterestError(f"'{canonical}' is already in the profile"
                            + (f" for scope {scope}" if scope else ""))

    row = AriesInterest(
        topic=canonical, label=topic.strip()[:160], stance=stance, scope=scope or "",
        weight=weight,
        synonyms_json=json.dumps(_clean_synonyms(canonical, synonyms)),
        preferred_sources_json=json.dumps(sorted(set(preferred_sources or []))),
        notification_level=notification_level, created_by=created_by)
    db.add(row)
    await db.flush()
    await audit.log_event(db, actor_type="human" if created_by == "user" else "system",
                          actor=created_by, action="interest.added", entity_type="interest",
                          entity_id=row.id, detail={"topic": canonical, "stance": stance,
                                                    "weight": weight, "scope": scope or None})
    if commit:
        await db.commit()
    return row


def _clean_synonyms(canonical: str, synonyms: list[str] | None) -> list[str]:
    out, seen = [], {canonical}
    for s in synonyms or []:
        n = normalise(s)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


async def get(db: AsyncSession, topic: str, *, scope: str = "") -> AriesInterest | None:
    return (await db.execute(select(AriesInterest).where(
        AriesInterest.topic == normalise(topic),
        AriesInterest.scope == (scope or "")))).scalar_one_or_none()


async def update(db: AsyncSession, topic: str, *, scope: str = "", actor: str = "user",
                 commit: bool = True, **fields) -> AriesInterest:
    row = await get(db, topic, scope=scope)
    if row is None:
        raise InterestError(f"'{topic}' is not in the profile")

    if "weight" in fields:
        w = fields["weight"]
        if w is not None and not 0.0 <= float(w) <= 1.0:
            raise InterestError(f"weight must be between 0 and 1, got {w}")
        row.weight = None if w is None else float(w)
    if fields.get("stance"):
        if fields["stance"] not in STANCES:
            raise InterestError(f"stance must be one of {list(STANCES)}")
        row.stance = fields["stance"]
    if "synonyms" in fields and fields["synonyms"] is not None:
        row.synonyms_json = json.dumps(_clean_synonyms(row.topic, fields["synonyms"]))
    if "preferred_sources" in fields and fields["preferred_sources"] is not None:
        row.preferred_sources_json = json.dumps(sorted(set(fields["preferred_sources"])))
    if "notification_level" in fields:
        row.notification_level = fields["notification_level"]
    if fields.get("label"):
        row.label = str(fields["label"])[:160]

    await db.flush()
    await audit.log_event(db, actor_type="human", actor=actor, action="interest.updated",
                          entity_type="interest", entity_id=row.id,
                          detail={"topic": row.topic, "changed": sorted(fields)})
    if commit:
        await db.commit()
    return row


async def remove(db: AsyncSession, topic: str, *, scope: str = "", actor: str = "user",
                 commit: bool = True) -> bool:
    row = await get(db, topic, scope=scope)
    if row is None:
        return False
    await audit.log_event(db, actor_type="human", actor=actor, action="interest.removed",
                          entity_type="interest", entity_id=row.id, detail={"topic": row.topic})
    await db.delete(row)
    if commit:
        await db.commit()
    return True


async def list_interests(db: AsyncSession, *, scope: str | None = None,
                         stance: str | None = None) -> list[AriesInterest]:
    q = select(AriesInterest)
    if scope is not None:
        q = q.where(AriesInterest.scope == scope)
    if stance:
        q = q.where(AriesInterest.stance == stance)
    return list((await db.execute(q.order_by(AriesInterest.stance, AriesInterest.topic))).scalars().all())


# ── scoring ─────────────────────────────────────────────────────────────────

async def profile(db: AsyncSession, *, scope: str | None = None) -> list[Matchable]:
    """The profile reduced to what the matcher needs.

    A scope chain, weakest first, like settings and sources: global interests
    apply everywhere, and a scoped one is added on top when working in that
    project.
    """
    scopes = [""] if scope is None else ["", scope]
    rows = list((await db.execute(
        select(AriesInterest).where(AriesInterest.scope.in_(scopes)))).scalars().all())
    default = float(await SettingsService(db).get("interests.default_weight"))
    return [Matchable.build(r.topic, r.synonyms, r.effective_weight(default),
                            avoid=r.avoid, source=r.weight_source())
            for r in rows]


async def score_text(db: AsyncSession, text: str, *, scope: str | None = None) -> Relevance:
    """How relevant is this text to the user, and why?"""
    return score_terms(text, await profile(db, scope=scope))


async def topics_for(db: AsyncSession, *, stance: str = WANT, scope: str | None = None) -> list[str]:
    """The plain topic list — what a source query or a search needs.

    This is the bridge Entry 005 left open: the Sources Registry matches topics
    as exact strings, so asking it with the canonical topic AND its synonyms is
    what makes a source tagged "artificial intelligence" findable by a user who
    wrote "ai".
    """
    scopes = [""] if scope is None else ["", scope]
    rows = list((await db.execute(select(AriesInterest).where(
        AriesInterest.scope.in_(scopes), AriesInterest.stance == stance))).scalars().all())
    out: list[str] = []
    for r in rows:
        out.extend([r.topic, *r.synonyms])
    return sorted(set(out))


# ── learning (§25, §16) ─────────────────────────────────────────────────────

async def learn(db: AsyncSession, topic: str, weight: float, *, confidence: float,
                rationale: str, scope: str = "", commit: bool = True) -> dict:
    """The learning loop's ONLY entry point.

    It writes `learned_weight` and cannot reach `weight`. When the user has set
    a weight, the inference is stored but reported as shadowed — kept, because
    §25 requires the user be able to inspect what ARIES concluded, and because
    clearing their own weight should fall back to it rather than to the default.
    """
    if not 0.0 <= weight <= 1.0:
        raise InterestError(f"weight must be between 0 and 1, got {weight}")
    row = await get(db, topic, scope=scope)
    if row is None:
        raise InterestError(f"'{topic}' is not in the profile — learning does not invent topics")
    row.learned_weight = float(weight)
    row.learned_confidence = float(confidence)
    row.learned_rationale = rationale
    await db.flush()
    default = float(await SettingsService(db).get("interests.default_weight"))
    effective = row.effective_weight(default)
    if commit:
        await db.commit()
    return {"topic": row.topic, "learned": weight, "effective": effective,
            "shadowed": row.weight is not None,
            "note": None if row.weight is None else
                    f"stored, but the user's weight of {row.weight} still decides"}


async def record_engagement(db: AsyncSession, topics: list[str], *, shown: bool = False,
                            engaged: bool = False, dismissed: bool = False,
                            scope: str = "", commit: bool = True) -> int:
    """Count what happened to items matching these topics — §17's reward signal
    in its simplest form. Counting only; turning counts into a weight is `learn`."""
    n = 0
    for t in topics:
        row = await get(db, t, scope=scope)
        if row is None:
            continue
        if shown:
            row.times_shown += 1
        if engaged:
            row.times_engaged += 1
        if dismissed:
            row.times_dismissed += 1
        n += 1
    await db.flush()
    if commit:
        await db.commit()
    return n


async def summary(db: AsyncSession) -> dict:
    rows = await list_interests(db)
    return {"total": len(rows),
            "wanted": sum(1 for r in rows if r.stance == WANT),
            "avoided": sum(1 for r in rows if r.stance == AVOID),
            "user_weighted": sum(1 for r in rows if r.weight is not None),
            "learned": sum(1 for r in rows if r.learned_weight is not None),
            "shadowed": sum(1 for r in rows if r.learned_weight is not None and r.weight is not None)}
