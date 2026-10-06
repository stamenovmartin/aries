"""Per-automation health, and the question `genome.health` does not ask: cadence.

`genome.health` already gives a per-automation success rate over a window and is
already honest about an empty window. Two things it does not do, both of which
the data supports:

  1. An INTERVAL. `aries.learning` has run 8 times, all ok. `genome.health`
     reports 1.0. The Wilson lower bound is 0.63, and the difference matters: one
     of those numbers invites the user to stop watching.

  2. CADENCE ADHERENCE. An automation that succeeds every time it runs but runs
     half as often as it is supposed to is broken in a way no success rate can
     show. The observed median gap between consecutive runs is compared against
     the declared interval from the genome — `schedule_setting` resolved through
     `SettingsService`, exactly as `genome.due` resolves it, so the two cannot
     disagree. A time-of-day automation (`time_setting`, e.g. the 07:30 brief) is
     expected daily, so its target is 1,440 minutes.

Gaps come from a LAG window function rather than from pulling timestamps into
Python, and the median gap rather than the mean: a machine asleep overnight
produces one enormous gap that would drag a mean past every real one.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aries.analytics.core import Window, absent, metric, rate

# Median gap per automation, in minutes, in one query. Same nearest-rank trick as
# `core._DISTRIBUTION`, partitioned. The first run of each automation has a NULL
# gap by definition and is excluded; `runs_paired` reports how many gaps there
# actually were, so "cadence from a single gap" is visible as such.
_CADENCE = """
    WITH g AS (
        SELECT automation_id, started_at,
               (julianday(started_at) - julianday(
                   LAG(started_at) OVER (PARTITION BY automation_id ORDER BY started_at)
               )) * 1440.0 AS gap
          FROM aries_automation_runs
         WHERE started_at >= :cutoff
    ),
    o AS (SELECT automation_id, gap,
                 ROW_NUMBER() OVER (PARTITION BY automation_id ORDER BY gap) rn,
                 COUNT(*) OVER (PARTITION BY automation_id) n
            FROM g WHERE gap IS NOT NULL)
    SELECT automation_id, n, MIN(gap), MAX(CASE WHEN rn <= (n*50+99)/100 THEN gap END), MAX(gap)
      FROM o GROUP BY automation_id, n
"""

# Below this many observed gaps, a ratio is reported but never characterised. Four
# is where a daily automation inside a one-week window stops being clipped by the
# window's own edges.
MIN_GAPS = 5


_STATUS = """
    SELECT automation_id, status, COUNT(*), MAX(started_at),
           MAX(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END)
      FROM aries_automation_runs
     WHERE started_at >= :cutoff
     GROUP BY automation_id, status
"""


@metric("automation_health", source="aries_automation_runs (+ genome specs & settings)",
        cost="two GROUP BYs over an index on started_at (1,265 rows total, ~3 ms) plus one "
             "settings read per registered automation")
async def automation_health(db: AsyncSession, window: Window) -> dict:
    """One row per automation: outcome mix with an interval, last run, cadence.

    Automations with a registered genome but no run in the window are listed with
    `runs: 0` and a reason rather than omitted — an automation that stopped
    running is the thing the user most needs to see, and silence looks identical
    to health.
    """
    status_rows = (await db.execute(text(_STATUS), {"cutoff": window.cutoff})).all()
    cadence_rows = (await db.execute(text(_CADENCE), {"cutoff": window.cutoff})).all()
    cadence = {a: {"gaps": int(n), "min_minutes": round(float(mn), 1),
                   "median_minutes": round(float(med), 1), "max_minutes": round(float(mx), 1)}
               for a, n, mn, med, mx in cadence_rows}

    per: dict[str, dict] = {}
    for aid, status, n, last, _dur in status_rows:
        e = per.setdefault(aid, {"counts": {}, "last_run_at": None})
        e["counts"][status] = int(n)
        if last and (e["last_run_at"] is None or last > e["last_run_at"]):
            e["last_run_at"] = last

    declared = await _declared_intervals(db)
    out = []
    for aid in sorted(set(per) | set(declared)):
        e = per.get(aid)
        if e is None:
            out.append({"automation_id": aid, "runs": 0,
                        "reason": "registered but has not run in this window",
                        "declared_interval_minutes": declared.get(aid, {}).get("minutes"),
                        "enabled": declared.get(aid, {}).get("enabled")})
            continue
        counts = e["counts"]
        total = sum(counts.values())
        # `skipped` is the scheduler correctly declining ("ran 40 min ago"), not a
        # failure, so it leaves the denominator instead of dragging the rate down.
        attempted = total - counts.get("skipped", 0)
        d = declared.get(aid, {})
        row = {"automation_id": aid, "runs": total, "counts": counts,
               "last_run_at": e["last_run_at"],
               "ok": rate(counts.get("ok", 0), attempted,
                          of="runs that actually attempted work (skipped runs excluded)"),
               "declared_interval_minutes": d.get("minutes"),
               "paced_by": d.get("paced_by"), "enabled": d.get("enabled"),
               "cadence": cadence.get(aid) or {
                   "gaps": 0, "reason": "only one run in this window — no gap to measure"}}
        row["cadence_adherence"] = _adherence(row["cadence"], d.get("minutes"))
        out.append(row)

    durations = (await db.execute(text(
        "SELECT automation_id, COUNT(*), CAST(AVG(duration_ms) AS INTEGER), MAX(duration_ms)"
        "  FROM aries_automation_runs WHERE started_at >= :cutoff AND duration_ms IS NOT NULL"
        " GROUP BY 1"), {"cutoff": window.cutoff})).all()
    dur = {a: {"n": int(n), "mean_ms": int(m or 0), "max_ms": int(x or 0)}
           for a, n, m, x in durations}
    for row in out:
        row["duration"] = dur.get(row["automation_id"])

    ran = sum(r.get("runs", 0) for r in out)
    if not ran:
        # The registered-but-silent rows are still worth returning — an automation
        # that stopped is the thing the user most needs to see — but a window in
        # which nothing ran has no reliability to report and must say so.
        return absent("no automation ran in this window" if declared else
                      "no automation has run and none is registered", automations=out)
    return {"n": ran, "automations": out,
            "note": "per-run duration percentiles are in the `latency` metric; these are the "
                    "cheap mean/max only, to keep this query to two scans"}


async def _declared_intervals(db: AsyncSession) -> dict:
    """What each genome says its cadence should be, resolved through settings.

    Resolved the same way `genome.due` resolves it, so a user who changed the
    interval sees their own number. Failures are swallowed per automation: a
    missing setting definition should cost one cell, not the whole metric.
    """
    try:
        from aries.automations import genome
        from aries.settings import SettingsService
    except Exception:                                                # noqa: BLE001
        return {}
    settings = SettingsService(db)
    out: dict[str, dict] = {}
    for spec in genome.all_automations():
        try:
            enabled = await genome.is_enabled(spec, settings)
            if spec.time_setting:
                # Paced by a moment in the user's day, not by elapsed minutes, so
                # the only meaningful target is "once a day".
                out[spec.automation_id] = {"minutes": 1440, "paced_by": "time_of_day",
                                           "enabled": enabled}
            else:
                out[spec.automation_id] = {
                    "minutes": await genome.interval_minutes(spec, settings),
                    "paced_by": "interval", "enabled": enabled}
        except Exception:                                            # noqa: BLE001
            out[spec.automation_id] = {"minutes": None, "paced_by": None, "enabled": None}
    return out


def _adherence(cadence: dict, target: float | None) -> dict:
    """Observed median gap against the declared interval.

    A ratio, not a verdict. The scheduler paces from the LAST RECORDED RUN and
    catches up after a sleep, so a ratio slightly above 1 is normal and expected
    — the interesting readings are well above (running late, or the machine is
    off) and well below (something is triggering it out of band).
    """
    med, gaps = cadence.get("median_minutes"), cadence.get("gaps", 0)
    if not target or not gaps or med is None:
        return {"ratio": None, "reading": None,
                "reason": "no declared interval" if not target else
                          "not enough runs in this window to measure a gap"}
    ratio = round(med / target, 2)
    if gaps < MIN_GAPS:
        # A handful of gaps is not a cadence. Report the ratio and refuse to
        # characterise it — the daily brief with three gaps in a seven-day window
        # comes out at ratio 0.57, which would read as "running twice as often as
        # declared" when what actually happened is that the window clipped the
        # pattern at both ends.
        return {"ratio": ratio, "target_minutes": target, "gaps": gaps, "reading": None,
                "reason": f"only {gaps} gap(s) observed — too few to call this a cadence"}
    reading = ("on cadence" if 0.8 <= ratio <= 1.3 else
               "running late" if ratio > 1.3 else "running more often than declared")
    return {"ratio": ratio, "target_minutes": target, "gaps": gaps, "reading": reading}
