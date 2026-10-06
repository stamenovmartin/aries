"""Reproduce the contention in a THROWAWAY database, never the live one.

The engine is built by importing agentic_core.database.base with DATABASE_URL
pointed at a scratch file, so WAL, synchronous=NORMAL, busy_timeout=15000 and
NullPool are exactly what aries-core runs -- not a hand-rolled imitation.

Four scenarios, each one question:
  A  HEAD's reaper shape (unconditional bulk UPDATE matching ZERO rows) while a
     holder keeps a write transaction open across an await. Does a write that
     changes nothing still fail?
  B  the working-tree shape (SELECT first, commit only when a row matched) under
     the same holder. Does a read-only pass survive?
  C  the working-tree shape WITH an orphan to reap, under the same holder.
  D  read-then-write in one transaction while another writer commits in the gap.
     This is SQLITE_BUSY_SNAPSHOT, which busy_timeout does not retry -- it should
     fail in milliseconds, not after 15 s.
"""
import asyncio, os, sys, time, pathlib

SCRATCH = pathlib.Path(os.environ.get("SCRATCH", "/tmp/aries-locking/-home-stamenovmartin/dc3eb2cb-6b81-4c4c-9601-41f12d0750c0/scratchpad")) / "contend.db"
for suffix in ("", "-wal", "-shm"):
    pathlib.Path(str(SCRATCH) + suffix).unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{SCRATCH}"
os.environ.setdefault("DATA_DIR", str(SCRATCH.parent))

from sqlalchemy import text                                    # noqa: E402
from agentic_core.database.base import async_session, engine    # noqa: E402

HOLD = float(os.environ.get("HOLD", "20"))   # > the 15 s busy timeout, as in production


async def setup():
    async with async_session() as db:
        await db.execute(text("CREATE TABLE IF NOT EXISTS goals ("
                              "id TEXT PRIMARY KEY, state TEXT, updated_at TEXT)"))
        await db.execute(text("CREATE TABLE IF NOT EXISTS other (id INTEGER PRIMARY KEY, v TEXT)"))
        await db.commit()
    for p in ("journal_mode", "busy_timeout", "synchronous"):
        async with async_session() as db:
            print(f"   pragma {p:13} = {(await db.execute(text(f'PRAGMA {p}'))).scalar()}")
    print(f"   pool          = {type(engine.pool).__name__}")


async def holder(seconds, started):
    """A writer that opens a write transaction and then awaits I/O.

    asyncio.sleep stands in for the 17.5 s HTTP POST to the model gateway seen in
    the live journal. SQLite cannot tell the difference: the lock is held for the
    whole transaction either way.
    """
    async with async_session() as db:
        await db.execute(text("INSERT INTO other (v) VALUES ('holder')"))
        await db.execute(text("SELECT 1"))          # force the flush -> write lock taken
        started.set()
        await asyncio.sleep(seconds)                # <- the await that does I/O
        await db.commit()


async def timed(label, body):
    t0 = time.monotonic()
    try:
        await body()
        return f"   {label:<52} OK      after {time.monotonic()-t0:6.2f}s"
    except Exception as exc:
        return f"   {label:<52} FAILED  after {time.monotonic()-t0:6.2f}s  {type(exc).__name__}: {str(exc).splitlines()[0][:60]}"


async def scenario(label, victim, *, seed_orphan=False, hold=HOLD):
    async with async_session() as db:
        await db.execute(text("DELETE FROM goals"))
        if seed_orphan:
            await db.execute(text("INSERT INTO goals VALUES ('g1','running',"
                                  "datetime('now','-10 minutes'))"))
        await db.commit()
    started = asyncio.Event()
    h = asyncio.create_task(holder(hold, started))
    await started.wait()
    await asyncio.sleep(0.2)
    print(await timed(label, victim))
    await h


# --- the victims -----------------------------------------------------------
async def head_shape():
    """What HEAD's dispatch() does: one bulk UPDATE, run whether or not it matches."""
    async with async_session() as db:
        await db.execute(text("SELECT id FROM goals WHERE state='running'"
                              " AND updated_at < datetime('now','-5 minutes')"))
        await db.execute(text("UPDATE goals SET state='interrupted' WHERE state='running'"
                              " AND updated_at < datetime('now','-5 minutes')"))
        await db.commit()

async def worktree_shape():
    """SELECT first; write only when a row matched; commit is a no-op otherwise."""
    async with async_session() as db:
        rows = (await db.execute(text("SELECT id FROM goals WHERE state='running'"
                                      " AND updated_at < datetime('now','-5 minutes')"))).all()
        for (gid,) in rows:
            await db.execute(text("UPDATE goals SET state='interrupted' WHERE id=:i"), {"i": gid})
        await db.commit()

async def snapshot_upgrade():
    """Read, let another connection commit, then write on the stale snapshot."""
    async with async_session() as db:
        await db.execute(text("SELECT id FROM goals"))          # read snapshot opens here
        async with async_session() as other:                    # a different connection
            await other.execute(text("INSERT INTO other (v) VALUES ('interloper')"))
            await other.commit()
        await db.execute(text("UPDATE goals SET state='interrupted' WHERE state='running'"))
        await db.commit()


async def main():
    print(f"throwaway database: {SCRATCH}")
    await setup()
    print(f"\n   holder keeps a write transaction open for {HOLD:.0f}s across an await\n")
    await scenario("A  HEAD shape, ZERO rows match (idle poll)", head_shape)
    await scenario("B  working-tree shape, ZERO rows match", worktree_shape)
    await scenario("C  working-tree shape, ONE row to reap", worktree_shape, seed_orphan=True)
    print()
    print(await timed("D  read-then-write, interloper commits in the gap", snapshot_upgrade))
    await engine.dispose()

asyncio.run(main())


# ── follow-ups ─────────────────────────────────────────────────────────────
async def holder_commits_first(seconds, started):
    """The proposed fix: the same work, with the transaction closed BEFORE the
    await that does I/O. One commit moved; nothing else changes."""
    async with async_session() as db:
        await db.execute(text("INSERT INTO other (v) VALUES ('holder')"))
        await db.commit()                            # <- moved ahead of the await
        started.set()
        await asyncio.sleep(seconds)                 # the model call
        await db.execute(text("INSERT INTO other (v) VALUES ('after')"))
        await db.commit()

async def claim_shape():
    """What dispatch() does to claim a queued goal -- the path a spoken command takes."""
    async with async_session() as db:
        await db.execute(text("UPDATE goals SET state='running' WHERE id='g1' AND state='running'"))
        await db.commit()

async def followups():
    print("\n   --- E: does closing the transaction before the await fix it? ---")
    for label, h in (("holder holds across the await  (today)", holder),
                     ("holder commits before the await (fix)", holder_commits_first)):
        for vlabel, victim in (("reap one orphan", worktree_shape), ("claim a queued goal", claim_shape)):
            # A FRESH holder per victim. Reusing one holder lets the second victim
            # see only the remainder of the hold, which reads as a pass it did not earn.
            async with async_session() as db:
                await db.execute(text("DELETE FROM goals"))
                await db.execute(text("INSERT INTO goals VALUES ('g1','running',datetime('now','-10 minutes'))"))
                await db.commit()
            started = asyncio.Event()
            task = asyncio.create_task(h(HOLD, started))
            await started.wait(); await asyncio.sleep(0.2)
            print(await timed(f"{vlabel} while {label}", victim))
            await task

    print("\n   --- why D did not fail: pysqlite defers BEGIN until the first DML ---")
    async with async_session() as db:
        raw = (await (await db.connection()).get_raw_connection()).dbapi_connection._connection
        print(f"   sqlite3 isolation_level = {raw.isolation_level!r}   (''/None decide when BEGIN is issued)")
        await db.execute(text("SELECT COUNT(*) FROM goals"))
        print(f"   in_transaction after a SELECT = {raw.in_transaction}   "
              f"<- no read snapshot, so there is nothing to upgrade")
        await db.execute(text("UPDATE goals SET state=state WHERE 1=0"))
        print(f"   in_transaction after an UPDATE = {raw.in_transaction}")
        await db.commit()

async def main2():
    await followups()
    await engine.dispose()

if os.environ.get("FOLLOWUPS"):
    asyncio.run(main2())
