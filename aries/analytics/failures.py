"""What kind of failure, not how many — the most actionable table in the system.

"12 failures this week" is a number you can do nothing with. "12 failures, all
CAPABILITY_UNAVAILABLE, all on desktop.windows" names a thing to fix. ARIES
already types every failure at the moment it happens; nothing has ever read those
types back.

FOUR TAXONOMIES, THREE OF THEM REAL, AND THEY ARE NOT MERGED
------------------------------------------------------------
  typed_codes    `$.error.code` on a goal's steps. ARIES's own vocabulary, from
                 `aries/workspace/agent.py`: TRANSIENT, NETWORK_ERROR,
                 CAPABILITY_UNAVAILABLE, PERMISSION_REQUIRED, TARGET_NOT_FOUND,
                 VERIFICATION_FAILED, AUTH_REQUIRED, AMBIGUOUS, NON_RETRYABLE.
                 Each is annotated with what `orchestration.ROUTE` decided to do
                 about it — retry, reroute or stop — because the count is only
                 half the story: 13 reroutes and 13 dead stops are different
                 weeks.
  operation_class `execution_operations.error_class`. The ENGINE's taxonomy, and a
                 different, lowercase one: unknown, validation, capability,
                 transient, uncertain, policy, auth. Reported beside the typed
                 codes, never folded into them — mapping `unknown` onto
                 `NON_RETRYABLE` would be inventing data.
  log_failures   `automation_logs` rows with `status='failure'`, grouped by
                 action. This is where the infrastructure failures live, and on
                 this machine 154 of them are one sentence: `database is locked`,
                 on the same UPDATE, once an hour. That is the 2026-09-29
                 incident, still happening, and no other metric in ARIES shows
                 it.
  task_class     `tasks.error_class`. Recorded, but only ever `uncertain` (7
                 rows), so it is reported as-is and carries a note saying it
                 carries almost no information.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aries.analytics.core import GOAL_STEPS, Window, absent, metric

# What each code means and what ARIES does about it, read from the routing table
# rather than copied — a copy would silently stop matching behaviour. Imported
# lazily because `aries.workspace.orchestration` costs ~500 ms to import and an
# analytics call must not pay that to annotate a column.
_ROUTE: dict | None = None


def _routing() -> dict:
    global _ROUTE
    if _ROUTE is None:
        try:
            from aries.workspace.orchestration import ROUTE
            _ROUTE = {k: {"action": v[0], "why": v[1]} for k, v in ROUTE.items()}
        except Exception:                                            # noqa: BLE001
            # Degrade to no annotation rather than failing the whole dashboard:
            # the counts are the metric, the annotation is a courtesy.
            _ROUTE = {}
    return _ROUTE


@metric("failure_shapes", source="goal steps, execution_operations, automation_logs, tasks",
        cost="one capped result_json parse (~27 ms / 600 goals) plus three indexed GROUP BYs "
             "(~1 ms each); automation_logs is filtered on an indexed created_at, so the "
             "288k-row table is never scanned whole")
async def failure_shapes(db: AsyncSession, window: Window) -> dict:
    """Every failure taxonomy ARIES records, each kept in its own vocabulary."""
    routing = _routing()

    typed = (await db.execute(text(f"""
        WITH steps AS ({GOAL_STEPS})
        SELECT json_extract(step, '$.error.code')  AS code,
               COALESCE(json_extract(step, '$.capability'), '(none)') AS cap,
               COUNT(*) AS n
          FROM steps
         WHERE json_extract(step, '$.error.code') IS NOT NULL
         GROUP BY code, cap ORDER BY n DESC
    """), {"cutoff": window.cutoff, "cap": window.goal_scan})).all()

    by_code: dict[str, dict] = {}
    for code, cap, n in typed:
        e = by_code.setdefault(code, {"code": code, "n": 0, "capabilities": {},
                                      **(routing.get(code) or {})})
        e["n"] += int(n)
        e["capabilities"][cap] = int(n)
    typed_codes = sorted(by_code.values(), key=lambda r: -r["n"])

    op_rows = (await db.execute(text(
        "SELECT COALESCE(error_class, '(none)'), COALESCE(tool, '(none)'), COUNT(*)"
        "  FROM execution_operations"
        " WHERE created_at >= :cutoff AND state IN ('failed', 'uncertain')"
        " GROUP BY 1, 2 ORDER BY 3 DESC"), {"cutoff": window.cutoff})).all()
    op_class: dict[str, dict] = {}
    for cls, tool, n in op_rows:
        e = op_class.setdefault(cls, {"error_class": cls, "n": 0, "tools": {}})
        e["n"] += int(n)
        e["tools"][tool] = int(n)

    logs = (await db.execute(text(
        "SELECT action, COALESCE(source, '(none)'), COUNT(*), MAX(created_at)"
        "  FROM automation_logs"
        " WHERE created_at >= :cutoff AND status = 'failure'"
        " GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20"), {"cutoff": window.cutoff})).all()

    task_cls = (await db.execute(text(
        "SELECT error_class, COUNT(*) FROM tasks"
        " WHERE created_at >= :cutoff AND error_class IS NOT NULL"
        " GROUP BY 1 ORDER BY 2 DESC"), {"cutoff": window.cutoff})).all()

    total = sum(r["n"] for r in typed_codes) + sum(r["n"] for r in op_class.values()) \
        + sum(int(r[2]) for r in logs)
    if total == 0:
        return absent("nothing failed in this window — or nothing ran")
    return {
        "n": total,
        "typed_codes": typed_codes or None,
        "typed_codes_reason": None if typed_codes else
            "no step in the scanned goals carried an $.error.code — only the M14 orchestration "
            "engine writes them, and the window may contain none of its runs",
        "operation_classes": sorted(op_class.values(), key=lambda r: -r["n"]) or None,
        "log_failures": [{"action": a, "source": s, "n": int(n), "last_at": last}
                         for a, s, n, last in logs] or None,
        "task_error_classes": ({c: int(n) for c, n in task_cls} or None),
        "task_error_classes_note": "tasks.error_class only ever holds 'uncertain' on this "
                                   "machine; it distinguishes nothing",
        "vocabularies_are_separate": "typed_codes are ARIES's own uppercase codes; "
                                     "operation_classes are the engine's lowercase ones. They "
                                     "are not merged because no recorded mapping exists",
    }


@metric("locking_failures", source="automation_logs",
        cost="one indexed range scan plus a LIKE on the filtered rows; ~2 ms. The LIKE only "
             "ever sees rows already narrowed by created_at AND status='failure'")
async def locking_failures(db: AsyncSession, window: Window) -> dict:
    """`database is locked`, counted — the 2026-09-29 incident, still open.

    Broken out of `failure_shapes` because it is not one failure among many: it is
    a writer losing to another writer on a single-file database, it recurs on a
    schedule, and it is invisible everywhere else in ARIES. The count per hour is
    the useful shape, since a steady hourly rate and a burst mean different
    things.
    """
    # Hour and action in one pass. The LIKE is the expensive part of this query, so
    # it is paid once and grouped by both keys rather than run twice.
    rows = (await db.execute(text(
        "SELECT substr(created_at, 1, 13) AS hour, action, COUNT(*)"
        "  FROM automation_logs"
        " WHERE created_at >= :cutoff AND status = 'failure'"
        "   AND details LIKE '%database is locked%'"
        " GROUP BY hour, action ORDER BY hour DESC"), {"cutoff": window.cutoff})).all()
    if not rows:
        return absent("no 'database is locked' failure was logged in this window")
    per_hour: dict[str, int] = {}
    per_action: dict[str, int] = {}
    for hour, action, c in rows:
        per_hour[hour] = per_hour.get(hour, 0) + int(c)
        per_action[action] = per_action.get(action, 0) + int(c)
    return {"n": sum(per_hour.values()), "hours_affected": len(per_hour),
            "per_hour_max": max(per_hour.values()),
            "recent_hours": [{"hour_utc": h, "n": c} for h, c in list(per_hour.items())[:24]],
            "actions": dict(sorted(per_action.items(), key=lambda kv: -kv[1])),
            "means": "a writer lost the file lock to another writer. Recurring at a steady "
                     "hourly rate means a scheduled job is colliding with something, not that "
                     "the machine is overloaded"}
