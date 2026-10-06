"""Turning Readings into Findings: thresholds first, then what is normal here.

This is the only module that decides anything is wrong. Probes measure,
baselines remember, and judgement happens here — in one place, so the rules can
be read, tested and changed without touching either.

The judgement is two-stage and the order matters:

  1. THRESHOLDS decide a provisional severity from the user's configured limits.
  2. BASELINES may then SOFTEN that severity — never harden it — when the value
     is ordinary for this machine and the metric is one where "usual" really does
     imply "fine" (see `baseline.SUPPRESSIBLE`).

Baselines can only ever lower a finding, and only within a configured ceiling
(`health.baseline_suppress_max_severity`, default: never suppress a CRITICAL).
That asymmetry is deliberate. A learning system that can *raise* alarms on its
own teaches the user to distrust it, and one that can silence a critical alert is
dangerous: a disk that has been 96% full for a month has a perfectly stable
baseline and is still about to fail.

Rules are DATA. Adding a metric is one `Rule` entry plus its settings, not a new
branch in a growing if-tree.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from aries.health.baseline import SUPPRESSIBLE, Baseline
from aries.health.findings import Finding, Reading, Severity

_SEVERITY_BY_NAME = {s.label: s for s in Severity}


@dataclass
class Rule:
    """How one metric is judged."""

    metric: str
    code: str                                   # the finding's stable identity
    warn_setting: str | None = None             # settings key holding the warning threshold
    critical_setting: str | None = None
    summary: Callable[[Reading, Severity], str] = lambda r, s: f"{r.metric} = {r.value}"
    advice: str = ""
    # A reading this returns True for is not judged at all (measured, not alarmed).
    skip: Callable[[Reading, dict], bool] = lambda r, cfg: False
    # Severity when the value is at or above the warning threshold but no
    # critical threshold is configured.
    warn_severity: Severity = Severity.WARNING


def _fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "unknown"
    return f"{v:g}{'' if unit in ('', None) else (' ' + unit if unit != '%' else '%')}"


def _disk_skip(r: Reading, cfg: dict) -> bool:
    """Removable and mounted media are measured but never alarmed on — "free up
    space" is not useful advice for a USB stick the user deliberately filled."""
    return any(r.subject.startswith(p) for p in cfg.get("health.disk_ignored_mounts", []))


RULES: list[Rule] = [
    Rule("disk.used_pct", "disk.full",
         "health.disk_warn_pct", "health.disk_critical_pct",
         summary=lambda r, s: f"{r.subject} is {_fmt(r.value, r.unit)} full "
                              f"({r.detail.get('free_gib', '?')} GiB free)",
         advice="Free space: caches, old logs, build artefacts, unused container images.",
         skip=_disk_skip),
    Rule("memory.used_pct", "memory.high",
         "health.memory_warn_pct", "health.memory_critical_pct",
         summary=lambda r, s: f"memory is {_fmt(r.value, r.unit)} used "
                              f"({r.detail.get('available_gib', '?')} GiB available)",
         advice="Identify the largest consumers before killing anything."),
    Rule("memory.swap_used_pct", "memory.swapping", "health.swap_warn_pct",
         # Severity-aware phrasing: a summary that reads as a complaint must not
         # be printed when the finding is healthy.
         summary=lambda r, s: f"swap is {_fmt(r.value, r.unit)} used"
                              + (" — the machine is paging" if s else ""),
         advice="Sustained swapping means memory pressure; more RAM or fewer resident processes."),
    Rule("memory.pressure", "memory.pressure",
         "health.pressure_warn_pct", "health.pressure_critical_pct",
         summary=lambda r, s: f"memory pressure {_fmt(r.value, r.unit)} of the last minute stalled",
         advice="Tasks are waiting on memory, not merely using it."),
    Rule("cpu.pressure", "cpu.pressure",
         "health.pressure_warn_pct", "health.pressure_critical_pct",
         summary=lambda r, s: f"CPU pressure {_fmt(r.value, r.unit)} of the last minute stalled",
         advice="Work is being delayed by CPU contention."),
    Rule("cpu.load_per_core", "cpu.load", "health.cpu_load_warn_per_core",
         summary=lambda r, s: f"load {r.detail.get('load1', '?')} across "
                              f"{r.detail.get('cores', '?')} cores ({_fmt(r.value, '')} per core)",
         advice="Sustained load above one per core means the queue is not draining.",
         warn_severity=Severity.NOTICE),
    Rule("thermal.celsius", "thermal.hot",
         "health.temp_warn_celsius", "health.temp_critical_celsius",
         summary=lambda r, s: f"{r.subject} at {_fmt(r.value, r.unit)}",
         advice="Check airflow and dust; sustained heat throttles the machine."),
    Rule("gpu.temp_celsius", "gpu.hot",
         "health.gpu_temp_warn_celsius", "health.gpu_temp_critical_celsius",
         summary=lambda r, s: f"{r.detail.get('name', r.subject)} at {_fmt(r.value, r.unit)}",
         advice="GPU thermal throttling reduces performance before it causes damage."),
]

RULES_BY_METRIC: dict[str, Rule] = {r.metric: r for r in RULES}


def _threshold_severity(value: float, warn: float | None, crit: float | None,
                        warn_severity: Severity) -> tuple[Severity, float | None]:
    if crit is not None and value >= crit:
        return Severity.CRITICAL, crit
    if warn is not None and value >= warn:
        return warn_severity, warn
    return Severity.OK, warn


def judge(readings: list[Reading], config: dict,
          baselines: dict[str, Baseline] | None = None) -> list[Finding]:
    """Judge every reading. Returns a Finding for each, including healthy ones —
    the caller decides what to show, and an OK finding is what proves a probe
    actually ran rather than silently vanishing."""
    baselines = baselines or {}
    use_baselines = bool(config.get("health.baseline_enabled", True))
    ceiling = _SEVERITY_BY_NAME.get(
        str(config.get("health.baseline_suppress_max_severity", "warning")), Severity.WARNING)
    out: list[Finding] = []

    for r in readings:
        # An unmeasurable reading is never a healthy one. It is reported as a
        # NOTICE naming the reason, so a sensor that quietly stopped working is
        # visible instead of looking like good news.
        if r.value is None:
            if r.unavailable and r.metric in RULES_BY_METRIC:
                out.append(Finding(code="probe.unavailable", severity=Severity.NOTICE, subject=r.key,
                                   summary=f"{r.metric} could not be measured: {r.unavailable}",
                                   evidence={"metric": r.metric, "reason": r.unavailable},
                                   advice="A sensor that stopped reporting is worth knowing about."))
            continue

        special = _judge_special(r, config)
        if special is not None:
            out.append(special)
            continue

        rule = RULES_BY_METRIC.get(r.metric)
        if rule is None or rule.skip(r, config):
            continue

        warn = config.get(rule.warn_setting) if rule.warn_setting else None
        crit = config.get(rule.critical_setting) if rule.critical_setting else None
        sev, threshold = _threshold_severity(float(r.value), warn, crit, rule.warn_severity)

        f = Finding(code=rule.code, severity=sev, subject=r.subject, summary=rule.summary(r, sev),
                    value=r.value, unit=r.unit, threshold=threshold,
                    evidence={"metric": r.metric, **r.detail}, advice=rule.advice if sev else "")

        # Stage 2 — a baseline may soften, never harden.
        bl = baselines.get(r.key)
        if (use_baselines and bl is not None and bl.trusted and sev > Severity.OK
                and sev <= ceiling and r.metric in SUPPRESSIBLE and bl.contains(float(r.value))):
            f.baseline = bl.as_dict()
            f.suppressed = (f"ordinary for this machine: {bl.n} samples over {bl.window_days} days "
                            f"put 95% at or below {bl.p95:.1f}{r.unit}")
            f.severity = Severity(max(Severity.OK, sev - 1))
        elif bl is not None:
            f.baseline = bl.as_dict()
        out.append(f)

    return out


def _judge_special(r: Reading, config: dict) -> Finding | None:
    """Metrics whose judgement is not a threshold comparison."""
    if r.metric == "services.failed_count":
        units = r.detail.get("units") or []
        n = int(r.value or 0)
        return Finding(
            code="services.failed", severity=Severity.WARNING if n else Severity.OK, subject="systemd",
            summary=(f"{n} systemd unit{'s' if n != 1 else ''} failed: {', '.join(units[:5])}"
                     if n else "no failed systemd units"),
            value=r.value, evidence={"units": units},
            advice="Read the unit's journal before restarting it — a unit that failed once "
                   "usually explains itself." if n else "")

    if r.metric == "uptime.reboot_required":
        pending = bool(r.value)
        pkgs = r.detail.get("packages") or []
        return Finding(
            code="uptime.reboot_required", severity=Severity.NOTICE if pending else Severity.OK,
            subject="system",
            summary=(f"a reboot is required to finish updating {len(pkgs)} package(s)"
                     if pending else "no reboot pending"),
            value=r.value, evidence={"packages": pkgs},
            advice="Reboot when convenient; kernel and library updates are not active until then."
                   if pending else "")

    if r.metric == "uptime.days":
        limit = float(config.get("health.uptime_notice_days", 21.0))
        over = (r.value or 0) >= limit
        return Finding(
            code="uptime.long", severity=Severity.NOTICE if over else Severity.OK, subject="system",
            summary=f"up for {r.value:g} days" + (f" (over the {limit:g}-day notice)" if over else ""),
            value=r.value, unit="days", threshold=limit if over else None,
            advice="Long uptime is not itself a problem, but pending kernel updates are." if over else "")

    if r.metric in ("gpu.utilization_pct", "gpu.memory_used_pct"):
        # Measured for the baseline and for context; a busy GPU is not a fault.
        return Finding(code="gpu.usage", severity=Severity.OK, subject=r.subject,
                       summary=f"{r.detail.get('name', r.subject)} {r.metric.split('.')[1]} "
                               f"{_fmt(r.value, r.unit)}",
                       value=r.value, unit=r.unit, evidence={"metric": r.metric, **r.detail})
    return None
