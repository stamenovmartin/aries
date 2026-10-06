"""Which environment this process is, and what it is therefore allowed to do.

Lifted verbatim in spirit from backend/app/core/environments.py. The lesson it
encodes: a test script once ran `drop_all` against the live database because
`DATABASE_URL` alone decided what a process talked to. Environment is now an
explicit, separate fact:

    APP_ENV = development | test | staging | production

and the default is PRODUCTION — a missing value must be the safest one.
"""
from __future__ import annotations

import os

DEVELOPMENT = "development"
TEST = "test"
STAGING = "staging"
PRODUCTION = "production"
ALL = (DEVELOPMENT, TEST, STAGING, PRODUCTION)
_DEFAULT = PRODUCTION


def current() -> str:
    raw = (os.environ.get("APP_ENV") or "").strip().lower()
    return raw if raw in ALL else _DEFAULT


def is_test() -> bool:
    return current() == TEST


def is_production() -> bool:
    return current() == PRODUCTION


def describe() -> dict:
    raw = (os.environ.get("APP_ENV") or "").strip().lower()
    return {"env": current(), "explicit": raw in ALL,
            "note": ("APP_ENV not set — assuming production, deliberately the "
                     "strictest value." if raw not in ALL else None)}
