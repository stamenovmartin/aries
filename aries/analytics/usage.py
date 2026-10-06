"""What the user actually asks for — which is what tells you what to improve next.

A failure rate says what is broken. Usage says what is worth fixing. A capability
with a 40% failure rate and three attempts all week is a curiosity; the same rate
on the capability invoked 500 times is the product.

FOUR VIEWS, BECAUSE THEY MEASURE DIFFERENT LAYERS
-------------------------------------------------
  capabilities  `$.capability` on goal steps. The closest thing to "what the user
                asked ARIES to do", because a goal is submitted by a request.
  intents       `$.intent` on `aries_intelligence_events` kind `route`. What the
                ROUTER thought the request was. The gap between this and
                `capabilities` is itself informative, and the single largest
                bucket on this machine is `UNKNOWN` — 53 of 256 — which is a
                classifier that failed to classify one request in five.
  tools         `execution_operations.tool`. The mechanism layer. Recorded with a
                state, so usage and reliability come from one query.
  triggers      `aries_automation_runs.trigger`. How work arrives: schedule vs
                operator vs api vs cli. On this machine 84% is `schedule`, which
                means most of the recorded history is ARIES talking to itself and
                every rate on this dashboard should be read in that light.

Requests themselves are NOT aggregated by text. `aries_workspace_goals.request`
holds verbatim user speech, in Macedonian and English; grouping it would need
either exact-string matching (which turns "open youtube" and "open YouTube" into
two topics) or clustering, and no clustering of these strings is recorded. Topics
the user cares about live in `aries_interests` with real weights and are reported
from there instead of guessed at from raw text.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aries.analytics.core import GOAL_STEPS, Window, absent, metric, rate


@metric("capability_usage", source="goal steps, intelligence routes, execution_operations, "
                                  "automation runs",
        cost="one capped result_json parse (~27 ms / 600 goals) plus three small indexed "
             "GROUP BYs (~1 ms each)")
async def capability_usage(db: AsyncSession, window: Window, *, top: int = 25) -> dict:
    """Usage at four layers, each from the table that actually records it."""
    caps = (await db.execute(text(f"""
        WITH steps AS ({GOAL_STEPS})
        SELECT COALESCE(json_extract(step, '$.capability'), '(none)') AS cap,
               COALESCE(json_extract(step, '$.kind'), '(none)') AS kind, COUNT(*) AS n
          FROM steps GROUP BY cap, kind ORDER BY n DESC
    """), {"cutoff": window.cutoff, "cap": window.goal_scan})).all()

    intents = (await db.execute(text(
        "SELECT json_extract(data_json, '$.intent'), COUNT(*),"
        "       ROUND(AVG(json_extract(data_json, '$.confidence')), 3)"
        "  FROM aries_intelligence_events"
        " WHERE kind = 'route' AND created_at >= :cutoff"
        " GROUP BY 1 ORDER BY 2 DESC"), {"cutoff": window.cutoff})).all()

    tools = (await db.execute(text(
        "SELECT tool, state, COUNT(*) FROM execution_operations"
        " WHERE created_at >= :cutoff GROUP BY 1, 2"), {"cutoff": window.cutoff})).all()
    per_tool: dict[str, dict] = {}
    for tool, state, n in tools:
        per_tool.setdefault(tool or "(none)", {})[state] = int(n)

    triggers = (await db.execute(text(
        'SELECT "trigger", COUNT(*) FROM aries_automation_runs'
        ' WHERE started_at >= :cutoff GROUP BY 1 ORDER BY 2 DESC'),
        {"cutoff": window.cutoff})).all()

    if not (caps or intents or tools or triggers):
        return absent("nothing was requested or executed in this window")

    cap_rows: dict[str, dict] = {}
    for cap, kind, n in caps:
        e = cap_rows.setdefault(cap, {"capability": cap, "n": 0, "kinds": {}})
        e["n"] += int(n)
        e["kinds"][kind] = int(n)

    tool_rows = [{"tool": t, "n": sum(s.values()), "states": s,
                  "succeeded": rate(s.get("succeeded", 0),
                                    sum(v for k, v in s.items() if k != "skipped"),
                                    of="operations that attempted (skipped excluded)")}
                 for t, s in per_tool.items()]
    tool_rows.sort(key=lambda r: -r["n"])

    total_routes = sum(int(n) for _, n, _ in intents)
    unknown = next((int(n) for i, n, _ in intents if i == "UNKNOWN"), 0)
    return {
        "n": sum(r["n"] for r in cap_rows.values()),
        "capabilities": sorted(cap_rows.values(), key=lambda r: -r["n"])[:top],
        "capability_count": len(cap_rows),
        "intents": [{"intent": i or "(none)", "n": int(n), "mean_confidence": c}
                    for i, n, c in intents][:top] or None,
        "unrouted": rate(unknown, total_routes,
                         of="routing decisions that came back UNKNOWN — the share of requests "
                            "the router could not classify") if total_routes else None,
        "tools": tool_rows[:top] or None,
        "triggers": {t: int(n) for t, n in triggers} or None,
        "automation_share": rate(
            next((int(n) for t, n in triggers if t == "schedule"), 0),
            sum(int(n) for _, n in triggers),
            of="automation runs started by the schedule rather than by a person") if triggers
            else None,
        "requests_not_aggregated": "goal request text is verbatim user speech in two languages "
                                   "and is not clustered anywhere, so it is not grouped here",
    }


@metric("model_usage", source="aries_intelligence_events (generation, fallback)",
        cost="two GROUP BYs over an indexed created_at, 1,735 rows total. ~3 ms")
async def model_usage(db: AsyncSession, window: Window) -> dict:
    """Which model did the work, how often it succeeded, and what fell back.

    Cost is reported as a SUM only where `$.estimated_cost_usd` is non-null, with
    the count it was summed over — on this machine it is null for every local
    call, and a total that silently treated null as zero would claim ARIES runs
    for free.
    """
    rows = (await db.execute(text(
        "SELECT json_extract(data_json, '$.level'), json_extract(data_json, '$.provider'),"
        "       json_extract(data_json, '$.model'), json_extract(data_json, '$.task_type'),"
        "       COUNT(*), SUM(json_extract(data_json, '$.ok') = 1),"
        "       SUM(json_extract(data_json, '$.input_tokens')),"
        "       SUM(json_extract(data_json, '$.output_tokens')),"
        "       SUM(json_extract(data_json, '$.estimated_cost_usd')),"
        "       SUM(json_extract(data_json, '$.estimated_cost_usd') IS NOT NULL),"
        "       SUM(json_extract(data_json, '$.input_tokens') IS NOT NULL)"
        "  FROM aries_intelligence_events"
        " WHERE kind = 'generation' AND created_at >= :cutoff"
        " GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC"), {"cutoff": window.cutoff})).all()
    if not rows:
        return absent("no model call was recorded in this window")
    fallbacks = (await db.execute(text(
        "SELECT json_extract(data_json, '$.from_level'), json_extract(data_json, '$.to_level'),"
        "       json_extract(data_json, '$.reason'), COUNT(*)"
        "  FROM aries_intelligence_events"
        " WHERE kind = 'fallback' AND created_at >= :cutoff"
        " GROUP BY 1, 2, 3 ORDER BY 4 DESC"), {"cutoff": window.cutoff})).all()
    models = [{"level": lvl, "provider": prov, "model": mdl or "(unnamed)", "task_type": tt,
               "n": int(n), "ok": rate(int(ok or 0), int(n), of="model calls"),
               "input_tokens": int(it or 0), "output_tokens": int(ot or 0),
               # How many of the n calls actually carried a token count. A SUM
               # over a column that is mostly NULL reads as a small total, not as
               # missing data, and dividing it by `n` invents a per-call average
               # for calls that never reported one. Three separate sessions drew
               # opposite conclusions about the local planner from exactly that
               # arithmetic on 2026-09-30 — one of them mine. Say the denominator.
               "token_counted_calls": int(counted or 0),
               "cost_usd": round(float(cost), 4) if cost is not None else None,
               "cost_priced_calls": int(priced or 0)}
              for lvl, prov, mdl, tt, n, ok, it, ot, cost, priced, counted in rows]
    total = sum(m["n"] for m in models)
    priced_total = sum(m["cost_priced_calls"] for m in models)
    return {"n": total, "models": models,
            "cost_usd": round(sum(m["cost_usd"] or 0.0 for m in models), 4)
                        if priced_total else None,
            "cost_reason": None if priced_total else
                           "no call in this window recorded an estimated cost, so the total is "
                           "unknown rather than zero",
            "cost_covers": f"{priced_total} of {total} calls",
            "fallbacks": [{"from": f, "to": t, "reason": r, "n": int(n)}
                          for f, t, r, n in fallbacks] or None,
            "cloud_share": rate(sum(m["n"] for m in models if m["level"] == "cloud"), total,
                                of="model calls that went to the cloud")}


@metric("attention", source="aries_notifications + aries_feedback + aries_interests",
        cost="three GROUP BYs on indexed columns over 594 / 38 / 6 rows. ~2 ms")
async def attention(db: AsyncSession, window: Window, *, top: int = 15) -> dict:
    """What ARIES chose to tell the user, and what the user told it back.

    The delivered/held/suppressed split is the honest measure of whether the
    notification policy is working: a system that delivers everything is not
    filtering, and one that holds everything is not reachable.
    """
    notes = (await db.execute(text(
        "SELECT level, disposition, COUNT(*) FROM aries_notifications"
        " WHERE created_at >= :cutoff GROUP BY 1, 2"), {"cutoff": window.cutoff})).all()
    fb = (await db.execute(text(
        "SELECT classification, applied, COUNT(*) FROM aries_feedback"
        " WHERE created_at >= :cutoff GROUP BY 1, 2"), {"cutoff": window.cutoff})).all()
    interests = (await db.execute(text(
        "SELECT topic, stance, weight, learned_weight FROM aries_interests"
        " ORDER BY COALESCE(weight, learned_weight) DESC LIMIT :top"), {"top": top})).all()
    if not (notes or fb or interests):
        return absent("no notification, feedback or interest is recorded")
    disp: dict[str, int] = {}
    for _lvl, d, n in notes:
        disp[d] = disp.get(d, 0) + int(n)
    total = sum(disp.values())
    return {"n": total,
            "notifications_by_disposition": disp or None,
            "notifications_by_level": {str(lvl): sum(int(n) for l2, _d, n in notes if l2 == lvl)
                                       for lvl in {l for l, _d, _n in notes}} or None,
            "delivered": rate(disp.get("delivered", 0), total,
                              of="notifications raised") if total else None,
            "feedback": [{"classification": c, "applied": bool(a), "n": int(n)}
                         for c, a, n in fb] or None,
            "interests": [{"topic": t, "stance": s, "user_weight": w,
                           "learned_weight": lw} for t, s, w, lw in interests] or None,
            "interests_note": "interests are not windowed — they are current state, not events"}
