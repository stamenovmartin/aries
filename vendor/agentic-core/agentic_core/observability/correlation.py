"""One id that ties everything a single request or job caused back together.
Lifted from backend/app/core/correlation.py."""
from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

_WELL_FORMED = re.compile(r"^[A-Za-z0-9_.:-]{8,36}$")
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_id() -> str:
    return str(uuid.uuid4())


def is_well_formed(value: str | None) -> bool:
    return bool(value) and bool(_WELL_FORMED.match(value))


def accept(inbound: str | None) -> str:
    """The caller's id if usable, else a fresh one — never a refusal."""
    return inbound if is_well_formed(inbound) else new_id()


def current() -> str | None:
    return _correlation_id.get()


def set_current(value: str | None):
    return _correlation_id.set(value)


def reset(token) -> None:
    _correlation_id.reset(token)


@contextmanager
def use_correlation(value: str | None = None):
    """Run a block under one id — a worker tick, a scheduled job, a test."""
    token = _correlation_id.set(value or new_id())
    try:
        yield _correlation_id.get()
    finally:
        _correlation_id.reset(token)
