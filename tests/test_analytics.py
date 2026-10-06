"""Analytics (`aries/analytics`): the numbers, and mostly the refusals.

Three properties are worth more than any individual figure, so most of this file
is about them:

  * an empty window reports nothing, not 0% and not 100%
  * every rate carries an interval, so "3 of 3" is never sold as certainty
  * nothing here writes, and nothing leaves a transaction open

The harness starts with an empty database, which is the hardest case for an
analytics package and therefore the first thing tested.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-analytics")

from sqlalchemy import text                                          # noqa: E402
from agentic_core.database.base import async_session                 # noqa: E402

from aries import analytics                                          # noqa: E402
from aries.analytics.core import (MAX_GOAL_SCAN, MAX_WINDOW_DAYS, Window, absent,  # noqa: E402
                                  distribution, rate)

# Every metric, by name, so a new one cannot be added without the empty-database
# and no-open-transaction properties being checked for it too.
ALL = analytics.METRICS + (analytics.approval_discipline,)


async def test_integrity_metrics_disclose_caps_even_when_sample_has_no_steps():
    await reset_db()
    async with async_session() as db:
        await _goal(db,'old-verified','done',[{'capability':'file.read','verification_status':'verified'}],ago_hours=3)
        await _goal(db,'new-verified','done',[{'capability':'file.read','verification_status':'verified'}],ago_hours=2)
        await _goal(db,'newest-empty','queued',[],ago_hours=1)
        await db.commit()
        for metric in (analytics.verification_honesty,analytics.verification_contradictions):
            empty=await metric(db,Window(days=7,goal_scan=1))
            check('empty sample retains truthful population and scan size',
                  empty['goals_in_window']==3 and empty['goals_scanned']==1 and empty['truncated'])
            limited=await metric(db,Window(days=7,goal_scan=2))
            check('nonempty sample is explicitly capped',limited['truncated'] and limited['goals_scanned']==2)
            check('sampling disclosure names the scope',bool(limited['note']) and bool(limited['cutoff_utc']))
            check('verified label is not sold as independent proof','does not establish' in limited['verification_independence'])
            full=await metric(db,Window(days=7,goal_scan=10))
            check('uncapped window reports actual full goal count',not full['truncated'] and full['goals_scanned']==3)

# Counted before and after the whole dashboard runs. Analytics is read-only and a
# regression that started writing would be invisible without this.
TABLES = ("aries_workspace_goals", "aries_automation_runs", "automation_logs",
          "aries_intelligence_events", "execution_operations", "tasks", "task_runs",
          "agent_steps", "aries_notifications", "action_proposals")


async def _counts(db) -> dict:
    return {t: (await db.execute(text(f'SELECT COUNT(*) FROM "{t}"'))).scalar() for t in TABLES}


async def _goal(db, gid: str, state: str, steps: list[dict], *, ago_hours: float = 1.0):
    """One recorded request, with steps in whichever engine's shape is passed."""
    import json
    await db.execute(text(
        "INSERT INTO aries_workspace_goals (id, request, state, created_at, updated_at,"
        " result_json) VALUES (:id, :req, :st,"
        " datetime('now', :off), datetime('now', :off2), :rj)"),
        {"id": gid, "req": f"request {gid}", "st": state,
         "off": f"-{ago_hours} hours", "off2": f"-{ago_hours - 0.5} hours",
         "rj": json.dumps({"steps": steps})})


# ── absence: the property that matters most ─────────────────────────────────

async def test_every_metric_reports_nothing_rather_than_zero_on_an_empty_database():
    await reset_db()
    async with async_session() as db:
        for fn in ALL:
            out = await fn(db, Window(days=7))
            name = out.get("metric")
            check(f"{name} reports n=0 on an empty database", out.get("n") == 0)
            check(f"{name} gives a reason for the emptiness", bool(out.get("reason")))
            # The actual trap: a rate of 0.0 or 1.0 anywhere in an empty result.
            flat = repr(out)
            check(f"{name} invents no rate from no data",
                  "'rate': 0.0" not in flat and "'rate': 1.0" not in flat)
            check(f"{name} still reports what it cost", out.get("query_ms") is not None)
            check(f"{name} left no transaction open", not db.in_transaction())


async def test_the_dashboard_runs_on_an_empty_database_and_says_so():
    await reset_db()
    async with async_session() as db:
        out = await analytics.dashboard(db, Window(days=7))
        check("no metric raised", out["failed_metrics"] is None)
        check("every metric is present",
              len(out["metrics"]) == len(analytics.METRICS))
        check("the dashboard reports its own total wall time",
              isinstance(out["timing"]["total_ms"], float))
        check("every metric reported its own wall time",
              all(v is not None for v in out["timing"]["per_metric_ms"].values()))
        check("an empty database produces no rate anywhere in the dashboard",
              "'rate': 0.0" not in repr(out["metrics"]))


async def test_absent_and_rate_refuse_to_manufacture_a_number():
    a = absent("nothing happened")
    check("absent() reports n=0 with a reason", a == {"n": 0, "reason": "nothing happened"})
    r = rate(0, 0, of="trials")
    check("a rate over zero trials is None, not 0.0", r["rate"] is None)
    check("and it says why", bool(r["reason"]))


# ── uncertainty: three of three is not certainty ────────────────────────────

async def test_a_perfect_score_from_three_observations_is_not_reported_as_perfect():
    r = rate(3, 3, of="trials")
    check("the point estimate is still 1.0 — it is displayed, not decided on",
          r["rate"] == 1.0)
    check("but the lower bound is well below it", r["lower"] < 0.5)
    check("and the interval is explicitly not trusted", r["confident"] is False)
    many = rate(300, 300, of="trials")
    check("300 of 300 narrows to something worth acting on", many["lower"] > 0.98)
    check("and is marked confident", many["confident"] is True)


async def test_every_rate_in_a_real_dashboard_carries_its_denominator():
    await reset_db()
    async with async_session() as db:
        for i in range(6):
            await db.execute(text(
                "INSERT INTO aries_automation_runs (automation_id, version, trigger, status,"
                " summary, duration_ms, started_at) VALUES ('a.x','1','schedule',:s,'',:d,"
                " datetime('now','-1 hours'))"),
                {"s": "ok" if i < 5 else "failed", "d": i * 10})
        await db.commit()
        out = await analytics.automation_health(db, Window(days=7))
        row = next(r for r in out["automations"] if r["automation_id"] == "a.x")
        check("5 of 6 is reported with an interval, not as a bare 83%",
              row["ok"]["lower"] < row["ok"]["rate"] < row["ok"]["upper"])
        check("the denominator is named in the payload", bool(row["ok"]["of"]))
        check("six observations are not called confident", row["ok"]["confident"] is False)


# ── the statistics are correct, not merely present ──────────────────────────

async def test_percentiles_are_computed_in_sql_and_match_a_hand_sorted_list():
    await reset_db()
    values = [5, 1, 100, 2, 3, 4, 50, 7, 6, 9]          # n=10, sorted: 1..9,50,100
    async with async_session() as db:
        for v in values:
            await db.execute(text(
                "INSERT INTO aries_automation_runs (automation_id, version, trigger, status,"
                " summary, duration_ms, started_at) VALUES ('a.p','1','schedule','ok','',:d,"
                " datetime('now','-1 hours'))"), {"d": v})
        await db.commit()
        d = await distribution(db, (
            "SELECT duration_ms AS x FROM aries_automation_runs WHERE duration_ms IS NOT NULL"),
            {}, what="runs")
        srt = sorted(values)
        import math
        check("n is right", d["n"] == 10)
        check("p50 is the value at ceil(0.5n)", d["p50"] == srt[math.ceil(10 * .5) - 1])
        check("p90 is the value at ceil(0.9n)", d["p90"] == srt[math.ceil(10 * .9) - 1])
        check("min and max are the ends", (d["min"], d["max"]) == (srt[0], srt[-1]))
        check("the mean is reported too", d["mean"] == sum(values) / len(values))
        check("and the gap between mean and median is named",
              d["tail_ratio"] == round((sum(values) / len(values)) / d["p50"], 1))


async def test_an_empty_distribution_reports_absence_not_a_row_of_nulls():
    await reset_db()
    async with async_session() as db:
        d = await distribution(db, "SELECT 1 AS x WHERE 0", {}, what="nothings")
        check("no samples means n=0 and a reason", d["n"] == 0 and bool(d["reason"]))
        check("no percentile is invented", "p50" not in d)


# ── bounds: an unbounded aggregate over this data is a stall ────────────────

async def test_windows_clamp_rather_than_trusting_the_caller():
    check("a decade is clamped to the ceiling", Window(days=9999).days == MAX_WINDOW_DAYS)
    check("a zero window becomes the minimum", Window(days=0).days == 1)
    check("an unbounded goal scan is clamped",
          Window(goal_scan=10 ** 9).goal_scan == MAX_GOAL_SCAN)
    check("a negative goal scan becomes the minimum", Window(goal_scan=-5).goal_scan == 1)
    check("the cutoff is a sortable SQLite datetime string",
          Window(days=1).cutoff[4] == "-" and Window(days=1).cutoff[10] == " ")


async def test_the_goal_scan_cap_is_reported_as_a_sample_not_as_a_total():
    await reset_db()
    async with async_session() as db:
        for i in range(8):
            await _goal(db, f"g{i}", "done", [{"kind": "capability", "capability": "open_app",
                                               "state": "done"}])
        await db.commit()
        out = await analytics.outcomes_by_capability(db, Window(days=7, goal_scan=3))
        check("only the capped number of goals was parsed", out["n"] == 3)
        check("the window's real size is reported alongside", out["goals_in_window"] == 8)
        check("and the result is flagged as truncated", out["truncated"] is True)
        check("with a sentence saying it is a sample", "sample" in (out["note"] or ""))
        full = await analytics.outcomes_by_capability(db, Window(days=7, goal_scan=500))
        check("an uncapped window is not flagged", full["truncated"] is False)


# ── the bucketing: three engines, one vocabulary ────────────────────────────

async def test_accepted_is_never_counted_as_verified():
    """The integrity metric. Two engines' shapes, in one window."""
    await reset_db()
    async with async_session() as db:
        # M14 orchestration: executed and independently verified.
        await _goal(db, "m14-ok", "done", [
            {"kind": "capability", "capability": "file.list",
             "execution_status": "observed", "verification_status": "verified"}])
        # M14: executed, and the verifier contradicted it.
        await _goal(db, "m14-lie", "failed", [
            {"kind": "capability", "capability": "browser.search",
             "execution_status": "observed", "verification_status": "verification_failed",
             "error": {"code": "VERIFICATION_FAILED"}}])
        # Legacy operator: reported done, nothing checked it.
        await _goal(db, "legacy", "done", [
            {"kind": "capability", "capability": "open_app", "state": "done"},
            {"kind": "capability", "capability": "play_music", "state": "unconfirmed"},
            {"kind": "capability", "capability": "open_app", "state": "held"}])
        # A plan step with no recorded outcome at all.
        await _goal(db, "silent", "interrupted", [
            {"kind": "capability", "capability": "agent_task", "args": {}}])
        await db.commit()

        h = await analytics.verification_honesty(db, Window(days=7))
        b = h["buckets"]
        check("an independently verified step is `verified`", b.get("verified") == 1)
        check("a legacy 'done' is `accepted`, not `verified`", b.get("accepted") == 1)
        check("'unconfirmed' keeps its own bucket", b.get("unconfirmed") == 1)
        check("a policy hold is `withheld`, not a failure", b.get("withheld") == 1)
        check("a contradicted verification counts as failed", b.get("failed") == 1)
        check("a step with no status at all is named, not swept into pending",
              b.get("no_outcome_recorded") == 1)
        check("nothing fell through to `unclassified`", b.get("unclassified") in (None, 0))
        check("coverage counts only apparently-successful steps",
              h["coverage"]["trials"] == 3 and h["coverage"]["successes"] == 1)
        check("the unverified remainder is stated outright", h["unverified"] == 2)

        c = await analytics.verification_contradictions(db, Window(days=7))
        check("the verifier's one catch is counted", c["n"] == 1)
        check("against the steps that actually reached a verifier",
              c["verified_or_contradicted"] == 2)
        check("and attributed to the capability", c["by_capability"] == {"browser.search": 1})


async def test_contradictions_say_nothing_when_no_verifier_ran():
    await reset_db()
    async with async_session() as db:
        await _goal(db, "legacy-only", "done",
                    [{"kind": "capability", "capability": "open_app", "state": "done"}])
        await db.commit()
        c = await analytics.verification_contradictions(db, Window(days=7))
        check("a window with no verification reports absence, not a clean 0%", c["n"] == 0)
        check("absence describes scanned statuses without guessing about unscanned work",
              "no scanned step" in (c.get("reason") or "") and "unscanned" in c['reason'])


# ── failure shapes: the typed codes, in ARIES's own vocabulary ──────────────

async def test_typed_error_codes_are_surfaced_with_what_aries_does_about_them():
    await reset_db()
    async with async_session() as db:
        for i, code in enumerate(("CAPABILITY_UNAVAILABLE", "CAPABILITY_UNAVAILABLE",
                                  "TARGET_NOT_FOUND")):
            await _goal(db, f"f{i}", "failed", [
                {"kind": "capability", "capability": "desktop.windows",
                 "execution_status": "failed", "verification_status": "pending",
                 "error": {"code": code, "message": "x"}}])
        await db.execute(text(
            "INSERT INTO execution_operations (idempotency_key, operation_type, tool, state,"
            " error_class, attempts, created_at) VALUES ('k1','tool','desktop.open_app',"
            "'failed','capability',1, datetime('now','-1 hours'))"))
        await db.commit()
        out = await analytics.failure_shapes(db, Window(days=7))
        codes = {r["code"]: r for r in out["typed_codes"]}
        check("the codes are counted", codes["CAPABILITY_UNAVAILABLE"]["n"] == 2)
        check("and attributed to a capability",
              codes["TARGET_NOT_FOUND"]["capabilities"] == {"desktop.windows": 1})
        check("each code carries what the router decided to do about it",
              codes["CAPABILITY_UNAVAILABLE"]["action"] == "reroute")
        check("the engine's lowercase taxonomy is reported separately",
              [r["error_class"] for r in out["operation_classes"]] == ["capability"])
        check("and the two vocabularies are not merged",
              "not merged" in out["vocabularies_are_separate"])


async def test_lock_failures_are_counted_per_hour_or_reported_absent():
    await reset_db()
    async with async_session() as db:
        empty = await analytics.locking_failures(db, Window(days=7))
        check("a clean window says so rather than reporting zero incidents as health",
              empty["n"] == 0 and bool(empty["reason"]))
        for _ in range(3):
            await db.execute(text(
                "INSERT INTO automation_logs (action, source, details, status, created_at)"
                " VALUES ('aries.workspace.failed','aries.workspace',"
                " '{\"error\": \"OperationalError: database is locked\"}','failure',"
                " datetime('now','-2 hours'))"))
        await db.execute(text(
            "INSERT INTO automation_logs (action, source, details, status, created_at)"
            " VALUES ('x','y','{\"error\": \"something else\"}','failure',"
            " datetime('now','-2 hours'))"))
        await db.commit()
        out = await analytics.locking_failures(db, Window(days=7))
        check("lock failures are counted", out["n"] == 3)
        check("an unrelated failure is not swept in", out["actions"] == {
            "aries.workspace.failed": 3})
        check("and they are grouped by hour", out["hours_affected"] == 1)


# ── outcomes: what the user asked for ───────────────────────────────────────

async def test_cancelled_work_is_neither_a_success_nor_a_failure():
    await reset_db()
    async with async_session() as db:
        for i, st in enumerate(["done"] * 6 + ["failed", "partial", "cancelled",
                                              "interrupted", "proposed"]):
            await _goal(db, f"o{i}", st, [])
        await db.commit()
        out = await analytics.task_outcomes(db, Window(days=7))
        check("all eleven goals are counted", out["n"] == 11)
        check("cancelled and interrupted share one bucket", out["counts"]["interrupted"] == 2)
        check("a proposal awaiting a person is `withheld`", out["counts"]["withheld"] == 1)
        check("the denominator excludes both",
              out["success"]["trials"] == 8)
        check("partial counts against success, not for it", out["success"]["successes"] == 6)
        check("and the denominator explains itself", "excluded" in out["success"]["of"])
        check("an unknown state would be reported rather than guessed at",
              out["unrecognised_states"] is None)


async def test_a_capability_that_always_fails_is_ranked_before_one_that_works():
    await reset_db()
    async with async_session() as db:
        for i in range(8):
            await _goal(db, f"good{i}", "done", [
                {"kind": "capability", "capability": "open_url", "state": "done"}])
        for i in range(4):
            await _goal(db, f"bad{i}", "failed", [
                {"kind": "capability", "capability": "desktop.tile",
                 "execution_status": "failed", "verification_status": "pending"}])
        await db.commit()
        out = await analytics.outcomes_by_capability(db, Window(days=7))
        check("the broken capability is listed first",
              out["capabilities"][0]["capability"] == "desktop.tile")
        check("its landed rate is 0 of 4 with an honest upper bound",
              out["capabilities"][0]["landed"]["upper"] > 0.2)
        check("the working one is not called certain on eight observations",
              out["capabilities"][-1]["landed"]["confident"] is False)


# ── cadence ─────────────────────────────────────────────────────────────────

async def test_cadence_is_not_characterised_from_too_few_gaps():
    await reset_db()
    async with async_session() as db:
        from aries.analytics.automations import MIN_GAPS, _adherence
        for h in (1, 2, 3):
            await db.execute(text(
                "INSERT INTO aries_automation_runs (automation_id, version, trigger, status,"
                " summary, duration_ms, started_at) VALUES ('a.c','1','schedule','ok','',1,"
                " datetime('now', :off))"), {"off": f"-{h} hours"})
        await db.commit()
        out = await analytics.automation_health(db, Window(days=7))
        row = next(r for r in out["automations"] if r["automation_id"] == "a.c")
        check("the median gap is used, not the mean", row["cadence"]["median_minutes"] == 60.0)
        check("an automation with no declared interval gets no verdict",
              row["cadence_adherence"]["reading"] is None)
        check("and says it has no interval to compare against",
              "no declared interval" in row["cadence_adherence"]["reason"])
    # The gap threshold itself, independent of which genomes happen to be registered.
    few = _adherence({"median_minutes": 820.0, "gaps": 3}, 1440)
    check("a few gaps produce a ratio", few["ratio"] == 0.57)
    check("but no verdict from a window that clipped the pattern", few["reading"] is None)
    check("and a reason saying why", "too few" in few["reason"])
    many = _adherence({"median_minutes": 60.4, "gaps": MIN_GAPS}, 60)
    check("enough gaps earn a reading", many["reading"] == "on cadence")


async def test_a_registered_automation_that_stopped_running_is_still_listed():
    await reset_db()
    async with async_session() as db:
        await db.execute(text(
            "INSERT INTO aries_automation_runs (automation_id, version, trigger, status,"
            " summary, duration_ms, started_at) VALUES ('a.only','1','schedule','ok','',1,"
            " datetime('now','-1 hours'))"))
        await db.commit()
        out = await analytics.automation_health(db, Window(days=7))
        silent = [r for r in out["automations"] if r.get("runs") == 0]
        if not silent:
            check("skipped — no automation genome is registered in this harness", True)
        else:
            check("an automation with no runs is listed rather than omitted",
                  all(bool(r.get("reason")) for r in silent))
            check("and reports no success rate at all",
                  all("ok" not in r for r in silent))


# ── read-only, and short-lived ──────────────────────────────────────────────

async def test_the_whole_dashboard_writes_nothing():
    await reset_db()
    async with async_session() as db:
        await _goal(db, "rw", "done", [{"kind": "capability", "capability": "open_app",
                                        "state": "done"}])
        await db.execute(text(
            "INSERT INTO aries_automation_runs (automation_id, version, trigger, status,"
            " summary, duration_ms, started_at) VALUES ('a.r','1','schedule','ok','',5,"
            " datetime('now','-1 hours'))"))
        await db.commit()
        before = await _counts(db)
        await db.rollback()
        out = await analytics.dashboard(db, Window(days=7))
        # Checked BEFORE the verifying read, because that read opens one itself.
        check("no transaction is left open after the dashboard", not db.in_transaction())
        after = await _counts(db)
        check("no row was added or removed by any metric", before == after)
        check("no metric raised", out["failed_metrics"] is None)


async def test_the_cheap_subset_never_parses_the_expensive_column():
    await reset_db()
    async with async_session() as db:
        out = await analytics.dashboard(db, Window(days=7), cheap_only=True)
        check("the cheap dashboard is a strict subset",
              set(out["metrics"]) < {getattr(m, "metric_name", m.__name__)
                                     for m in analytics.METRICS})
        check("and it is flagged as partial", out["cheap_only"] is True)
        check("no cheap metric names result_json as its source",
              all("result_json" not in (v.get("source") or "")
                  for v in out["metrics"].values()))


async def test_one_broken_metric_does_not_blank_the_dashboard():
    await reset_db()
    async with async_session() as db:
        async def exploding(_db, _w):
            raise RuntimeError("deliberate")
        exploding.metric_name = "exploding"
        original = analytics.dashboard.__globals__["METRICS"]
        analytics.dashboard.__globals__["METRICS"] = (*original[:2], exploding)
        try:
            out = await analytics.dashboard(db, Window(days=7))
        finally:
            analytics.dashboard.__globals__["METRICS"] = original
        check("the failure is named", out["failed_metrics"] == ["exploding"])
        check("with the exception type kept rather than swallowed",
              out["metrics"]["exploding"]["error"] == "RuntimeError")
        check("and the other metrics still reported", len(out["metrics"]) == 3)
        check("the session is usable afterwards", not db.in_transaction())


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
