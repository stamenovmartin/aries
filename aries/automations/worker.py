"""The ARIES automations worker — one background task that dispatches them all.

Registered into the engine's worker roster, so it starts and stops with the API
process, is visible at `/api/observability/workers`, records a heartbeat, and is
never started under `APP_ENV=test` (a test wants the routes, not the clock).

ONE WORKER, NOT ONE PER AUTOMATION
----------------------------------
Each automation already knows its own interval, and `genome.due()` answers
"should this run now?" from its last recorded run. So the worker is a dispatcher
that wakes on a short cadence and asks each automation whether it is due, rather
than a timer per automation.

That choice matters for more than tidiness:

  * twenty automations do not become twenty asyncio tasks and twenty heartbeats;
  * an automation's interval can be changed in Settings and takes effect on the
    next tick, with no worker to restart;
  * pacing stays where it belongs — in the durable run history, not in a timer's
    memory, so a reboot or a suspended laptop resumes instead of resetting.

The cadence below (60s) is how often the question is ASKED, which is not how
often anything runs. An automation set to 15 minutes is checked 15 times and run
once; the 14 extra checks are one indexed query each.

WHY IT CAN BE TURNED OFF
------------------------
`automations.worker_enabled` defaults to FALSE. §11 says not to activate
everything automatically, and that applies most of all to the thing that runs
other things unattended. Turning it on is a deliberate act.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from agentic_core.scheduler.registry import register
from agentic_core.scheduler.worker import Worker

from aries.settings.schema import SettingDef, define

logger = logging.getLogger(__name__)

WORKER_NAME = "aries.automations"

define(SettingDef("automations.worker_enabled", bool, False, "Run automations in the background",
                  "Whether ARIES runs enabled automations on their own schedule. Off means "
                  "automations only run when explicitly asked.",
                  "automations", control="toggle", user_only=True))
define(SettingDef("automations.check_interval_seconds", int, 60, "Dispatcher cadence",
                  "How often ARIES asks which automations are due. This is not how often they "
                  "run — each automation has its own interval.",
                  "automations", control="number", minimum=10, maximum=3600, unit="seconds",
                  advanced=True, restart_required=True))


# The worker's `enabled` callback is synchronous (the engine calls it on every
# tick), but the setting lives in the database behind an async service. The value
# is therefore refreshed at the END of each pass and cached here. The cost is that
# switching the worker on takes effect one tick later; the alternative — a
# blocking database read inside a synchronous predicate on the event loop — is
# worse, and a one-tick delay on a background dispatcher is not a real cost.
_enabled_cache = {"value": False}


def worker_enabled() -> bool:
    return bool(_enabled_cache["value"])


async def _refresh_enabled() -> bool:
    from agentic_core.database.base import async_session

    from aries.settings import SettingsService
    async with async_session() as db:
        value = bool(await SettingsService(db).get("automations.worker_enabled"))
    _enabled_cache["value"] = value
    return value


async def dispatch_pass() -> dict:
    """One tick: reconcile Background Mode and the resource policy, refresh the
    switch, run what is due."""
    from agentic_core.database.base import async_session

    from aries.automations.runner import run_due
    from aries.power import governor, reconcile

    # BEFORE the enabled check, deliberately. Background Mode must hold its
    # inhibitor whether or not the automations dispatcher is switched on — and
    # the holder can die without asking, so this is also where a lost inhibitor
    # is noticed and retaken.
    power = {}
    try:
        async with async_session() as db:
            power = await reconcile(db, reason="dispatcher tick")
    except Exception:                                       # noqa: BLE001
        logger.exception("Background Mode reconcile failed")

    # Also before the enabled check, and for the same reason twice over. A heavy
    # job started by hand from the Control Centre keeps running while the
    # dispatcher is switched off, so its budget must still be watched; and a
    # thermal hold taken during that job must still be released afterwards, or
    # switching the dispatcher off would strand the policy in its last state.
    resources = {}
    try:
        async with async_session() as db:
            resources = {"released": await governor.release_holds(db),
                         "over_budget": await governor.check_budgets(db)}
            await db.commit()
    except Exception:                                       # noqa: BLE001
        logger.exception("Resource policy pass failed")

    enabled = await _refresh_enabled()
    if not enabled:
        return {"skipped": "automations.worker_enabled is off", "power": power,
                "resources": resources}
    out = await run_due(trigger="schedule")
    if out["ran"]:
        logger.info("ARIES automations: ran %d, skipped %d", out["ran"], out["skipped"])
    return {**out, "power": power, "resources": resources}


class DispatcherWorker(Worker):
    async def _due(self):
        # The per-automation run history decides when work is due. This poll
        # must keep refreshing switches even after a backward clock correction.
        return True, None


def register_worker(*, check_every_s: int = 60) -> Worker:
    """Add the dispatcher to the engine's roster. Idempotent."""
    from agentic_core.scheduler import registry
    existing = registry.get(WORKER_NAME)
    if existing is not None:
        return existing
    return register(DispatcherWorker(
        WORKER_NAME, dispatch_pass,
        # `every` is the worker's own pacing; the dispatcher must consider running
        # on every tick, so they are the same and per-automation intervals decide.
        every=timedelta(seconds=check_every_s),
        check_every_s=check_every_s,
        # Always allowed to TICK — the tick is what reads the switch. A pass with
        # the switch off does nothing but refresh it, which is how turning the
        # worker on from the UI can ever take effect without a restart.
        enabled=lambda: True,
    ))


register_worker()
