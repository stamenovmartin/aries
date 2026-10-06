"""Applying retention: rehearse, refuse, report.

THREE RULES THIS FOLLOWS
------------------------
**Nothing is deleted that a dependant still needs.** Every policy names what
reads it and the shortest window that keeps those readers correct. A window
below the minimum is refused — not clamped silently, refused with the reason —
because the failure it prevents is not a crash. The circuit breaker with no run
history does not error; it decides the automation is fine. Learning with no
engagement rows does not fail; it concludes less. A subsystem that quietly
starts answering differently is the worst outcome available here.

**The first pass is a rehearsal.** `preview()` counts what would go without
touching anything, and `data.dry_run_first` makes a real pass do that first and
act only on the next one. Anything that deletes should be boring by the time it
runs.

**Every deletion is audited.** The audit log itself is never cleaned — a
retention policy that erased the evidence of its own deletions would be the one
part of this system nobody could check.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aries.lifecycle import policy
from aries.settings import SettingsService

logger = logging.getLogger(__name__)


async def _table_exists(db: AsyncSession, table: str) -> bool:
    row = (await db.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table})).first()
    return row is not None


async def _window_for(settings: SettingsService, rule: policy.Retention) -> tuple[int | None, str]:
    """The window in days, and why it is what it is."""
    if rule.forever:
        return None, "kept until you remove it"
    days = int(await settings.get(rule.setting, fallback=rule.default_days))
    if days < rule.minimum_days:
        # Refused, not clamped. A window that starves a dependant is a
        # correctness bug wearing a preference's clothes.
        return rule.minimum_days, (
            f"{days} days is below the {rule.minimum_days}-day minimum "
            f"({', '.join(rule.dependants)} read this), so {rule.minimum_days} was used")
    return days, f"older than {days} days"


async def preview(db: AsyncSession) -> dict:
    """What a cleaning pass would remove. Touches nothing."""
    settings = SettingsService(db)
    now = datetime.now(timezone.utc)
    lines: list[dict] = []
    total = 0

    for rule in policy.POLICIES:
        if not await _table_exists(db, rule.table):
            continue
        present = (await db.execute(
            text(f'SELECT COUNT(*) FROM "{rule.table}"'))).scalar() or 0

        if rule.kind == policy.WORKING:
            # Not a window in days: the orphan sweep. Counting it here means
            # `aries data` shows the one thing a person actually wants to know
            # about the working set — whether anything has been left behind.
            from aries.lifecycle import working
            orphan_cutoff = now - timedelta(hours=working.SWEEP_HOURS)
            orphans = (await db.execute(
                text(f'SELECT COUNT(*) FROM "{rule.table}" WHERE created_at < :cutoff'),
                {"cutoff": orphan_cutoff.replace(tzinfo=None)})).scalar() or 0
            total += orphans
            lines.append({"table": rule.table, "kind": rule.kind, "reason": rule.reason,
                          "present": present,
                          "would_remove": orphans, "hours": working.SWEEP_HOURS,
                          "why": f"released when the task ends; orphans collected after "
                                 f"{working.SWEEP_HOURS}h",
                          "dependants": list(rule.dependants)})
            continue

        if rule.kind == policy.AUDIT:
            lines.append({"table": rule.table, "kind": rule.kind, "reason": rule.reason,
                          "present": present,
                          "would_remove": 0, "why": "never deleted automatically"})
            continue
        if rule.forever:
            lines.append({"table": rule.table, "kind": rule.kind, "reason": rule.reason,
                          "present": present,
                          "would_remove": 0, "why": "kept until you remove it"})
            continue

        days, why = await _window_for(settings, rule)
        cutoff = now - timedelta(days=days)
        stale = (await db.execute(
            text(f'SELECT COUNT(*) FROM "{rule.table}" WHERE {rule.timestamp_column} < :cutoff'),
            {"cutoff": cutoff.replace(tzinfo=None)})).scalar() or 0
        total += stale
        lines.append({"table": rule.table, "kind": rule.kind, "reason": rule.reason,
                          "present": present,
                      "would_remove": stale, "why": why, "days": days,
                      "dependants": list(rule.dependants)})

    size = (await db.execute(
        text("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
    )).scalar() or 0
    return {"at": now.isoformat(), "tables": lines, "would_remove": total,
            "database_bytes": size}


async def apply(db: AsyncSession, *, force: bool = False) -> dict:
    """Remove what has passed its window. Records what it did, in audit."""
    from agentic_core.observability.audit import log_event

    settings = SettingsService(db)
    plan = await preview(db)

    if not force and bool(await settings.get("data.dry_run_first")):
        # A rehearsal is recorded so the next pass can tell it happened, and so
        # a user who asks "what would you delete?" gets the same answer the
        # cleaner acted on rather than a fresh one computed later.
        await log_event(db, actor_type="system", actor="aries:data",
                        action="data.rehearsed",
                        detail={"would_remove": plan["would_remove"],
                                "tables": [t for t in plan["tables"] if t["would_remove"]]})
        await settings.set("data.dry_run_first", False, set_by="user:data", commit=False)
        await db.commit()
        return {**plan, "removed": 0,
                "note": "rehearsed only — the next pass will act on this plan"}

    removed: dict[str, int] = {}
    now = datetime.now(timezone.utc)
    for line in plan["tables"]:
        if not line["would_remove"]:
            continue
        rule = policy.BY_TABLE[line["table"]]
        if rule.kind == policy.WORKING:
            from aries.lifecycle import working
            removed[rule.table] = (await working.sweep(db))["swept"]
            continue
        cutoff = now - timedelta(days=line["days"])
        result = await db.execute(
            text(f'DELETE FROM "{rule.table}" WHERE {rule.timestamp_column} < :cutoff'),
            {"cutoff": cutoff.replace(tzinfo=None)})
        removed[rule.table] = result.rowcount or 0

    if removed:
        await log_event(db, actor_type="system", actor="aries:data",
                        action="data.cleaned",
                        detail={"removed": removed, "total": sum(removed.values())})
        await db.commit()
        logger.info("data lifecycle removed %d row(s): %s", sum(removed.values()), removed)

    return {**plan, "removed": sum(removed.values()), "by_table": removed}


async def vacuum(db: AsyncSession) -> dict:
    """Give the freed space back to the filesystem.

    Deleting rows in SQLite leaves the file the same size — which means a user
    who just cleaned 3,000 rows looks at the database and sees no change, and
    reasonably concludes nothing happened.
    """
    before = (await db.execute(
        text("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
    )).scalar() or 0
    await db.execute(text("VACUUM"))
    after = (await db.execute(
        text("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
    )).scalar() or 0
    return {"before_bytes": before, "after_bytes": after, "reclaimed_bytes": before - after}
