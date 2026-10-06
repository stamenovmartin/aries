"""The Morning Intelligence Brief — §13/01.

    parallel collection → compose → deliver

Every section is a node in a workflow the Director runs with `parallel=True`,
which is the first place ARIES actually uses concurrent execution. §13/01 asks
for parallel collection, and it is the right shape here: the sections share
nothing, several of them are independent queries, and the brief is only as fast
as its slowest section rather than the sum of them.

WHY NO SECTION NODE IS EVER SKIPPED
-----------------------------------
The obvious design gives each section a gate — "run the calendar node only if
`briefing.sections` includes calendar" — and `compose` depends on all of them.
That reproduces the bug Entry 007 found: a skipped dependency skips its
dependents, so disabling one section would skip the step that assembles the
brief.

So the sections always run, and a section that is switched off returns itself
marked `unavailable` instead. The information is identical from the user's side —
they see *why* a section is absent — and `compose` cannot be skipped by the
configuration it is meant to render.

WHY THE ORDER COMES FROM SETTINGS, NOT FROM THE GRAPH
-----------------------------------------------------
`briefing.sections` is a list, and the user's ordering is the brief's ordering.
The graph decides what is COLLECTED and in what concurrency; the setting decides
what is SHOWN and in what order. Keeping those apart means reordering a brief
never touches the workflow.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from agentic_core.evaluators.base import Evaluator, issue
from agentic_core.orchestrator.lifecycle import LifecyclePolicy
from agentic_core.scheduler.queue import register_kind
from agentic_core.security.permissions import Permission
from agentic_core.workflows import spec as wf

from aries.automations.genome import AutomationSpec, register
from aries.brief import sections as sec
from aries.brief import settings as _settings  # noqa: F401  registers the settings
from aries.brief.models import AriesBrief
from aries.brief.render import headline, render
from aries.notify import policy as notify
from aries.health.findings import Severity
from aries.settings import SettingsService

logger = logging.getLogger(__name__)

AUTOMATION_ID = "aries.brief"
TASK_KIND = "aries.brief.morning"
WORKFLOW = "morning_brief"


def _section_node(name: str):
    """One collector as a workflow node."""
    async def _run(ctx: dict) -> dict:
        cfg = ctx.get("brief_config") or {}
        enabled = ctx.get("enabled_sections") or []
        t0 = time.monotonic()
        if name not in enabled:
            section = sec.Section(name, name.title(),
                                  unavailable="not in briefing.sections")
        else:
            fn = sec.get(name)
            try:
                section = await fn(cfg)
            except Exception as e:                    # noqa: BLE001
                logger.exception("Brief section %s failed", name)
                # One broken section must not cost the user the brief.
                section = sec.Section(name, name.title(),
                                      unavailable=f"could not be collected: {type(e).__name__}: {e}")
        section.duration_ms = int((time.monotonic() - t0) * 1000)
        return {f"section_{name}": section}
    return _run


async def prepare(ctx: dict) -> dict:
    """Read the configuration once, before the parallel fan-out.

    Deliberately its own node: every collector needs the settings, and having
    each read them would mean eight concurrent settings queries for one answer.
    """
    db = ctx["db"]
    s = SettingsService(db)
    cfg = await s.section("briefing")
    cfg.update(await s.section("news"))
    cfg.update(await s.section("notifications"))
    cfg["brief.window_hours"] = float(await s.get("brief.window_hours"))
    enabled = [n for n in (cfg.get("briefing.sections") or []) if sec.get(n)]
    unknown = [n for n in (cfg.get("briefing.sections") or []) if not sec.get(n)]
    return {"brief_config": cfg, "enabled_sections": enabled, "unknown_sections": unknown,
            "brief_length": cfg.get("briefing.length", "standard")}


async def compose(ctx: dict) -> dict:
    """Assemble, store and deliver the brief."""
    db = ctx["db"]
    cfg = ctx.get("brief_config") or {}
    order = [n for n in (cfg.get("briefing.sections") or []) if sec.get(n)]
    # Anything collected but not listed goes after the user's ordering, so a new
    # section is visible without being silently ranked first.
    extra = [n for n in sec.names() if n not in order and f"section_{n}" in ctx]
    collected: list[sec.Section] = []
    for name in order + extra:
        section = ctx.get(f"section_{name}")
        if not isinstance(section, sec.Section):
            continue
        # A section the user switched off is ABSENT, not a line saying it is off.
        # "not in briefing.sections" is information for the operator, not for the
        # reader of a brief — printing it every morning is the noise §26 exists to
        # prevent, arriving by a different route.
        if section.unavailable == "not in briefing.sections":
            continue
        collected.append(section)

    length = ctx.get("brief_length", "standard")
    text = render(collected, length=length, when=datetime.now().strftime("%a %d %b, %H:%M"))
    line = headline(collected)
    items = sum(len(s.items) for s in collected)
    worst = max((sec._rank(i.severity) for s in collected for i in s.items), default=0)
    severity = sec._name(worst)

    row = AriesBrief(kind="morning", length=length, headline=line[:500],
                     sections_json=json.dumps([s.as_dict() for s in collected],
                                              ensure_ascii=False, default=str),
                     rendered=text, severity=severity, item_count=items,
                     duration_ms=sum(s.duration_ms for s in collected))
    db.add(row)
    await db.flush()

    # The brief itself is one notification, not one per item. Everything in it
    # has already been through the policy on its own; announcing the brief again
    # per item is precisely the noise §26 exists to prevent.
    decision, _ = await notify.emit(
        db, key=f"brief:{row.id}", title=f"Morning brief — {line}",
        severity=Severity.WARNING if worst >= 2 else Severity.NOTICE,
        source=AUTOMATION_ID, body=text[:2000], config=cfg)
    await db.commit()

    return {"result": {
        "success": True, "status": "ok",
        "summary": f"{items} item(s) across {len(collected)} section(s): {line}",
        "details": line, "brief_id": row.id, "headline": line, "length": length,
        "severity": severity, "item_count": items,
        "sections": [s.as_dict() for s in collected],
        "rendered": text, "delivery": decision.as_dict(),
        "unknown_sections": ctx.get("unknown_sections") or [],
    }}


SPEC_WF = wf.register(wf.WorkflowSpec(
    WORKFLOW,
    description="Collect every part of the morning brief at once, then assemble and deliver it.",
    parallel=True,
    nodes=[
        wf.NodeSpec("prepare", label="Read the configuration", fn=prepare),
        *[wf.NodeSpec(f"collect_{n}", label=f"Collect {n}", fn=_section_node(n),
                      depends_on=["prepare"])
          for n in sec.names()],
        wf.NodeSpec("compose", label="Assemble the brief", fn=compose,
                    depends_on=[f"collect_{n}" for n in sec.names()]),
    ]))


async def _produced_a_brief(result, task, ctx) -> list[dict]:
    if not isinstance(result, dict) or not result.get("brief_id"):
        return [issue("error", "no_brief", "the brief was not assembled")]
    return []


async def _section_health(result, task, ctx) -> list[dict]:
    out = []
    for s in (result or {}).get("sections", []):
        if s.get("unavailable") and "not in briefing.sections" not in (s["unavailable"] or ""):
            out.append(issue("warn", "section_unavailable", f"{s['title']}: {s['unavailable']}"))
    for name in (result or {}).get("unknown_sections", []):
        out.append(issue("warn", "unknown_section",
                         f"briefing.sections names '{name}', which does not exist"))
    return out


EVALUATORS = [
    Evaluator("brief_assembled", _produced_a_brief, weight=2.0),
    Evaluator("section_health", _section_health, weight=0.5),
]

SPEC = AutomationSpec(
    automation_id=AUTOMATION_ID,
    name="Morning Brief",
    version="1.0.0",
    purpose="Once a morning, gather what needs the user's decision, what the machine is doing, "
            "what is worth reading and what ARIES has learned — in one page.",
    run=lambda ctx: _via_task(ctx),
    trigger="schedule",
    time_setting="briefing.morning_time",
    default_interval_minutes=24 * 60,
    conditions=["briefing.morning_enabled is on", "the local time has passed briefing.morning_time"],
    input_sources=["aries_news_items", "aries_automation_runs", "action_proposals",
                   "aries_interests"],
    task_kind=TASK_KIND,
    workflow=WORKFLOW,
    agents=[],                       # assembly, not generation — no model involved
    tools=[],
    permissions=[Permission.VIEW_DATA],
    memory_dependencies=["aries_briefs"],
    enabled_setting="briefing.morning_enabled",
    writes_settings=[],
    risk="low",
    requires_approval=False,
    evaluation_metrics=["sections_available", "items_per_brief", "brief_seen_rate",
                        "decisions_cleared_after_brief"],
    reward_signals=["the brief was read", "a pending decision was resolved after it",
                    "the user changed briefing.length", "the user removed a section"],
    learning_status=lambda db: _learning_status(db),
)


async def _learning_status(db) -> dict:
    from sqlalchemy import func, select
    rows = (await db.execute(select(func.count(AriesBrief.id),
                                    func.sum(AriesBrief.item_count)))).one()
    seen = (await db.execute(select(func.count(AriesBrief.id))
                             .where(AriesBrief.seen.is_(True)))).scalar() or 0
    total = int(rows[0] or 0)
    return {"briefs": total, "items_total": int(rows[1] or 0), "seen": seen,
            "seen_rate": round(seen / total, 3) if total else None,
            "explanation": (
                f"{total} brief(s) produced, {seen} marked read. "
                + ("Preferred length and structure are not learned yet — §13/01 lists them, and "
                   "the record that would support it is what these rows are."
                   if total else "Nothing produced yet."))}


register(SPEC)
register_kind(TASK_KIND, workflow=WORKFLOW, evaluators=EVALUATORS,
              policy=LifecyclePolicy(max_retries=0, max_replans=0, pass_threshold=0.6))


async def _via_task(ctx: dict) -> dict:
    raise RuntimeError("aries.brief runs through its task kind, not directly")
