"""The in-process worker: one asyncio task, no Celery/APScheduler, paced by
the LAST RECORDED RUN in the database rather than a sleeping timer.
Lifted from backend/app/services/{data_worker,learning_scheduler,autopilot/loop}.py.

Why last-run pacing: a timer restarts from zero on every reload, so a daily
job on a machine that reboots never fires; reading the last run means a missed
cycle is caught up late instead of skipped. The check itself is one indexed
MAX(created_at). Every pass stamps a heartbeat so "is it alive?" is answerable.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from agentic_core.database.base import async_session
from agentic_core.memory import checkpoints
from agentic_core.observability import metrics
from agentic_core.observability.correlation import use_correlation

logger = logging.getLogger(__name__)


@dataclass
class Worker:
    name: str
    fn: Callable[[], Awaitable[dict | None]]     # one pass; returns a summary or None
    every: timedelta                              # how often a pass is DUE
    check_every_s: int = 300                      # how often to ask "is a pass due?"
    enabled: Callable[[], bool] = field(default=lambda: True)
    run_hour: int | None = None                   # only after this local hour (daily jobs)
    # A queue poll every few seconds is not a job worth a row and a log line per
    # pass: 247k "nothing to do" rows had piled up in automation_logs. With
    # quiet=True, a pass returning {"idle": True} leaves no trace.
    quiet: bool = False
    _task: asyncio.Task | None = None
    _last_tick: datetime | None = None

    def last_tick(self) -> datetime | None:
        return self._last_tick

    def alive(self) -> bool:
        if self._last_tick is None or self._task is None or self._task.done():
            return False
        age = (datetime.now(timezone.utc).replace(tzinfo=None) - self._last_tick).total_seconds()
        return age < self.check_every_s * 2

    async def _due(self) -> tuple[bool, datetime | None]:
        async with async_session() as db:
            last = await checkpoints.last_run_at(db, self.name, (f"{self.name}.run", f"{self.name}.failed"))
        now = datetime.utcnow()
        if last is None or (now - last) >= self.every:
            if self.run_hour is not None and last is not None and now.hour < self.run_hour and (now - last) < self.every * 2:
                return False, last
            return True, last
        return False, last

    async def run_once(self) -> dict | None:
        """One pass, recorded whatever happens. Public so an API can trigger it."""
        t0 = time.monotonic(); ok = True; out = None
        with use_correlation():
            try:
                out = await self.fn()
            except asyncio.CancelledError:
                ok = False
                out = {"error": "Worker pass interrupted by cancellation", "interrupted": True}
                raise
            except Exception as e:
                ok = False; out = {"error": f"{type(e).__name__}: {e}"}
                logger.exception("Worker %s pass failed", self.name)
            finally:
                ms = (time.monotonic() - t0) * 1000
                metrics.record_job(self.name, ms, ok)
                if self.quiet and ok and isinstance(out, dict) and out.get("idle"):
                    return out
                try:
                    async with async_session() as db:
                        await checkpoints.mark_run(db, self.name, f"{self.name}.run" if ok else f"{self.name}.failed",
                                                   str(out)[:1500] if out else "", ok=ok)
                        await db.commit()
                except asyncio.CancelledError:
                    logger.warning("Recording run of %s was interrupted by cancellation", self.name)
                    raise
                except Exception as exc:
                    cause = getattr(exc, "orig", exc)
                    logger.exception("Could not record run of %s (sqlite_errorcode=%s sqlite_errorname=%s)",
                                     self.name, getattr(cause, "sqlite_errorcode", None),
                                     getattr(cause, "sqlite_errorname", None))
        return out

    async def _loop(self) -> None:
        logger.info("Worker %s started (every=%s, check=%ss)", self.name, self.every, self.check_every_s)
        while True:
            try:
                self._last_tick = datetime.now(timezone.utc).replace(tzinfo=None)
                if self.enabled():
                    due, last = await self._due()
                    if due:
                        (logger.debug if self.quiet else logger.info)("Worker %s due (last=%s)", self.name, last)
                        await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker %s check failed; will retry", self.name)
            try:
                await asyncio.sleep(self.check_every_s)
            except asyncio.CancelledError:
                raise

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    def status(self) -> dict:
        t = self._task
        state = "not started" if t is None else ("running" if not t.done() else
                ("cancelled" if t.cancelled() else ("crashed" if t.exception() else "finished")))
        return {"name": self.name, "state": state, "alive": self.alive(),
                "last_tick": self._last_tick.isoformat() if self._last_tick else None,
                "every_seconds": int(self.every.total_seconds()), "check_every_s": self.check_every_s,
                "enabled": bool(self.enabled()),
                "error": (str(t.exception())[:200] if t and t.done() and not t.cancelled() and t.exception() else None)}
