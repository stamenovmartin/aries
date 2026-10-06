"""Shared test bootstrap. Every test process sets APP_ENV=test and its OWN sqlite
file BEFORE importing agentic_core, exactly as the original run_tests.py did —
`setdefault` is not enough inside a container where DATABASE_URL is exported."""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import tempfile


def bootstrap(name: str) -> None:
    d = tempfile.mkdtemp(prefix=f"agentic-{name}-")
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{d}/{name}_test.db"
    os.environ["DATA_DIR"] = d
    os.environ["RUNTIME_STORE"] = f"{d}/runtime.json"
    os.environ["CONTEXT_DIR"] = f"{d}/context"
    os.environ["AI_PROVIDER"] = "template"
    os.environ["DRY_RUN"] = "true"
    os.environ["LIVE_TOOLS"] = ""
    os.environ["API_KEY"] = ""
    os.environ.pop("CREDENTIALS_KEY", None)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def reset_db():
    from agentic_core.database.base import Base, engine
    from agentic_core.database import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


_ok = True


def check(label: str, cond) -> None:
    global _ok
    print(("PASS  " if cond else "FAIL  ") + label)
    _ok = _ok and bool(cond)


def run_module(mod) -> int:
    """Run every test_* function in a module (sync or async). Returns exit code."""
    global _ok
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        fn = getattr(mod, name)
        if not callable(fn):
            continue
        print(f"--- {name}")
        try:
            r = fn()
            if inspect.iscoroutine(r):
                asyncio.run(r)
        except AssertionError as e:
            print(f"FAIL  {name}: assertion: {e}"); _ok = False
        except Exception as e:  # noqa: BLE001
            import traceback; traceback.print_exc()
            print(f"FAIL  {name}: {type(e).__name__}: {e}"); _ok = False
    print("ALL PASSED" if _ok else "FAILURES")
    return 0 if _ok else 1
