"""The Morning Brief (§13/01): parallel collection, honest absence, and the
difference between a section that is empty and one that is switched off."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-brief")

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.automations import run_automation  # noqa: E402
from aries.automations.genome import due, last_run, next_run_at  # noqa: E402
from aries.brief import SPEC, AriesBrief  # noqa: E402
from aries.brief.render import headline, render  # noqa: E402
from aries.brief.sections import Item, Section, names  # noqa: E402
from aries.settings import SettingsService  # noqa: E402


async def _enable(**kw):
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("briefing.morning_enabled", True, set_by="user")
        for k, v in kw.items():
            await s.set(k.replace("__", "."), v, set_by="user")


# ── the workflow ────────────────────────────────────────────────────────────

async def test_collection_is_a_parallel_graph():
    from agentic_core.orchestrator.graph import AgentNode, _levels
    from agentic_core.workflows.spec import get
    wf = get("morning_brief")
    check("the brief is a registered workflow", wf is not None)
    check("that runs in parallel", wf.parallel is True)
    levels = _levels([AgentNode(n.name, None, depends_on=n.depends_on) for n in wf.nodes])
    check("configuration is read once, before the fan-out",
          len(levels[0]) == 1 and levels[0][0].name == "prepare")
    check("every section is collected concurrently", len(levels[1]) == len(names()))
    check("and assembly waits for all of them",
          len(levels[2]) == 1 and levels[2][0].name == "compose")


async def test_a_brief_is_produced_and_kept():
    await _enable()
    out = await run_automation("aries.brief", trigger="manual", force=True)
    check("the pass succeeds", out["ran"] and out["verdict"] == "pass")
    async with async_session() as db:
        row = (await db.execute(select(AriesBrief))).scalar_one()
    check("the brief is stored, not only printed", row.rendered)
    check("with its sections, so it can be re-rendered later", row.sections)
    check("and a one-line headline", row.headline)
    check("every node ran", len(row.sections) >= 1)


async def test_one_broken_section_does_not_cost_the_brief():
    """A collector that raises must not take the morning with it."""
    from aries.brief import sections as sec

    await _enable(briefing__sections=["system", "news"])
    original = sec._COLLECTORS["news"]

    async def _explode(cfg):
        raise RuntimeError("the feed table is on fire")

    sec._COLLECTORS["news"] = _explode
    try:
        out = await run_automation("aries.brief", trigger="manual", force=True)
    finally:
        sec._COLLECTORS["news"] = original

    check("the brief is still produced", out["verdict"] == "pass")
    async with async_session() as db:
        row = (await db.execute(select(AriesBrief))).scalar_one()
    news = next(s for s in row.sections if s["name"] == "news")
    check("the broken section reports the failure rather than vanishing",
          "on fire" in (news["unavailable"] or ""))
    check("and the other sections are intact",
          any(s["name"] == "system" for s in row.sections))


async def test_absent_and_switched_off_are_different():
    await _enable(briefing__sections=["system", "calendar"])
    await run_automation("aries.brief", trigger="manual", force=True)
    async with async_session() as db:
        row = (await db.execute(select(AriesBrief))).scalar_one()
    shown = {s["name"] for s in row.sections}
    check("a section the user did not ask for is simply absent", "news" not in shown)
    check("a section that cannot work yet IS shown, with the reason", "calendar" in shown)
    cal = next(s for s in row.sections if s["name"] == "calendar")
    check("and the reason names what is missing", "Integrations" in (cal["unavailable"] or ""))


async def test_an_unknown_section_is_reported():
    await _enable(briefing__sections=["system", "news"])
    async with async_session() as db:
        # Bypass the schema's choices to simulate a stale configuration.
        from aries.settings import Layer
        from aries.settings.store import write
        await write(db, "briefing.sections", Layer.USER, ["system", "priorities"])
        await db.commit()
    out = await run_automation("aries.brief", trigger="manual", force=True)
    check("a brief naming a section that does not exist still succeeds",
          out["verdict"] == "pass")
    async with async_session() as db:
        from agentic_core.database.models import TaskRun
        run = (await db.execute(select(TaskRun).order_by(TaskRun.id.desc()).limit(1))).scalar_one()
    check("and the evaluation warns about it", "priorities" in (run.evaluation or ""))


# ── rendering ───────────────────────────────────────────────────────────────

def _sample() -> list[Section]:
    return [
        Section("decisions", "Waiting for you",
                [Item("approve: free disk space", "the / mount is 96% full", severity="critical")],
                summary="1 decision(s) pending", severity="critical"),
        Section("system", "System", [Item("cpu at 91 °C", "check airflow", severity="warning")],
                summary="1 thing to look at"),
        Section("news", "News",
                [Item(f"story {i}", "ai", link=f"https://x/{i}") for i in range(9)],
                summary="9 worth your time"),
        Section("calendar", "Calendar", unavailable="no calendar is connected"),
        Section("learning", "What I learned", summary="nothing changed"),
    ]


async def test_lengths_answer_different_questions():
    secs = _sample()
    short = render(secs, length="headlines")
    standard = render(secs, length="standard")
    detailed = render(secs, length="detailed")

    check("headlines keeps what needs the user", "approve: free disk space" in short)
    check("and drops the quiet sections", "nothing changed" not in short)
    check("standard shows every requested section", "News" in standard and "Calendar" in standard)
    check("detailed carries the links", "https://x/0" in detailed)
    check("headlines does not", "https://x/0" not in short)
    check("each is longer than the last", len(short) < len(standard) < len(detailed))


async def test_urgent_items_explain_themselves_at_every_length():
    secs = _sample()
    for length in ("headlines", "standard", "detailed"):
        text = render(secs, length=length)
        check(f"a critical item carries its explanation at '{length}'",
              "the / mount is 96% full" in text)
    check("a news item does not, at standard length",
          "ai" not in render([_sample()[2]], length="standard").replace("Nothing", ""))


async def test_empty_sections_are_one_line():
    text = render(_sample(), length="standard")
    check("an empty section states its summary instead of a heading plus 'nothing'",
          "nothing changed" in text and "— nothing" not in text)
    check("an unavailable one still says why", "no calendar is connected" in text)


async def test_headline_leads_with_what_is_blocked():
    check("a pending decision leads", "decision" in headline(_sample()))
    quiet = [Section("news", "News", [Item("a story")], summary="1")]
    check("otherwise it says nothing needs you", headline(quiet).startswith("nothing needs you"))
    check("and still says what there is to read", "1 news" in headline(quiet))
    check("a truly empty brief says so", headline([]) == "nothing needs you")


# ── time-of-day scheduling ──────────────────────────────────────────────────

async def test_scheduled_by_time_of_day_not_interval():
    await _enable(briefing__morning_time="07:30")
    async with async_session() as db:
        s = SettingsService(db)
        ok, why = await due(db, SPEC, s, now=datetime.now().replace(hour=6, minute=0))
        check("before the hour it is not due", not ok and "07:30" in why)
        ok, why = await due(db, SPEC, s, now=datetime.now().replace(hour=9, minute=0))
        check("after the hour, having never run, it is due", ok)

        nxt = await next_run_at(db, SPEC, s)
        check("and the next run is a real moment", isinstance(nxt, datetime))

    await run_automation("aries.brief", trigger="manual", force=True)
    async with async_session() as db:
        s = SettingsService(db)
        ok, why = await due(db, SPEC, s, now=datetime.now().replace(hour=9, minute=0))
        check("having run today, it is not due again", not ok and "already ran today" in why)
        check("the run is recorded", (await last_run(db, "aries.brief")) is not None)


async def test_a_missed_morning_is_caught_up_not_skipped():
    """The machine was asleep at 07:30. The brief is produced when it wakes."""
    await _enable(briefing__morning_time="07:30")
    await run_automation("aries.brief", trigger="manual", force=True)
    async with async_session() as db:
        row = await last_run(db, "aries.brief")
        row.started_at = datetime.utcnow() - timedelta(days=2)
        await db.commit()
        s = SettingsService(db)
        ok, why = await due(db, SPEC, s, now=datetime.now().replace(hour=9, minute=0))
    check("a brief that has not run today is due, not skipped", ok and "due since" in why)


async def test_the_automation_ships_off():
    from aries.settings import get_def
    check("the brief is off by default", get_def("briefing.morning_enabled").default is False)
    check("it is scheduled by time of day", SPEC.time_setting == "briefing.morning_time")
    check("it uses no model", SPEC.agents == [])
    check("and the shipped sections all exist",
          all(n in names() for n in get_def("briefing.sections").default))


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
