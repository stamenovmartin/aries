#!/usr/bin/env python3
"""Create the schema (idempotent) and, if AGENTIC_APP is set, import that
package so its agents/tools/kinds register. Safe to run on every boot."""
from __future__ import annotations

import asyncio
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "agentic-core"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


async def main() -> int:
    from agentic_core.database.migrate import run_migrations
    await run_migrations()
    app = os.environ.get("AGENTIC_APP", "").strip()
    if app:
        importlib.import_module(app)
        print(f"schema ready; application package '{app}' imported")
    else:
        print("schema ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
