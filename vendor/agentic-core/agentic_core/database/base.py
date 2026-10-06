"""Engine + session factory. Lifted from backend/app/core/database.py."""
from __future__ import annotations

import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from agentic_core.config.settings import settings
from agentic_core.database import guard

logger = logging.getLogger(__name__)

# Installed before any engine exists — see database/guard.py.
guard.install()

# ONE number, named once. A writer that queues for 15 s and a writer that gives
# up after 0.2 s behave completely differently under the same contention, and
# the 2026-09-29 incident was diagnosed by the length of the wait, so the length
# has to be a constant something can read and assert on rather than a literal
# repeated per connection. `connect_args["timeout"]` below is the same number in
# seconds: pysqlite applies it before the first statement, the PRAGMA applies it
# again on the connection itself, and they must not disagree.
BUSY_TIMEOUT_MS = 15000


def apply_sqlite_pragmas(target, *, url: str = "") -> None:
    """Install ARIES's SQLite pragmas on ANY engine, not just the one below.

    WAL: readers never block the writer and the writer never blocks readers —
    the rollback journal made every API read wait behind any background write.
    busy_timeout: a writer queues for the lock instead of failing instantly with
    "database is locked".

    Exported because this process is not the only writer of the file and this
    engine is not the only engine: probes, migrations and one-off scripts build
    their own, and an engine without busy_timeout fails instantly where the
    shared engine would have waited. Anything that calls create_async_engine on
    a SQLite URL calls this too.

    A ?mode=ro URL gets busy_timeout but no journal_mode — WAL is a write to the
    database header, so attempting it on a read-only probe raises and would take
    the probe down. In-memory databases cannot use WAL at all and keep theirs.
    """
    from sqlalchemy import event

    sync_engine = getattr(target, "sync_engine", target)
    url = url or str(sync_engine.url)
    writable = ":memory:" not in url and "mode=ro" not in url

    @event.listens_for(sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):      # noqa: ANN001
        cur = dbapi_conn.cursor()
        try:
            if writable:
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            # Read back rather than assume. A pragma that silently did not take
            # (a locked header, a driver that opened a second connection behind
            # our back) is the one failure mode that looks exactly like no
            # configuration at all, and it would otherwise only show up as a
            # "database is locked" hours later with nothing to point at.
            # The async adapter's cursor.execute() returns None, unlike pysqlite's —
            # so fetch in a second call rather than chaining off execute().
            cur.execute("PRAGMA busy_timeout")
            got_wait = cur.fetchone()[0]
            cur.execute("PRAGMA journal_mode")
            got_mode = cur.fetchone()[0]
            if int(got_wait) < BUSY_TIMEOUT_MS or (writable and str(got_mode).lower() != "wal"):
                logger.warning(
                    "SQLite pragmas did not take on %s: journal_mode=%s busy_timeout=%s "
                    "(wanted %s / %s). Writers on this connection can fail with "
                    "'database is locked' without waiting.",
                    url, got_mode, got_wait, "wal" if writable else got_mode, BUSY_TIMEOUT_MS)
        finally:
            cur.close()


_url = settings.database_url
_kwargs: dict = {
    "echo": os.environ.get("SQL_ECHO", "").lower() in ("1", "true", "yes"),
    "pool_pre_ping": True,
}
if _url.startswith("sqlite"):
    _kwargs["connect_args"] = {"check_same_thread": False, "timeout": BUSY_TIMEOUT_MS / 1000}

engine = create_async_engine(_url, **_kwargs)

if _url.startswith("sqlite"):
    apply_sqlite_pragmas(engine, url=_url)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session
