"""The Automation Genome — specification §12, and the registry that holds them.

§11 insists automations are "versioned, inspectable workflows", and §27 requires
one graphical place showing, for every automation: whether it is enabled, its
version, purpose, trigger, last run, next run, last result, health, the agents it
uses, its permissions and its evolution history. None of that is possible if an
automation is just a function somebody scheduled.

So an automation is a DECLARATION — an `AutomationSpec` — plus a run history.
The split matters:

  * the SPEC is static, versioned and diffable. Two versions can be compared,
    a change can be reviewed before it is promoted, and §18's controlled
    evolution has something concrete to sandbox and roll back to.
  * the HISTORY is durable and append-only, so "last result", "health" and
    "failure history" are queries rather than state somebody has to remember to
    update.

CONCEPT — why a genome rather than a config file. §19 describes evolution at
seven levels, from parameters up to workflow topology. Every one of those
operates on a declaration: you cannot mutate, benchmark or roll back a Python
function, but you can do all three to a versioned object that says what the
automation is. The genome is what makes controlled evolution possible later
without redesigning anything now — and equally, what makes it impossible for an
automation to quietly change itself, since a new behaviour means a new version.

Fields follow §12. `execution_history` and `failure_history` are deliberately
NOT fields: they are derived from `AriesAutomationRun` rows, because a history
that must be maintained by hand is a history that goes stale.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base
from agentic_core.security.permissions import Permission

# An automation's body: given a context, do the work and report what happened.
AutomationFn = Callable[[dict], Awaitable[dict]]


@dataclass
class AutomationSpec:
    """One automation, declared. §12's genome."""

    automation_id: str                       # stable id, e.g. "aries.health"
    name: str                                # what the user sees
    version: str                             # semantic; a behaviour change means a new version
    purpose: str                             # one sentence, shown in the Control Centre
    run: AutomationFn

    # ── when it runs ────────────────────────────────────────────────────────
    trigger: str = "schedule"                # schedule | event | manual | threshold
    schedule_setting: str | None = None      # settings key holding the interval, in minutes
    default_interval_minutes: int = 60
    # An automation that belongs to a time of day rather than to an interval.
    # `time_setting` names a setting holding "HH:MM" in LOCAL time — a morning
    # brief at 07:30 is a statement about the user's morning, not about elapsed
    # minutes. When set, it replaces interval pacing entirely.
    time_setting: str | None = None
    conditions: list[str] = field(default_factory=list)   # human-readable preconditions

    # ── what it uses ────────────────────────────────────────────────────────
    input_sources: list[str] = field(default_factory=list)
    task_kind: str | None = None             # the engine task kind it runs through
    workflow: str | None = None
    agents: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    permissions: list[Permission] = field(default_factory=list)
    memory_dependencies: list[str] = field(default_factory=list)

    # ── control ─────────────────────────────────────────────────────────────
    # No automation is enabled by default (§11). The setting is the truth; the
    # spec only says where to look.
    enabled_setting: str | None = None
    writes_settings: list[str] = field(default_factory=list)   # what it may learn
    risk: str = "low"                        # low | medium | high
    requires_approval: bool = False

    # ── what it costs the machine (Entry 013's resource policy) ─────────────
    # `risk` is about consequences — what this automation could do to the
    # user's data or attention if it went wrong. `workload` is about cost:
    # what it does to the processor, the GPU and the temperature while it is
    # merely working correctly. They are genuinely different axes, and a
    # single "is this a big deal?" field would have collapsed them: the
    # Morning Brief is low risk and lightweight; a nightly local-model
    # re-index would be low risk and very heavy indeed.
    #
    # Declared rather than measured, and declared here rather than in the
    # policy, so it is versioned with the rest of the genome and a change of
    # cost is a change of version. `light` by default: adding the field must
    # not silently reclassify anything that already exists.
    workload: str = "light"                  # light | inference_light | heavy_cpu | heavy_gpu
    # Would interrupting this mid-run lose work or leave a half-finished side
    # effect? Stateful work is never asked to stop in the middle — it is
    # recorded as over budget and its NEXT run waits instead.
    stateful: bool = False
    # A partial pass is normally unsuccessful. Diagnostic monitors may remain
    # useful without every sensor; they can explicitly make degraded neutral.
    breaker_on_degraded: bool = True

    # ── how it is judged (§12, and the reward signals of §17) ───────────────
    evaluation_metrics: list[str] = field(default_factory=list)
    reward_signals: list[str] = field(default_factory=list)

    # What this automation has learned so far, for §27's "learning status"
    # column. An async callable taking a session — the automation knows where
    # its own learning lives (a baseline table, learned rules, a policy), and the
    # Control Centre should not have to.
    learning_status: Callable[[AsyncSession], Awaitable[dict]] | None = None

    # ── evolution (§18/§19) ─────────────────────────────────────────────────
    parent_version: str | None = None
    evolution_history: list[dict] = field(default_factory=list)
    rollback_version: str | None = None

    def describe(self) -> dict:
        """The JSON the Automation Control Centre renders from."""
        return {"automation_id": self.automation_id, "name": self.name, "version": self.version,
                "purpose": self.purpose, "trigger": self.trigger,
                "schedule_setting": self.schedule_setting,
                "default_interval_minutes": self.default_interval_minutes,
                "time_setting": self.time_setting,
                "conditions": self.conditions, "input_sources": self.input_sources,
                "task_kind": self.task_kind, "workflow": self.workflow, "agents": self.agents,
                "tools": self.tools, "permissions": [p.value for p in self.permissions],
                "memory_dependencies": self.memory_dependencies,
                "enabled_setting": self.enabled_setting, "writes_settings": self.writes_settings,
                "risk": self.risk, "requires_approval": self.requires_approval,
                "workload": self.workload, "stateful": self.stateful,
                "breaker_on_degraded": self.breaker_on_degraded,
                "evaluation_metrics": self.evaluation_metrics, "reward_signals": self.reward_signals,
                "parent_version": self.parent_version, "evolution_history": self.evolution_history,
                "rollback_version": self.rollback_version,
                "has_learning_status": self.learning_status is not None}


class AriesAutomationRun(Base):
    """One execution of one automation. Append-only; the source of every
    'last run', 'health' and 'failure history' the Control Centre shows."""

    __tablename__ = "aries_automation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    automation_id: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(40), default="")
    trigger: Mapped[str] = mapped_column(String(40), default="schedule")
    status: Mapped[str] = mapped_column(String(30), index=True)    # ok | degraded | failed | skipped
    summary: Mapped[str] = mapped_column(String(500), default="")
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    def as_dict(self) -> dict:
        return {"id": self.id, "automation_id": self.automation_id, "version": self.version,
                "trigger": self.trigger, "status": self.status, "summary": self.summary,
                "detail": json.loads(self.detail_json) if self.detail_json else None,
                "task_id": self.task_id, "duration_ms": self.duration_ms,
                "started_at": self.started_at.isoformat() if self.started_at else None}


_REGISTRY: dict[str, AutomationSpec] = {}


def register(spec: AutomationSpec, *, replace: bool = False) -> AutomationSpec:
    if spec.automation_id in _REGISTRY and not replace:
        raise ValueError(f"automation '{spec.automation_id}' is already registered")
    _REGISTRY[spec.automation_id] = spec
    return spec


def get(automation_id: str) -> AutomationSpec | None:
    return _REGISTRY.get(automation_id)


def all_automations() -> list[AutomationSpec]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


async def is_enabled(spec: AutomationSpec, settings) -> bool:
    """No automation runs unless its setting says so (§11)."""
    if spec.enabled_setting is None:
        return False
    return bool(await settings.get(spec.enabled_setting))


async def interval_minutes(spec: AutomationSpec, settings) -> int:
    if spec.schedule_setting is None:
        return spec.default_interval_minutes
    from aries.settings import get_def
    definition = get_def(spec.schedule_setting)
    factor = 60 if definition and definition.unit == 'hours' else 1
    return int(await settings.get(spec.schedule_setting, fallback=spec.default_interval_minutes / factor)) * factor


async def record_run(db: AsyncSession, spec: AutomationSpec, *, status: str, summary: str,
                     detail: dict | None = None, task_id: int | None = None,
                     duration_ms: int = 0, trigger: str = "schedule") -> AriesAutomationRun:
    row = AriesAutomationRun(
        automation_id=spec.automation_id, version=spec.version, trigger=trigger, status=status,
        summary=summary[:500],
        detail_json=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
        task_id=task_id, duration_ms=duration_ms)
    db.add(row)
    await db.flush()
    return row


async def last_run(db: AsyncSession, automation_id: str) -> AriesAutomationRun | None:
    return (await db.execute(
        select(AriesAutomationRun).where(AriesAutomationRun.automation_id == automation_id)
        .order_by(AriesAutomationRun.id.desc()).limit(1)
    )).scalar_one_or_none()


async def health(db: AsyncSession, automation_id: str, *, window_days: int = 7) -> dict:
    """Recent reliability — what the Control Centre's health column shows.

    Honest observability (§13/20): with no runs in the window this reports a
    success rate of `None` with a reason, never 0.0, because "never ran" and
    "always failed" are different facts and only one of them is alarming.
    """
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    rows = (await db.execute(
        select(AriesAutomationRun.status, func.count(AriesAutomationRun.id))
        .where(AriesAutomationRun.automation_id == automation_id,
               AriesAutomationRun.started_at >= cutoff)
        .group_by(AriesAutomationRun.status)
    )).all()
    counts = {status: int(n) for status, n in rows}
    total = sum(counts.values())
    if total == 0:
        return {"automation_id": automation_id, "window_days": window_days, "runs": 0,
                "success_rate": None, "reason": "no runs in the window", "counts": counts}
    return {"automation_id": automation_id, "window_days": window_days, "runs": total,
            "success_rate": round(counts.get("ok", 0) / total, 3), "reason": None, "counts": counts}


def _parse_hhmm(text: str) -> tuple[int, int] | None:
    try:
        h, m = str(text).strip().split(":")
        h, m = int(h), int(m)
        return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None
    except (ValueError, AttributeError):
        return None


async def _daily_target(spec: AutomationSpec, settings, *, now_local: datetime) -> datetime | None:
    """Today's scheduled moment, in local time, or None if not time-scheduled."""
    if not spec.time_setting:
        return None
    hhmm = _parse_hhmm(await settings.get(spec.time_setting, fallback="07:30"))
    if hhmm is None:
        return None
    return now_local.replace(hour=hhmm[0], minute=hhmm[1], second=0, microsecond=0)


async def next_run_at(db: AsyncSession, spec: AutomationSpec, settings) -> datetime | None:
    """When this automation is next expected to run, or None if it never will.

    Derived from the last recorded run plus the interval — the same source
    `due()` uses, so the two can never disagree. A disabled automation has no
    next run, and that is reported as None rather than as a date that will not
    happen.
    """
    if not await is_enabled(spec, settings) or spec.trigger != "schedule":
        return None
    if spec.time_setting:
        now_local = datetime.now()
        target = await _daily_target(spec, settings, now_local=now_local)
        if target is None:
            return None
        return target if now_local < target else target + timedelta(days=1)
    row = await last_run(db, spec.automation_id)
    if row is None or row.started_at is None:
        return datetime.utcnow()                 # due now
    return row.started_at + timedelta(minutes=await interval_minutes(spec, settings))


async def due(db: AsyncSession, spec: AutomationSpec, settings, *, now: datetime | None = None) -> tuple[bool, str]:
    """Whether the automation should run now.

    Paced by the LAST RECORDED RUN rather than by a timer, which is the engine's
    rule for its workers: a missed cycle (the machine was asleep, the process
    restarted) is caught up on the next poll instead of being silently skipped.
    """
    if not await is_enabled(spec, settings):
        return False, "disabled"
    row = await last_run(db, spec.automation_id)

    if spec.time_setting:
        # Time-of-day pacing: due once the local moment has passed, unless a run
        # has already happened since it. Still driven by the last RECORDED run,
        # so a machine asleep at 07:30 produces the brief when it wakes rather
        # than skipping the day — the same catch-up rule as interval pacing.
        now_local = now or datetime.now()
        target = await _daily_target(spec, settings, now_local=now_local)
        if target is None:
            return False, f"{spec.time_setting} is not a valid time"
        if now_local < target:
            return False, f"scheduled for {target.strftime('%H:%M')} today"
        if row is None:
            return True, f"never run, and {target.strftime('%H:%M')} has passed"
        # started_at is UTC; the target is local. Compare in one frame.
        last_local = row.started_at + (now_local - datetime.utcnow())
        if last_local >= target:
            return False, f"already ran today at {last_local.strftime('%H:%M')}"
        return True, f"due since {target.strftime('%H:%M')}"

    if row is None:
        return True, "never run"
    every = await interval_minutes(spec, settings)
    age = (now or datetime.utcnow()) - (row.started_at or datetime.utcnow())
    if age >= timedelta(minutes=every):
        return True, f"last run {age.total_seconds() / 60:.0f} min ago (every {every} min)"
    return False, f"ran {age.total_seconds() / 60:.0f} min ago (every {every} min)"
