"""Making the machine's state match the setting — and keeping it that way.

Background Mode is a setting; the inhibitor is a live process. `reconcile()` is
what keeps those two in agreement, and it is called from three places for three
different reasons:

    at startup           a reboot or a crash means no inhibitor is held, whatever
                         the setting says
    when the user toggles it   so the switch feels immediate rather than taking
                         up to a minute
    on every dispatcher tick   because the holder can die without asking — and
                         an inhibitor that silently stopped existing is exactly
                         the failure Background Mode must not have

It is idempotent, which is what lets it be called from all three without
coordination.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from aries.power import governor, inhibit, state
from aries.settings import Layer, SettingsService

logger = logging.getLogger(__name__)


async def reconcile(db: AsyncSession, *, reason: str = "tick") -> dict:
    """Bring the inhibitor and the display timeout into line with the settings."""
    s = SettingsService(db)
    cfg = await s.section("power")
    wanted = bool(cfg["power.background_mode"])
    allow_suspend = bool(cfg["power.allow_suspend"])
    should_hold = wanted and not allow_suspend

    actions: list[str] = []
    was_held = inhibit.held()

    if should_hold and not was_held:
        ok, detail = inhibit.acquire()
        actions.append(f"took the sleep inhibitor ({detail})" if ok
                       else f"could not take the sleep inhibitor: {detail}")
        if not ok:
            logger.warning("Background Mode is on but the inhibitor could not be taken: %s",
                           detail)
    elif not should_hold and was_held:
        ok, detail = inhibit.release()
        actions.append(f"released the sleep inhibitor ({detail})")

    # ── the display timeout: written, so recorded and restorable ────────────
    if wanted:
        target = int(cfg["power.display_off_after_minutes"]) * 60
        current = state.read_idle_delay()
        if current is not None and current != target:
            previous = int(cfg["power.restore_idle_delay"])
            if previous < 0:
                # First change. Remember what was there before touching it.
                await s.set("power.restore_idle_delay", current, layer=Layer.USER,
                            set_by="user:power", commit=False)
                actions.append(f"recorded the previous display timeout ({current}s)")
            ok, detail = state.write_idle_delay(target)
            actions.append(f"display timeout set to {target}s" if ok
                           else f"could not set the display timeout: {detail}")
    else:
        previous = int(cfg["power.restore_idle_delay"])
        if previous >= 0:
            ok, detail = state.write_idle_delay(previous)
            actions.append(f"display timeout restored to {previous}s" if ok
                           else f"could not restore the display timeout: {detail}")
            if ok:
                await s.set("power.restore_idle_delay", -1, layer=Layer.USER,
                            set_by="user:power", commit=False)

    if actions:
        await db.commit()
        logger.info("Background Mode reconciled (%s): %s", reason, "; ".join(actions))
    return {"background_mode": wanted, "allow_suspend": allow_suspend,
            "inhibitor_held": inhibit.held(), "actions": actions, "reason": reason}


async def snapshot(db: AsyncSession) -> dict:
    """Everything the status panel shows — measured, not remembered."""
    s = SettingsService(db)
    cfg = await s.section("power")
    display, display_why = state.display_state()
    mine = inhibit.listed()
    others = [row for row in inhibit.all_sleep_blockers() if not row.startswith(inhibit.WHO)]
    policy = state.read_suspend_policy()
    session = state.session()
    ok, unavailable = inhibit.available()

    wanted = bool(cfg["power.background_mode"])
    allow_suspend = bool(cfg["power.allow_suspend"])
    holding = inhibit.held()

    # An honest note, because on many machines suspend was never going to happen
    # anyway and ARIES should not claim credit for it.
    ac_type = policy.get("sleep-inactive-ac-type")
    if ac_type == "nothing":
        effect = ("this machine is already set never to suspend on mains power, so the "
                  "inhibitor changes nothing while it is plugged in — it matters on battery")
    elif holding:
        effect = "automatic suspend is being held back by ARIES"
    elif wanted and allow_suspend:
        effect = "Background Mode is on, but you have allowed normal suspend"
    else:
        effect = "normal power behaviour"

    return {
        "background_mode": wanted,
        "allow_suspend": allow_suspend,
        "allow_gpu_jobs": bool(cfg["power.allow_gpu_jobs"]),
        # Changed in the same milestone that made it true. The switch used to be
        # declared and unread; it is now the live gate for the `heavy_gpu`
        # workload class. What is still absent is an automation that declares
        # that class — a different and much smaller claim, and the note says
        # which of the two it is.
        "gpu_jobs_note": "the gate is live: any automation declaring heavy GPU work meets it. "
                         "No automation declares heavy GPU work yet, so nothing is being "
                         "refused today.",
        "display": {"state": display, "detail": display_why,
                    "off_after_seconds": state.read_idle_delay(),
                    "configured_minutes": int(cfg["power.display_off_after_minutes"]),
                    "will_restore_to": (int(cfg["power.restore_idle_delay"])
                                        if int(cfg["power.restore_idle_delay"]) >= 0 else None)},
        "system": {"awake": True, "session": session},
        "inhibitor": {
            "available": ok, "unavailable_reason": unavailable or None,
            "active": holding, "what": inhibit.WHAT, "mode": inhibit.MODE,
            "held_by_aries": mine,
            "other_sleep_blockers": others,
        },
        "suspend_policy": policy,
        "effect": effect,
        # Staying awake and being fit to work are two different questions, and
        # the panel answers both in one place because the user asks them
        # together: "is ARIES still going, and is it cooking my machine?"
        "resources": await governor.snapshot(db),
    }
