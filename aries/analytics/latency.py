"""How long things took — as a distribution, because a mean is a different question.

Measured on this machine's automation runs: mean 3,111 ms, median 104 ms, p90
7,565 ms, max 233,356 ms. The mean is describing a four-minute health pass; the
median is describing what running an automation actually feels like. Reporting
the mean alone would have said "3 seconds" about an experience that is either
instant or four minutes and never three seconds.

FOUR CLOCKS, AND WHAT EACH ONE ACTUALLY TIMES
---------------------------------------------
  automation_runs   `aries_automation_runs.duration_ms`, written by the runner.
                    Whole-automation wall time. Always present.
  executor_steps    `agent_steps.duration_ms` for `agent='executor'`. The other
                    1,101 rows are `agent='evaluator'` and every one has a NULL
                    duration, so the evaluator is NOT timed and this file does not
                    pretend otherwise.
  model_generation  `$.latency_ms` on `aries_intelligence_events` kind
                    `generation`, split by level — local vs cloud is the
                    difference the user feels and averaging across it is
                    meaningless.
  routing           `$.latency_ms` on kind `route`. How long ARIES took to decide
                    what the request was, before doing any of it.

GOAL WALL TIME IS DELIBERATELY NOT HERE. `aries_workspace_goals` has no duration
column, so the only candidate is `updated_at - created_at`, and on the live data
six of 6,637 rows come out NEGATIVE — up to -7,173 s, in two clean bursts on
2026-09-17 and 2026-09-23, which is a host clock stepping backwards about two
hours, not a measurement. `goal_elapsed` reports that estimate WITH the count of
rows it had to discard, and says in the payload that it is an estimate. A single
mean over that column would have been -41.9 s, and a dashboard that shows a
negative duration has already lost the user.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aries.analytics.core import Window, absent, distribution, metric

_AUTOMATION = ("SELECT duration_ms AS x FROM aries_automation_runs"
               " WHERE started_at >= :cutoff AND duration_ms IS NOT NULL")
_EXECUTOR = ("SELECT duration_ms AS x FROM agent_steps"
             " WHERE at >= :cutoff AND agent = 'executor' AND duration_ms IS NOT NULL")
_INTEL = ("SELECT json_extract(data_json, '$.latency_ms') AS x FROM aries_intelligence_events"
          " WHERE kind = :kind AND created_at >= :cutoff"
          "   AND json_extract(data_json, '$.latency_ms') IS NOT NULL")
_INTEL_LEVEL = _INTEL + " AND json_extract(data_json, '$.level') = :level"


@metric("latency", source="aries_automation_runs, agent_steps, aries_intelligence_events",
        cost="one indexed range scan per distribution, ranked by a window function; "
             "6 queries, ~13 ms total measured")
async def latency(db: AsyncSession, window: Window) -> dict:
    """Every clock ARIES actually keeps, each as its own distribution."""
    out = {
        "automation_runs": await distribution(db, _AUTOMATION, {"cutoff": window.cutoff},
                                              what="automation runs"),
        "executor_steps": await distribution(db, _EXECUTOR, {"cutoff": window.cutoff},
                                             what="executor steps"),
        "routing": await distribution(db, _INTEL, {"cutoff": window.cutoff, "kind": "route"},
                                      what="routing decisions"),
        "model_generation": {},
    }
    # Split by level rather than averaged over it: local and cloud are not the
    # same population and the combined median would describe neither.
    for level in ("local", "cloud"):
        out["model_generation"][level] = await distribution(
            db, _INTEL_LEVEL, {"cutoff": window.cutoff, "kind": "generation", "level": level},
            what=f"{level} model calls")
    out["n"] = sum(v.get("n", 0) for v in (out["automation_runs"], out["executor_steps"],
                                           out["routing"], *out["model_generation"].values()))
    if not out["n"]:
        # Every sub-distribution already carries its own reason; the caller reads
        # the top-level `n` first, so it needs one too.
        return absent("no clock recorded a single sample in this window", **out)
    out["reads"] = "median and p90 are the metric; `mean` and `tail_ratio` are there to show " \
                   "how much the mean is lying"
    return out


@metric("goal_elapsed", source="aries_workspace_goals.updated_at - created_at",
        cost="one scan of two DATETIME columns, no result_json. ~8 ms")
async def goal_elapsed(db: AsyncSession, window: Window) -> dict:
    """Estimated wall time of a whole user request, and why it is only an estimate.

    There is no duration column, so this is the gap between two timestamps
    written by different code paths. Rows where the gap is negative are dropped
    and counted, not clamped: a clamped clock error becomes a plausible-looking
    zero and stops being investigable.
    """
    bad = (await db.execute(text(
        "SELECT COUNT(*) FROM aries_workspace_goals"
        " WHERE created_at >= :cutoff AND updated_at < created_at"),
        {"cutoff": window.cutoff})).scalar() or 0
    dist = await distribution(db, (
        "SELECT CAST((julianday(updated_at) - julianday(created_at)) * 86400000 AS INTEGER) AS x"
        "  FROM aries_workspace_goals"
        " WHERE created_at >= :cutoff AND updated_at >= created_at"),
        {"cutoff": window.cutoff}, what="completed goals")
    dist.update(estimate=True, discarded_negative=int(bad),
                caveat="derived from two timestamps, not measured; rows with updated_at earlier "
                       "than created_at are host clock steps and were discarded, not clamped")
    return dist if dist.get("n") else absent(
        "no goal in this window has a usable elapsed time", estimate=True,
        discarded_negative=int(bad))
