"""ARIES test bootstrap — the engine's harness, plus the ARIES tables.

Each test process gets its own sqlite file and APP_ENV=test before anything
imports agentic_core, for the reason the engine's harness gives: a test that
reads the live switches is a test that runs against production state.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "vendor", "agentic-core"), os.path.join(ROOT, "vendor"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests._harness_shim import bootstrap, check, run_module  # noqa: E402,F401


async def reset_db():
    """Drop and recreate every table — the engine's AND ARIES's."""
    import aries  # noqa: F401  registers the ARIES tables on the shared Base
    from agentic_core.database import models  # noqa: F401
    from agentic_core.database.base import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
