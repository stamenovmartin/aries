"""The ALTER TABLE this project has no alembic for.

`Base.metadata.create_all` is the whole of schema evolution here, and it does
exactly one thing: it creates tables that do not exist. It will not add a column
to a table that does. The live `var/aries.db` already has
`aries_workspace_memories(id, text, source, created_at)` from before semantic
memory existed, so without this the new columns would be in the model, absent
from the database, and every read would fail at runtime rather than at start-up.

Rules this file follows, because a migration that has to be watched is a
migration that will be skipped:

  * idempotent — it reads `PRAGMA table_info` and adds only what is missing;
  * additive only — no column is dropped, renamed or retyped, so an older ARIES
    keeps working against a migrated database;
  * every added column is nullable or has a constant default, which is the only
    kind SQLite can add to a populated table at all;
  * new TABLES are left to `create_all`, which handles them correctly.

It runs from `aries.cli` after `create_all`, and again, cheaply, the first time
anything in `aries.workspace.memory` touches the database — because the API
server creates its schema through the engine's `run_migrations()`, which this
package cannot hook without editing the engine.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

# table -> column -> the DDL fragment after ADD COLUMN.
COLUMNS = {
    "aries_workspace_memories": {
        "lang": "VARCHAR(8) NOT NULL DEFAULT ''",
        "kind": "VARCHAR(24) NOT NULL DEFAULT 'fact'",
        "layer": "INTEGER NOT NULL DEFAULT 60",
        "embedding": "BLOB",
        "embedding_model": "VARCHAR(64) NOT NULL DEFAULT ''",
        "importance": "FLOAT NOT NULL DEFAULT 0",
        "valid_at": "DATETIME",
        "invalid_at": "DATETIME",
        "expired_at": "DATETIME",
        "superseded_by": "VARCHAR(40)",
        "retrievals": "INTEGER NOT NULL DEFAULT 0",
        "last_retrieved_at": "DATETIME",
    },
}
_done = False


def _plan(existing, table):
    return [f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'
            for name, ddl in COLUMNS[table].items() if name not in existing]


def upgrade_sync(connection):
    """Run inside `conn.run_sync(...)`. Returns the statements it issued."""
    inspector = inspect(connection)
    issued = []
    for table in COLUMNS:
        if not inspector.has_table(table):
            continue                      # create_all will make it complete
        existing = {c["name"] for c in inspector.get_columns(table)}
        for statement in _plan(existing, table):
            connection.execute(text(statement))
            issued.append(statement)
    return issued


async def upgrade(engine=None):
    """Idempotent, and cheap enough to call on any path that needs the columns."""
    global _done
    if engine is None:
        from agentic_core.database.base import engine as default_engine
        engine = default_engine
    async with engine.begin() as connection:
        issued = await connection.run_sync(upgrade_sync)
    _done = True
    return issued


async def ensure(engine=None):
    """Once per process. The columns cannot go missing again while it runs."""
    if _done:
        return []
    return await upgrade(engine)
