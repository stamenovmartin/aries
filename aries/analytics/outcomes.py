"""What happened to the things the user asked for.

`aries_workspace_goals` is the only table that records a request the user made
and what became of it, so it is the only honest source for "does ARIES work?".
The engine's own `tasks`/`task_runs` tables look like a better answer — 1,101 of
1,108 runs verdict `pass` — but on this machine every one of those was created by
an automation (`created_by` is `automation:aries.health` and friends), so their
success rate measures the scheduler, not ARIES. Both are reported, separately and
labelled, because conflating them would produce a 99% headline that is true of
the wrong population.

THE BUCKETS, AND WHY `partial` IS NOT A SUCCESS
----------------------------------------------
Goal states as recorded: done, answered, partial, failed, cancelled,
interrupted, proposed.

`answered` is the success of a QUESTION rather than of an action, and it counts
as one. It was previously unlisted, so it fell into `unrecognised_states` and
was in neither the numerator nor the denominator — the module reported it rather
than hiding it, which is how it was noticed, but a question ARIES answered is not
an unknown outcome. The distinction is not lost by counting it: `states` returns
the raw per-state breakdown, so `answered` stays separately visible there while
`counts.succeeded` includes it. Response shape is unchanged, deliberately —
a new bucket key would break a dashboard that already reads these.

  succeeded    done
  partial      partial      — some sub-goals verified, some did not
  failed       failed
  withheld     proposed, needs_clarification — ARIES deliberately did not act.
                              `proposed` is frozen for a person to approve;
                              `needs_clarification` is ARIES asking which one was
                              meant instead of guessing. Counting either as a
                              failure makes correct behaviour look broken, and
                              counting it as a success is worse. On 2026-10-03
                              there were 35 of them in `unrecognised_states` — in
                              neither numerator nor denominator — which is how
                              they were noticed; the module reported them rather
                              than hiding them, and that is the design working.
  interrupted  interrupted, cancelled — the process died or the user stopped it

The Wilson interval is taken over succeeded / (succeeded + partial + failed): the
outcomes ARIES is answerable for. `withheld` and `interrupted` are excluded from
the denominator and reported next to it, because counting a request the user
cancelled as a failure makes ARIES look broken when it behaved correctly, and
counting it as a success is worse.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aries.analytics.core import GOAL_STEPS, STEP_BUCKET, Window, absent, metric, rate

# Which recorded state lands in which bucket. Anything unlisted is reported as
# `other` rather than guessed at — a new state appearing is news, not noise.
BUCKETS = {"done": "succeeded", "answered": "succeeded",
           "partial": "partial", "failed": "failed",
           "proposed": "withheld", "needs_clarification": "withheld",
           "interrupted": "interrupted", "cancelled": "interrupted"}
ANSWERABLE = ("succeeded", "partial", "failed")


@metric("task_outcomes", source="aries_workspace_goals",
        cost="one GROUP BY over an unindexed created_at; reads no result_json. "
             "~9 ms / 6,600 rows measured")
async def task_outcomes(db: AsyncSession, window: Window) -> dict:
    """Success / partial / failed / withheld over the window, with an interval.

    Cheap despite the 118 MB table: `created_at` and `state` both sit before
    `result_json` in the row, so SQLite never follows the overflow pages.
    """
    rows = (await db.execute(text(
        "SELECT state, COUNT(*) FROM aries_workspace_goals"
        " WHERE created_at >= :cutoff GROUP BY state"), {"cutoff": window.cutoff})).all()
    if not rows:
        return absent("no goals were submitted in this window")
    states = {s: int(n) for s, n in rows}
    counts = {b: 0 for b in ("succeeded", "partial", "failed", "withheld", "interrupted")}
    other: dict[str, int] = {}
    for s, n in states.items():
        b = BUCKETS.get(s)
        (counts if b else other)[b or s] = (counts.get(b, 0) + n) if b else n
    answerable = sum(counts[b] for b in ANSWERABLE)
    return {"n": sum(states.values()), "counts": counts, "states": states,
            "unrecognised_states": other or None,
            "success": rate(counts["succeeded"], answerable,
                            of="goals ARIES is answerable for (done + partial + failed); "
                               "withheld and interrupted are excluded and listed separately"),
            "failure_share": rate(counts["failed"], answerable,
                                  of="the same denominator, counting failures")}


@metric("outcomes_by_capability", source="aries_workspace_goals.result_json (steps)",
        cost="parses result_json for up to `goal_scan` goals. ~27 ms / 600 goals, "
             "~54 ms / 2,000 measured")
async def outcomes_by_capability(db: AsyncSession, window: Window, *,
                                 top: int = 25) -> dict:
    """Which capabilities actually fail, and how often — the point of the whole file.

    One row per capability, bucketed by `core.STEP_BUCKET`, with a Wilson
    interval over landed / attempted. `withheld` and `pending` are attempts that
    never reached the world, so they stay out of the denominator; `accepted` and
    `unconfirmed` stay IN it and count as landed, because the user did get an
    effect — whether anyone checked it is `integrity.py`'s question, not this
    one.
    """
    rows = (await db.execute(text(f"""
        WITH steps AS ({GOAL_STEPS})
        SELECT COALESCE(json_extract(step, '$.capability'), '(none)') AS cap,
               {STEP_BUCKET} AS bucket, COUNT(*) AS n
          FROM steps GROUP BY cap, bucket
    """), {"cutoff": window.cutoff, "cap": window.goal_scan})).all()
    if not rows:
        return absent("no capability steps were recorded in this window")

    per: dict[str, dict] = {}
    for cap, bucket, n in rows:
        per.setdefault(cap, {})[bucket] = int(n)
    out = []
    for cap, b in per.items():
        landed = b.get("verified", 0) + b.get("accepted", 0) + b.get("unconfirmed", 0)
        attempted = landed + b.get("failed", 0)
        out.append({"capability": cap, "attempts": sum(b.values()), "buckets": b,
                    "landed": rate(landed, attempted,
                                   of="steps that reached the world (verified + accepted + "
                                      "unconfirmed) out of those that tried")})
    # Ordered by how much trouble a capability is in, not alphabetically: the
    # widest-interval / lowest-lower-bound rows are the ones worth reading.
    out.sort(key=lambda r: (r["landed"].get("lower") or 0.0, -r["attempts"]))
    scanned = (await db.execute(text(
        "SELECT COUNT(*) FROM aries_workspace_goals WHERE created_at >= :cutoff"),
        {"cutoff": window.cutoff})).scalar() or 0
    return {"n": sum(r["attempts"] for r in out), "capabilities": out[:top],
            "capability_count": len(out), "goals_in_window": int(scanned),
            "truncated": int(scanned) > window.goal_scan,
            "note": None if int(scanned) <= window.goal_scan else
                    f"{scanned} goals in the window, only the {window.goal_scan} most recent "
                    f"were parsed — this is a sample, not a total"}


@metric("engine_task_outcomes", source="tasks + task_runs",
        cost="two GROUP BYs over 1,100-row tables, status indexed. ~1 ms")
async def engine_task_outcomes(db: AsyncSession, window: Window) -> dict:
    """The scheduler's own reliability. Reported separately and labelled as such.

    Every task in this table on this machine was created by an automation, so
    this is the health of the automation runner, not of ARIES answering a person.
    Kept because a divergence between the two is itself the signal: a green
    scheduler over a red goal table means the work is being started and not
    finished.
    """
    runs = (await db.execute(text(
        'SELECT status, verdict, COUNT(*) FROM task_runs'
        ' WHERE started_at >= :cutoff GROUP BY status, verdict'),
        {"cutoff": window.cutoff})).all()
    if not runs:
        return absent("no engine task runs in this window")
    by_status: dict[str, int] = {}
    by_verdict: dict[str, int] = {}
    for status, verdict, n in runs:
        by_status[status] = by_status.get(status, 0) + int(n)
        by_verdict[verdict or "(none)"] = by_verdict.get(verdict or "(none)", 0) + int(n)
    total = sum(by_status.values())
    kinds = (await db.execute(text(
        "SELECT created_by, COUNT(*) FROM tasks WHERE created_at >= :cutoff"
        " GROUP BY created_by ORDER BY 2 DESC LIMIT 12"), {"cutoff": window.cutoff})).all()
    return {"n": total, "by_status": by_status, "by_verdict": by_verdict,
            "created_by": {k or "(none)": int(v) for k, v in kinds},
            "done": rate(by_status.get("done", 0), total, of="engine task runs in the window"),
            "caveat": "these runs were started by automations, not by the user — this measures "
                      "the scheduler, not whether ARIES did what a person asked"}
