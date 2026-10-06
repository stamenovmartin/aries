"""What goes into a morning brief, gathered one section at a time.

§13/01 lists what a brief should contain — important news, research, active
projects, calendar, deadlines, pending tasks, system warnings — and describes the
pipeline as PARALLEL COLLECTION followed by synthesis. Sections are therefore
independent collectors, registered by name, and the workflow runs them
concurrently.

EACH COLLECTOR OPENS ITS OWN DATABASE SESSION
---------------------------------------------
Not a style preference — verified on this machine before the design relied on it.
Five coroutines sharing one `AsyncSession` inside `asyncio.gather` raise:

    IllegalStateChangeError: Method 'close()' can't be called here;
    method '_connection_for_bind()' is already in progress

An `AsyncSession` is a single logical connection with in-flight state, and two
coroutines in it corrupt each other. The engine's own guidance says the same
thing from the other direction — "keep tool calls that share a session
sequential, or give each its own session" — and parallel collection is exactly
where that bites. So every collector takes no session and opens one.

HONEST ABSENCE
--------------
Several sections §13/01 asks for need integrations that do not exist yet:
calendar (§22), email (§21), projects (§13/05). They are declared here and
report themselves as **unavailable, with the reason**, rather than being omitted.
A brief that silently drops the calendar looks identical to a brief on a day with
no meetings, and the user cannot tell which they are reading.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import func, select

from agentic_core.database.base import async_session

logger = logging.getLogger(__name__)


@dataclass
class Item:
    """One line in a section."""

    text: str
    detail: str = ""
    link: str = ""
    severity: str = "info"        # info | notice | warning | critical
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"text": self.text, "detail": self.detail, "link": self.link,
                "severity": self.severity, "meta": self.meta}


@dataclass
class Section:
    """One part of the brief."""

    name: str
    title: str
    items: list[Item] = field(default_factory=list)
    summary: str = ""
    severity: str = "info"
    unavailable: str | None = None      # why there is nothing, when that is the reason
    duration_ms: int = 0

    @property
    def empty(self) -> bool:
        return not self.items

    def as_dict(self) -> dict:
        return {"name": self.name, "title": self.title, "summary": self.summary,
                "severity": self.severity, "unavailable": self.unavailable,
                "duration_ms": self.duration_ms,
                "items": [i.as_dict() for i in self.items]}


Collector = Callable[[dict], Awaitable[Section]]
_COLLECTORS: dict[str, Collector] = {}


def collector(name: str):
    def deco(fn: Collector):
        _COLLECTORS[name] = fn
        return fn
    return deco


def get(name: str) -> Collector | None:
    return _COLLECTORS.get(name)


def names() -> list[str]:
    return sorted(_COLLECTORS)


# ── system health ───────────────────────────────────────────────────────────

@collector("system")
async def system_section(cfg: dict) -> Section:
    """What the machine looked like at the last health pass."""
    from aries.automations.genome import last_run

    async with async_session() as db:
        row = await last_run(db, "aries.health")
    if row is None:
        return Section("system", "System", unavailable="the health automation has not run yet")

    detail = row.as_dict().get("detail") or {}
    findings = [f for f in detail.get("findings", []) if f["severity"] != "ok"]
    items = [Item(text=f["summary"], detail=f.get("advice", ""), severity=f["severity"],
                  meta={"code": f["code"]})
             for f in sorted(findings, key=lambda x: -_rank(x["severity"]))]
    worst = max((_rank(f["severity"]) for f in findings), default=0)
    age_min = (datetime.utcnow() - (row.started_at or datetime.utcnow())).total_seconds() / 60
    return Section("system", "System", items=items,
                   summary=("everything healthy" if not items
                            else f"{len(items)} thing(s) to look at"),
                   severity=_name(worst),
                   unavailable=(f"the last health pass was {age_min / 60:.0f}h ago"
                                if age_min > 24 * 60 else None))


def _rank(severity: str) -> int:
    return {"info": 0, "ok": 0, "notice": 1, "warning": 2, "critical": 3}.get(severity, 0)


def _name(rank: int) -> str:
    return ["info", "notice", "warning", "critical"][max(0, min(3, rank))]


# ── news ────────────────────────────────────────────────────────────────────

@collector("news")
async def news_section(cfg: dict) -> Section:
    """What was worth reading since the last brief, best first."""
    from aries.news.models import AriesNewsItem

    since = datetime.utcnow() - timedelta(hours=float(cfg.get("brief.window_hours", 24)))
    limit = int(cfg.get("news.max_items_per_briefing", 8))
    async with async_session() as db:
        from aries.news.selection import briefing_rows
        rows = await briefing_rows(db, limit=limit,
                                   hours=float(cfg.get("brief.window_hours", 24)))
        total = (await db.execute(
            select(func.count(AriesNewsItem.id)).where(
                AriesNewsItem.first_seen_at >= since))).scalar() or 0

    if not rows and total == 0:
        return Section("news", "News", unavailable="nothing collected since the last brief")
    items = [Item(text=r.title, detail=f"{r.source_id} · {r.published_at.isoformat() if r.published_at else 'датум непознат'} — {r.summary[:350]}", link=r.link,
                  severity="notice" if r.relevance >= 0.9 else "info",
                  meta={"relevance": round(r.relevance, 2), "source": r.source_id, "topics": r.topics,
                        "published": r.published_at.isoformat() if r.published_at else None})
             for r in rows]
    if cfg.get("news.local_summaries", False):
        import time
        from aries.news.summaries import summarize
        deadline = time.monotonic() + 90
        for row, item in zip(rows, items):
            # Native Macedonian feeds already provide an excerpt; no translation needed.
            if row.source_id in {"makfax-makedonija", "meta-mk", "telma", "sloboden-pecat"}:
                item.meta["summary_status"] = "original_macedonian"
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                item.meta["summary_status"] = "budget_exhausted"
                continue
            try:
                summary = await summarize(row.title, row.summary, timeout=min(45,remaining))
                item.meta["summary_status"] = summary["status"]
                item.meta["summary_cached"] = summary["cached"]
                item.meta["original_title"] = row.title
                item.meta["summary_source_digest"] = summary["source_digest"]
                if summary["status"] == "generated":
                    item.detail = "Локално AI резиме (непроверено): " + summary["summary_mk"] + " — " + row.source_id
            except Exception as exc:
                item.meta["summary_status"] = "fallback"
                item.meta["summary_error_type"] = type(exc).__name__
    return Section("news", "News", items=items,
                   summary=(f"{len(items)} worth your time, of {total} seen"
                            if items else f"nothing cleared the bar, of {total} seen"))


# ── decisions waiting on a human ────────────────────────────────────────────

@collector("decisions")
async def decisions_section(cfg: dict) -> Section:
    """§13/01's "pending tasks": what ARIES cannot do without the user.

    First section by default, because it is the only one that is BLOCKED on them.
    Everything else in a brief is information; this is a queue.
    """
    from agentic_core.database.models import ActionProposal

    async with async_session() as db:
        rows = (await db.execute(
            select(ActionProposal).where(ActionProposal.status == "proposed")
            .order_by(ActionProposal.id.desc()).limit(20))).scalars().all()
    if not rows:
        return Section("decisions", "Waiting for you", summary="nothing needs a decision")
    # The title alone is often the task's name ("System Health Monitor"), which
    # says nothing about what is being decided. The KIND is what distinguishes
    # "your disk is critical" from "this needs approval to run", so it goes in
    # the line itself rather than in a detail the reader may never see.
    items = [Item(text=f"{r.kind}: {r.title}" if r.title and r.kind not in (r.title or "")
                       else (r.title or r.kind),
                  detail=(r.rationale or "")[:300],
                  severity="critical" if r.risk == "high" else "warning",
                  meta={"proposal_id": r.id, "kind": r.kind, "risk": r.risk})
             for r in rows]
    return Section("decisions", "Waiting for you", items=items,
                   summary=f"{len(items)} decision(s) pending",
                   severity="critical" if any(r.risk == "high" for r in rows) else "warning")


# ── how ARIES itself is doing ───────────────────────────────────────────────

@collector("automations")
async def automations_section(cfg: dict) -> Section:
    """Automations that are failing or paused — ARIES reporting on itself.

    §13/20 asks ARIES to evaluate itself. This is the small, daily form: an
    automation that has quietly stopped working is exactly the kind of thing a
    user never notices on their own.
    """
    from aries.automations.breaker import state as breaker_state
    from aries.automations.genome import all_automations, health, is_enabled, last_run
    from aries.settings import SettingsService

    items = []
    async with async_session() as db:
        s = SettingsService(db)
        for spec in all_automations():
            if not await is_enabled(spec, s):
                continue
            breaker = await breaker_state(db, spec.automation_id)
            if not breaker.allows_run:
                items.append(Item(
                    text=f"{spec.name} is paused after {breaker.consecutive_failures} failures",
                    detail=breaker.last_error[:160], severity="warning",
                    meta={"automation_id": spec.automation_id}))
                continue
            h = await health(db, spec.automation_id, window_days=7)
            if h["success_rate"] is not None and h["success_rate"] < 0.8:
                items.append(Item(
                    text=f"{spec.name} succeeded {h['success_rate']:.0%} of the time this week",
                    detail=f"{h['runs']} runs", severity="notice",
                    meta={"automation_id": spec.automation_id}))
            row = await last_run(db, spec.automation_id)
            if row is not None and row.status == "failed":
                items.append(Item(text=f"{spec.name}'s last run failed",
                                  detail=(row.summary or "")[:160], severity="warning",
                                  meta={"automation_id": spec.automation_id}))
    return Section("automations", "ARIES itself", items=items,
                   summary="everything running" if not items else f"{len(items)} thing(s) degraded",
                   severity="warning" if items else "info")


# ── what ARIES has learned ──────────────────────────────────────────────────

@collector("learning")
async def learning_section(cfg: dict) -> Section:
    """What the loop concluded recently, so it is never a silent change."""
    from aries.interests.models import AriesInterest

    since = datetime.utcnow() - timedelta(hours=float(cfg.get("brief.window_hours", 24)))
    async with async_session() as db:
        rows = (await db.execute(
            select(AriesInterest).where(
                AriesInterest.learned_weight.is_not(None),
                AriesInterest.updated_at >= since))).scalars().all()
    if not rows:
        return Section("learning", "What I learned", summary="nothing changed")
    items = []
    for r in rows:
        shadowed = r.weight is not None
        items.append(Item(
            text=(f"'{r.topic}' — I would weight it {r.learned_weight:.2f}"
                  + (f", but yours is {r.weight:.2f}" if shadowed else "")),
            detail=(r.learned_rationale or "")[:200],
            severity="info", meta={"topic": r.topic, "shadowed": shadowed}))
    return Section("learning", "What I learned", items=items,
                   summary=f"{len(items)} preference(s) adjusted")


# ── sections that need something ARIES does not have yet ────────────────────

def _pending(name: str, title: str, why: str) -> Collector:
    async def _collect(cfg: dict) -> Section:
        return Section(name, title, unavailable=why)
    return _collect


for _name_, _title_, _why_ in (
    ("calendar", "Calendar", "no calendar is connected — Integrations (§22) is not built yet"),
    ("email", "Email", "no mailbox is connected — Integrations (§21) is not built yet"),
    ("projects", "Projects", "project tracking (§13/05) is not built yet"),
):
    _COLLECTORS[_name_] = _pending(_name_, _title_, _why_)
