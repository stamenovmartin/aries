#!/usr/bin/env python3
"""A2 smoke test: 3 parallel read-only sub-goals + 1 writer, no lock error.

    APP_ENV=test PYTHONPATH=vendor/agentic-core:vendor:. .venv/bin/python eval/locking/smoke.py

WHAT IS REAL HERE
-----------------
The engine is the real one — `agentic_core.database.base.engine`, the same module
`aries-core` imports, with the same pragmas, on a scratch file. The sub-goals are
real `WorkspaceGoal` rows created by the real `orchestration.fan_out` and executed
by the real `orchestration.tick` → `claim` → `_drive` → `attempt` → `_invoke`
path, running real read-only capabilities. The writer lane runs the real
`agentic_core.memory.recovery.recover_stuck()` — the exact statement that failed
live at 2026-10-03 14:09:11 — plus a write through the new one-writer session.

TWO THINGS ARE SUBSTITUTED, AND ONLY TWO
----------------------------------------
1. The database file: a fresh temporary one, never `var/aries.db`. A smoke test
   that writes the live database is not a smoke test.
2. `orchestration.capacity`: the power governor caps this machine at ONE slot
   while the display is off ("one goal at a time — not enabled for while the
   display is off"), which would run the three sub-goals one after another and
   test nothing about concurrency. The subject under test is SQLite locking, so
   the governor is stubbed to three slots. Nothing else is stubbed, and the test
   asserts that at least two sub-goals really did overlap rather than assuming it.

A NEGATIVE CONTROL RUNS FIRST. A pass only means something if a failure could
have been seen, so the test first provokes a real "database is locked" on a
deliberately unconfigured connection (busy_timeout=0, no WAL pragma) and asserts
that the detector catches it. If the control does not fail, the run aborts.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "vendor" / "agentic-core", ROOT / "vendor", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
sys.path.insert(0, str(ROOT / "tests"))

from tests._bootstrap import bootstrap, check, reset_db        # noqa: E402

bootstrap("a2-locking-smoke")

from sqlalchemy import func, select, text                      # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine         # noqa: E402

import aries                                                   # noqa: E402,F401  registers tables + capabilities
from agentic_core.database.base import BUSY_TIMEOUT_MS, async_session, engine  # noqa: E402
from agentic_core.database.models import AutomationLog         # noqa: E402
from agentic_core.database import writer                       # noqa: E402
from agentic_core.memory.recovery import recover_stuck         # noqa: E402
from aries.settings import SettingsService                     # noqa: E402
from aries.workspace import orchestration, service             # noqa: E402
from aries.workspace.models import WorkspaceGoal               # noqa: E402

HOME_FILE = str(ROOT / "README.md")
HOME_DIR = str(ROOT / "eval" / "locking")
WRITE_SECONDS = 8.0


# ── the detector ────────────────────────────────────────────────────────────

def lock_error_in(blob) -> bool:
    t = str(blob).lower()
    return "database is locked" in t or "database table is locked" in t


# ── negative control: can this test see a lock error at all? ────────────────

async def control_can_detect() -> str:
    """Provoke a real lock error on an unconfigured connection. Returns its text."""
    url = os.environ["DATABASE_URL"]
    # No apply_sqlite_pragmas, busy_timeout 0: the shape every direct
    # sqlite3.connect() in a codebase has until someone sets the pragma.
    bare = create_async_engine(url, connect_args={"timeout": 0})
    try:
        async with async_session() as holder:
            await holder.execute(text("BEGIN EXCLUSIVE"))
            await holder.execute(text(
                "INSERT INTO automation_logs (action, source, details, status, created_at) "
                "VALUES ('control.hold', 'a2', 'holding the write lock', 'success', datetime('now'))"))
            try:
                async with bare.connect() as loser:
                    await loser.execute(text("PRAGMA busy_timeout=0"))
                    await loser.execute(text(
                        "INSERT INTO automation_logs (action, source, details, status, created_at) "
                        "VALUES ('control.loser', 'a2', 'should not get in', 'failure', datetime('now'))"))
                    await loser.commit()
                return ""                                  # no error: control failed
            except Exception as exc:                       # noqa: BLE001
                return f"{getattr(exc, 'orig', exc)}"
            finally:
                await holder.rollback()
    finally:
        await bare.dispose()


# ── the three parallel read-only sub-goals ──────────────────────────────────

async def fan_out_three() -> dict:
    async with async_session() as db:
        await SettingsService(db).set("workspace.enabled", True, set_by="user")
        await db.commit()
    async with async_session() as db:
        return await orchestration.fan_out(db, "report status and check two paths", [
            {"capability": "system.status", "args": {}},
            {"capability": "file.exists", "args": {"path": HOME_FILE}},
            {"capability": "file.list", "args": {"path": HOME_DIR}},
        ], source="a2-smoke")


async def run_subgoals(report: dict) -> None:
    """Drive the real orchestrator until the three children leave the queue."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            await orchestration.tick(wait=True)
        except Exception as exc:                            # noqa: BLE001
            report["reader_errors"].append(f"{type(exc).__name__}: {exc}")
            if lock_error_in(exc):
                report["lock_errors"].append(f"orchestration.tick: {exc}")
            return
        async with async_session() as db:
            states = [r.state for r in (await db.execute(
                select(WorkspaceGoal).where(WorkspaceGoal.id.in_(report["children"])))).scalars().all()]
        report["child_states"] = states
        if all(s not in ("queued", "running") for s in states):
            return
        await asyncio.sleep(0.05)
    report["reader_errors"].append("the three sub-goals did not finish within 120 s")


# ── the one writer, running at the same time ────────────────────────────────

async def run_writer(report: dict, lane: str = "a") -> None:
    """The live failing writer plus a one-writer write, as fast as it will go.

    Two lanes run this, so the in-process writer lock is genuinely contended: a
    serialiser nobody ever queues behind proves nothing.
    """
    end = time.monotonic() + WRITE_SECONDS
    while time.monotonic() < end:
        # (a) the real reaper that failed on the live database today.
        try:
            await recover_stuck(older_than_minutes=0)
            report["reaper_passes"] += 1
        except Exception as exc:                            # noqa: BLE001
            report["writer_errors"].append(f"recover_stuck: {type(exc).__name__}: {exc}")
            if writer.is_locked_error(exc):
                report["lock_errors"].append(f"recover_stuck: {getattr(exc, 'orig', exc)}")
        # (b) a sub-goal-shaped write routed through the single writer.
        try:
            async with writer.write_session(name=f"a2-smoke-{lane}") as db:
                db.add(AutomationLog(action="a2.writer", source="a2-smoke",
                                     details=f"{lane} pass {report['writer_passes']}", status="success"))
                if writer.held():
                    report["lock_observed_held"] = True
            report["writer_passes"] += 1
        except Exception as exc:                            # noqa: BLE001
            report["writer_errors"].append(f"write_session: {type(exc).__name__}: {exc}")
            if writer.is_locked_error(exc):
                report["lock_errors"].append(f"write_session: {getattr(exc, 'orig', exc)}")
        await asyncio.sleep(0)


async def sample_overlap(report: dict) -> None:
    """Did the sub-goals actually run at the same time? Measured, not assumed."""
    end = time.monotonic() + WRITE_SECONDS + 20
    while time.monotonic() < end and not report.get("finished"):
        running = sum(1 for gid in report["children"] if gid in service._supervisors)
        report["max_concurrent"] = max(report["max_concurrent"], running)
        await asyncio.sleep(0.02)


# ── checks ──────────────────────────────────────────────────────────────────

async def test_every_pooled_connection_is_configured():
    """Not one connection — every connection the pool hands out."""
    await reset_db()
    modes, waits = set(), set()

    async def probe():
        async with async_session() as db:
            modes.add(str((await db.execute(text("PRAGMA journal_mode"))).scalar()).lower())
            waits.add(int((await db.execute(text("PRAGMA busy_timeout"))).scalar()))
            await asyncio.sleep(0.2)                        # hold it, so the pool opens more
    await asyncio.gather(*(probe() for _ in range(6)))
    check(f"every pooled connection runs in WAL (saw {sorted(modes)})", modes == {"wal"})
    check(f"every pooled connection waits >= 5000 ms (saw {sorted(waits)})",
          waits and min(waits) >= 5000)
    check(f"the configured wait is the one constant ({BUSY_TIMEOUT_MS} ms)",
          waits == {BUSY_TIMEOUT_MS})


async def test_three_parallel_read_only_subgoals_plus_one_write():
    await reset_db()

    control = await control_can_detect()
    check("negative control: an unconfigured connection DOES fail, so a failure "
          f"would have been seen ({control[:60] or 'nothing raised'})", lock_error_in(control))
    if not lock_error_in(control):
        return

    await reset_db()
    out = await fan_out_three()
    report = {"children": out["children"], "writer_passes": 0, "reaper_passes": 0,
              "writer_errors": [], "reader_errors": [], "lock_errors": [],
              "max_concurrent": 0, "child_states": [], "lock_observed_held": False}

    # The governor, and only the governor. See the module docstring.
    real_capacity = orchestration.capacity

    async def three_slots(db):
        cap = await real_capacity(db)
        return orchestration.Capacity(slots=3, reason="stubbed by eval/locking/smoke.py",
                                      measurement=cap.measurement, limits=cap.limits,
                                      workload_status=cap.workload_status)
    orchestration.capacity = three_slots
    try:
        await asyncio.gather(run_subgoals(report), run_writer(report, "a"),
                             run_writer(report, "b"), sample_overlap(report))
    finally:
        report["finished"] = True
        orchestration.capacity = real_capacity

    async with async_session() as db:
        logged = (await db.execute(select(AutomationLog).where(
            AutomationLog.details.like("%database is locked%")))).scalars().all()
        goals = (await db.execute(select(WorkspaceGoal))).scalars().all()
        rows_written = (await db.execute(select(func.count()).select_from(AutomationLog)
                                        .where(AutomationLog.action == "a2.writer"))).scalar()
    for row in logged:
        report["lock_errors"].append(f"automation_logs {row.action}: {row.details[:200]}")
    for g in goals:
        if lock_error_in(g.result_json):
            report["lock_errors"].append(f"goal {g.id[:8]} ({g.state}): lock error in its own record")

    print(f"      3 read-only sub-goals ran, states={report['child_states']}, "
          f"max overlapping={report['max_concurrent']}")
    print(f"      writer: {report['writer_passes']} one-writer transactions "
          f"({rows_written} rows), {report['reaper_passes']} recover_stuck passes "
          f"in {WRITE_SECONDS:g} s")
    print(f"      writer lock stats: {writer.stats()}")
    if report["writer_errors"] or report["reader_errors"]:
        print(f"      non-lock errors: {(report['writer_errors'] + report['reader_errors'])[:3]}")

    check("the three sub-goals really overlapped (>= 2 at once)", report["max_concurrent"] >= 2)
    check("all three read-only sub-goals left the queue",
          len(report["child_states"]) == 3
          and all(s not in ("queued", "running") for s in report["child_states"]))
    check("the writer committed at least 20 transactions alongside them",
          report["writer_passes"] >= 20)
    check("the real recover_stuck() reaper ran alongside them",
          report["reaper_passes"] >= 20)
    check("writes were serialised through the one in-process writer",
          report["lock_observed_held"] and writer.stats()["acquired"] >= report["writer_passes"])
    check("the two writer lanes really queued behind each other "
          f"({writer.stats()['contended']} contended acquisitions)",
          writer.stats()["contended"] > 0 and writer.stats()["timed_out"] == 0)
    check("NO 'database is locked' anywhere: lanes, goal records, automation_logs "
          f"({len(report['lock_errors'])} found)", not report["lock_errors"])
    for e in report["lock_errors"][:5]:
        print("      LOCK ERROR:", e)


async def test_a_read_then_write_transaction_cannot_lose_its_snapshot():
    """SQLITE_BUSY_SNAPSHOT is the error busy_timeout does NOT retry.

    It needs an open read snapshot to upgrade. Under this driver a SELECT does not
    open one — pysqlite only begins a transaction before DML — so the upgrade
    succeeds even after another connection committed underneath it. This check
    pins that behaviour down: if a future change starts a real transaction on
    read (isolation_level=None, PEP 249 autocommit, or SQLAlchemy's BEGIN
    recipe), it fails here instead of as a 3 a.m. "database is locked".
    """
    await reset_db()
    async with async_session() as a, async_session() as b:
        await a.execute(select(func.count()).select_from(AutomationLog))   # A reads
        b.add(AutomationLog(action="a2.snapshot", source="a2-smoke", details="b wins",
                            status="success"))
        await b.commit()                                                   # B commits under A
        try:
            await a.execute(text("UPDATE automation_logs SET status='success' "
                                 "WHERE action='a2.snapshot'"))
            await a.commit()
            ok, why = True, "the upgrade succeeded"
        except Exception as exc:                                           # noqa: BLE001
            orig = getattr(exc, "orig", exc)
            ok = False
            why = f"{type(orig).__name__} {getattr(orig, 'sqlite_errorname', '')}: {orig}"
    check(f"a read-then-write transaction does not hit SQLITE_BUSY_SNAPSHOT ({why})", ok)
    print("      and BEGIN IMMEDIATE in write_session() keeps it unreachable even if "
          "the driver's isolation changes")


if __name__ == "__main__":
    from tests._bootstrap import run_module
    sys.exit(run_module(sys.modules[__name__]))
