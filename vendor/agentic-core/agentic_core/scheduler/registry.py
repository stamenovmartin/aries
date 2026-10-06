"""The roster of background workers, started by the app lifespan and never
in APP_ENV=test (a test wants the routes, not the clock)."""
from __future__ import annotations

import logging

from agentic_core.scheduler.worker import Worker
from agentic_core.security import environments

logger = logging.getLogger(__name__)
_WORKERS: dict[str, Worker] = {}


def register(w: Worker, *, replace: bool = False) -> Worker:
    if w.name in _WORKERS and not replace:
        raise ValueError(f"worker '{w.name}' already registered")
    _WORKERS[w.name] = w
    return w


def get(name: str) -> Worker | None:
    return _WORKERS.get(name)


def all_workers() -> list[Worker]:
    return [_WORKERS[k] for k in sorted(_WORKERS)]


def start_all() -> list[str]:
    if environments.is_test():
        logger.info("APP_ENV=test — background workers not started")
        return []
    started = []
    for w in all_workers():
        w.start(); started.append(w.name)
    return started


async def stop_all() -> None:
    for w in all_workers():
        await w.stop()


def status() -> list[dict]:
    return [w.status() for w in all_workers()]
