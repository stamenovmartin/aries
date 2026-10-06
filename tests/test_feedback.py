"""The fast loop (§16, §15): turning something said into something done — and,
more often, into a question."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-feedback")

from sqlalchemy import select  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402
from agentic_core.database.models import AuditEvent  # noqa: E402

from aries.interests import service as interests  # noqa: E402
from aries.learning import explain, preferences  # noqa: E402
from aries.learning import feedback as fb  # noqa: E402
from aries.settings import Layer, SettingsService  # noqa: E402


async def _say(text: str, **context):
    async with async_session() as db:
        return (await fb.submit(db, text, context=context)).as_dict()


# ── not everything is feedback ──────────────────────────────────────────────

async def test_ordinary_conversation_is_not_feedback():
    await reset_db()
    for line in ["what about the other one?", "the deploy finished at 5pm",
                 "I'll look at it tomorrow", "how many items were there?",
                 "the disk is at 90 percent"]:
        d = await _say(line)
        check(f"{line!r} is not read as feedback", d["classification"] == fb.NOT_FEEDBACK)
        check("and nothing is applied", d["applied"] is False)
    async with async_session() as db:
        check("but it is still recorded, so the reading can be audited",
              len(await fb.recent(db)) == 5)


# ── classification ──────────────────────────────────────────────────────────

async def test_classifications():
    await reset_db()
    cases = {
        "shorter": fb.CORRECTION,
        "too dark": fb.CORRECTION,
        "always keep briefs shorter": fb.PERSISTENT,
        "just this once, shorter": fb.ONE_OFF,
        "this is good": fb.APPROVAL,
        "don't do that": fb.REJECTION,
        "never do that again": fb.PERSISTENT,
        "I prefer the short version": fb.PREFERENCE,
        # An imperative ARIES has no rule for is an INSTRUCTION, not a
        # correction: it is understood as being about now, and it changes
        # nothing, because inventing a setting change from free text is exactly
        # the overgeneralisation this classifier exists to avoid.
        "set the theme to light": fb.INSTRUCTION,
    }
    for text, expected in cases.items():
        d = await _say(text)
        check(f"{text!r} → {expected}", d["classification"] == expected)


# ── ambiguity is asked about, not guessed ───────────────────────────────────

async def test_an_unscoped_correction_asks_instead_of_generalising():
    await reset_db()
    d = await _say("shorter")
    check("a bare correction is ambiguous", d["ambiguous"] is True)
    check("it asks how far it reaches", "just this once" in (d["question"] or ""))
    check("and nothing is written until it is answered", d["applied"] is False)

    async with async_session() as db:
        before = await SettingsService(db).get("briefing.length")
    check("the setting is untouched", before == "standard")


async def test_answering_applies_it_at_the_chosen_scope():
    await reset_db()
    d = await _say("shorter")
    async with async_session() as db:
        row = await fb.answer(db, d["id"], scope=fb.GLOBAL)
        value = await SettingsService(db).get("briefing.length")
        e = await SettingsService(db).explain("briefing.length")
    check("answering applies the change", row.applied is True)
    check("at the user layer for a global scope", row.layer == "user")
    check("and the value moves one step shorter", value == "headlines")
    check("the stored rationale quotes what was said", "shorter" in str(e["stack"]))

    await reset_db()
    d = await _say("shorter")
    async with async_session() as db:
        row = await fb.answer(db, d["id"], scope=fb.RESULT)
        e = await SettingsService(db).explain("briefing.length")
    check("a narrow answer writes the instruction layer instead", row.layer == "instruction")
    check("and it is visible as such", e["source"] == "instruction")


# ── explicit statements carry user authority ────────────────────────────────

async def test_an_explicit_rule_is_applied_at_once():
    await reset_db()
    d = await _say("always keep briefs shorter")
    check("an explicit rule is not ambiguous", d["ambiguous"] is False)
    check("it is applied immediately", d["applied"] is True)
    check("at the user layer, because the user said it", d["layer"] == "user")
    check("and is scoped globally", d["scope"] == fb.GLOBAL)


async def test_one_off_stays_narrow():
    await reset_db()
    d = await _say("just this once, shorter")
    check("a one-off is applied", d["applied"] is True)
    check("but only as an instruction", d["layer"] == "instruction")
    check("scoped to the current result", d["scope"] == fb.RESULT)


async def test_a_stated_scope_is_honoured():
    await reset_db()
    d = await _say("shorter for this project", project="insomnia")
    check("a stated project scope is used", d["scope"] == fb.PROJECT)
    check("and the project is captured", d["scope_target"] == "insomnia")
    check("written at the project layer", d["layer"] == "project")
    async with async_session() as db:
        scoped = await SettingsService(db, scope="project:insomnia").get("briefing.length")
        globally = await SettingsService(db).get("briefing.length")
    check("the project value changed", scoped == "headlines")
    check("and the global one did not", globally == "standard")


async def test_scope_is_never_widened_by_guessing():
    """§15's example: 'too dark' about one catalogue must not become
    'the user dislikes dark interfaces'."""
    await reset_db()
    d = await _say("too dark", project="insomnia")
    check("an unscoped aesthetic correction is ambiguous", d["ambiguous"] is True)
    check("and is not applied globally on its own", d["applied"] is False)
    check("the narrowest scope is assumed until answered", d["scope"] == fb.RESULT)


# ── corrections are relative to what is actually set ────────────────────────

async def test_a_relative_correction_is_relative():
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set("briefing.length", "detailed", set_by="user")
    d = await _say("always shorter")
    check("shorter from 'detailed' gives 'standard'", d["action"]["value"] == "standard")

    d = await _say("always shorter")
    check("and shorter again gives 'headlines'", d["action"]["value"] == "headlines")

    d = await _say("always shorter")
    check("it stops at the shortest rather than failing",
          d["action"]["value"] == "headlines")


# ── approval and rejection ──────────────────────────────────────────────────

async def test_approval_changes_nothing_but_is_recorded():
    await reset_db()
    d = await _say("this is good")
    check("approval is classified", d["classification"] == fb.APPROVAL)
    check("nothing is changed by praise", d["applied"] is False)
    check("but it is recorded as a signal", d["id"] > 0)


async def test_a_rejection_without_scope_asks():
    await reset_db()
    d = await _say("don't do that")
    check("a bare rejection is ambiguous", d["ambiguous"] is True)
    check("and asks whether it is a standing rule",
          "in future" in (d["question"] or ""))
    d = await _say("never do that again")
    check("a rejection stated as a rule is not ambiguous", d["ambiguous"] is False)
    check("and is global", d["scope"] == fb.GLOBAL)


# ── audit ───────────────────────────────────────────────────────────────────

async def test_every_reading_is_audited():
    await reset_db()
    await _say("always keep briefs shorter")
    await _say("what about the other one?")
    async with async_session() as db:
        rows = (await db.execute(select(AuditEvent).where(
            AuditEvent.action == "feedback.received"))).scalars().all()
    check("every utterance produces an audit event", len(rows) == 2)
    check("including the ones ARIES decided were not feedback",
          any("not_feedback" in (r.detail or "") for r in rows))


# ── explain ─────────────────────────────────────────────────────────────────

async def test_explain_a_setting():
    await reset_db()
    await _say("always keep briefs shorter")
    async with async_session() as db:
        e = (await explain(db, "briefing.length")).as_dict()
    # "shorter" from the shipped default of "standard" gives "headlines".
    check("explain says what the value is", e["value"] == "headlines")
    check("that it came from the user", e["explicit"] is True)
    check("why, in the user's own words", "shorter" in e["because"])
    check("what its scope is", "scope" in e)
    check("and shows the feedback that produced it",
          any("shorter" in f["text"] for f in e["feedback"]))


async def test_explain_a_topic():
    await reset_db()
    async with async_session() as db:
        await interests.add(db, topic="ai", weight=0.9)
        await interests.learn(db, "ai", 0.3, confidence=0.8, rationale="you ignored 30 of 34")
        e = (await explain(db, "ai")).as_dict()
    check("explain reports the effective weight", e["value"] == 0.9)
    check("names it as explicit", e["explicit"] is True)
    check("and still shows what ARIES would have concluded",
          any(a.get("layer") == "learned" and a.get("value") == 0.3 for a in e["alternatives"]))
    check("with the reasoning", "30 of 34" in e["because"])
    check("and says there is no behavioural evidence yet",
          "note" in e["evidence"] or "overall" in e["evidence"])


async def test_explain_something_unknown():
    await reset_db()
    async with async_session() as db:
        e = (await explain(db, "not.a.thing")).as_dict()
    check("an unknown subject is reported honestly", e["available"] is False)
    check("with a hint about where to look", "settings" in e["because"])


async def test_preferences_omits_untouched_defaults():
    await reset_db()
    async with async_session() as db:
        before = await preferences(db)
        await SettingsService(db).set("general.theme", "dark", set_by="user")
        await interests.add(db, topic="ai", weight=0.8)
        after = await preferences(db)
    check("a fresh system has decided nothing", before["settings"] == [])
    check("a changed setting appears", any(s["key"] == "general.theme"
                                           for s in after["settings"]))
    check("marked as the user's", next(s for s in after["settings"]
                                       if s["key"] == "general.theme")["explicit"] is True)
    check("and topics are listed with their origin",
          any(t["topic"] == "ai" and t["explicit"] for t in after["topics"]))


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
