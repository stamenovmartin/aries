"""The automation that enforces retention — declared, like every other.

Not a hidden cleaner in a worker. It is an `AutomationSpec`, so it appears in
the Automations screen with its purpose, its last run and its history; it can be
switched off; its failures open its circuit breaker; and it ships DISABLED like
everything else (§11). A process that deletes the user's data unasked, from a
place they cannot see, is the one automation that must not be invisible.
"""
from __future__ import annotations

import logging

from aries.automations.genome import AutomationSpec, register
from aries.settings.schema import SettingDef, define

logger = logging.getLogger(__name__)

AUTOMATION_ID = "aries.data"

define(SettingDef("data.enabled", bool, False, "Data lifecycle",
                  "Whether ARIES removes data that has passed its retention window, on a "
                  "schedule. Off means nothing is ever deleted automatically.",
                  "data", control="toggle", user_only=True))


async def run(ctx: dict) -> dict:
    """One pass: sweep abandoned working sets, then apply retention."""
    from aries.lifecycle import service, working

    db = ctx["db"]
    swept = await working.sweep(db)

    if not bool(await _cleaning_enabled(db)):
        return {"status": "ok",
                "summary": (f"swept {swept['swept']} abandoned working row(s); "
                            f"automatic deletion is off"),
                "swept": swept, "removed": 0}

    outcome = await service.apply(db)
    kept = sum(t["present"] for t in outcome["tables"])
    return {
        "status": "ok",
        "summary": (f"removed {outcome['removed']} row(s), kept {kept}"
                    if outcome["removed"] else
                    outcome.get("note", "nothing was past its window")),
        "swept": swept,
        "removed": outcome["removed"],
        "by_table": outcome.get("by_table", {}),
    }


async def _cleaning_enabled(db) -> bool:
    from aries.settings import SettingsService
    return bool(await SettingsService(db).get("data.cleaning_enabled"))


SPEC = register(AutomationSpec(
    automation_id=AUTOMATION_ID,
    name="Data Lifecycle",
    version="1.0.0",
    purpose="Release the context of finished work, and remove data that has passed the "
            "retention window the user set. Keeps ARIES from hoarding what it read.",
    run=run,
    trigger="schedule",
    schedule_setting="data.clean_interval_hours",
    default_interval_minutes=24 * 60,
    conditions=("nothing is deleted unless data.cleaning_enabled is on",
                "audit is never deleted",
                "a window below a dependant's minimum is refused, not clamped"),
    task_kind=None,                  # bookkeeping: nothing to evaluate or approve
    agents=[],
    tools=[],
    enabled_setting="data.enabled",
    risk="medium",                   # it deletes; that is not a low-risk verb
    workload="light",
    evaluation_metrics=["rows removed", "rows kept", "database size"],
))
