"""The Personal Interest Profile (§25): what matters, what is refused, and the
rule that the user's word always wins."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-interests")

from agentic_core.database.base import async_session  # noqa: E402

from aries.interests import matching, service as ints  # noqa: E402
from aries.interests.matching import Matchable, normalise  # noqa: E402
from aries.interests.matching import score as score_terms  # noqa: E402
from aries.interests.service import InterestError  # noqa: E402
from aries.settings import SettingsService  # noqa: E402


# ── matching ────────────────────────────────────────────────────────────────

async def test_substring_trap_is_avoided():
    """`if "ai" in text` matches said, email, campaign, Ukraine, against."""
    ai = Matchable.build("ai", [], 0.9)
    for decoy in ["she said so", "check your email", "a campaign", "Ukraine", "against it",
                  "certainly", "maintain"]:
        r = score_terms(decoy, [ai])
        check(f"'ai' does not match inside {decoy!r}", r.score == 0.0)
    check("but it matches the word itself", score_terms("new AI model", [ai]).score == 0.9)
    check("and matches it when punctuated", score_terms("AI, again", [ai]).score == 0.9)


async def test_phrases_and_synonyms():
    m = Matchable.build("llm agents", ["agentic", "artificial intelligence"], 0.8)
    check("a multi-word term matches as a phrase", score_terms("building llm agents", [m]).score == 0.8)
    check("with flexible whitespace", score_terms("llm   agents\nhere", [m]).score == 0.8)
    check("the words apart do not match", score_terms("agents of an llm", [m]).score == 0.0)
    check("a synonym matches", score_terms("agentic loops", [m]).score == 0.8)
    check("a multi-word synonym matches",
          score_terms("Artificial Intelligence news", [m]).score == 0.8)


async def test_normalisation():
    check("case is ignored", normalise("AI Agents") == "ai agents")
    check("accents are folded", normalise("café") == "cafe")
    check("whitespace is collapsed", normalise("  a   b  ") == "a b")
    m = Matchable.build("cafe", [], 0.7)
    check("so an accented word matches an unaccented topic",
          score_terms("the café opened", [m]).score == 0.7)


async def test_terms_with_punctuation():
    """A word boundary cannot sit next to a non-word character."""
    m = Matchable.build("c++", [], 0.7)
    check("a term ending in punctuation still matches",
          score_terms("written in c++ lately", [m]).score == 0.7)
    net = Matchable.build(".net", [], 0.7)
    check("and one starting with punctuation matches",
          score_terms("the .net runtime", [net]).score == 0.7)


async def test_noisy_or_scoring():
    a = Matchable.build("alpha", [], 0.9)
    b = Matchable.build("beta", [], 0.6)
    one = score_terms("alpha only", [a, b]).score
    two = score_terms("alpha and beta", [a, b]).score
    check("one match scores its weight", one == 0.9)
    check("two matches score higher than either", two > one)
    check("but never exceed 1", two <= 1.0)
    check("combining 0.9 and 0.6 gives 0.96", abs(two - 0.96) < 1e-9)
    check("a weight of 1.0 saturates", score_terms(
        "alpha", [Matchable.build("alpha", [], 1.0)]).score == 1.0)


async def test_avoid_disqualifies_outright():
    """§25 lists 'topics I do not care about' as its own category: the user
    means 'not this', not 'this, but less'."""
    strong = Matchable.build("ai", [], 1.0)
    avoid = Matchable.build("crypto", ["bitcoin"], 0.5, avoid=True)
    r = score_terms("AI trading bots for bitcoin", [strong, avoid])
    check("an avoided topic disqualifies despite a perfect positive match", r.score == 0.0)
    check("and the exclusion says which topic did it", r.excluded_by["topic"] == "crypto")
    check("and is reported as an exclusion, not a low score", r.excluded is True)


async def test_explanations_are_inspectable():
    m = Matchable.build("llm agents", ["agentic"], 0.8)
    r = score_terms("agentic systems", [m])
    check("a score names the topic that matched", r.matched[0]["topic"] == "llm agents")
    check("and the term it matched on", r.matched[0]["hits"][0]["term"] == "agentic")
    check("and where the weight came from", r.matched[0]["source"] == "user")
    check("and reads as a sentence", "matches 1 topic" in r.explanation)


# ── the profile ─────────────────────────────────────────────────────────────

async def test_add_and_refuse():
    await reset_db()
    async with async_session() as db:
        row = await ints.add(db, topic="LLM Agents", synonyms=["Agentic", "llm agents"], weight=0.9)
        check("the topic is stored canonically", row.topic == "llm agents")
        check("the label keeps what the user typed", row.label == "LLM Agents")
        check("a synonym equal to the topic is dropped", row.synonyms == ["agentic"])
        check("adding the same topic twice is refused",
              await _araises(ints.add(db, topic="llm agents")))
        check("a weight outside 0..1 is refused",
              await _araises(ints.add(db, topic="x", weight=1.5)))
        check("an unknown stance is refused",
              await _araises(ints.add(db, topic="y", stance="maybe")))
        check("an empty topic is refused", await _araises(ints.add(db, topic="   ")))


async def test_max_topics():
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set("interests.max_topics", 1, set_by="user")
        await ints.add(db, topic="one")
        check("the topic limit is enforced", await _araises(ints.add(db, topic="two")))


async def test_update_and_remove():
    await reset_db()
    async with async_session() as db:
        await ints.add(db, topic="telecom", synonyms=["5g"])
        r = await ints.update(db, "telecom", weight=0.8, synonyms=["5g", "telecommunications"])
        check("a weight can be set", r.weight == 0.8)
        check("synonyms can be replaced", r.synonyms == ["5g", "telecommunications"])
        r = await ints.update(db, "telecom", stance="avoid")
        check("a topic can be switched to avoid", r.avoid is True)
        check("updating an unknown topic is refused",
              await _araises(ints.update(db, "nope", weight=0.5)))
        check("a topic can be removed", await ints.remove(db, "telecom") is True)
        check("removing it again reports false", await ints.remove(db, "telecom") is False)


# ── §25's precedence rule ───────────────────────────────────────────────────

async def test_user_weight_beats_learned():
    await reset_db()
    async with async_session() as db:
        await ints.add(db, topic="telecom")
        check("with nothing set, the default weight applies",
              (await ints.score_text(db, "telecom news")).score == 0.6)

        await ints.learn(db, "telecom", 0.2, confidence=0.9, rationale="ignored 14 of 15")
        check("a learned weight applies when the user has said nothing",
              (await ints.score_text(db, "telecom news")).score == 0.2)

        await ints.update(db, "telecom", weight=0.9)
        check("an explicit user weight outranks the learned one",
              (await ints.score_text(db, "telecom news")).score == 0.9)

        out = await ints.learn(db, "telecom", 0.01, confidence=0.99, rationale="ignored everything")
        check("learning again does not move the effective weight",
              (await ints.score_text(db, "telecom news")).score == 0.9)
        check("and the learner is told it is shadowed", out["shadowed"] is True)

        await ints.update(db, "telecom", weight=None)
        check("clearing the user weight promotes the learned one, not the default",
              (await ints.score_text(db, "telecom news")).score == 0.01)


async def test_learning_cannot_invent_topics():
    """A learning loop may weigh what the user chose to follow; it may not decide
    what they follow."""
    await reset_db()
    async with async_session() as db:
        check("learning about an unknown topic is refused",
              await _araises(ints.learn(db, "surprise", 0.9, confidence=1.0, rationale="guessed")))
        check("and a learned weight outside 0..1 is refused too",
              await _araises(ints.learn(db, "surprise", 5.0, confidence=1.0, rationale="x")))


async def test_learned_weight_stays_inspectable():
    """§25: the user must always be able to inspect what ARIES concluded."""
    await reset_db()
    async with async_session() as db:
        await ints.add(db, topic="telecom", weight=0.9)
        await ints.learn(db, "telecom", 0.1, confidence=0.8, rationale="ignored 14 of 15 items")
        row = await ints.get(db, "telecom")
        d = row.as_dict()
        check("the effective weight is the user's", d["weight"] == 0.9)
        check("the learned one is still visible", d["learned"]["weight"] == 0.1)
        check("with the reasoning that produced it",
              "14 of 15" in d["learned"]["rationale"])
        check("and marked as overridden", d["learned"]["shadowed"] is True)
        check("the weight's origin is named", d["weight_source"] == "user")


# ── scope, bridging and engagement ──────────────────────────────────────────

async def test_scope():
    await reset_db()
    async with async_session() as db:
        await ints.add(db, topic="ai", weight=0.5)
        await ints.add(db, topic="pottery", weight=0.9, scope="project:kiln")
        check("a scoped topic is invisible globally",
              (await ints.score_text(db, "medieval pottery")).score == 0.0)
        check("and applies inside its project",
              (await ints.score_text(db, "medieval pottery", scope="project:kiln")).score == 0.9)
        check("while global topics still apply there",
              (await ints.score_text(db, "ai models", scope="project:kiln")).score == 0.5)


async def test_topics_for_bridges_to_sources():
    """Entry 005 left source topics as exact strings; this is what closes it."""
    await reset_db()
    async with async_session() as db:
        await ints.add(db, topic="ai", synonyms=["artificial intelligence"])
        await ints.add(db, topic="crypto", stance="avoid")
        wanted = await ints.topics_for(db)
        check("the canonical topic is included", "ai" in wanted)
        check("and every synonym, so a source tagged either way is findable",
              "artificial intelligence" in wanted)
        check("avoided topics are not offered as things to look for", "crypto" not in wanted)
        check("they can be asked for explicitly",
              await ints.topics_for(db, stance="avoid") == ["crypto"])


async def test_engagement_counting():
    await reset_db()
    async with async_session() as db:
        await ints.add(db, topic="ai")
        row = await ints.get(db, "ai")
        check("engagement rate is unknown before anything is shown",
              row.engagement_rate is None)
        await ints.record_engagement(db, ["ai"], shown=True)
        await ints.record_engagement(db, ["ai"], shown=True, engaged=True)
        row = await ints.get(db, "ai")
        check("engagements are counted", row.times_engaged == 1)
        check("and the rate is computed once there is data", row.engagement_rate == 0.5)
        check("an unknown topic is skipped, not raised",
              await ints.record_engagement(db, ["ghost"]) == 0)


async def test_summary():
    await reset_db()
    async with async_session() as db:
        await ints.add(db, topic="ai", weight=0.9)
        await ints.add(db, topic="crypto", stance="avoid")
        await ints.learn(db, "ai", 0.2, confidence=0.5, rationale="x")
        s = await ints.summary(db)
        check("the summary counts what is followed", s["wanted"] == 1)
        check("and what is ignored", s["avoided"] == 1)
        check("and how many learned weights the user has overridden", s["shadowed"] == 1)


async def _araises(coro) -> bool:
    try:
        await coro; return False
    except (InterestError, ValueError):
        return True


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
