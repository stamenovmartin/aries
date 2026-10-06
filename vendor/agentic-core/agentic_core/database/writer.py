"""One writer per process, for the sub-goals that run in parallel inside it.

WHY THIS EXISTS AND WHAT IT CANNOT DO
-------------------------------------
`busy_timeout` makes a losing writer wait. It does not make it win: when the
holder keeps the write lock longer than the timeout, the loser still fails with
"database is locked" — which is exactly what the 2026-09-29..2026-10-03 failures
were (every single one waited 15-19 s before failing, measured in
`experiments/locking/waited.py`). Waiting longer is not a fix; not queueing in
SQLite is. So parallel sub-goals in ONE process take this lock before they write
and hold it only for the transaction.

This is a process-local lock, and that is the honest boundary: four processes on
this machine point `DATABASE_URL` at `var/aries.db` (`aries-core`,
`aries-local-model`, `aries-voice`, plus every `scripts/aries` invocation). This
serialises the writers inside whichever process imports it. Against the other
processes, SQLite's own locking plus `busy_timeout` remains the only mechanism.

`BEGIN IMMEDIATE` is taken on purpose. A transaction that reads first and writes
later asks SQLite to upgrade a read snapshot to a write, and if anyone committed
in between SQLite answers SQLITE_BUSY_SNAPSHOT — the same "database is locked"
text, returned instantly, which `busy_timeout` does NOT retry. Taking the write
lock at BEGIN makes that upgrade impossible; a plain SQLITE_BUSY at BEGIN
IMMEDIATE *is* covered by busy_timeout.

The acquire is bounded. An unbounded in-process lock would turn a 15 s error
into a silent forever-hang the moment one writer held it across network I/O, and
a hang is worse than an error because nothing records it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import weakref

from sqlalchemy import text

from agentic_core.database.base import async_session

logger = logging.getLogger(__name__)

# Longer than busy_timeout, so a writer that would have survived SQLite's own
# queue is never failed by this one; short enough that a wedged holder surfaces.
ACQUIRE_TIMEOUT_S = 30.0

# One lock per event loop, not one per process: tests and CLI entry points run
# asyncio.run() more than once, and an asyncio.Lock bound to a closed loop
# raises instead of locking.
_locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

_stats = {"acquired": 0, "contended": 0, "timed_out": 0, "max_wait_s": 0.0}


class WriterBusy(RuntimeError):
    """The in-process writer lock was held for longer than the bound."""


def _lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lk = _locks.get(loop)
    if lk is None:
        lk = _locks[loop] = asyncio.Lock()
    return lk


def held() -> bool:
    """Is the writer lock held on this loop right now? For assertions only."""
    try:
        return _lock().locked()
    except RuntimeError:
        return False


def stats() -> dict:
    return dict(_stats)


@contextlib.asynccontextmanager
async def write_session(*, name: str = "write", timeout: float = ACQUIRE_TIMEOUT_S,
                        immediate: bool = True):
    """A session that is the only writer in this process while it is open.

    Commits on a clean exit, rolls back on an exception, and releases the lock
    either way. Keep the body short: everything in it is serialised against every
    other writer in this process, so no network call, no browser step and no
    model call belongs inside.
    """
    lk = _lock()
    contended = lk.locked()
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(lk.acquire(), timeout)
    except (asyncio.TimeoutError, TimeoutError):
        _stats["timed_out"] += 1
        raise WriterBusy(
            f"{name}: the in-process SQLite writer lock was still held after {timeout:g} s. "
            "A writer is holding a transaction open across slow work; that is the bug, "
            "not the lock.") from None
    waited = time.monotonic() - t0
    _stats["acquired"] += 1
    _stats["contended"] += int(contended)
    _stats["max_wait_s"] = max(_stats["max_wait_s"], waited)
    if waited > 1.0:
        logger.warning("Writer %s waited %.2f s for the in-process write lock", name, waited)
    try:
        async with async_session() as db:
            if immediate:
                await db.execute(text("BEGIN IMMEDIATE"))
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
    finally:
        lk.release()


def is_locked_error(exc: BaseException) -> bool:
    """Is this the "database is locked" family, whatever the driver wrapped it in?"""
    cause = getattr(exc, "orig", exc)
    name = str(getattr(cause, "sqlite_errorname", "") or "")
    if name in ("SQLITE_BUSY", "SQLITE_BUSY_SNAPSHOT", "SQLITE_LOCKED"):
        return True
    text_ = f"{cause}".lower()
    return "database is locked" in text_ or "database table is locked" in text_


async def retry_busy(fn, *, attempts: int = 4, base_delay: float = 0.05, name: str = "write"):
    """Run `fn()` again from the top if it lost the lock.

    `busy_timeout` cannot help with SQLITE_BUSY_SNAPSHOT: it is returned with no
    wait at all, because the only valid recovery is to abandon the read snapshot
    and start the transaction over — which only the caller can do. `fn` must
    therefore open its own session and be safe to run twice.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except BaseException as exc:                              # noqa: BLE001
            if attempt == attempts or not is_locked_error(exc):
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("Writer %s lost the lock (attempt %d/%d): %s — retrying in %.0f ms",
                           name, attempt, attempts, getattr(exc, "orig", exc), delay * 1000)
            await asyncio.sleep(delay)
