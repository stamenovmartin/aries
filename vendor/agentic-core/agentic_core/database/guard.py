"""A refusal to drop tables on a database that is not a throwaway.

Lifted from backend/app/core/dbguard.py. Installed at import time by
database/base.py, so it is active in every process that can reach the
database. A drop is permitted only when BOTH hold:
  * APP_ENV=test, and
  * the connection is sqlite, or a Postgres database whose name ends `_test`.
"""
from __future__ import annotations

import logging

from sqlalchemy import MetaData
from sqlalchemy.engine.url import URL, make_url

from agentic_core.security import environments

logger = logging.getLogger(__name__)

SCRATCH_SUFFIX = "_test"
_installed = False


class DropRefused(RuntimeError):
    """Raised instead of destroying a database that is not disposable."""


def _url_of(bind) -> URL | None:
    for attr in ("url", "engine"):
        obj = getattr(bind, attr, None)
        if obj is None:
            continue
        if isinstance(obj, URL):
            return obj
        inner = getattr(obj, "url", None)
        if isinstance(inner, URL):
            return inner
    try:
        return make_url(str(bind))
    except Exception:
        return None


def is_disposable(url: URL | None) -> tuple[bool, str]:
    if not environments.is_test():
        return False, (f"APP_ENV is '{environments.current()}', not 'test'. "
                       "Dropping tables is allowed only in a test environment.")
    if url is None:
        return False, "Cannot determine the database — refusing to drop blindly."
    backend = (url.get_backend_name() or "").lower()
    if backend.startswith("sqlite"):
        return True, ""
    name = (url.database or "").strip()
    if name.endswith(SCRATCH_SUFFIX):
        return True, ""
    return False, (f"Database '{name}' on {backend} is not disposable. Allowed: "
                   f"sqlite, or a name ending in '{SCRATCH_SUFFIX}'.")


def install() -> None:
    global _installed
    if _installed:
        return
    original = MetaData.drop_all

    def guarded(self, bind, tables=None, checkfirst=True):
        url = _url_of(bind)
        allowed, why = is_disposable(url)
        if not allowed:
            shown = url.render_as_string(hide_password=True) if url else "unknown"
            raise DropRefused(
                f"REFUSED drop_all on {shown}. {why}\n"
                f"If this is a test, run it with:\n"
                f"  APP_ENV=test DATABASE_URL=sqlite+aiosqlite:///./<name>_test.db")
        return original(self, bind, tables=tables, checkfirst=checkfirst)

    MetaData.drop_all = guarded          # type: ignore[method-assign]
    _installed = True
    logger.debug("drop_all guard installed (APP_ENV=%s)", environments.current())
