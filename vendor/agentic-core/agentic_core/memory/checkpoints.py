"""Checkpoints: durable progress a restart can resume from.

The marketing backend had four kinds and this module names them as one idea:
  * ExecutionPlan/Step rows        — a multi-step plan resumes at the first
                                     incomplete step (orchestrator/dag.py)
  * ExecutionOperation 'sent'      — persisted BEFORE the call, so a crash
                                     between send and record reconciles
  * worker cursors on disk         — e.g. the Telegram getUpdates offset, so a
                                     redeploy does not replay a batch
  * the last-run row in the DB     — workers pace on MAX(created_at) of their
                                     own AutomationLog line, not on a timer
This module provides the file-backed cursor and the DB last-run helpers."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from sqlalchemy import func, select

from agentic_core.config.settings import settings
from agentic_core.database.models import AutomationLog

logger = logging.getLogger(__name__)


def _path(name: str) -> str:
    return os.path.join(settings.data_dir, "cursors", f"{name}.cursor")


def load_cursor(name: str) -> str | None:
    try:
        with open(_path(name), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def save_cursor(name: str, value) -> None:
    path = _path(name)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(value))
        os.replace(tmp, path)
    except OSError:
        logger.warning("Could not persist cursor %s", name)


async def last_run_at(db, source: str, actions: tuple[str, ...] | None = None) -> datetime | None:
    q = select(func.max(AutomationLog.created_at)).where(AutomationLog.source == source)
    if actions:
        q = q.where(AutomationLog.action.in_(actions))
    return (await db.execute(q)).scalar()


async def mark_run(db, source: str, action: str, details: str = "", *, ok: bool = True) -> None:
    db.add(AutomationLog(action=action, source=source, details=details[:2000], status="success" if ok else "failure"))
