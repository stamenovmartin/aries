"""ARIES data lifecycle — what is kept, for how long, and what is discarded.

A browser opens a page, you read it, you close it. What survives is a bookmark,
not the HTML. This package is that rule, made explicit:

    policy.py    every table, its class, its window, and what reads it
    working.py   context held for one task, released when the task ends
    service.py   rehearse, refuse a window that starves a dependant, report
    automation.py  the declared automation that enforces it
    settings.py  the windows, as settings the user owns
"""
from __future__ import annotations

from aries.lifecycle import policy, service, working
from aries.lifecycle import settings as _settings      # noqa: F401  registers settings
from aries.lifecycle import automation as _automation  # noqa: F401  registers the automation

__all__ = ["policy", "service", "working"]
