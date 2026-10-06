"""The deterministic gate every action passes before it touches the world.
Lifted from backend/app/policy/engine.py, made generic: a registry of rules,
each returning blocks/warnings, composed into one Decision that explains itself.

Built-in rules (mirroring the original's): a frequency cap on actions per
rolling hour, "nothing to act on", risk tier requires approval, and the tool's
own preconditions. Applications register more with `rule(...)`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.config.settings import settings
from agentic_core.database.models import ExecutionOperation

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    allowed: bool
    blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    risk: str = "low"
    requires_approval: bool = False

    @property
    def summary(self) -> str:
        if self.blocks:
            return "Blocked: " + " · ".join(self.blocks)
        if self.warnings:
            return "Allowed with notes: " + " · ".join(self.warnings)
        return "Allowed."

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "blocks": self.blocks, "warnings": self.warnings,
                "risk": self.risk, "requires_approval": self.requires_approval, "summary": self.summary}


# rule(db, action: dict, decision) -> None ; mutates decision
Rule = Callable[[AsyncSession, dict, Decision], Awaitable[None]]
_RULES: list[tuple[str, Rule]] = []


def rule(name: str):
    def deco(fn: Rule):
        _RULES.append((name, fn))
        return fn
    return deco


@rule("frequency")
async def _frequency(db, action, d):
    since = datetime.utcnow() - timedelta(hours=1)
    recent = (await db.execute(select(func.count(ExecutionOperation.id)).where(
        ExecutionOperation.state.in_(("sent", "succeeded")), ExecutionOperation.created_at >= since))).scalar() or 0
    if recent >= settings.max_actions_per_hour:
        d.blocks.append(f"too many actions in the last hour ({recent} ≥ {settings.max_actions_per_hour})")
        d.risk = "high"


@rule("payload")
async def _payload(db, action, d):
    if not (action.get("payload") or action.get("command") or action.get("content")):
        d.blocks.append("nothing to act on (empty payload)")


@rule("risk")
async def _risk(db, action, d):
    r = action.get("risk") or "low"
    if r == "high":
        d.requires_approval = True
        d.risk = "high"
        d.warnings.append("high-risk action — a human must approve")
    elif r == "medium" and d.risk == "low":
        d.risk = "medium"


async def evaluate(db: AsyncSession, action: dict) -> Decision:
    """`action` = {"tool", "payload"|"command", "risk", "target", ...}. Deterministic."""
    d = Decision(allowed=True)
    for name, fn in _RULES:
        try:
            await fn(db, action, d)
        except Exception:
            logger.exception("Policy rule %s crashed; treating as a block", name)
            d.blocks.append(f"rule '{name}' failed to evaluate — fail closed")
    d.allowed = not d.blocks
    if d.warnings and d.risk == "low":
        d.risk = "medium"
    return d


def registered() -> list[str]:
    return [n for n, _ in _RULES]
