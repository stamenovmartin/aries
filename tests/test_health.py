"""System Health: probes measure honestly, judgement is separate, baselines soften
but never harden — and never silence something that only ever climbs."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-health")            # MUST precede every agentic_core / aries import

from datetime import datetime, timedelta  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.health import baseline, probes  # noqa: E402
from aries.health.findings import Finding, Reading, Severity, worst  # noqa: E402
from aries.health.judge import judge  # noqa: E402
from aries.settings import SettingsService  # noqa: E402

BASE_CFG = {
    "health.disk_warn_pct": 85.0, "health.disk_critical_pct": 93.0,
    "health.disk_ignored_mounts": ["/run/media", "/media", "/mnt", "/snap"],
    "health.memory_warn_pct": 88.0, "health.memory_critical_pct": 96.0,
    "health.swap_warn_pct": 60.0,
    "health.pressure_warn_pct": 20.0, "health.pressure_critical_pct": 50.0,
    "health.cpu_load_warn_per_core": 2.0,
    "health.temp_warn_celsius": 85.0, "health.temp_critical_celsius": 95.0,
    "health.gpu_temp_warn_celsius": 83.0, "health.gpu_temp_critical_celsius": 90.0,
    "health.uptime_notice_days": 21.0,
    "health.baseline_enabled": True, "health.baseline_suppress_max_severity": "warning",
}


async def test_probes_read_this_machine():
    results = await probes.run_all()
    by = {r.probe: r for r in results}
    check("every registered probe returns a result", set(by) == set(probes.PROBES))
    check("cpu and memory produce readings on a real machine",
          any(r.value is not None for r in by["cpu"].readings)
          and any(r.value is not None for r in by["memory"].readings))
    check("disk reports at least the root filesystem",
          any(r.subject == "/" for r in by["disk"].readings))
    check("no pseudo filesystem is reported as a disk",
          not any(r.detail.get("fstype") in probes.PSEUDO_FS for r in by["disk"].readings))
    check("a probe never takes the pass down with it", all(isinstance(r.probe, str) for r in results))


async def test_thermal_subjects_are_unique():
    """Two zones of the same type would otherwise share a baseline and an alert."""
    r = await probes.probe_thermal()
    keys = [x.key for x in r.readings]
    check("thermal subjects are unique even when zone types repeat", len(keys) == len(set(keys)))


async def test_unmeasurable_is_not_healthy():
    """Honest observability: absent is not zero, and not OK."""
    r = Reading("thermal.celsius", None, "°C", "gpu_sensor", unavailable="sensor disappeared")
    findings = judge([r], BASE_CFG)
    check("an unmeasurable reading becomes a NOTICE, not an OK",
          len(findings) == 1 and findings[0].code == "probe.unavailable"
          and findings[0].severity is Severity.NOTICE)
    check("and it carries the reason", "disappeared" in findings[0].summary)


async def test_implausible_temperature_is_discarded():
    r = await probes.probe_thermal()
    for reading in r.readings:
        if reading.unavailable and "implausible" in reading.unavailable:
            check("an implausible temperature is rejected with a reason, not believed",
                  reading.value is None)
            return
    lo, hi = probes.PLAUSIBLE_TEMP_C
    check("every believed temperature is inside the plausible band",
          all(lo <= x.value <= hi for x in r.readings if x.value is not None))


async def test_thresholds_decide_severity():
    def disk(pct, mount="/"):
        return Reading("disk.used_pct", pct, "%", mount, {"free_gib": 1.0})
    check("below the warning threshold is OK",
          judge([disk(50.0)], BASE_CFG)[0].severity is Severity.OK)
    check("at the warning threshold is a WARNING",
          judge([disk(85.0)], BASE_CFG)[0].severity is Severity.WARNING)
    check("at the critical threshold is CRITICAL",
          judge([disk(93.0)], BASE_CFG)[0].severity is Severity.CRITICAL)
    check("the finding carries the threshold it crossed",
          judge([disk(95.0)], BASE_CFG)[0].threshold == 93.0)


async def test_removable_media_is_measured_but_not_alarmed():
    r = Reading("disk.used_pct", 99.0, "%", "/run/media/user/USB", {"free_gib": 0.1})
    check("a full USB stick raises nothing — the advice would not apply",
          judge([r], BASE_CFG) == [])
    check("but a full system disk still does",
          judge([Reading("disk.used_pct", 99.0, "%", "/", {"free_gib": 0.1})], BASE_CFG)[0].severity
          is Severity.CRITICAL)


async def test_baseline_softens_what_is_normal_here():
    """A machine that always runs hot should not warn about running hot."""
    bl = baseline.Baseline(key="thermal.celsius:cpu", n=200, median=86.0, p05=80.0, p95=90.0,
                           minimum=78.0, maximum=92.0, window_days=14, trusted=True)
    r = Reading("thermal.celsius", 87.0, "°C", "cpu")
    plain = judge([r], BASE_CFG)[0]
    check("without a baseline, 87 °C is a warning", plain.severity is Severity.WARNING)
    softened = judge([r], BASE_CFG, {"thermal.celsius:cpu": bl})[0]
    check("with a baseline saying that is ordinary, it is downgraded",
          softened.severity is Severity.NOTICE)
    check("and the downgrade explains itself", "ordinary for this machine" in (softened.suppressed or ""))


async def test_baseline_never_silences_a_critical():
    bl = baseline.Baseline(key="thermal.celsius:cpu", n=500, median=97.0, p05=95.0, p95=99.0,
                           minimum=94.0, maximum=100.0, window_days=14, trusted=True)
    f = judge([Reading("thermal.celsius", 98.0, "°C", "cpu")], BASE_CFG,
              {"thermal.celsius:cpu": bl})[0]
    check("a machine that is always critically hot is still critically hot",
          f.severity is Severity.CRITICAL and f.suppressed is None)


async def test_baseline_never_silences_an_accumulating_metric():
    """A disk that has been 96% full for a month is still about to fail."""
    bl = baseline.Baseline(key="disk.used_pct:/", n=900, median=95.0, p05=94.0, p95=97.0,
                           minimum=93.0, maximum=98.0, window_days=14, trusted=True)
    f = judge([Reading("disk.used_pct", 96.0, "%", "/", {"free_gib": 2.0})], BASE_CFG,
              {"disk.used_pct:/": bl})[0]
    check("disk usage is not in SUPPRESSIBLE, so a baseline cannot soften it",
          f.severity is Severity.CRITICAL and f.suppressed is None)
    check("and disk usage really is excluded", "disk.used_pct" not in baseline.SUPPRESSIBLE)


async def test_untrusted_baseline_suppresses_nothing():
    bl = baseline.Baseline(key="thermal.celsius:cpu", n=4, median=86.0, p05=85.0, p95=90.0,
                           minimum=85.0, maximum=90.0, window_days=14, trusted=False)
    f = judge([Reading("thermal.celsius", 87.0, "°C", "cpu")], BASE_CFG,
              {"thermal.celsius:cpu": bl})[0]
    check("too few samples to be trusted — thresholds alone decide",
          f.severity is Severity.WARNING and f.suppressed is None)


async def test_baselines_are_robust_to_outliers():
    await reset_db()
    async with async_session() as db:
        for v in [40.0] * 60:
            await baseline.record(db, [Reading("thermal.celsius", v, "°C", "cpu")])
        await baseline.record(db, [Reading("thermal.celsius", 400.0, "°C", "cpu")])
        await db.commit()
        bl = await baseline.compute(db, "thermal.celsius:cpu", min_samples=30)
    check("one extreme sample cannot move the median", bl.median == 40.0)
    check("nor inflate the p95 into accepting it", bl.p95 <= 45.0)
    check("the maximum still records that it happened", bl.maximum == 400.0)
    check("enough samples makes the baseline trusted", bl.trusted is True)


async def test_baseline_bookkeeping():
    await reset_db()
    async with async_session() as db:
        await baseline.record(db, [
            Reading("cpu.load_per_core", 0.5), Reading("memory.used_pct", 30.0, "%"),
            Reading("thermal.celsius", None, "°C", "dead", unavailable="gone"),
        ])
        await db.commit()
        check("unmeasurable readings are not stored as samples",
              (await baseline.compute(db, "thermal.celsius:dead")) is None)
        many = await baseline.compute_many(db, ["cpu.load_per_core", "memory.used_pct"], min_samples=1)
        check("compute_many returns a baseline per key in one query", len(many) == 2)
        check("an unknown key simply has no baseline",
              (await baseline.compute(db, "nothing.at.all")) is None)

        from aries.health.baseline import AriesHealthSample
        old = AriesHealthSample(key="x", metric="x", subject="", value=1.0,
                                recorded_at=datetime.utcnow() - timedelta(days=200))
        db.add(old)
        await db.commit()
        removed = await baseline.prune(db, keep_days=90)
        await db.commit()
    check("pruning drops samples past the retention window", removed == 1)


async def test_settings_drive_judgement():
    """Thresholds are settings, so the user can retune without touching code."""
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("health.temp_warn_celsius", 50.0, set_by="user")
        cfg = await s.section("health")
    f = judge([Reading("thermal.celsius", 60.0, "°C", "cpu")], cfg)[0]
    check("lowering the threshold in settings changes the verdict",
          f.severity is Severity.WARNING and f.threshold == 50.0)


async def test_worst_of():
    check("the severity of a set is its worst member",
          worst([Finding("a", Severity.OK, "", ""), Finding("b", Severity.WARNING, "", "")])
          is Severity.WARNING)
    check("an empty set is OK", worst([]) is Severity.OK)


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
