"""The resource policy: whether the machine may do *this* work right now.

Background Mode answers "may the machine stay awake?". This answers the question
that only becomes urgent once the first answer is yes — because a machine that
never sleeps and will start anything it is asked to is a machine that can spend
a night at 95 °C with nobody in the room.

THE SHAPE OF THE RULE
---------------------
Two gates, and they are not the same kind of thing:

  * **permission** — may this *class* of work run unattended at all? A static
    question, answered from settings, and default-closed for heavy work. Nothing
    measures anything.
  * **condition** — is the machine in a state to take it *now*? A live question,
    answered from the processor, the GPU and the thermal sensors.

Keeping them apart is what makes the refusals legible. "Heavy GPU work is not
enabled while the display is off" and "the machine is at 84 °C" are different
problems with different fixes, and a policy that reported one number for both
would leave the user guessing which.

WHAT IS NEVER DEFERRED
----------------------
Lightweight work. Health checks, news fetching, memory maintenance and short
inference all run regardless of temperature, and that is deliberate rather than
an oversight: they cost a fraction of a core for seconds, and the health check in
particular is *how ARIES learns the machine is hot*. A policy that silenced its
own thermometer to save heat would be measuring nothing and protecting nothing.

HYSTERESIS, AGAIN
-----------------
Entry 010 taught this project that hysteresis expressed as a moved threshold
becomes an unreachable rule. The same trap is here: "resume when below the limit"
restarts the job the instant the fan wins one degree, and the machine oscillates.
So resuming requires the temperature to come back below the limit *minus a
margin*, and to stay there for a number of consecutive checks. Both are settings,
both are reachable, and the margin is measured downward from a limit the user
chose rather than being a second limit nobody can see.

MEASUREMENT
-----------
CPU utilisation is a delta of `/proc/stat` between calls, so on the dispatcher's
cadence it reports the average since the last check — which is the right window
for a rule about *sustained* load. The first call has nothing to subtract, so it
samples over a quarter of a second instead. Temperature and GPU reuse the health
probes rather than reading the sensors a second way: two readers of one sensor
drift, and the health screen and the power policy disagreeing about how hot the
machine is would be worse than either being slightly stale.

Readings are cached for a few seconds. Four automations asking in the same tick
is one measurement, not four.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

from aries.power import state, workload
from aries.settings import SettingsService

logger = logging.getLogger(__name__)

MEASUREMENT_TTL_S = 5.0


# ── the record ──────────────────────────────────────────────────────────────

class AriesResourceEvent(Base):
    """Append-only: every time the resource policy said no, or let go again.

    A separate table from the engine's audit log, and written *in addition* to
    it, for the reason the automation run history is separate from it too: this
    is queried — "is there a hold on heavy CPU work right now?" is answered by
    reading the last row for that class, and the current state of the policy is
    therefore derived from the record rather than remembered alongside it. A
    state kept next to its own history is a state that can disagree with it.
    """

    __tablename__ = "aries_resource_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)   # deferred|resumed|blocked|over_budget
    workload: Mapped[str] = mapped_column(String(40), index=True)
    automation_id: Mapped[str] = mapped_column(String(120), default="")
    reason: Mapped[str] = mapped_column(String(400), default="")
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    def as_dict(self) -> dict:
        return {"id": self.id, "at": self.at.isoformat() if self.at else None,
                "kind": self.kind, "workload": self.workload,
                "automation_id": self.automation_id, "reason": self.reason,
                "detail": json.loads(self.detail_json) if self.detail_json else None}


# ── measuring ───────────────────────────────────────────────────────────────

@dataclass
class Measurement:
    cpu_pct: float | None = None
    cpu_unavailable: str | None = None
    cpu_window: str = ""
    gpu_pct: float | None = None
    gpu_subject: str | None = None
    gpu_unavailable: str | None = None
    temperature_c: float | None = None
    temperature_subject: str | None = None
    temperature_unavailable: str | None = None
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {"cpu_pct": self.cpu_pct, "cpu_unavailable": self.cpu_unavailable,
                "cpu_window": self.cpu_window,
                "gpu_pct": self.gpu_pct, "gpu_subject": self.gpu_subject,
                "gpu_unavailable": self.gpu_unavailable,
                "temperature_celsius": self.temperature_c,
                "temperature_subject": self.temperature_subject,
                "temperature_unavailable": self.temperature_unavailable,
                "measured_at": datetime.fromtimestamp(self.at).isoformat()}


_cpu_sample: tuple[float, float] | None = None        # (idle_all, total)
_cached: Measurement | None = None


def _read_proc_stat() -> tuple[float, float] | None:
    try:
        with open("/proc/stat", "r") as fh:
            line = fh.readline()
    except OSError:
        return None
    parts = line.split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [float(v) for v in parts[1:]]
    except ValueError:
        return None
    if len(values) < 5:
        return None
    idle_all = values[3] + values[4]          # idle + iowait
    return idle_all, sum(values)


async def _cpu_utilisation() -> tuple[float | None, str | None, str]:
    """Per cent busy since the previous call, or over 250 ms on the first one."""
    global _cpu_sample
    now = _read_proc_stat()
    if now is None:
        return None, "/proc/stat unreadable", ""
    previous, window = _cpu_sample, "since the previous check"
    if previous is None:
        await asyncio.sleep(0.25)
        previous, window = now, "250 ms"
        now = _read_proc_stat()
        if now is None:
            return None, "/proc/stat unreadable", ""
    _cpu_sample = now
    d_idle, d_total = now[0] - previous[0], now[1] - previous[1]
    if d_total <= 0:
        # Two reads inside one clock tick. Not an error, and not zero either.
        return None, "no time elapsed between samples", window
    return round(max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total))), 1), None, window


async def measure(*, fresh: bool = False) -> Measurement:
    """Read the machine. Cached briefly so one tick is one measurement."""
    global _cached
    if _cached is not None and not fresh and (time.time() - _cached.at) < MEASUREMENT_TTL_S:
        return _cached

    from aries.health import probes

    m = Measurement()
    m.cpu_pct, m.cpu_unavailable, m.cpu_window = await _cpu_utilisation()

    try:
        thermal = await probes.probe_thermal()
    except Exception as e:                                     # noqa: BLE001
        thermal = None
        m.temperature_unavailable = f"{type(e).__name__}: {e}"
    if thermal is not None:
        hot = [r for r in thermal.readings if r.metric == "thermal.celsius" and r.value is not None]
        if hot:
            worst = max(hot, key=lambda r: r.value)
            m.temperature_c, m.temperature_subject = float(worst.value), worst.subject
        else:
            m.temperature_unavailable = thermal.unavailable or "no usable thermal zone"

    try:
        gpu = await probes.probe_gpu()
    except Exception as e:                                     # noqa: BLE001
        gpu = None
        m.gpu_unavailable = f"{type(e).__name__}: {e}"
    if gpu is not None:
        used = [r for r in gpu.readings if r.metric == "gpu.utilization_pct" and r.value is not None]
        if used:
            worst = max(used, key=lambda r: r.value)
            m.gpu_pct, m.gpu_subject = float(worst.value), worst.subject
        else:
            m.gpu_unavailable = gpu.unavailable or "no GPU reported"
        # A GPU's own temperature counts toward the thermal limit: it is in the
        # same case, and on most desktops it is the hottest thing in it.
        gpu_temps = [r for r in gpu.readings if r.metric == "gpu.temp_celsius" and r.value is not None]
        if gpu_temps:
            hottest = max(gpu_temps, key=lambda r: r.value)
            if m.temperature_c is None or float(hottest.value) > m.temperature_c:
                m.temperature_c, m.temperature_subject = float(hottest.value), hottest.subject
                m.temperature_unavailable = None

    _cached = m
    return m


async def limits(db: AsyncSession) -> dict:
    cfg = await SettingsService(db).section("power")
    return {"temperature_celsius": int(cfg["power.temperature_limit_celsius"]),
            "cpu_pct": int(cfg["power.cpu_limit_pct"]),
            "gpu_pct": int(cfg["power.gpu_limit_pct"]),
            "heavy_job_max_minutes": int(cfg["power.heavy_job_max_minutes"]),
            "resume_margin_celsius": int(cfg["power.thermal_resume_margin_celsius"]),
            "clear_checks": int(cfg["power.thermal_clear_checks"]),
            "allow_heavy_cpu": bool(cfg["power.allow_heavy_cpu"]),
            "allow_gpu_jobs": bool(cfg["power.allow_gpu_jobs"])}


# ── holds ───────────────────────────────────────────────────────────────────

_clear_streak: dict[str, int] = {}


async def _record(db: AsyncSession, *, kind: str, cls: str, reason: str,
                  automation_id: str = "", detail: dict | None = None) -> AriesResourceEvent:
    """One row here, one line in the engine's audit log. Neither is the other's
    copy: the row is what the policy reads back, the audit line is what a human
    reviewing everything ARIES did will page through."""
    from agentic_core.observability.audit import log_event

    event = AriesResourceEvent(kind=kind, workload=cls, automation_id=automation_id,
                               reason=reason[:400],
                               detail_json=json.dumps(detail, default=str) if detail else None)
    db.add(event)
    await log_event(db, actor_type="system", actor="aries:power",
                    action=f"resource_policy.{kind}", entity_type="workload", entity_id=cls,
                    detail={"reason": reason, "automation_id": automation_id, **(detail or {})})
    logger.info("resource policy %s for %s: %s", kind, cls, reason)
    return event


async def active_hold(db: AsyncSession, cls: str) -> AriesResourceEvent | None:
    """The current hold on a class, read back from the record rather than kept."""
    row = (await db.execute(
        select(AriesResourceEvent).where(AriesResourceEvent.workload == cls,
                                       AriesResourceEvent.kind.in_(("deferred", "over_budget", "resumed")))
        .order_by(AriesResourceEvent.id.desc()).limit(1))).scalar_one_or_none()
    if row is not None and row.kind in ("deferred", "over_budget"):
        return row
    return None


async def release_holds(db: AsyncSession, *, measurement: Measurement | None = None) -> list[dict]:
    """Let go of what is safe to let go of. Called on every dispatcher tick.

    Resuming is the half of a protective rule that is usually forgotten, and a
    rule that only ever tightens is a rule that ends with everything switched
    off. It is also where the oscillation lives, so it is the half with the
    margin and the streak.
    """
    lim = await limits(db)
    released: list[dict] = []
    for cls in workload.ORDER:
        hold = await active_hold(db, cls)
        if hold is None:
            _clear_streak.pop(cls, None)
            continue
        m = measurement or await measure()
        ceiling = lim["temperature_celsius"] - lim["resume_margin_celsius"]
        temp = m.temperature_c
        if not _valid_reading(temp) or m.temperature_unavailable:
            # Missing evidence cannot establish cooling. A blind sample also
            # breaks the required consecutive run of cool measurements.
            _clear_streak[cls] = 0
            continue
        if temp > ceiling:
            _clear_streak[cls] = 0
            continue
        _clear_streak[cls] = _clear_streak.get(cls, 0) + 1
        if _clear_streak[cls] < lim["clear_checks"]:
            continue
        await _record(db, kind="resumed", cls=cls,
                      reason=f"{temp:.1f} °C, back under {ceiling} °C for "
                             f"{_clear_streak[cls]} checks",
                      detail={"measurement": m.as_dict(), "limits": lim})
        released.append({"workload": cls, "temperature_celsius": temp})
        _clear_streak.pop(cls, None)
    return released


# ── the decision ────────────────────────────────────────────────────────────

@dataclass
class Verdict:
    allowed: bool
    code: str                 # ok | not_enabled | too_hot | cpu_busy | gpu_busy | held | sensor_unavailable | invalid_workload
    reason: str
    workload: str
    measurement: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "code": self.code, "reason": self.reason,
                "workload": self.workload, "measurement": self.measurement,
                "limits": self.limits}


async def may_run(db: AsyncSession, spec, *, force: bool = False) -> Verdict:
    """May this automation start right now?

    `force` is a person pressing Run now. It carries the *permission* gate —
    "blocked unless explicitly enabled" is satisfied by someone explicitly asking
    — but not the thermal one: no amount of wanting makes an 88 °C machine a good
    place to start a GPU job, and the refusal says which setting would change it.
    """
    automation_id = getattr(spec, "automation_id", str(spec))
    try:
        cls = workload.get(getattr(spec, "workload", None))
    except ValueError as exc:
        reason = str(exc)
        await _record(db, kind="blocked", cls="invalid", automation_id=automation_id,
                      reason=reason, detail={"workload": repr(getattr(spec, "workload", None))})
        return Verdict(False, "invalid_workload", reason, "invalid")
    if not cls.heavy:
        return Verdict(True, "ok", f"{cls.title.lower()} work always runs", cls.name)

    lim = await limits(db)
    display, _ = state.display_state()
    unattended = display != "on"       # unknown counts as away: the safe reading

    if cls.permission_setting and not force and unattended:
        if not bool(lim.get(cls.permission_setting.split(".")[-1], False)):
            reason = (f"{cls.title.lower()} work is not enabled for while the display is off "
                      f"— turn on “{cls.permission_setting}” to allow it")
            await _record(db, kind="blocked", cls=cls.name, automation_id=automation_id,
                          reason=reason, detail={"limits": lim, "display": display})
            return Verdict(False, "not_enabled", reason, cls.name, {}, lim)

    hold = await active_hold(db, cls.name)
    if hold is not None:
        return Verdict(False, "held", f"held since {hold.at:%H:%M}: {hold.reason}",
                       cls.name, {}, lim)

    m = await measure()
    missing = _missing_readings(cls, m)
    if missing:
        reason = "required sensor unavailable: " + ", ".join(missing)
        await _record(db, kind="blocked", cls=cls.name, automation_id=automation_id,
                      reason=reason, detail={"measurement": m.as_dict(), "limits": lim})
        return Verdict(False, "sensor_unavailable", reason, cls.name, m.as_dict(), lim)

    if workload.TEMPERATURE in cls.watches and m.temperature_c is not None:
        if m.temperature_c >= lim["temperature_celsius"]:
            reason = (f"{m.temperature_subject or 'the machine'} is at {m.temperature_c:.1f} °C, "
                      f"at or above the {lim['temperature_celsius']} °C limit")
            await _record(db, kind="deferred", cls=cls.name, automation_id=automation_id,
                          reason=reason, detail={"measurement": m.as_dict(), "limits": lim})
            return Verdict(False, "too_hot", reason, cls.name, m.as_dict(), lim)

    if workload.CPU in cls.watches and m.cpu_pct is not None and m.cpu_pct >= lim["cpu_pct"]:
        # Not a hold: utilisation is a moment, not a condition. It is re-asked on
        # the next tick and needs no margin, because nothing about starting the
        # job later makes the reading oscillate.
        return Verdict(False, "cpu_busy",
                       f"the processor is at {m.cpu_pct:.0f} %, at or above the "
                       f"{lim['cpu_pct']} % limit", cls.name, m.as_dict(), lim)

    if workload.GPU in cls.watches and m.gpu_pct is not None and m.gpu_pct >= lim["gpu_pct"]:
        return Verdict(False, "gpu_busy",
                       f"the GPU is at {m.gpu_pct:.0f} %, at or above the "
                       f"{lim['gpu_pct']} % limit", cls.name, m.as_dict(), lim)

    return Verdict(True, "ok", "within limits", cls.name, m.as_dict(), lim)


def _valid_reading(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _missing_readings(cls, m):
    return [name for name, value, unavailable in (
        (workload.TEMPERATURE, m.temperature_c, m.temperature_unavailable),
        (workload.CPU, m.cpu_pct, m.cpu_unavailable),
        (workload.GPU, m.gpu_pct, m.gpu_unavailable),
    ) if name in cls.watches and (not _valid_reading(value) or unavailable)]


# ── the budget ──────────────────────────────────────────────────────────────

@dataclass
class Running:
    automation_id: str
    workload: str
    stateful: bool
    started_at: float
    stop_requested: bool = False
    recorded: bool = False


_running: dict[str, Running] = {}


def note_start(spec) -> None:
    cls = workload.get(getattr(spec, "workload", None))
    if not cls.budgeted:
        return
    _running[spec.automation_id] = Running(
        spec.automation_id, cls.name, bool(getattr(spec, "stateful", False)), time.monotonic())


def note_finish(automation_id: str) -> None:
    _running.pop(automation_id, None)


def stop_requested(automation_id: str) -> bool:
    """What a long-running heavy automation checks between units of work.

    This is the whole of "stop": a flag a cooperating job reads. Nothing here
    cancels a task or signals a process, because the requirement was explicit
    that stateful work is never silently killed — and a job that is killed at an
    arbitrary line is the definition of silently. A job that ignores the flag
    keeps running; it is recorded as over budget, and the record is what a person
    acts on.
    """
    job = _running.get(automation_id)
    return bool(job and job.stop_requested)


def running() -> list[dict]:
    now = time.monotonic()
    return [{"automation_id": j.automation_id, "workload": j.workload, "stateful": j.stateful,
             "elapsed_seconds": round(now - j.started_at, 1),
             "stop_requested": j.stop_requested} for j in _running.values()]


async def check_budgets(db: AsyncSession) -> list[dict]:
    """Called on every tick: has a heavy job outstayed its budget?"""
    if not _running:
        return []
    lim = await limits(db)
    budget_s = lim["heavy_job_max_minutes"] * 60
    now = time.monotonic()
    over: list[dict] = []
    for job in list(_running.values()):
        elapsed = now - job.started_at
        if elapsed < budget_s or job.recorded:
            continue
        job.recorded = True
        if job.stateful:
            reason = (f"{job.automation_id} has run {elapsed / 60:.0f} min, past its "
                      f"{lim['heavy_job_max_minutes']} min budget. It holds state, so it is "
                      f"being left to finish — its next run waits instead.")
        else:
            job.stop_requested = True
            reason = (f"{job.automation_id} has run {elapsed / 60:.0f} min, past its "
                      f"{lim['heavy_job_max_minutes']} min budget. Asked to stop at its next "
                      f"checkpoint.")
        await _record(db, kind="over_budget", cls=job.workload, automation_id=job.automation_id,
                      reason=reason,
                      detail={"elapsed_seconds": round(elapsed, 1), "limits": lim,
                              "stateful": job.stateful, "stop_requested": job.stop_requested})
        over.append({"automation_id": job.automation_id, "elapsed_seconds": round(elapsed, 1),
                     "stateful": job.stateful, "stop_requested": job.stop_requested})
    return over


async def recent_events(db: AsyncSession, limit: int = 20) -> list[dict]:
    rows = (await db.execute(select(AriesResourceEvent)
                             .order_by(AriesResourceEvent.id.desc()).limit(limit))).scalars().all()
    return [r.as_dict() for r in rows]


def _status_of(cls, hold, m: Measurement, lim: dict, unattended: bool) -> tuple[str, str]:
    """What would happen to this class of work if it were asked for right now.

    Deliberately the same order of questions as `may_run`, because a panel that
    predicted something different from what the gate would do is worse than no
    panel: it would be believed. Nothing here records an event — showing a
    screen is not a decision.
    """
    if not cls.heavy:
        return "allowed", "always runs, including while the display is off"
    if (cls.permission_setting and unattended
            and not bool(lim.get(cls.permission_setting.split(".")[-1], False))):
        return "blocked", "not enabled for while the display is off"
    if hold is not None:
        return "held", hold.reason
    missing = _missing_readings(cls, m)
    if missing:
        return "blocked", "required sensor unavailable: " + ", ".join(missing)
    if workload.TEMPERATURE in cls.watches and m.temperature_c is not None \
            and m.temperature_c >= lim["temperature_celsius"]:
        return "deferred", (f"{m.temperature_subject or 'the machine'} is at "
                            f"{m.temperature_c:.1f} °C, at or above the "
                            f"{lim['temperature_celsius']} °C limit")
    if workload.CPU in cls.watches and m.cpu_pct is not None and m.cpu_pct >= lim["cpu_pct"]:
        return "deferred", f"the processor is at {m.cpu_pct:.0f} %, at or above the limit"
    if workload.GPU in cls.watches and m.gpu_pct is not None and m.gpu_pct >= lim["gpu_pct"]:
        return "deferred", f"the GPU is at {m.gpu_pct:.0f} %, at or above the limit"
    if not unattended:
        return "allowed", "the display is on — the unattended rule does not apply"
    return "allowed", "enabled for while the display is off, and within limits"


async def snapshot(db: AsyncSession) -> dict:
    """Everything the Power & Background panel shows about resources."""
    m = await measure()
    lim = await limits(db)
    display, _ = state.display_state()
    unattended = display != "on"
    classes = []
    for name in workload.ORDER:
        cls = workload.CLASSES[name]
        hold = await active_hold(db, name) if cls.heavy else None
        status, why = _status_of(cls, hold, m, lim, unattended)
        classes.append({**cls.as_dict(), "status": status, "why": why})
    return {"measurement": m.as_dict(), "limits": lim, "classes": classes,
            "display_off": unattended, "running_heavy": running(),
            "events": await recent_events(db, 10)}
