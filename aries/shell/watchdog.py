"""Bring the ARIES shell back when GNOME leaves it switched off.

On 2026-09-29 the extension went INACTIVE twice when the screen blanked (17:49,
17:59) and stayed that way after the person came back: no panel, no dock, no
Super+Space, and every desktop action reported "bridge unavailable". GNOME
disables extensions while the screen shield is up and is meant to re-enable
them afterwards; in the ARIES session mode it did not. The setting still said
"enabled", so `gnome-extensions enable` was a no-op — only disable+enable
brings it back.

This watches for exactly that state and repairs it, and nothing else:
  * the shield is down (ScreenSaver.GetActive is false) — while it is up,
    INACTIVE is GNOME doing its job, not a fault;
  * the extension is Enabled in settings but State INACTIVE / ERROR;
  * never in tests, where it would toggle the developer's real desktop.
Every repair is written to the audit log so it is visible, not silent.
"""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import timedelta

UUID = "aries@aries.local"
logger = logging.getLogger(__name__)


def _run(*argv: str, timeout: float = 5) -> str | None:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def extension_state() -> tuple[bool | None, str | None]:
    """(enabled in settings, runtime state) — None where it cannot be read."""
    info = _run("gnome-extensions", "info", UUID)
    if info is None:
        return None, None
    enabled = re.search(r"Enabled:\s*(\w+)", info)
    state = re.search(r"State:\s*(\w+)", info)
    return ((enabled.group(1).lower() in ("yes", "true")) if enabled else None,
            state.group(1).upper() if state else None)


def needs_repair(enabled: bool | None, state: str | None, shield_up: bool | None) -> bool:
    return enabled is True and shield_up is False and state in ("INACTIVE", "ERROR", "DISABLED")


def repair() -> dict:
    from aries.operator.desktop import session_locked
    enabled, state = extension_state()
    shield = session_locked()
    if not needs_repair(enabled, state, shield):
        return {"idle": True, "state": state}
    _run("gnome-extensions", "disable", UUID)
    _run("gnome-extensions", "enable", UUID)
    _, after = extension_state()
    return {"repaired": after == "ACTIVE", "was": state, "now": after}


async def tick() -> dict:
    import asyncio
    out = await asyncio.to_thread(repair)
    if not out.get("idle"):
        logger.warning("ARIES shell was %s with the screen unlocked; re-enabled -> %s", out["was"], out["now"])
        from agentic_core.database.base import async_session
        from agentic_core.observability.audit import log_event
        async with async_session() as db:
            await log_event(db, actor_type="system", actor="aries:shell.watchdog",
                            action="shell.reenabled", detail=out)
            await db.commit()
    return out


def _enabled() -> bool:
    from agentic_core.security import environments
    return not environments.is_test()


from agentic_core.scheduler.registry import register  # noqa: E402
from agentic_core.scheduler.worker import Worker  # noqa: E402

register(Worker("aries.shell.watchdog", tick, every=timedelta(seconds=15), check_every_s=15,
                enabled=_enabled, quiet=True))
