"""The medium learning loop (§16): what it changes, and — mostly — what it refuses to."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-learning")

from agentic_core.database.base import async_session  # noqa: E402

from aries.interests import service as interests  # noqa: E402
from aries.learning import apply, gather, propose, run_pass  # noqa: E402
from aries.learning.statistics import step_toward, wilson  # noqa: E402
from aries.news.models import AriesNewsItem, fingerprint  # noqa: E402
from aries.settings import SettingsService  # noqa: E402


async def _items(topic: str, *, shown: int, engaged: int = 0, dismissed: int = 0,
                 disposition: str = "delivered"):
    """Fabricate evidence: `shown` items about a topic, `engaged` of them opened."""
    import json
    async with async_session() as db:
        for i in range(shown):
            db.add(AriesNewsItem(
                item_id=fingerprint(topic, disposition, str(i)), source_id="s",
                title=f"{topic} item {i}", disposition=disposition,
                relevance=0.8, matched_json=json.dumps([{"topic": topic, "weight": 0.8}]),
                engaged=i < engaged, dismissed=engaged <= i < engaged + dismissed))
        await db.commit()


# ── the statistics ──────────────────────────────────────────────────────────

async def test_intervals_refuse_to_overreact():
    tiny = wilson(1, 3)
    check("one click in three is not evidence — the interval spans most of the range",
          tiny.lower < 0.1 and tiny.upper > 0.7)
    solid = wilson(2, 40)
    check("two in forty is decisively low even optimistically", solid.upper < 0.2)
    strong = wilson(30, 40)
    check("thirty in forty is decisively high even pessimistically", strong.lower > 0.55)
    none = wilson(0, 0)
    check("no observations means the rate could be anything",
          none.lower == 0.0 and none.upper == 1.0)
    check("and its point estimate is unknown, not zero", none.point is None)


async def test_steps_are_bounded():
    check("a step is capped however confident",
          step_toward(0.9, 0.0, confidence=1.0, max_step=0.15) == 0.75)
    check("and scaled by confidence",
          abs(step_toward(0.5, 1.0, confidence=0.2, max_step=0.5) - 0.6) < 1e-9)
    check("it never leaves [0, 1]",
          step_toward(0.05, 0.0, confidence=1.0, max_step=0.5) == 0.0
          and step_toward(0.95, 1.0, confidence=1.0, max_step=0.5) == 1.0)


# ── evidence ────────────────────────────────────────────────────────────────

async def test_evidence_counts_what_the_user_could_see():
    await reset_db()
    await _items("ai", shown=5, engaged=3, disposition="delivered")
    await _items("ai", shown=4, engaged=1, disposition="held")
    await _items("ai", shown=9, engaged=0, disposition="below_threshold")
    await _items("ai", shown=3, engaged=0, disposition="excluded")
    async with async_session() as db:
        ev = await gather(db)
    check("delivered items count", ev["ai"].shown >= 5)
    check("held items count too — they reach the user in the briefing",
          ev["ai"].shown == 9 and ev["ai"].engaged == 4)
    check("items never shown are excluded, so the loop cannot confirm its own guesses",
          ev["ai"].shown == 9)


# ── proposals ───────────────────────────────────────────────────────────────

async def _prepare(topic="ai", weight=None, **settings):
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("learning.enabled", True, set_by="user")
        for k, v in settings.items():
            await s.set(k.replace("__", "."), v, set_by="user")
        await interests.add(db, topic=topic, weight=weight)


async def test_too_little_evidence_changes_nothing():
    await _prepare(weight=None)
    await _items("ai", shown=4, engaged=4)
    async with async_session() as db:
        props = await propose(db)
    check("four observations do not move a weight, however one-sided", props == [])


async def test_a_topic_that_is_read_goes_up():
    await _prepare(weight=None)
    await _items("ai", shown=30, engaged=24)
    async with async_session() as db:
        props = await propose(db)
    p = next((x for x in props if x.target == "ai"), None)
    check("a consistently opened topic is proposed for a raise",
          p is not None and p.direction == "up")
    check("and it moves upward from the default", p.proposed > p.current)
    check("the rationale quotes the evidence", "24 of 30" in p.rationale)
    check("the step is capped", p.proposed - p.current <= 0.15 + 1e-9)


async def test_a_topic_that_is_ignored_goes_down():
    await _prepare(weight=None)
    await _items("ai", shown=40, engaged=0)
    async with async_session() as db:
        props = await propose(db)
    p = next((x for x in props if x.target == "ai"), None)
    check("a consistently ignored topic is proposed for a cut",
          p is not None and p.direction == "down")
    check("and it moves downward", p.proposed < p.current)
    check("the rationale explains the optimistic bound", "optimistic end" in p.rationale)


async def test_an_ambiguous_topic_is_left_alone():
    await _prepare(weight=None)
    await _items("ai", shown=20, engaged=5)          # 25%: between the two thresholds
    async with async_session() as db:
        props = await propose(db)
    check("a middling engagement rate is not decisive, so nothing changes",
          not [x for x in props if x.target == "ai"])


async def test_learning_never_overrules_the_user():
    """§25 and §30, exercised by the component they were written for."""
    await _prepare(weight=0.9)
    await _items("ai", shown=40, engaged=0)
    async with async_session() as db:
        props = await apply(db, await propose(db))
        effective = (await interests.score_text(db, "ai news")).score
        row = await interests.get(db, "ai")
    p = next(x for x in props if x.target == "ai")
    check("the loop still records what it concluded", p.applied and row.learned_weight is not None)
    check("it is reported as shadowed", p.shadowed is True)
    check("and the user's weight is what actually applies", effective == 0.9)

    async with async_session() as db:
        await interests.update(db, "ai", weight=None)
        after = (await interests.score_text(db, "ai news")).score
    check("clearing the user's weight promotes what was learned", after == row.learned_weight)


async def test_learning_cannot_invent_a_topic():
    await _prepare(topic="ai")
    await _items("pottery", shown=50, engaged=45)
    async with async_session() as db:
        props = await propose(db)
    check("a topic the user never chose is not added, however engaging",
          not [p for p in props if p.target == "pottery"])


async def test_the_relevance_bar_only_ever_goes_up():
    await _prepare(weight=None)
    await _items("ai", shown=40, engaged=1, dismissed=30)
    async with async_session() as db:
        props = await propose(db)
    t = next((p for p in props if p.kind == "relevance_threshold"), None)
    check("heavy dismissal proposes a higher bar", t is not None and t.direction == "up")
    check("and the proposal is above the current value", t.proposed > t.current)

    await _prepare(weight=None)
    await _items("ai", shown=40, engaged=38)
    async with async_session() as db:
        props = await propose(db)
    check("strong engagement never proposes LOWERING the bar — that would reason "
          "from items the user never saw",
          not [p for p in props if p.kind == "relevance_threshold"])


async def test_proposals_can_be_watched_without_being_applied():
    """§18's observe → measure → propose, in the small."""
    await _prepare(weight=None, learning__apply_changes=False)
    await _items("ai", shown=40, engaged=0)
    async with async_session() as db:
        out = await run_pass({"db": db})
        row = await interests.get(db, "ai")
    check("a pass in propose-only mode still works out what it would do",
          out["proposals"] and out["applied"] is False)
    check("and says so", "not applied" in out["summary"])
    check("but writes nothing", row.learned_weight is None)

    await _prepare(weight=None, learning__apply_changes=True)
    await _items("ai", shown=40, engaged=0)
    async with async_session() as db:
        out = await run_pass({"db": db})
        row = await interests.get(db, "ai")
    check("with applying on, the weight is written", row.learned_weight is not None)
    check("into the learned layer only", row.weight is None)


async def test_a_pass_with_no_evidence_is_not_a_failure():
    await _prepare(weight=None)
    async with async_session() as db:
        out = await run_pass({"db": db})
    check("a quiet pass succeeds", out["success"] is True)
    check("and says plainly that nothing was decisive",
          "not yet decisive" in out["summary"])


async def test_the_automation_is_registered_and_off_by_default():
    from aries.automations import all_automations
    from aries.settings import get_def
    spec = next(a for a in all_automations() if a.automation_id == "aries.learning")
    check("the learning loop is an automation like any other", spec.enabled_setting == "learning.enabled")
    check("it ships disabled", get_def("learning.enabled").default is False)
    check("it uses no model", spec.agents == [])
    check("whether it applies what it learns is user-only",
          get_def("learning.apply_changes").user_only is True)


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
