"""The fast loop — turning something the user says into something ARIES does.

§16's fast loop runs in seconds: the user corrects ARIES, and the correction
takes effect now rather than after a fortnight of statistics. §15 adds the
constraint that makes it hard — feedback must be SCOPE-AWARE:

    "This catalogue is too dark."  →  prefer brighter backgrounds
                                      FOR the Insomnia autumn catalogue

    and NOT                       →  the user dislikes dark interfaces

That second reading is the characteristic failure. It is also the tempting one,
because it is more useful when it happens to be right.

TWO THINGS THIS MUST NOT DO
---------------------------
**Treat every sentence as feedback.** Most of what a person says is not a
preference. A classifier that reads "this is fine, what about the other one?" as
an approval and a scope change will accumulate rules nobody stated. Anything that
does not match a feedback shape is classified `not_feedback` and recorded as
such — visible, and acted on by nothing.

**Guess at persistence.** "Shorter" is genuinely ambiguous: this one, these, or
everything from now on? The requirement is explicit — ASK rather than
overgeneralise — so ambiguity is a first-class outcome carrying the question to
put to the user, and nothing is written until it is answered.

HOW SCOPE BECOMES A LAYER
-------------------------
The Settings Service already has the right vocabulary, built in Entry 002 for
exactly this and unused until now:

    INSTRUCTION   "for this task, do Y"      ← an unambiguous narrow correction,
                                               applied immediately
    PROJECT       scoped to one project      ← "for this project, always …"
    USER          an explicit statement      ← "always", "never", "from now on"

An explicit statement carries USER authority because the user made it — that is
the difference between telling ARIES something and ARIES noticing something, and
§30's precedence already ranks the two. The learning loop of Entry 008 can never
reach these layers; a person speaking can.

NO MODEL
--------
Deterministic patterns, like the health judge and the interest matcher. It works
offline, it is explainable — `aries learning explain` has to say *why* — and it
fails in a predictable direction: unmatched input becomes `not_feedback` rather
than a confident misreading. A model would catch more phrasings and could not be
audited, which is the wrong trade for something that rewrites preferences.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

logger = logging.getLogger(__name__)

POLICY_VERSION = "feedback-v1"

# ── the vocabulary ──────────────────────────────────────────────────────────
CORRECTION = "correction"          # "too dark", "shorter" — adjust what was done
PREFERENCE = "preference"          # "I prefer X" — a stated taste
INSTRUCTION = "instruction"        # "do X" — an imperative for now
APPROVAL = "approval"              # "this is good"
REJECTION = "rejection"            # "don't do that"
ONE_OFF = "one_off"                # "just this once"
PERSISTENT = "persistent_rule"     # "always", "never", "from now on"
NOT_FEEDBACK = "not_feedback"

# Scopes, narrowest first. The default is the narrowest that fits, always.
RESULT, TASK, WORKFLOW, PROJECT, AUTOMATION, DOMAIN, GLOBAL = (
    "current_result", "current_task", "current_workflow", "project",
    "automation", "domain", "global")
SCOPES = (RESULT, TASK, WORKFLOW, PROJECT, AUTOMATION, DOMAIN, GLOBAL)


class AriesFeedback(Base):
    """One thing the user said, what ARIES made of it, and what it did."""

    __tablename__ = "aries_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(30), index=True)
    scope: Mapped[str] = mapped_column(String(30), default=RESULT, index=True)
    scope_target: Mapped[str] = mapped_column(String(160), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # What it was said ABOUT — the context that makes scope meaningful.
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    # The setting change it produced, if any.
    action_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    layer: Mapped[str] = mapped_column(String(20), default="")

    # Set when ARIES declined to act because persistence or scope was unclear.
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered: Mapped[bool] = mapped_column(Boolean, default=False)

    reason: Mapped[str] = mapped_column(Text, default="")
    policy_version: Mapped[str] = mapped_column(String(40), default=POLICY_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "classification": self.classification,
                "scope": self.scope, "scope_target": self.scope_target or None,
                "confidence": round(self.confidence, 3),
                "context": json.loads(self.context_json or "{}"),
                "action": json.loads(self.action_json) if self.action_json else None,
                "applied": self.applied, "layer": self.layer or None,
                "ambiguous": self.ambiguous, "question": self.question,
                "answered": self.answered, "reason": self.reason,
                "policy_version": self.policy_version,
                "at": self.created_at.isoformat() if self.created_at else None}


@dataclass
class Reading:
    """What ARIES made of one utterance."""

    text: str
    classification: str
    scope: str = RESULT
    scope_target: str = ""
    confidence: float = 0.0
    action: dict | None = None            # {"setting": key, "value": v}
    ambiguous: bool = False
    question: str | None = None
    reason: str = ""

    @property
    def actionable(self) -> bool:
        return self.action is not None and not self.ambiguous

    def as_dict(self) -> dict:
        return {"text": self.text, "classification": self.classification, "scope": self.scope,
                "scope_target": self.scope_target or None, "confidence": round(self.confidence, 3),
                "action": self.action, "ambiguous": self.ambiguous, "question": self.question,
                "reason": self.reason}


# ── patterns ────────────────────────────────────────────────────────────────
# Each is anchored on words that carry intent. Deliberately narrow: a phrase that
# does not clearly mean something becomes `not_feedback`.

_PERSISTENT = re.compile(
    r"\b(always|never|from now on|in future|in the future|every time|each time|"
    r"by default|stop (doing|showing)|don'?t ever)\b", re.I)
_ONE_OFF = re.compile(r"\b(just (this|once|now)|this time|for now|only here|this one)\b", re.I)
_APPROVAL = re.compile(r"\b(this is (good|great|right|perfect)|that'?s (good|right|better)|"
                       r"perfect|exactly|well done|keep (it|that)|yes,? (good|right))\b", re.I)
_REJECTION = re.compile(r"\b(don'?t|do not|stop|no,? (don'?t|not)|never do|that'?s wrong|"
                        r"this is wrong|not (this|that|like this))\b", re.I)
_PREFERENCE = re.compile(r"\b(i (prefer|like|want|"
                         r"would rather)|prefer|rather have|use .* instead)\b", re.I)
_INSTRUCTION = re.compile(r"^(please\s+)?(do|make|set|use|show|hide|add|remove|send|run|keep)\b",
                          re.I)

# Corrections that map onto a concrete setting. `apply` receives the current
# value and returns the new one, so a relative correction ("shorter") is applied
# relative to whatever is actually configured.
_LENGTHS = ["headlines", "standard", "detailed"]


def _shorter(current):
    i = _LENGTHS.index(current) if current in _LENGTHS else 1
    return _LENGTHS[max(0, i - 1)]


def _longer(current):
    i = _LENGTHS.index(current) if current in _LENGTHS else 1
    return _LENGTHS[min(len(_LENGTHS) - 1, i + 1)]


@dataclass
class Rule:
    pattern: re.Pattern
    setting: str
    apply: object                     # callable(current) -> new value
    what: str
    # Scope this correction can sensibly have. A theme is global; a brief's
    # length belongs to briefs.
    natural_scope: str = RESULT


CORRECTION_RULES: list[Rule] = [
    Rule(re.compile(r"(?:icons beside ARIES|ikoni do aries|икони до aries)", re.I),
         "shell.dock_position", lambda _: "top", "put small application icons beside ARIES", GLOBAL),
    Rule(re.compile(r"(?:close temporary (?:agent |tool )?(?:browsers|windows)|zatvaraj privremeni prozorci|затворај привремени прозорци)", re.I),
         "workspace.auto_close_tools", lambda _: True, "close temporary agent browsers after completion", GLOBAL),
    Rule(re.compile(r"(?:keep temporary (?:agent |tool )?(?:browsers|windows) open)", re.I),
         "workspace.auto_close_tools", lambda _: False, "keep temporary agent browsers open", GLOBAL),
    Rule(re.compile(r"(?:close completed result windows)", re.I),
         "workspace.auto_close_results", lambda _: True, "close completed result windows", GLOBAL),
    Rule(re.compile(r"(?:keep completed result windows open)", re.I),
         "workspace.auto_close_results", lambda _: False, "keep completed result windows open", GLOBAL),
    Rule(re.compile(r"\b(shorter|too long|less detail|briefer|trim)\b", re.I),
         "briefing.length", _shorter, "make briefs shorter", DOMAIN),
    Rule(re.compile(r"\b(longer|more detail|too short|expand)\b", re.I),
         "briefing.length", _longer, "make briefs longer", DOMAIN),
    Rule(re.compile(r"\b(too dark|brighter|lighter)\b", re.I),
         "general.theme", lambda c: "light", "use a light theme", GLOBAL),
    Rule(re.compile(r"\b(too bright|darker|dark mode)\b", re.I),
         "general.theme", lambda c: "dark", "use a dark theme", GLOBAL),
    Rule(re.compile(r"\b(too (much|many|noisy)|too often|less (news|noise)|quieter|"
                    r"only .*important)\b", re.I),
         "notifications.minimum_level", lambda c: "important",
         "only notify about important things", GLOBAL),
    Rule(re.compile(r"\b(too few|more news|show me more)\b", re.I),
         "news.max_items_per_briefing", lambda c: min(50, int(c) + 5),
         "include more items", DOMAIN),
]


def classify(text: str, *, context: dict | None = None,
             current: dict | None = None) -> Reading:
    """Read one utterance. Never writes anything.

    `context` says what was on screen — task, automation, project — which is what
    makes a narrow scope meaningful. `current` holds the present values of any
    settings a rule might adjust, so a relative correction is relative to reality.
    """
    context = context or {}
    current = current or {}
    raw = (text or "").strip()
    if not raw:
        return Reading(raw, NOT_FEEDBACK, reason="empty")

    persistent = bool(_PERSISTENT.search(raw))
    one_off = bool(_ONE_OFF.search(raw))

    # An explicit scope in the words themselves always wins over inference.
    stated_scope, stated_target = _stated_scope(raw, context)

    rule = next((r for r in CORRECTION_RULES if r.pattern.search(raw)), None)
    if rule is not None:
        value = rule.apply(current.get(rule.setting))
        action = {"setting": rule.setting, "value": value, "what": rule.what}

        if persistent:
            return Reading(raw, PERSISTENT, scope=stated_scope or GLOBAL,
                           scope_target=stated_target, confidence=0.9, action=action,
                           reason=f"an explicit persistent rule: {rule.what}")
        if one_off:
            return Reading(raw, ONE_OFF, scope=RESULT, confidence=0.8, action=action,
                           reason=f"just this once: {rule.what}")
        if stated_scope:
            return Reading(raw, CORRECTION, scope=stated_scope, scope_target=stated_target,
                           confidence=0.85, action=action,
                           reason=f"a correction scoped to {stated_scope}: {rule.what}")
        # Nothing said how far this goes. THIS is the case the requirement is
        # about: acting globally would be convenient and would be inventing a
        # rule the user did not state.
        return Reading(raw, CORRECTION, scope=RESULT, confidence=0.5, action=action,
                       ambiguous=True,
                       question=(f"Should I {rule.what} just this once, or "
                                 f"{'for everything from now on' if rule.natural_scope == GLOBAL else 'from now on'}?"),
                       reason="the correction is clear; how far it reaches is not")

    if _APPROVAL.search(raw):
        return Reading(raw, APPROVAL, scope=stated_scope or RESULT, scope_target=stated_target,
                       confidence=0.7,
                       reason="approval — recorded as a positive signal, nothing changed")
    if _REJECTION.search(raw):
        return Reading(raw, PERSISTENT if persistent else REJECTION,
                       scope=stated_scope or (GLOBAL if persistent else RESULT),
                       scope_target=stated_target, confidence=0.75 if persistent else 0.6,
                       ambiguous=not persistent and not stated_scope,
                       question=(None if persistent or stated_scope else
                                 "Should I avoid this in future, or just here?"),
                       reason="a rejection" + (" stated as a rule" if persistent else ""))
    if _PREFERENCE.search(raw):
        return Reading(raw, PREFERENCE, scope=stated_scope or RESULT, scope_target=stated_target,
                       confidence=0.6, ambiguous=not stated_scope and not persistent,
                       question=(None if stated_scope or persistent else
                                 "Is that a general preference, or just for this?"),
                       reason="a stated preference with no setting ARIES knows how to change")
    if _INSTRUCTION.match(raw):
        return Reading(raw, INSTRUCTION, scope=stated_scope or TASK, scope_target=stated_target,
                       confidence=0.5,
                       reason="an instruction for the current task, not a standing rule")

    if context.get('scope') == GLOBAL:
        return Reading(raw, PERSISTENT, scope=GLOBAL, confidence=1.0,
                       reason="Explicitly saved for future tasks; supplied to the planner, no matching automatic setting change")
    return Reading(raw, NOT_FEEDBACK, confidence=0.0,
                   reason="this does not look like feedback, so nothing was inferred from it")


def _stated_scope(text: str, context: dict) -> tuple[str, str]:
    """A scope the user named explicitly, or ("", "")."""
    low = text.lower()
    if re.search(r"\bfor (this|the) project\b", low) and context.get("project"):
        return PROJECT, str(context["project"])
    if re.search(r"\bfor (this|the) (automation|brief|briefing|report)\b", low):
        return (AUTOMATION, str(context.get("automation", "")))
    if re.search(r"\bfor (all|every)\b|\beverywhere\b|\bglobally\b", low):
        return GLOBAL, ""
    if re.search(r"\b(here|this one|this result)\b", low):
        return RESULT, ""
    if re.search(r"\bfor (this|the) task\b", low):
        return TASK, str(context.get("task", ""))
    if context.get("scope") in SCOPES:
        return context["scope"], str(context.get("task", ""))
    return "", ""


# ── acting on it ────────────────────────────────────────────────────────────

# Scope decides which layer a change is written at. An explicit persistent rule
# is the USER speaking; a narrow correction is an instruction for now.
_LAYER_FOR_SCOPE = {
    RESULT: "instruction", TASK: "instruction", WORKFLOW: "instruction",
    PROJECT: "project", AUTOMATION: "project", DOMAIN: "user", GLOBAL: "user",
}


async def current_values(db: AsyncSession, keys: list[str]) -> dict:
    from aries.settings import SettingsService
    return await SettingsService(db).get_many(keys)


async def submit(db: AsyncSession, text: str, *, context: dict | None = None,
                 commit: bool = True) -> AriesFeedback:
    """Read one utterance, act on it if it is unambiguous, and record either way."""
    from agentic_core.observability import audit

    from aries.settings import Layer, SettingsService

    keys = sorted({r.setting for r in CORRECTION_RULES})
    if (context or {}).get('origin') == 'implementation':
        reading = Reading(text.strip(), 'implementation_note', scope=GLOBAL, confidence=1.0,
                          reason='Recorded implementation lesson and validation evidence; no automatic setting mutation or model training')
    else:
        reading = classify(text, context=context, current=await current_values(db, keys))

    row = AriesFeedback(
        text=reading.text[:4000], classification=reading.classification, scope=reading.scope,
        scope_target=reading.scope_target or "", confidence=reading.confidence,
        context_json=json.dumps(context or {}, default=str),
        action_json=json.dumps(reading.action) if reading.action else None,
        ambiguous=reading.ambiguous, question=reading.question, reason=reading.reason,
        policy_version=POLICY_VERSION)

    if reading.actionable:
        layer_name = _LAYER_FOR_SCOPE.get(reading.scope, "instruction")
        layer = {"instruction": Layer.INSTRUCTION, "project": Layer.PROJECT,
                 "user": Layer.USER}[layer_name]
        scope = (f"project:{reading.scope_target}"
                 if reading.scope == PROJECT and reading.scope_target else None)
        s = SettingsService(db, scope=scope)
        try:
            await s.set(reading.action["setting"], reading.action["value"], layer=layer,
                        set_by="user:feedback", scope=scope,
                        rationale=f'from your feedback: "{reading.text[:120]}"', commit=False)
            row.applied = True
            row.layer = layer_name
        except Exception as e:                       # noqa: BLE001
            row.reason += f" — could not apply: {type(e).__name__}: {e}"
    db.add(row)
    await db.flush()
    await audit.log_event(db, actor_type="human", actor="user", action="feedback.received",
                          entity_type="feedback", entity_id=row.id,
                          detail={"classification": row.classification, "scope": row.scope,
                                  "applied": row.applied, "ambiguous": row.ambiguous})
    if commit:
        await db.commit()
    return row


async def answer(db: AsyncSession, feedback_id: int, *, scope: str,
                 commit: bool = True) -> AriesFeedback:
    """Resolve an ambiguous piece of feedback with the scope the user chose."""
    from aries.settings import Layer, SettingsService

    row = await db.get(AriesFeedback, feedback_id)
    if row is None:
        raise ValueError(f"no feedback {feedback_id}")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {list(SCOPES)}")
    action = json.loads(row.action_json) if row.action_json else None
    row.scope, row.ambiguous, row.answered, row.question = scope, False, True, None
    if action:
        layer_name = _LAYER_FOR_SCOPE.get(scope, "instruction")
        layer = {"instruction": Layer.INSTRUCTION, "project": Layer.PROJECT,
                 "user": Layer.USER}[layer_name]
        await SettingsService(db).set(action["setting"], action["value"], layer=layer,
                                      set_by="user:feedback",
                                      rationale=f'from your feedback: "{row.text[:120]}"',
                                      commit=False)
        row.applied, row.layer = True, layer_name
    await db.flush()
    if commit:
        await db.commit()
    return row


async def recent(db: AsyncSession, *, limit: int = 30,
                 pending_only: bool = False) -> list[AriesFeedback]:
    q = select(AriesFeedback).order_by(AriesFeedback.id.desc())
    if pending_only:
        q = q.where(AriesFeedback.ambiguous.is_(True), AriesFeedback.answered.is_(False))
    return list((await db.execute(q.limit(limit))).scalars().all())


async def standing_rules(db):
    """Explicit global feedback only. It guides plans but never grants capabilities."""
    rows = (await db.execute(select(AriesFeedback).where(
        AriesFeedback.scope == GLOBAL, AriesFeedback.ambiguous.is_(False),
        AriesFeedback.classification.in_([PERSISTENT, PREFERENCE, CORRECTION])
    ).order_by(AriesFeedback.id.desc()).limit(12))).scalars().all()
    return [{"id": r.id, "text": r.text[:1000]} for r in rows]


async def implementation_notes(db):
    rows = (await db.execute(select(AriesFeedback).where(
        AriesFeedback.classification == 'implementation_note', AriesFeedback.scope == GLOBAL
    ).order_by(AriesFeedback.id.desc()).limit(6))).scalars().all()
    return [{"id":r.id, "text":r.text[:1800]} for r in rows]
