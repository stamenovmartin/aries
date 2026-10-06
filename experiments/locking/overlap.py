"""Which writer was IN FLIGHT when each reaper write was blocked?

`aries_automation_runs.started_at` has no explicit value, so the DB default
CURRENT_TIMESTAMP stamps it at flush time -- the END of the run. A run therefore
occupies [started_at - duration_ms, started_at], which is the opposite of what the
column name suggests. Getting this backwards hides exactly the long runs that
matter, so the interval is spelled out here.

The blocked window is [fail_at - waited, fail_at], where `waited` is recovered
from the cutoff parameter SQLAlchemy recorded in the error text.
"""
import sqlite3, re, collections
from datetime import datetime, timedelta
c = sqlite3.connect("file:/home/stamenovmartin/aries/var/aries.db?mode=ro&uri=true", uri=True)
runs = [(a, datetime.fromisoformat(s) - timedelta(milliseconds=d or 0),
         datetime.fromisoformat(s), d or 0)
        for a, s, d in c.execute("SELECT automation_id, started_at, duration_ms FROM aries_automation_runs"
                                 " WHERE started_at >= datetime('now','-8 days')")]
fails = c.execute("SELECT created_at, details FROM automation_logs"
                  " WHERE created_at >= datetime('now','-7 days') AND status='failure'"
                  "   AND details LIKE '%database is locked%'"
                  "   AND details LIKE '%aries_workspace_goals%' ORDER BY created_at DESC").fetchall()
tally = collections.Counter(); covered = 0
for at, det in fails:
    fail = datetime.fromisoformat(at)
    stamps = re.findall(r"'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)'", det)
    begin = min(datetime.fromisoformat(s) for s in stamps) + timedelta(minutes=5)
    hits = [(a, b, e, d) for a, b, e, d in runs if b <= fail and e >= begin and d >= 1000]
    hits.sort(key=lambda h: -h[3])
    if hits:
        covered += 1
        for a, *_ in hits: tally[a] += 1
    span = f"blocked {begin:%H:%M:%S}->{fail:%H:%M:%S} ({(fail-begin).total_seconds():.1f}s)"
    print(f"{at}  {span}: " + (", ".join(f"{a} {d/1000:.1f}s ending {e:%H:%M:%S}" for a,b,e,d in hits[:3])
                               or "no automation run >=1s spanned the block"))
print(f"\n{covered}/{len(fails)} blocked windows overlap an automation run of >=1 s")
for a, n in tally.most_common(): print(f"  {n:3} {a}")
