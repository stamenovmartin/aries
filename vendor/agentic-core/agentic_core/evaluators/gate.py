"""Gate on hard errors and repair: re-generate any item whose output has a
hard error, up to `rounds`, and adopt the new draft only when it has STRICTLY
fewer hard errors than the one it replaces. Lifted from
backend/app/services/agent/review.py::gate_and_repair. Never blocks — a
regenerate that fails or does not improve leaves the prior output."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from agentic_core.evaluators.base import Issue

logger = logging.getLogger(__name__)

# hard_errors(item) -> list[Issue] ; regenerate(item, prior, issues) -> new_output | None
HardErrorsFn = Callable[[dict], list[Issue]]
RegenerateFn = Callable[[dict, str, list[Issue]], Awaitable[str | None]]


async def gate_and_repair(items: list[dict], *, hard_errors: HardErrorsFn,
                          regenerate: RegenerateFn, rounds: int = 1, key: str = "content") -> dict:
    """`items` are dicts with `key` holding the output; mutated in place.
    Returns {"repaired": [names], "attempted": [names], "remaining": {name: n_errors}}."""
    attempted, repaired = [], []
    for _ in range(max(0, rounds)):
        pending = [it for it in items if hard_errors(it)]
        if not pending:
            break
        for it in pending:
            name = it.get("name") or it.get("platform_name") or str(id(it))
            prior = it.get(key) or ""
            issues = hard_errors(it)
            attempted.append(name)
            try:
                new = await regenerate(it, prior, issues)
            except Exception:
                logger.exception("Repair regenerate failed for %s", name)
                new = None
            if new:
                candidate = {**it, key: new}
                if len(hard_errors(candidate)) < len(issues):
                    it[key] = new
                    repaired.append(name)
    remaining = {(it.get("name") or it.get("platform_name") or str(id(it))): len(hard_errors(it))
                 for it in items if hard_errors(it)}
    return {"repaired": repaired, "attempted": attempted, "remaining": remaining}
