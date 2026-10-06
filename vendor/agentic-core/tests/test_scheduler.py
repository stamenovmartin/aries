from _harness import bootstrap, check, reset_db, run_module
bootstrap("scheduler")

from datetime import datetime, timedelta  # noqa: E402

from agentic_core.config.settings import settings  # noqa: E402
from agentic_core.database.base import async_session  # noqa: E402
from agentic_core.database.models import ScheduledTask, Task  # noqa: E402
from agentic_core.scheduler import triggers  # noqa: E402
from agentic_core.scheduler.scheduled import in_quiet_hours, next_allowed_slot, process_due, schedule  # noqa: E402


async def _task(db, status="approved"):
    t = Task(kind="generic", title="job", brief="do", status=status)
    db.add(t); await db.commit(); await db.refresh(t)
    return t


def test_quiet_hours():
    check("wrap window 23→8", in_quiet_hours(datetime(2026, 1, 1, 2), 23, 8) and not in_quiet_hours(datetime(2026, 1, 1, 12), 23, 8))
    check("start==end disables", not in_quiet_hours(datetime(2026, 1, 1, 2), 0, 0))
    check("next slot is window end", next_allowed_slot(datetime(2026, 1, 1, 2), 23, 8).hour == 8)


async def test_process_due_guards_and_retry():
    await reset_db()
    settings.quiet_hours_start = settings.quiet_hours_end = 0
    settings.scheduler_retry_backoff_minutes = 5
    now = datetime(2026, 6, 1, 12, 0)
    seen = []

    async def run_fn(task_id, kind):
        seen.append(task_id)
        return {"attempted": True, "success": False, "details": "boom"} if len(seen) == 1 else {"attempted": True, "success": True}
    async with async_session() as db:
        t = await _task(db)
        sp = await schedule(db, t.id, now - timedelta(minutes=1), max_attempts=3)
        pending = await _task(db, status="awaiting_approval")
        sp2 = await schedule(db, pending.id, now - timedelta(minutes=1))
        rejected = await _task(db, status="rejected")
        sp3 = await schedule(db, rejected.id, now - timedelta(minutes=1))
        out = await process_due(db, now=now, run_fn=run_fn)
        by = {o["id"]: o for o in out}
        check("failed run requeued with backoff", by[sp.id]["status"] == "retry")
        await db.refresh(sp)
        check("run_at moved by backoff and attempts=1", sp.attempts == 1 and sp.run_at == now + timedelta(minutes=5) and sp.status == "queued")
        check("unapproved task deferred, not run", by[sp2.id]["status"] == "deferred" and pending.id not in seen)
        check("rejected task's schedule canceled", by[sp3.id]["status"] == "canceled")
        out = await process_due(db, now=now + timedelta(minutes=6), run_fn=run_fn)
        check("retry succeeded → done", any(o["id"] == sp.id and o["status"] == "done" for o in out))


async def test_deferral_keeps_schedule_and_dead_letter():
    await reset_db()
    now = datetime(2026, 6, 1, 12, 0)

    async def held(task_id, kind):
        return {"attempted": False, "success": False, "deferred": "dry_run"}
    async with async_session() as db:
        t = await _task(db)
        sp = await schedule(db, t.id, now, max_attempts=1)
        out = await process_due(db, now=now, run_fn=held)
        check("a non-attempt keeps the row queued", out[0]["status"] == "deferred")
        await db.refresh(sp)
        check("attempts not consumed by a deferral", sp.attempts == 0 and sp.status == "queued")

        async def fail(task_id, kind):
            return {"attempted": True, "success": False, "details": "x"}
        sp.run_at = now; await db.commit()
        out = await process_due(db, now=now, run_fn=fail)
        check("max_attempts=1 → dead letter", out[0]["status"] == "failed")


async def test_triggers_propose_conservatively():
    await reset_db()
    import agentic_core.agents.builtin  # noqa: F401
    triggers.register(triggers.Trigger(
        name="disk_full", matches=lambda ev: ev["kind"] == "disk" and ev["data"].get("pct", 0) >= 90,
        make_task=lambda ev: _mk(ev), cooldown_hours=24))

    async def _mk(ev):
        return {"kind": "generic", "title": f"Free disk on {ev['subject']}", "brief": f"disk {ev['subject']} at {ev['data']['pct']}%"}
    async with async_session() as db:
        await triggers.record(db, "disk", "/var", {"pct": 95})
        await triggers.record(db, "disk", "/home", {"pct": 40})
        await triggers.record(db, "disk", "/var", {"pct": 97})
        await db.commit()
        out = await triggers.propose(db)
        check("one task for /var, the 40% event ignored, the second /var event skipped by cooldown",
              len(out["proposed"]) == 1 and any(s["why"].startswith("subject") for s in out["skipped"]))
        out2 = await triggers.propose(db)
        check("re-running proposes nothing new", out2["proposed"] == [])


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
