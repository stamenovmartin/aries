"""How long did each failing writer actually wait? That number tests busy_timeout.

The failing statement carries its own cutoff parameter. The reaper builds that
cutoff as `utcnow() - 5 min` immediately before executing, so
    logged_at - (cutoff + 5 min)
is the time the statement spent blocked plus the log write. If busy_timeout=15000
is in force and exhausted, this clusters just above 15 s. If the failure were
SQLITE_BUSY_SNAPSHOT it would be ~0 s, because that error never retries.
"""
import asyncio, re, statistics
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

LIVE = "sqlite+aiosqlite:///file:/home/stamenovmartin/aries/var/aries.db?mode=ro&uri=true"
OFFSET = {"aries_workspace_goals": 5, "task_runs": 10}   # staleness window per site, minutes

async def main():
    engine = create_async_engine(LIVE)
    async with engine.connect() as db:
        rows = (await db.execute(text(
            "SELECT created_at, action, details FROM automation_logs"
            " WHERE created_at >= datetime('now','-7 days') AND status='failure'"
            "   AND details LIKE '%database is locked%' ORDER BY created_at"))).all()
    await engine.dispose()
    buckets = {}
    for r in rows:
        m = re.search(r"UPDATE (\w+) SET", r.details or "")
        if not m or m.group(1) not in OFFSET:
            buckets.setdefault("no statement recorded", []).append(None); continue
        table = m.group(1)
        stamps = re.findall(r"'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)'", r.details)
        if not stamps:
            continue
        cutoff = min(datetime.fromisoformat(s) for s in stamps)
        logged = datetime.fromisoformat(r.created_at)
        waited = (logged - (cutoff + timedelta(minutes=OFFSET[table]))).total_seconds()
        buckets.setdefault(table, []).append(waited)
    for table, vals in buckets.items():
        vals = [v for v in vals if v is not None]
        if not vals:
            print(f"{table:24} n={len(buckets[table])}  (no timing recoverable)"); continue
        vals.sort()
        print(f"{table:24} n={len(vals):3}  min={vals[0]:6.2f}s  median={statistics.median(vals):6.2f}s  "
              f"max={vals[-1]:6.2f}s  >=15s: {sum(v>=15 for v in vals)}/{len(vals)}")
        print(f"{'':24} all: {[round(v,1) for v in vals]}")

asyncio.run(main())

# --- second pass: does the wait split by date? The 15 s busy_timeout landed in
# commit bb77f16 on 2026-09-29, so a 5 s cluster before it and a 15 s cluster
# after it would confirm the pragma took effect on the live process.
async def by_date():
    engine = create_async_engine(LIVE)
    async with engine.connect() as db:
        rows = (await db.execute(text(
            "SELECT created_at, details FROM automation_logs"
            " WHERE created_at >= datetime('now','-7 days') AND status='failure'"
            "   AND details LIKE '%database is locked%'"
            "   AND details LIKE '%aries_workspace_goals%' ORDER BY created_at"))).all()
    await engine.dispose()
    for r in rows:
        stamps = re.findall(r"'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)'", r.details)
        cutoff = min(datetime.fromisoformat(s) for s in stamps)
        waited = (datetime.fromisoformat(r.created_at) - (cutoff + timedelta(minutes=5))).total_seconds()
        print(f"{r.created_at}  waited={waited:6.2f}s")
asyncio.run(by_date())
