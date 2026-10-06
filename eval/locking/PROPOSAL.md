# A2 — the two patches I could not apply, with their exact diffs

`vendor/agentic-core/agentic_core/database/writer.py` is new and in my write scope.
**Nothing calls it from production code yet**, because both call sites are outside
it. Until one of these two patches lands, `write_session()` is exercised only by
`eval/locking/smoke.py` (1 164 transactions, 609 of them contended, in that run)
and ARIES's parallel sub-goals still queue on SQLite's file lock rather than on
the in-process one.

Both patches are small, both are confined to one function, and the smoke test
already covers the behaviour they would switch on.

---

## Patch 1 — `aries/workspace/service.py` · `save()` and `progress()`

**Why this file and not another:** `_persist()` in `orchestration.py` is the only
write a running sub-goal makes, and it is one line — `await save(goal_id, data,
state)`. Every parallel sub-goal's writes therefore funnel through `save()` and
`progress()` in `service.py`. Routing those two through the one writer routes all
of them; nothing else needs touching.

**Not applied because** `aries/workspace/service.py` is contended and belongs to
another worker today (WORKPLAN: "Two files are contended and belong to Codex
today"), and codex claimed `service.py` again at 14:04 UTC in `COORDINATION.md`.

`progress()` is the more interesting half: it reads the row and then updates it in
the same transaction. That is the one read-then-write shape in the sub-goal path,
i.e. the shape that becomes `SQLITE_BUSY_SNAPSHOT` — the error `busy_timeout` does
not retry — the day anyone changes the driver's isolation. `write_session()` takes
`BEGIN IMMEDIATE`, so the upgrade it would have needed does not exist.

```diff
--- a/aries/workspace/service.py
+++ b/aries/workspace/service.py
@@
 from sqlalchemy import select, update
 from agentic_core.database.base import async_session
+from agentic_core.database import writer
 from agentic_core.observability.audit import log_event
@@ async def save(goal_id, data, state="running"):
-async def save(goal_id, data, state="running"):
-    async with async_session() as db:
-        changed = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == goal_id, WorkspaceGoal.state == "running").values(result_json=json.dumps(data), state=state, updated_at=datetime.utcnow()))
-        await db.commit()
-        if not changed.rowcount:
-            raise asyncio.CancelledError()
+async def save(goal_id, data, state="running"):
+    # Every parallel sub-goal's writes land here. One writer at a time inside this
+    # process, so they queue in asyncio — where waiting is free and bounded —
+    # instead of queueing on SQLite's file lock, where losing costs 15 s and then
+    # an unrecoverable "database is locked". write_session commits on exit.
+    async with writer.write_session(name=f"workspace.save:{goal_id[:8]}") as db:
+        changed = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == goal_id, WorkspaceGoal.state == "running").values(result_json=json.dumps(data), state=state, updated_at=datetime.utcnow()))
+    if not changed.rowcount:
+        raise asyncio.CancelledError()
@@ async def progress(goal_id, message):
 async def progress(goal_id, message):
     if not goal_id:
         return
-    async with async_session() as db:
+    # Reads the row and then writes it, in one transaction. Under BEGIN IMMEDIATE
+    # that cannot become SQLITE_BUSY_SNAPSHOT, which busy_timeout never retries.
+    async with writer.write_session(name=f"workspace.progress:{goal_id[:8]}") as db:
         row = await db.get(WorkspaceGoal, goal_id)
         if not row or row.state != 'running':
             raise asyncio.CancelledError()
         data = json.loads(row.result_json)
         data['progress'] = message[:300]
         await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == goal_id, WorkspaceGoal.state == 'running').values(result_json=json.dumps(data), updated_at=datetime.utcnow()))
-        await db.commit()
```

Behaviour that is preserved on purpose:

* `save()` committed before raising `CancelledError`, and still does — the raise
  just moves below the `async with`, after `write_session` has committed.
* `progress()` raised `CancelledError` *before* writing anything; `write_session`
  rolls back on any exception, so it still writes nothing.
* `async_session` stays imported — the other nineteen commits in the file are
  unchanged. Only the two sub-goal write paths move.

Risk, stated plainly: the body of `save()` is a single UPDATE and the body of
`progress()` is a get plus an UPDATE. Neither makes a network, browser or model
call, which is the one thing that must never happen inside this lock. I checked
both.

---

## Patch 2 — `vendor/agentic-core/agentic_core/memory/recovery.py` · `recover_stuck()`

**Why:** this is the writer that is *still failing on the live database*. The
newest `database is locked` row is `2026-10-03 14:09:11`, and its SQL is
`UPDATE task_runs SET status=?, verdict=?, finished_at=? WHERE task_runs.status = ?
AND task_runs.started_at < ?` — line 31–32 of this file. It runs at startup and on
**every scheduler tick**, so it is the most frequent single write transaction in
the process, and it is a read-then-write transaction (`select(Task)` first).

**Not applied because** my write scope is
`vendor/agentic-core/agentic_core/database/**`. `memory/recovery.py` is outside it,
and the WORKPLAN's A2 row does not list it either. I did not edit it.

```diff
--- a/vendor/agentic-core/agentic_core/memory/recovery.py
+++ b/vendor/agentic-core/agentic_core/memory/recovery.py
@@
-from agentic_core.database.base import async_session
+from agentic_core.database import writer
 from agentic_core.database.models import ExecutionOperation, ExecutionPlan, ScheduledTask, Task, TaskRun
@@ async def recover_stuck(older_than_minutes: int = 10) -> dict:
 async def recover_stuck(older_than_minutes: int = 10) -> dict:
     cutoff = datetime.utcnow() - timedelta(minutes=older_than_minutes)
     out = {"tasks": 0, "runs": 0, "operations": 0, "plans": 0, "scheduled": 0}
-    async with async_session() as db:
+    # Five bulk UPDATEs behind one SELECT, on every scheduler tick. It is the
+    # transaction that lost the file lock 200 times, most recently 2026-10-03
+    # 14:09:11 on task_runs, after waiting out the full 15 s busy_timeout.
+    async with writer.write_session(name="recover_stuck") as db:
         for t in (await db.execute(select(Task).where(Task.status.in_(("executing", "running")),
                                                        Task.updated_at < cutoff))).scalars().all():
@@
         out["scheduled"] = r.rowcount or 0
-        await db.commit()
     if any(out.values()):
```

`recover_stuck()` is idempotent — every statement is "if still stuck, release it"
— so it is also the safest candidate for `writer.retry_busy()` if the caller ever
wants cross-process retries on top of the in-process lock:

```python
    await writer.retry_busy(lambda: recover_stuck(older_than_minutes), name="recover_stuck")
```

---

## What neither patch can do

Four things point `DATABASE_URL` at `var/aries.db`: `aries-core`,
`aries-local-model`, `aries-voice` (via `.env`, no write path today) and every
`scripts/aries` invocation. `write_session()` is a *process-local* lock. It
serialises the parallel sub-goals, which is what A2 asked for and all of which run
inside `aries-core`'s one event loop. It does nothing about `aries-local-model`
writing `generation_usage` at the same instant. Across processes, WAL plus
`busy_timeout` is still the whole of the defence — see `writers.md` §3 and §5.
