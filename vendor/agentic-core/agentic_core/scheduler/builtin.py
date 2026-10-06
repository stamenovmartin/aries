"""The default workers, mirroring the marketing lifespan roster:
  scheduler   ← scheduler_worker     fires due ScheduledTasks (+ crash sweep)
  learning    ← learning_scheduler   nightly feedback → rules distillation
  triggers    ← data_worker/triggers events → proposed tasks
  housekeeping ← proposals.expire_stale  expire undecided proposals out loud
  autopilot   ← autopilot/loop       runtime-gated self-proposed work (hook)"""
from __future__ import annotations

import logging
from datetime import timedelta

from agentic_core.config import runtime
from agentic_core.config.settings import settings
from agentic_core.database.base import async_session
from agentic_core.scheduler.registry import register
from agentic_core.scheduler.worker import Worker

logger = logging.getLogger(__name__)


async def _scheduler_pass():
    from agentic_core.memory.recovery import recover_stuck
    from agentic_core.scheduler.scheduled import process_due
    await recover_stuck()
    async with async_session() as db:
        outcomes = await process_due(db)
    return {"processed": len(outcomes), "outcomes": outcomes[:20]}


async def _learning_pass():
    from agentic_core.memory.feedback import distill
    async with async_session() as db:
        return await distill(db)


async def _triggers_pass():
    from agentic_core.scheduler.triggers import propose
    async with async_session() as db:
        return await propose(db)


async def _housekeeping_pass():
    from agentic_core.security.approvals import expire_stale
    async with async_session() as db:
        return {"expired": await expire_stale(db)}


_AUTOPILOT_FN = None


def set_autopilot(fn) -> None:
    """An application plugs in what 'propose work on your own' means."""
    global _AUTOPILOT_FN
    _AUTOPILOT_FN = fn


async def _autopilot_pass():
    if _AUTOPILOT_FN is None:
        return {"skipped": "no autopilot function registered"}
    return await _AUTOPILOT_FN()


register(Worker("scheduler", _scheduler_pass, every=timedelta(seconds=settings.scheduler_poll_seconds),
                check_every_s=max(5, settings.scheduler_poll_seconds), enabled=lambda: settings.scheduler_enabled))
register(Worker("learning", _learning_pass, every=timedelta(hours=24), check_every_s=1800,
                run_hour=settings.learning_run_hour, enabled=lambda: settings.learning_nightly_enabled))
register(Worker("triggers", _triggers_pass, every=timedelta(minutes=10), check_every_s=120))
register(Worker("housekeeping", _housekeeping_pass, every=timedelta(hours=6), check_every_s=1800))
register(Worker("autopilot", _autopilot_pass, every=timedelta(hours=20), check_every_s=900, enabled=runtime.get_autopilot))
