"""Which writer held the lock? Read-only: what ran in the 40 s before each failure.

The failures are hourly and drift ~1 min/hour, so the holder is an hourly job.
automation_logs records every pass, so the pass that BRACKETS a failure names it.
"""
import sqlite3, re, collections
c = sqlite3.connect("file:/home/stamenovmartin/aries/var/aries.db?mode=ro&uri=true", uri=True)
fails = c.execute(
    "SELECT id, created_at FROM automation_logs"
    " WHERE created_at >= datetime('now','-7 days') AND status='failure'"
    "   AND details LIKE '%database is locked%'"
    "   AND details LIKE '%aries_workspace_goals%' ORDER BY created_at DESC LIMIT 6").fetchall()
tally = collections.Counter()
for fid, at in fails:
    print(f"\n===== failure {fid} at {at} — everything logged in the 40 s around it =====")
    rows = c.execute(
        "SELECT created_at, action, status, substr(coalesce(details,''),1,150) FROM automation_logs"
        " WHERE created_at BETWEEN datetime(?,'-40 seconds') AND datetime(?,'+15 seconds')"
        " ORDER BY created_at", (at, at)).fetchall()
    for r in rows:
        mark = "  <<< FAILURE" if r[2] == 'failure' else ""
        print(f"  {r[0]}  {r[1]:26} {r[2]:8} {r[3][:110]}{mark}")
        if r[2] != 'failure':
            tally[r[1]] += 1
print("\n===== actions seen in those windows =====")
for a, n in tally.most_common():
    print(f"  {n:4} {a}")

# The hourly cadence itself: which action has a run every ~hour that drifts?
print("\n===== cadence of every action, last 24 h =====")
for (a,) in c.execute("SELECT DISTINCT action FROM automation_logs WHERE created_at>=datetime('now','-1 day') AND status!='failure'"):
    ts = [r[0] for r in c.execute(
        "SELECT created_at FROM automation_logs WHERE action=? AND created_at>=datetime('now','-1 day')"
        " AND status!='failure' ORDER BY created_at", (a,))]
    if len(ts) < 3:
        print(f"  {a:26} n={len(ts)}"); continue
    from datetime import datetime
    d = [(datetime.fromisoformat(ts[i+1])-datetime.fromisoformat(ts[i])).total_seconds() for i in range(len(ts)-1)]
    d.sort()
    print(f"  {a:26} n={len(ts):6}  median gap={d[len(d)//2]:8.1f}s  max gap={d[-1]:8.1f}s")
