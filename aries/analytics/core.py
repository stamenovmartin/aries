"""Shared machinery for reading ARIES's own history back as insight.

WHY THIS MODULE EXISTS AT ALL
-----------------------------
Every number in `aries/analytics` has to answer three questions before it is
allowed to reach a dashboard, and the answers are not obvious enough to leave to
each metric:

  1. WHAT DID IT COST?  `automation_logs` holds 288,491 rows and
     `aries_workspace_goals` holds 118 MB of JSON. An aggregate that forgot to
     bound itself is not a slow dashboard, it is a stalled one — and it stalls
     while `aries-core.service` is writing to the same file. So every metric is
     windowed, every scan over the JSON column is row-capped, and every metric
     reports its own wall time in `query_ms`. A cost you cannot see is a cost you
     will ship.

  2. WHAT IF THERE IS NOTHING?  A window with no rows reports `n: 0` and a
     reason. Never 0%, never 100%. "Never ran" and "always failed" are different
     facts and only one of them is alarming — the same rule `genome.health`
     already follows, made reusable.

  3. HOW SURE IS IT?  3 of 3 is not 100%. Rates come out of
     `aries.learning.statistics.wilson`, so a dashboard cell carries its own
     interval and the user is never taught to trust a number built from four
     observations.

THE JSON COLUMN, AND THE ONE TRICK THAT MAKES IT AFFORDABLE
-----------------------------------------------------------
`aries_workspace_goals.result_json` averages 17.8 KB and reaches 615 KB, and the
table has NO index on `created_at` — so any recent-first query must sort. Written
the obvious way,

    SELECT result_json FROM aries_workspace_goals ORDER BY created_at DESC LIMIT n

SQLite puts `result_json` into the temp B-tree it sorts in, which means reading
and copying all 118 MB to answer a question about 200 rows. Measured on the live
database: 191 ms for n=200. Sorting the PRIMARY KEY instead and fetching the JSON
by key afterwards is the same answer for a tenth of the work — 17.6 ms for the
same n=200, 54 ms for n=2000. `RECENT_GOALS` below is that shape, and every
metric that opens a goal's JSON goes through it.

READ-ONLY, AND SHORT
--------------------
Nothing here writes. Each metric also ROLLS BACK when it finishes: a read
transaction left open on WAL pins the snapshot and stops `aries-core.service`
checkpointing, which is how `database is locked` happened on 2026-09-29 — and
that failure is still visible in this data (154 rows of it; see
`failures.locking_failures`). Metrics therefore do not share a snapshot with each
other, so two metrics in one dashboard may be microseconds apart. That is the
right trade: a consistent snapshot held across eight aggregates is a lock.
"""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aries.learning.statistics import wilson

# Hard ceilings. Not defaults — ceilings. A caller asking for a year of goal JSON
# is asking for a stall, and the answer is the cap plus a note saying so.
MAX_WINDOW_DAYS = 365
MAX_GOAL_SCAN = 3000


@dataclass(frozen=True)
class Window:
    """How far back to look, and how much of the expensive column to open.

    `days` bounds every metric. `goal_scan` bounds only the metrics that must
    parse `result_json`; it is a ROW cap rather than a time cap because the cost
    of that table is per row parsed, not per day covered. The two interact: the
    scan takes the most recent `goal_scan` goals *within* `days`, so a busy day
    can exhaust the cap and the metric says it did (`truncated: true`) rather
    than quietly reporting a sample as a total.
    """

    days: int = 7
    goal_scan: int = 500

    def __post_init__(self):
        object.__setattr__(self, "days", max(1, min(MAX_WINDOW_DAYS, int(self.days))))
        object.__setattr__(self, "goal_scan", max(1, min(MAX_GOAL_SCAN, int(self.goal_scan))))

    @property
    def cutoff(self) -> str:
        """The window's start, formatted as SQLite stores DATETIME in this file.

        A string, compared lexicographically, deliberately. Every timestamp here
        is written either by `datetime.utcnow()` or by SQLite's own
        `CURRENT_TIMESTAMP`, both UTC, both `YYYY-MM-DD HH:MM:SS[.ffffff]` — so
        `>=` on the text is exact and, unlike `julianday(...)`, leaves an index
        on the column usable where one exists.
        """
        return (datetime.utcnow() - timedelta(days=self.days)).isoformat(sep=" ")

    def as_dict(self) -> dict:
        return {"window_days": self.days, "goal_scan_cap": self.goal_scan,
                "cutoff_utc": self.cutoff}


DEFAULT = Window()

# The cheap half of the goal scan: sort keys, not payloads. See the module
# docstring — this is a 10x difference on the live database, not a style choice.
RECENT_GOALS = """
    SELECT id FROM aries_workspace_goals
     WHERE created_at >= :cutoff
     ORDER BY created_at DESC LIMIT :cap
"""

# Every step of every engine, one row each, for the capped goal set. Joined back
# by PRIMARY KEY so `result_json` is touched only for rows that survived the cap.
GOAL_STEPS = f"""
    WITH recent AS ({RECENT_GOALS})
    SELECT g.id AS goal_id, j.value AS step
      FROM recent r
      JOIN aries_workspace_goals g ON g.id = r.id,
           json_each(json_extract(g.result_json, '$.steps')) j
"""

# Three engines have written steps into `result_json` and they do not agree on
# shape, so the bucket is decided once, here, and every metric that classifies a
# step uses this expression. The ORDER MATTERS: an independent verification
# outranks whatever the executor claimed about itself.
#
#   verified            an independent verifier confirmed the effect happened
#   accepted            the executor reported success; NOTHING checked it
#   unconfirmed         the executor said in as many words that it could not confirm
#   failed              execution raised, or verification contradicted it
#   withheld            stopped at the policy gate, or frozen as a proposal for a person
#   pending             planned, and the engine recorded that it never executed
#   no_outcome_recorded the step exists in the plan and carries NO status field at
#                       all — the older engines wrote the intent and then nothing.
#                       Kept as its own bucket rather than swept into `pending`
#                       because "we know it did not run" and "we have no idea what
#                       happened" are different admissions, and the second is a
#                       recording gap worth seeing. 23 of 271 steps in the last
#                       week on this machine.
#   unclassified        a state this table has never seen. Should be 0; if it is
#                       not, a new state was introduced and this expression is out
#                       of date.
#
# `accepted` is a separate bucket from `verified` on purpose. Collapsing them is
# exactly the dishonesty `integrity.py` exists to measure.
STEP_BUCKET = """
    CASE
      WHEN json_extract(step, '$.verification_status') = 'verified'            THEN 'verified'
      WHEN json_extract(step, '$.verification_status') = 'verification_failed' THEN 'failed'
      WHEN json_extract(step, '$.execution_status')    = 'failed'             THEN 'failed'
      WHEN json_extract(step, '$.execution_status')    = 'planned'            THEN 'pending'
      WHEN json_extract(step, '$.state')               = 'unconfirmed'        THEN 'unconfirmed'
      WHEN json_extract(step, '$.state')  IN ('held', 'proposed')             THEN 'withheld'
      WHEN json_extract(step, '$.state')               = 'failed'             THEN 'failed'
      WHEN json_extract(step, '$.state')  IN ('done', 'verified')             THEN 'accepted'
      WHEN json_extract(step, '$.state')            IS NULL
       AND json_extract(step, '$.execution_status') IS NULL
       AND json_extract(step, '$.verification_status') IS NULL   THEN 'no_outcome_recorded'
      ELSE 'unclassified'
    END
"""

# Nearest-rank percentiles, in SQL, in one pass. SQLite has no percentile
# aggregate, and pulling the values into Python to sort them there is the
# unbounded-aggregate mistake this package is supposed to avoid — so rank the
# rows with a window function and pick the value at ceil(p*n).
#
# `(n*50+99)/100` is integer ceil(n/2): SQLite's `/` on two integers truncates.
# Because `o` is ordered ascending by `rn`, MAX(x) over `rn <= k` IS the value at
# rank k. Verified against a hand-sorted list on the live data (n=323, p50=104,
# p90=7565).
#
# On empty input the outer aggregate still returns one row, of NULLs — which is
# why `distribution` checks `n` before believing any of it.
_DISTRIBUTION = """
    WITH v AS ({inner}),
         o AS (SELECT x, ROW_NUMBER() OVER (ORDER BY x) rn, COUNT(*) OVER () n FROM v)
    SELECT n, MIN(x), MAX(x), AVG(x),
           MAX(CASE WHEN rn <= (n*50+99)/100 THEN x END),
           MAX(CASE WHEN rn <= (n*90+99)/100 THEN x END),
           MAX(CASE WHEN rn <= (n*99+99)/100 THEN x END)
      FROM o
"""


def absent(reason: str, **extra) -> dict:
    """What a metric returns when the window holds nothing.

    `n: 0` plus a sentence. No rate, not even a null one dressed up as a number —
    a dashboard that renders 0% for "nothing happened" teaches the user that
    ARIES fails constantly, and a dashboard that renders 100% teaches them to
    trust an empty set.
    """
    return {"n": 0, "reason": reason, **extra}


def rate(successes: int, trials: int, *, of: str) -> dict:
    """A proportion that carries its own uncertainty, and names its denominator.

    `of` is not decoration. "success rate" means nothing until you know what was
    counted as a trial, and every caller here answers a slightly different
    question — so the answer travels with the number.
    """
    if trials <= 0:
        return {"rate": None, "trials": 0, "of": of,
                "reason": "nothing to divide by in this window"}
    iv = wilson(successes, trials)
    d = iv.as_dict()
    d["of"] = of
    # The point estimate is for display; `lower`/`upper` are what a decision
    # should read. Width is the honest headline: 3 of 3 comes back 0.44-1.00.
    d["confident"] = iv.width <= 0.2
    return d


async def distribution(db: AsyncSession, inner: str, params: dict, *, unit: str = "ms",
                       what: str = "") -> dict:
    """min / p50 / p90 / p99 / max / mean for an `SELECT ... AS x` subquery.

    The mean is reported LAST and never alone. On this machine's automation runs
    the mean is 3,111 ms and the median is 104 ms: the mean is describing one
    four-minute health pass, not the experience of running an automation. The
    percentiles are the metric; the mean is there so the gap between them is
    visible.
    """
    row = (await db.execute(text(_DISTRIBUTION.format(inner=inner)), params)).first()
    if row is None or row[0] in (None, 0):
        return absent(f"no {what or 'samples'} recorded in this window", unit=unit)
    n, mn, mx, mean, p50, p90, p99 = row
    return {"n": int(n), "unit": unit, "min": _num(mn), "p50": _num(p50), "p90": _num(p90),
            "p99": _num(p99), "max": _num(mx), "mean": _num(mean),
            # A mean far above p50 means a long tail; say so rather than making
            # the reader divide two numbers to find out.
            "tail_ratio": round(mean / p50, 1) if p50 else None}


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f == int(f) else round(f, 3)


def metric(name: str, *, source: str, cost: str):
    """Wrap a metric so it always reports what it cost and lets go of the file.

    `source` and `cost` are recorded in the payload because the first two
    questions anyone asks a dashboard number are "where is that from?" and "what
    did asking cost?", and a docstring cannot answer them at runtime.

    The rollback is the load-bearing part: see the module docstring.
    """
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(db: AsyncSession, window: Window | None = None, **kw) -> dict:
            w = window or DEFAULT
            t0 = time.perf_counter()
            try:
                out = await fn(db, w, **kw)
            finally:
                await db.rollback()
            out.update(metric=name, source=source, cost=cost,
                       query_ms=round((time.perf_counter() - t0) * 1000, 1),
                       **w.as_dict())
            return out
        wrapper.metric_name = name
        return wrapper
    return deco
