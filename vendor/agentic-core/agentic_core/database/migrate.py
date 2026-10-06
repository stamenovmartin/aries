"""Bring the schema up at startup.

The original (backend/app/core/migrate.py) runs Alembic: `upgrade head` on a
fresh database, `stamp head` on a pre-Alembic one, and falls back to
`create_all` only outside production. The export ships without an Alembic
history (there is no existing database to migrate), so `create_all` is the
bootstrap; the hook is where `alembic upgrade head` goes the day you add
migrations — keep the production rule: a failed migration must stop the boot.
"""
from __future__ import annotations

import logging

from agentic_core.database.base import Base, engine

logger = logging.getLogger(__name__)


async def run_migrations() -> None:
    from agentic_core.database import models  # noqa: F401  registers every table
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Schema ready (create_all, idempotent).")
