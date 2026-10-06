"""The one call the top bar makes, and the settings the shell reads.

A panel indicator is polled forever. `/api/aries/home` already assembles most of
what it needs, and reusing it would have been the tidy choice — but Home returns
proposals, notifications, findings, every automation and recent learning, which
is tens of kilobytes of JSON parsed inside `gnome-shell`'s own process, several
times a minute, for a badge and a coloured dot.

So this is a deliberately narrow endpoint: counts and severities, nothing that
needs rendering. It is the same shape of decision as Home's — one round trip
instead of eight — pointed the other way, at a caller that needs almost nothing
very often rather than everything once.

THE SEVERITY IS COMPUTED HERE, NOT IN THE SHELL
-----------------------------------------------
"Is ARIES all right?" is a judgement, and the shell must not make it. If the
extension decided that a degraded runtime plus two warnings equals amber, that
rule would exist twice and the top bar could disagree with the window it opens.
So the core answers with a severity from the one vocabulary, and the shell picks
a colour for it — which is all a shell should do.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

ORDER = {"ok": 0, "info": 0, "notice": 1, "warning": 2, "critical": 3}


def _worst(*severities: str) -> str:
    return max((s for s in severities if s), key=lambda s: ORDER.get(s, 0), default="ok")


async def status(db: AsyncSession) -> dict:
    """Small, cheap, and polled — everything the top bar shows."""
    from agentic_core.database.models import ActionProposal

    from aries.automations import genome
    from aries.brief.models import AriesBrief
    from aries.notify.policy import AriesNotification
    from aries.power import inhibit
    from aries.runtime.status import _components_from, component_snapshot
    from aries.settings import SettingsService

    settings = SettingsService(db)

    decisions = int((await db.execute(
        select(func.count(ActionProposal.id))
        .where(ActionProposal.status == "proposed"))).scalar() or 0)

    # `AriesNotification.severity` is an integer enum, not the health judge's
    # string vocabulary — the two look interchangeable and are not, and reading
    # one as the other put the number 1 where a severity name belonged. Converted
    # at the boundary, once, rather than left for the shell to guess at.
    from aries.health.findings import Severity
    notes = (await db.execute(
        select(AriesNotification.severity)
        .where(AriesNotification.disposition == "delivered")
        .order_by(AriesNotification.id.desc()).limit(20))).scalars().all()
    note_severity = _worst(*[Severity(n).label for n in notes]) if notes else "ok"

    health_run = await genome.last_run(db, "aries.health")
    detail = (health_run.as_dict().get("detail") or {}) if health_run else {}
    findings = [f for f in detail.get("findings", []) if f.get("severity") != "ok"]
    health_severity = _worst(*[f.get("severity", "ok") for f in findings]) if findings else "ok"

    specs = genome.all_automations()
    enabled = 0
    next_run, next_name = None, ""
    for spec in specs:
        if await genome.is_enabled(spec, settings):
            enabled += 1
            when = await genome.next_run_at(db, spec, settings)
            if when and (next_run is None or when < next_run):
                next_run, next_name = when, spec.name

    brief = (await db.execute(
        select(AriesBrief).order_by(AriesBrief.id.desc()).limit(1))).scalar_one_or_none()
    today = datetime.now().date()
    brief_today = bool(brief and brief.created_at and brief.created_at.date() == today)

    components = _components_from(await component_snapshot(db))
    broken = [c for c in components if not c.ok]
    runtime_severity = _worst(*[c.severity for c in broken]) if broken else "ok"

    power_cfg = await settings.section("power")
    autonomy = await settings.get("autonomy.level", fallback="assisted")

    # One judgement, made once. A pending decision is not a fault — it is ARIES
    # waiting correctly — so it raises attention without raising severity.
    severity = _worst(runtime_severity, health_severity, note_severity)

    return {
        "severity": severity,
        "state": "DEGRADED" if broken else "RUNNING",
        "summary": (f"{len(broken)} component(s) need attention" if broken
                    else f"{enabled} automation(s) enabled"),
        "decisions": decisions,
        "notifications": len(notes),
        "notification_severity": note_severity,
        "health_severity": health_severity,
        "health_findings": len(findings),
        "automations_enabled": enabled,
        "automations_total": len(specs),
        "next_run": next_run.isoformat() if next_run else None,
        "next_run_name": next_name,
        "brief_ready": brief_today,
        "background_mode": bool(power_cfg.get("power.background_mode")),
        "inhibitor_held": inhibit.held(),
        "autonomy": autonomy,
        "at": datetime.now(timezone.utc).isoformat(),
    }
