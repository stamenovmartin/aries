"""A circuit breaker for automations — the debt recorded in Entry 004.

Until now an automation that failed every tick was retried every tick, forever.
That was tolerable while the only automation read `/proc` and could not really
fail. It stops being tolerable the moment one talks to a network: a feed host
that is down, a credential that expired, a DNS name that no longer exists — each
produces an automation that fails on a fixed schedule indefinitely, burning
requests, filling the run history with noise, and (once anything costs money)
spending it.

CONCEPT — the circuit breaker. Borrowed from electrical engineering by way of
distributed systems. Three states:

    CLOSED     normal. Calls go through. Failures are counted.
    OPEN       too many consecutive failures. Calls are REFUSED without being
               attempted, for a cooldown period.
    HALF_OPEN  the cooldown has passed. Exactly one trial call is allowed. If it
               succeeds the breaker closes and normal service resumes; if it
               fails the breaker opens again for another cooldown.

The half-open state is what makes a breaker different from simply giving up. A
system that disables a failing integration forever needs a human to notice and
re-enable it; a breaker re-tests on its own and heals when the world does, while
still not hammering a service that is down.

WHY IT READS THE RUN HISTORY RATHER THAN HOLDING STATE
------------------------------------------------------
The obvious implementation is a counter in memory. It would be wrong here for
the same reason the dispatcher is paced by the last recorded run rather than a
timer: a process restart resets it, so a failing automation gets a fresh set of
attempts every time the API is restarted — and during an incident, restarts are
exactly what happens. `AriesAutomationRun` is already durable and already records
every outcome, so the breaker is a query over facts rather than a second copy of
them that can disagree.

A `skipped` run (the overlap lock from Entry 004) is neither success nor failure
and is ignored: refusing to start because a previous pass was still running says
nothing about whether the automation works.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aries.automations.genome import AriesAutomationRun, get
from aries.settings.schema import SettingDef, define

logger = logging.getLogger(__name__)

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"

define(SettingDef("automations.breaker_threshold", int, 3, "Failures before pausing",
                  "How many unsuccessful passes in a row (failed or degraded unless the workflow "
                  "explicitly exempts partial diagnostic passes) before ARIES stops running "
                  "it and waits. Set to 0 to never pause a failing automation.",
                  "automations", control="number", minimum=0, maximum=100, unit="failures"))
define(SettingDef("automations.breaker_cooldown_minutes", int, 30, "Wait before retrying",
                  "How long ARIES waits after pausing a failing automation before allowing one "
                  "trial run.",
                  "automations", control="number", minimum=1, maximum=1440, unit="minutes"))


@dataclass
class BreakerState:
    state: str
    consecutive_failures: int
    threshold: int
    opened_at: datetime | None = None
    retry_at: datetime | None = None
    last_error: str = ""

    @property
    def allows_run(self) -> bool:
        return self.state in (CLOSED, HALF_OPEN)

    def as_dict(self) -> dict:
        return {"state": self.state, "consecutive_failures": self.consecutive_failures,
                "threshold": self.threshold, "allows_run": self.allows_run,
                "opened_at": self.opened_at.isoformat() if self.opened_at else None,
                "retry_at": self.retry_at.isoformat() if self.retry_at else None,
                "last_error": self.last_error,
                "means": {
                    CLOSED: "running normally",
                    OPEN: "paused after repeated failures; will try once after the cooldown",
                    HALF_OPEN: "cooldown over — the next run is a trial",
                }[self.state]}


async def state(db: AsyncSession, automation_id: str, *, threshold: int | None = None,
                cooldown_minutes: int | None = None, now: datetime | None = None) -> BreakerState:
    """The breaker's state, computed from the durable run history."""
    from aries.settings import SettingsService

    settings = SettingsService(db)
    if threshold is None:
        threshold = int(await settings.get("automations.breaker_threshold"))
    if cooldown_minutes is None:
        cooldown_minutes = int(await settings.get("automations.breaker_cooldown_minutes"))
    now = now or datetime.utcnow()

    # A partial pass cannot prove recovery. Diagnostic automations explicitly
    # exempting degraded passes treat them as neutral, never as successful.
    spec = get(automation_id)
    count_degraded = spec is None or spec.breaker_on_degraded
    outcomes = ("ok", "degraded", "failed") if count_degraded else ("ok", "failed")
    rows = list((await db.execute(
        select(AriesAutomationRun)
        .where(AriesAutomationRun.automation_id == automation_id,
               AriesAutomationRun.status.in_(outcomes))
        .order_by(AriesAutomationRun.id.desc()).limit(max(1, threshold) * 4)
    )).scalars().all())

    streak, opened_at, last_error = 0, None, ""
    for row in rows:
        if row.status in ("failed", "degraded"):
            streak += 1
            # Rows are newest first. A failed half-open trial must start a new
            # cooldown, not inherit the first failure's already-expired one.
            if opened_at is None:
                opened_at = row.started_at
            last_error = last_error or (row.summary or "")
        else:
            break

    if threshold <= 0 or streak < threshold:
        return BreakerState(CLOSED, streak, threshold, last_error=last_error)

    retry_at = (opened_at or now) + timedelta(minutes=cooldown_minutes)
    if now >= retry_at:
        return BreakerState(HALF_OPEN, streak, threshold, opened_at=opened_at,
                            retry_at=retry_at, last_error=last_error)
    return BreakerState(OPEN, streak, threshold, opened_at=opened_at, retry_at=retry_at,
                        last_error=last_error)


async def check(db: AsyncSession, automation_id: str, *, now: datetime | None = None) -> BreakerState:
    """What `run_automation` calls before starting a pass."""
    return await state(db, automation_id, now=now)
