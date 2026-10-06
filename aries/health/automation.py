"""The System Health automation — specification §13/08.

    measure → remember → judge → decide who needs to know → record

and, when something is genuinely wrong, put a proposal in a human's queue
instead of acting on the machine by itself.

TWO KINDS OF SUCCESS, KEPT APART
--------------------------------
The distinction this module is built around, and the one monitoring systems most
often get wrong:

  * did the CHECK work?      — did the probes run and produce readings?
  * is the MACHINE healthy?  — did the readings look fine?

They are independent. A perfectly working health check on a machine whose disk is
97% full has succeeded completely; it has simply found bad news. Conflating the
two gives you an automation whose reliability metric collapses exactly when the
machine needs watching most, and a "failed" status that tells you nothing about
which of the two things failed.

So:

  * the automation's run status (`ok` / `degraded` / `failed`) describes the
    CHECK — `degraded` when some probe could not run, `failed` only when the pass
    itself broke;
  * a CRITICAL finding makes the task's result carry `requires_approval`, so the
    engine's lifecycle records an `ActionProposal` and notifies a human. The task
    still completes successfully, because it did its job;
  * the lifecycle's ESCALATE path is reserved for the check being broken — every
    probe unavailable means ARIES is blind, which is itself an incident.

ARIES never repairs anything here. It measures, judges and asks. Section 33's
autonomy levels decide whether anything may act on that, and nothing in this
module is allowed to shortcut them.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from agentic_core.evaluators.base import Evaluator, issue
from agentic_core.orchestrator.lifecycle import LifecyclePolicy
from agentic_core.scheduler import triggers
from agentic_core.scheduler.queue import register_kind
from agentic_core.security.permissions import Permission

from aries.automations.genome import AutomationSpec, register
from aries.health import baseline, probes
from aries.health.findings import Finding, Severity, worst
from aries.health.baseline import SUPPRESSIBLE as _SUPPRESSIBLE
from aries.health.judge import judge
from aries.notify import policy as notify
from aries.settings import SettingsService

logger = logging.getLogger(__name__)

AUTOMATION_ID = "aries.health"
TASK_KIND = "aries.health.check"

# Findings that mean something on the machine needs attention, as opposed to
# something about ARIES's own view of it. Only these become events that a future
# repair automation may act on.
ACTIONABLE_CODES = {"disk.full", "services.failed", "memory.high", "thermal.hot", "gpu.hot"}


async def run_pass(ctx: dict) -> dict:
    """One health pass. The automation's body; also the task kind's executor."""
    db = ctx["db"]
    t0 = time.monotonic()
    settings = SettingsService(db)

    config = await settings.section("health")
    config.update(await settings.section("notifications"))

    enabled_probes = list(config.get("health.probes") or [])
    results = await probes.run_all(enabled_probes)
    readings = [r for pr in results for r in pr.readings]

    # ── remember: every measurable value feeds the baseline ─────────────────
    recorded = await baseline.record(db, readings)

    # ── judge: thresholds, then what is normal here ─────────────────────────
    bl = {}
    if config.get("health.baseline_enabled", True):
        keys = sorted({r.key for r in readings if r.value is not None})
        bl = await baseline.compute_many(
            db, keys,
            window_days=int(config.get("health.baseline_window_days", 14)),
            min_samples=int(config.get("health.baseline_min_samples", 30)))
    findings = judge(readings, config, bl)

    alerts = [f for f in findings if f.severity > Severity.OK]
    critical = [f for f in alerts if f.severity is Severity.CRITICAL]

    # ── decide who needs to know (§26) ──────────────────────────────────────
    notifications = []
    delivered: set[str] = set()
    for f in sorted(alerts, key=lambda x: -x.severity):
        decision, row = await notify.emit(
            db, key=f.key, title=f.summary, severity=f.severity, source=AUTOMATION_ID,
            body=f.advice or None, config=config)
        notifications.append({"key": f.key, **decision.as_dict()})
        if decision.delivered:
            delivered.add(f.key)

    # ── record events, so a repair automation can act on them later ─────────
    # Only for findings whose notification actually got through. Event recording
    # then inherits the repeat gate for free: a disk that stays critical writes
    # one event, not one every pass forever.
    for f in critical:
        if f.code in ACTIONABLE_CODES and f.key in delivered:
            await triggers.record(db, kind=f.code.split(".")[0], subject=f.subject or "system",
                                  data={"finding": f.as_dict()}, source=AUTOMATION_ID)

    unavailable = [pr.probe for pr in results if pr.unavailable]
    blind = not readings
    status = "failed" if blind else ("degraded" if unavailable else "ok")
    duration_ms = int((time.monotonic() - t0) * 1000)

    summary = _summarise(findings, alerts, critical, unavailable, blind)
    detail = {
        "probes": [pr.as_dict() for pr in results],
        "findings": [f.as_dict() for f in findings],
        "notifications": notifications,
        "samples_recorded": recorded,
        "baselines_used": len(bl),
    }
    # The run row is written by the runner (aries/automations/runner.py), which
    # does it for every automation on the lifecycle path. `status` travels back
    # in the result below so the runner records `degraded` rather than guessing
    # from the verdict.
    await db.commit()

    return {
        # The CHECK succeeded unless it was blind. Bad news is not failure.
        "success": not blind,
        "details": summary,
        "summary": summary,
        "status": status,
        "severity": worst(findings).label,
        "findings": [f.as_dict() for f in findings],
        "alerts": [f.as_dict() for f in alerts],
        "critical": [f.as_dict() for f in critical],
        "notifications": notifications,
        "probes_unavailable": unavailable,
        "samples_recorded": recorded,
        "duration_ms": duration_ms,
        # A critical finding needs a human. The engine's lifecycle turns this
        # into an ActionProposal and notifies — the machine is never touched by
        # ARIES on its own.
        "requires_approval": bool(critical),
        "proposal_kind": "system.critical" if critical else None,
        "risk": "high" if critical else "low",
    }


def _summarise(findings: list[Finding], alerts: list[Finding], critical: list[Finding],
               unavailable: list[str], blind: bool) -> str:
    if blind:
        return "no probe produced a reading — ARIES cannot see the machine"
    if critical:
        head = f"{len(critical)} critical: " + "; ".join(f.summary for f in critical[:3])
    elif alerts:
        head = f"{len(alerts)} issue{'s' if len(alerts) != 1 else ''}: " + \
               "; ".join(f.summary for f in alerts[:3])
    else:
        head = f"healthy — {len(findings)} checks, nothing above threshold"
    if unavailable:
        head += f" (probe unavailable: {', '.join(unavailable)})"
    return head


# ── evaluators: do they judge the CHECK, never the machine ──────────────────
async def _check_produced_readings(result, task, ctx) -> list[dict]:
    """ARIES being unable to see the machine is an incident in itself."""
    if not isinstance(result, dict):
        return [issue("error", "no_result", "the health pass returned nothing")]
    if not result.get("success"):
        return [issue("error", "blind", result.get("details") or "no probe produced a reading")]
    return []


async def _probe_coverage(result, task, ctx) -> list[dict]:
    """A probe that stopped reporting is a warning, not a silent gap."""
    out = []
    for probe in (result or {}).get("probes_unavailable") or []:
        out.append(issue("warn", "probe_unavailable", f"the {probe} probe could not run"))
    return out


EVALUATORS = [
    Evaluator("health_check_ran", _check_produced_readings, weight=2.0),
    Evaluator("probe_coverage", _probe_coverage, weight=0.5),
]


async def execute(task, ctx) -> dict:
    """The lifecycle executor for the `aries.health.check` task kind."""
    ctx.setdefault("task_id", getattr(task, "id", None))
    return await run_pass(ctx)


async def _learning_status(db) -> dict:
    """What the health automation has learned so far (§27's learning column).

    Reports how many metrics have a baseline and how many are TRUSTED — the
    distinction that matters, since an untrusted baseline suppresses nothing. A
    user looking at this should be able to tell whether learning is working yet.
    """
    from sqlalchemy import func, select

    from aries.health.baseline import AriesHealthSample

    rows = (await db.execute(
        select(AriesHealthSample.key, func.count(AriesHealthSample.id))
        .group_by(AriesHealthSample.key))).all()
    settings = SettingsService(db)
    min_samples = int(await settings.get("health.baseline_min_samples"))
    trusted = [k for k, n in rows if n >= min_samples]
    suppressible = [k for k in trusted if k.split(":")[0] in _SUPPRESSIBLE]
    return {
        "metrics_tracked": len(rows),
        "baselines_trusted": len(trusted),
        "baselines_that_can_suppress": len(suppressible),
        "samples_needed_per_metric": min_samples,
        "total_samples": sum(n for _, n in rows),
        "explanation": (
            f"{len(trusted)} of {len(rows)} metrics have at least {min_samples} samples and are "
            f"trusted; of those, {len(suppressible)} are the kind of metric a baseline is allowed "
            f"to soften. Accumulating metrics such as disk usage are never softened."),
    }


# ── the genome (§12) ────────────────────────────────────────────────────────
SPEC = AutomationSpec(
    automation_id=AUTOMATION_ID,
    name="System Health Monitor",
    version="1.0.1",
    purpose="Watch CPU, memory, disk, temperature, GPU and systemd units; learn what is "
            "normal for this machine; tell the user only what is worth knowing.",
    run=run_pass,
    trigger="schedule",
    schedule_setting="health.interval_minutes",
    default_interval_minutes=15,
    conditions=["health.enabled is on"],
    input_sources=["/proc", "/sys/class/thermal", "statvfs", "systemctl", "nvidia-smi"],
    task_kind=TASK_KIND,
    agents=[],                      # deterministic by design — no model is involved
    tools=["systemctl list-units", "nvidia-smi"],
    permissions=[Permission.VIEW_DATA],
    memory_dependencies=["aries_health_samples"],
    enabled_setting="health.enabled",
    writes_settings=[],             # baselines are learned into their own table, not settings
    risk="low",                     # read-only; it never changes the machine
    requires_approval=False,
    breaker_on_degraded=False,       # a missing optional sensor must not silence diagnostics
    evaluation_metrics=["probe_coverage", "false_alarm_rate", "notifications_delivered",
                        "critical_findings_confirmed"],
    learning_status=lambda db: _learning_status(db),
    reward_signals=["user dismissed a notification as noise",
                    "user acted on a notification",
                    "a critical finding was confirmed real",
                    "a suppressed finding later became critical"],
)

register(SPEC)
register_kind(TASK_KIND, executor=execute, evaluators=EVALUATORS,
              # A health pass is cheap, deterministic and has no side effects, so
              # a retry is harmless — but it is also pointless: the machine will
              # read the same a second later. One attempt, then report.
              policy=LifecyclePolicy(max_retries=0, max_replans=0, pass_threshold=0.6))
