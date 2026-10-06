"""Is the reaper killing live work? Read-only.

Two separate questions:
  (a) did the 74 failures kill anything -- they are FAILED writes, so no row
      changed; this checks that directly by looking for the goals they targeted;
  (b) does the reaper, when it succeeds, interrupt goals that were alive?
      A goal reaped at >5 min of silence should have life >= 5 min. A shorter
      life means the cutoff was computed against a clock that had moved.
"""
import sqlite3, json
c = sqlite3.connect("file:/home/stamenovmartin/aries/var/aries.db?mode=ro&uri=true", uri=True)

print("=== every goal ever marked interrupted, with its recorded life ===")
rows = c.execute(
    "SELECT id, created_at, updated_at,"
    "  (julianday(updated_at)-julianday(created_at))*86400 AS life_s, result_json"
    " FROM aries_workspace_goals WHERE state='interrupted' ORDER BY created_at").fetchall()
print(f"{len(rows)} interrupted goals total")
short = []
for gid, cr, up, life, rj in rows:
    try: data = json.loads(rj)
    except Exception: data = {}
    gaps = data.get("gaps") or []
    steps = data.get("steps") or []
    done = sum(1 for s in steps if s.get("state") == "done")
    reaped = any("Interrupted" in str(g) or "interrupted" in str(g) for g in gaps)
    flag = "  <<< LIFE < 5 MIN" if life is not None and life < 300 else ""
    if flag: short.append(gid)
    print(f"  {gid[:12]} life={life:9.1f}s steps={len(steps)}(done {done}) "
          f"gaps={len(gaps)} {str(gaps[:1])[:70]}{flag}")
print(f"\ninterrupted with life < 300 s (impossible under a 5-minute rule): {len(short)}")

print("\n=== the 6 negative-lifetime rows: are any of them interrupted? ===")
for r in c.execute("SELECT id, state, created_at, updated_at,"
                   " (julianday(updated_at)-julianday(created_at))*86400 AS d"
                   " FROM aries_workspace_goals"
                   " WHERE (julianday(updated_at)-julianday(created_at))*86400 < 0 ORDER BY d"):
    print(f"  {r[0][:12]} state={r[1]:12} created={r[2]} updated={r[3]} delta={r[4]:.0f}s")

print("\n=== did any of the 74 failures target a goal that was alive? ===")
print("The failing statement is an UPDATE that RAISED, so no row changed. Checking")
print("whether a goal was in state 'running' at each failure instant:")
for at, in c.execute("SELECT created_at FROM automation_logs WHERE created_at>=datetime('now','-7 days')"
                     " AND status='failure' AND details LIKE '%database is locked%'"
                     " AND details LIKE '%aries_workspace_goals%' ORDER BY created_at DESC LIMIT 8"):
    n = c.execute("SELECT COUNT(*) FROM aries_workspace_goals WHERE created_at <= ?"
                  " AND updated_at >= datetime(?,'-5 minutes') AND state IN ('running','queued')", (at, at)).fetchone()[0]
    tgt = c.execute("SELECT COUNT(*) FROM aries_workspace_goals WHERE state='interrupted'"
                    " AND updated_at BETWEEN datetime(?,'-2 minutes') AND datetime(?,'+2 minutes')", (at, at)).fetchone()[0]
    print(f"  {at}: goals still running/queued now={n}, goals interrupted within +-2 min={tgt}")
