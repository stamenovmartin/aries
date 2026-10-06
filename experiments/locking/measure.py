"""Read-only measurement of the `database is locked` failures on the live database.

Read-only by construction: the URI carries mode=ro, so SQLite refuses any write
and refuses to create -wal/-shm, which is what makes it safe to point at a file
`aries-core` is writing to right now.
"""
import asyncio, json, os, re, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

LIVE = "sqlite+aiosqlite:///file:/home/stamenovmartin/aries/var/aries.db?mode=ro&uri=true"

async def main():
    engine = create_async_engine(os.environ.get("PROBE_URL", LIVE))
    out = {}
    async with engine.connect() as db:
        for p in ("journal_mode", "busy_timeout", "synchronous", "wal_autocheckpoint"):
            out.setdefault("pragmas_on_this_readonly_connection", {})[p] = (
                await db.execute(text(f"PRAGMA {p}"))).scalar()

        # 1. The 74: what they are, and what the recorded detail actually says.
        rows = (await db.execute(text(
            "SELECT id, created_at, action, status, details FROM automation_logs"
            " WHERE created_at >= datetime('now','-7 days') AND status='failure'"
            "   AND details LIKE '%database is locked%'"
            " ORDER BY created_at"))).all()
        out["lock_failures_7d"] = len(rows)
        out["by_action"] = {}
        for r in rows:
            out["by_action"][r.action] = out["by_action"].get(r.action, 0) + 1
        out["first"] = rows[0].created_at if rows else None
        out["last"] = rows[-1].created_at if rows else None
        out["sample_details"] = [rows[i].details[:1400] for i in (0, len(rows)//2, -1)] if rows else []

        # Distinct detail shapes: one per statement site, so this names the sites.
        shapes = {}
        for r in rows:
            d = r.details or ""
            key = re.sub(r"[0-9a-f]{32}|\d+", "#", d)[:300]
            shapes.setdefault(key, []).append(r.created_at)
        out["distinct_shapes"] = [{"n": len(v), "shape": k, "first": v[0], "last": v[-1]}
                                  for k, v in sorted(shapes.items(), key=lambda kv: -len(kv[1]))]

        # 2. Per-hour, to separate a steady rate from bursts.
        out["per_hour"] = [dict(zip(("hour", "n"), row)) for row in (await db.execute(text(
            "SELECT substr(created_at,1,13), COUNT(*) FROM automation_logs"
            " WHERE created_at >= datetime('now','-7 days') AND status='failure'"
            "   AND details LIKE '%database is locked%' GROUP BY 1 ORDER BY 1"))).all()]

        # 3. Was a goal actually running at each failure? The reaper only writes when
        #    it found an orphan, so a coincident long-running goal is the suspect.
        out["coincident"] = []
        for r in rows:
            near = (await db.execute(text(
                "SELECT id, state, created_at, updated_at,"
                "  (julianday(:t)-julianday(created_at))*86400 AS age_s"
                " FROM aries_workspace_goals"
                " WHERE created_at <= :t AND updated_at >= datetime(:t,'-15 minutes')"
                " ORDER BY created_at DESC LIMIT 6"), {"t": r.created_at})).all()
            out["coincident"].append({"at": r.created_at, "action": r.action,
                "goals": [{"id": g.id, "state": g.state, "created": g.created_at,
                           "updated": g.updated_at, "age_s": round(g.age_s or 0, 1)} for g in near]})

        # 4. Reaper correctness. Negative lifetimes mean the wall clock moved back.
        out["negative_lifetime"] = [dict(zip(("id","state","created_at","updated_at","delta_s"), row))
            for row in (await db.execute(text(
            "SELECT id, state, created_at, updated_at,"
            "  (julianday(updated_at)-julianday(created_at))*86400 AS d"
            " FROM aries_workspace_goals WHERE d < 0 ORDER BY d"))).all()]
        out["total_goals"] = (await db.execute(text("SELECT COUNT(*) FROM aries_workspace_goals"))).scalar()
        out["interrupted_total"] = (await db.execute(text(
            "SELECT COUNT(*) FROM aries_workspace_goals WHERE state='interrupted'"))).scalar()

        # Interrupted goals whose recorded gap is the reaper's, with how long they
        # had actually been alive. A short life reaped at >5 min is impossible
        # unless the clock moved; that is the test for killing live work.
        out["interrupted_detail"] = [dict(zip(("id","created_at","updated_at","life_s","gaps"), row))
            for row in (await db.execute(text(
            "SELECT id, created_at, updated_at,"
            "  (julianday(updated_at)-julianday(created_at))*86400 AS life_s,"
            "  substr(result_json,1,0)||coalesce(json_extract(result_json,'$.gaps'),'[]')"
            " FROM aries_workspace_goals WHERE state='interrupted' ORDER BY created_at DESC LIMIT 40"))).all()]
    await engine.dispose()
    print(json.dumps(out, indent=1, default=str))

asyncio.run(main())
