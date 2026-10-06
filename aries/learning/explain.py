"""Why does ARIES believe this?

One question, asked of anything ARIES holds an opinion about — a setting or a
topic — and answered the same way for both:

    what   the value in force now
    why    the layer that decided it, and what that layer means
    from   the evidence, feedback or default that produced it
    scope  where it applies
    sure   how confident, when the answer is an inference
    kind   explicit (the user said so) or learned (ARIES concluded it)

§25 requires that the user be able to inspect and override anything inferred, and
§29 that nothing ARIES does be invisible. Neither is satisfied by a value with no
account of itself. This module is that account, and it is deliberately the union
of every source rather than a settings viewer: a preference the user stated in
words, one they set in a UI, and one ARIES inferred from behaviour are three
different provenances for the same number, and the answer has to say which.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class Explanation:
    subject: str
    kind: str                              # setting | topic | unknown
    value: Any = None
    source: str = ""                       # which layer decided
    source_label: str = ""
    explicit: bool = False                 # stated by the user, vs inferred
    scope: str | None = None
    confidence: float | None = None
    because: str = ""
    evidence: dict = field(default_factory=dict)
    alternatives: list[dict] = field(default_factory=list)   # layers that lost
    history: list[dict] = field(default_factory=list)
    feedback: list[dict] = field(default_factory=list)
    available: bool = True

    def as_dict(self) -> dict:
        return {"subject": self.subject, "kind": self.kind, "value": self.value,
                "source": self.source, "source_label": self.source_label,
                "explicit": self.explicit, "scope": self.scope,
                "confidence": self.confidence, "because": self.because,
                "evidence": self.evidence, "alternatives": self.alternatives,
                "history": self.history, "feedback": self.feedback,
                "available": self.available}


async def explain(db: AsyncSession, subject: str, *, scope: str | None = None) -> Explanation:
    """Explain a setting key or a topic. Tries settings first, then interests."""
    from aries.settings import get_def

    if get_def(subject) is not None:
        return await _setting(db, subject, scope=scope)
    topic = await _topic(db, subject, scope=scope)
    if topic is not None:
        return topic
    return Explanation(subject, "unknown", available=False,
                       because=("this is neither a setting nor a topic ARIES holds an opinion "
                                "about — `aries settings` and `aries interests` list what is"))


async def _setting(db: AsyncSession, key: str, *, scope: str | None) -> Explanation:
    from aries.learning.feedback import AriesFeedback
    from aries.learning.history import AriesLearningChange
    from aries.settings import SettingsService

    s = SettingsService(db, scope=scope)
    e = await s.explain(key)
    winner = e["source"]
    explicit = winner in ("user", "restriction", "security", "instruction", "project")

    # What produced the winning value.
    top = next((x for x in e["stack"] if x["layer"] == winner), None)
    because = e["definition"]["description"]
    if top and top.get("rationale"):
        because = top["rationale"]
    elif winner == "default":
        because = f"nothing has changed it, so the shipped default applies: {because}"

    changes = list((await db.execute(
        select(AriesLearningChange).where(AriesLearningChange.target == key)
        .order_by(AriesLearningChange.id.desc()).limit(10))).scalars().all())
    said = list((await db.execute(
        select(AriesFeedback).where(AriesFeedback.action_json.like(f'%"{key}"%'))
        .order_by(AriesFeedback.id.desc()).limit(10))).scalars().all())

    return Explanation(
        subject=key, kind="setting", value=e["value"], source=winner,
        source_label=e["source_label"], explicit=explicit, scope=e["scope"],
        confidence=(top or {}).get("confidence"), because=because,
        evidence={"definition": e["definition"]},
        alternatives=e["stack"], history=[c.as_dict() for c in changes],
        feedback=[f.as_dict() for f in said])


async def _topic(db: AsyncSession, topic: str, *, scope: str | None) -> Explanation | None:
    from aries.interests import service as interests
    from aries.learning import evidence as ev_mod
    from aries.learning.history import AriesLearningChange
    from aries.learning.reversal import AriesReversal
    from aries.settings import SettingsService

    row = await interests.get(db, topic, scope=scope or "")
    if row is None:
        return None

    default = float(await SettingsService(db).get("interests.default_weight"))
    source = row.weight_source()
    explicit = source == "user"
    value = row.effective_weight(default)

    if explicit:
        because = f"you set this to {row.weight:.2f}"
        if row.learned_weight is not None:
            because += (f"; ARIES would have said {row.learned_weight:.2f} — "
                        f"{row.learned_rationale or 'no reason recorded'}")
    elif source == "learned":
        because = row.learned_rationale or "inferred from what you read"
    else:
        because = f"neither you nor ARIES has set a weight, so the default of {default} applies"

    window = int(await SettingsService(db).get("learning.window_days"))
    all_ev = await ev_mod.gather(db, window_days=window)
    mine = all_ev.get(topic)

    changes = list((await db.execute(
        select(AriesLearningChange).where(AriesLearningChange.target == topic)
        .order_by(AriesLearningChange.id.desc()).limit(10))).scalars().all())
    reversals = list((await db.execute(
        select(AriesReversal).where(AriesReversal.target == topic)
        .order_by(AriesReversal.id.desc()).limit(5))).scalars().all())

    return Explanation(
        subject=topic, kind="topic", value=value, source=source,
        source_label={"user": "you said so", "learned": "ARIES inferred it",
                      "default": "the shipped default"}[source],
        explicit=explicit, scope=row.scope or None,
        confidence=row.learned_confidence if source == "learned" else None,
        because=because,
        evidence=(mine.as_dict() if mine else
                  {"note": f"nothing about '{topic}' has been delivered in the last "
                           f"{window} days, so there is no behavioural evidence either way"}),
        alternatives=([{"layer": "user", "value": row.weight}] if row.weight is not None else [])
                     + ([{"layer": "learned", "value": row.learned_weight,
                          "rationale": row.learned_rationale,
                          "confidence": row.learned_confidence}]
                        if row.learned_weight is not None else []),
        history=[c.as_dict() for c in changes] + [r.as_dict() for r in reversals],
        feedback=[])


async def preferences(db: AsyncSession) -> dict:
    """Everything ARIES currently believes, and where each belief came from.

    Settings whose value is still the shipped default are omitted: a list of 70
    unchanged defaults buries the dozen things that are actually true about this
    user, and the point of the view is to show what has been decided.
    """
    from aries.interests import service as interests
    from aries.settings import SettingsService, all_defs

    s = SettingsService(db)
    out_settings = []
    for d in all_defs():
        e = await s.explain(d.key)
        if e["source"] == "default":
            continue
        top = next((x for x in e["stack"] if x["layer"] == e["source"]), None)
        out_settings.append({
            "key": d.key, "value": e["value"], "source": e["source"],
            "source_label": e["source_label"], "section": d.section,
            "explicit": e["source"] in ("user", "restriction", "security",
                                        "instruction", "project"),
            "rationale": (top or {}).get("rationale"),
            "shadowing": [x for x in e["stack"] if x["layer"] != e["source"]]})

    default = float(await s.get("interests.default_weight"))
    topics = [{"topic": r.topic, "stance": r.stance, "weight": r.effective_weight(default),
               "source": r.weight_source(), "scope": r.scope or None,
               "explicit": r.weight is not None,
               "learned": r.learned_weight, "rationale": r.learned_rationale}
              for r in await interests.list_interests(db)]

    return {"settings": out_settings, "topics": topics,
            "means": "settings still at their shipped default are omitted — this is what has "
                     "actually been decided, by you or by ARIES"}
