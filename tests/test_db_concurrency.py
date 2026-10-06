import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-db-concurrency')
from sqlalchemy import text
from agentic_core.database.base import async_session


async def test_sqlite_is_configured_for_concurrent_writers():
    # 1602 "database is locked" errors made spoken commands fail (2026-09-29).
    await reset_db()
    async with async_session() as db:
        mode = (await db.execute(text('PRAGMA journal_mode'))).scalar()
        wait = (await db.execute(text('PRAGMA busy_timeout'))).scalar()
    check('the database runs in WAL mode', str(mode).lower() == 'wal')
    check('a writer waits for the lock instead of failing', int(wait) >= 10000)


async def test_news_fetches_hold_no_write_lock():
    """No DB write may be pending while a feed is being fetched over the network."""
    await reset_db()
    from aries.news import automation
    from aries.sources import service as sources
    seen = []

    async def fake_fetch(url, **_):
        seen.append(db.in_transaction() and bool(db.new or db.dirty or writes))
        raise automation.FetchRefused('offline in test')

    from aries.settings import SettingsService
    from aries.sources import add as add_source
    async with async_session() as db:
        await SettingsService(db).set('news.enabled', True, set_by='user')
        for i in range(3):
            await add_source(db, name=f'S{i}', type='rss', location=f'https://example.org/{i}.xml')
        await db.commit()
    writes = []
    real_sync = sources.record_sync

    async def spy_sync(*a, **k):
        writes.append(1)
        return await real_sync(*a, **k)

    async with async_session() as db:
        with patch.object(automation, 'fetch', fake_fetch), patch.object(sources, 'record_sync', spy_sync):
            await automation.collect({'db': db})
    check('feeds were fetched', len(seen) > 0)
    check('no write happened before or between fetches', not any(seen))
    check('each source outcome is still recorded', len(writes) == len(seen))


if __name__ == '__main__':
    run_module(sys.modules[__name__])
