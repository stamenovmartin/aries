"""The learning loop as an automation — versioned, inspectable, off by default.

§16's medium loop is the first thing ARIES does that changes its own behaviour,
so it is the last thing that should be invisible. As an automation it gets a
genome, a run history, a health figure, a circuit breaker and a place in the
Control Centre — and, like every automation, it is disabled until asked for.

It carries no task kind of its own: a learning pass is pure bookkeeping over
facts already recorded, with nothing to evaluate, no side effect outside ARIES
and no human to ask. The runner's direct path is the right one for it.
"""
from __future__ import annotations

from agentic_core.security.permissions import Permission

from aries.automations.genome import AutomationSpec, register
from aries.learning import settings as _settings  # noqa: F401  registers the settings
from aries.learning.loop import run_pass

AUTOMATION_ID = "aries.learning"


async def _learning_status(db) -> dict:
    """What it has concluded so far, and what it is still waiting for."""
    from aries.interests.models import AriesInterest
    from aries.learning.loop import gather
    from aries.settings import SettingsService
    from sqlalchemy import select

    rows = list((await db.execute(select(AriesInterest))).scalars().all())
    learned = [r for r in rows if r.learned_weight is not None]
    shadowed = [r for r in learned if r.weight is not None]
    s = SettingsService(db)
    min_obs = int(await s.get("learning.min_observations"))
    evidence = await gather(db, window_days=int(await s.get("learning.window_days")))
    ready = [t for t, e in evidence.items() if e.shown >= min_obs]
    return {
        "topics": len(rows),
        "with_a_learned_weight": len(learned),
        "overridden_by_you": len(shadowed),
        "topics_with_enough_evidence": len(ready),
        "topics_observed": len(evidence),
        "minimum_observations": min_obs,
        "explanation": (
            f"{len(ready)} of {len(evidence)} observed topics have at least {min_obs} delivered "
            f"items, which is what it takes before a weight may move. "
            + (f"{len(learned)} topics carry a learned weight, {len(shadowed)} of which you have "
               f"overridden." if learned else "Nothing has been learned yet.")),
    }


SPEC = AutomationSpec(
    automation_id=AUTOMATION_ID,
    name="Learning Loop",
    version="1.0.0",
    purpose="Watch what the user opens and dismisses, and adjust topic weights and the relevance "
            "bar accordingly — slowly, with evidence, and never over an explicit preference.",
    run=run_pass,
    trigger="schedule",
    schedule_setting="learning.interval_hours",
    default_interval_minutes=24 * 60,
    conditions=["learning.enabled is on", "enough delivered items to judge"],
    input_sources=["aries_news_items", "aries_interests"],
    task_kind=None,                  # pure bookkeeping; nothing to evaluate or approve
    agents=[],                       # deterministic statistics, no model
    tools=[],
    permissions=[Permission.VIEW_DATA],
    memory_dependencies=["aries_news_items", "aries_interests", "aries_settings"],
    enabled_setting="learning.enabled",
    writes_settings=["news.relevance_threshold (learned layer only)"],
    risk="low",
    requires_approval=False,
    evaluation_metrics=["proposals_per_pass", "shadowed_rate", "reversal_rate",
                        "topics_with_enough_evidence"],
    reward_signals=["a raised topic kept being opened",
                    "a lowered topic was later raised again — a sign of overreaction",
                    "the user cleared a weight and accepted the learned one",
                    "the user overrode a learned weight"],
    learning_status=lambda db: _learning_status(db),
)

register(SPEC)
