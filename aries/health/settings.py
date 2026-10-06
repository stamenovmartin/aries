"""Health settings — the thresholds that turn a Reading into a Finding.

These live in the Settings Service rather than as constants, for the reason §20
gives: the user must be able to retune the system without editing code, and a
threshold is exactly the kind of thing that is wrong for somebody. A laptop that
idles at 70 °C is normal; a server that reaches it is not.

Registered on import, like every other ARIES setting.
"""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

S = "health"

# Off by default. Section 11: "Do not automatically activate every automation."
# That applies even to a read-only one — the user decides what runs on their
# machine, and a default of True makes that decision for them.
define(SettingDef("health.enabled", bool, False, "System health monitoring",
                  "Whether ARIES periodically checks CPU, memory, disk, temperature, GPU and services.",
                  S, control="toggle"))
define(SettingDef("health.interval_minutes", int, 15, "Check frequency",
                  "How often a health pass runs.", S, control="number",
                  minimum=1, maximum=1440, unit="minutes"))
define(SettingDef("health.probes", list, ["cpu", "memory", "disk", "thermal", "gpu", "services", "uptime"],
                  "Active probes", "Which parts of the machine are measured.",
                  S, control="multiselect",
                  choices=("cpu", "memory", "disk", "thermal", "gpu", "services", "uptime")))

# ── disk ─────────────────────────────────────────────────────────────────────
define(SettingDef("health.disk_warn_pct", float, 85.0, "Disk warning",
                  "Filesystem usage at which ARIES warns that space is running low.",
                  S, control="slider", minimum=50.0, maximum=99.0, unit="%"))
define(SettingDef("health.disk_critical_pct", float, 93.0, "Disk critical",
                  "Filesystem usage at which ARIES treats space as an emergency and may propose a repair.",
                  S, control="slider", minimum=50.0, maximum=100.0, unit="%"))
define(SettingDef("health.disk_ignored_mounts", list, ["/run/media", "/media", "/mnt", "/snap"],
                  "Ignore these mounts",
                  "Mount-point prefixes excluded from disk alerts. Removable and mounted media are "
                  "measured but never alarmed on, because 'free up space' is not useful advice for a "
                  "USB stick the user deliberately filled.",
                  S, control="list"))

# ── memory ───────────────────────────────────────────────────────────────────
define(SettingDef("health.memory_warn_pct", float, 88.0, "Memory warning",
                  "Share of memory in use at which ARIES warns.",
                  S, control="slider", minimum=50.0, maximum=99.0, unit="%"))
define(SettingDef("health.memory_critical_pct", float, 96.0, "Memory critical",
                  "Share of memory in use at which ARIES treats memory as an emergency.",
                  S, control="slider", minimum=50.0, maximum=100.0, unit="%"))
define(SettingDef("health.swap_warn_pct", float, 60.0, "Swap warning",
                  "Swap usage at which ARIES warns that the machine is paging.",
                  S, control="slider", minimum=0.0, maximum=100.0, unit="%"))

# ── pressure (PSI) ───────────────────────────────────────────────────────────
define(SettingDef("health.pressure_warn_pct", float, 20.0, "Pressure warning",
                  "Share of the last minute that tasks were stalled waiting for a resource before "
                  "ARIES warns. Pressure measures whether the machine is suffering, which utilisation "
                  "does not.", S, control="slider", minimum=1.0, maximum=100.0, unit="%", advanced=True))
define(SettingDef("health.pressure_critical_pct", float, 50.0, "Pressure critical",
                  "Stall share at which ARIES treats the machine as seriously degraded.",
                  S, control="slider", minimum=1.0, maximum=100.0, unit="%", advanced=True))
define(SettingDef("health.cpu_load_warn_per_core", float, 2.0, "CPU load warning",
                  "One-minute load average per core at which ARIES warns. 1.0 means fully busy.",
                  S, control="number", minimum=0.5, maximum=20.0, advanced=True))

# ── temperature ──────────────────────────────────────────────────────────────
define(SettingDef("health.temp_warn_celsius", float, 85.0, "Temperature warning",
                  "Component temperature at which ARIES warns.",
                  S, control="number", minimum=40.0, maximum=110.0, unit="°C"))
define(SettingDef("health.temp_critical_celsius", float, 95.0, "Temperature critical",
                  "Component temperature at which ARIES treats overheating as an emergency.",
                  S, control="number", minimum=40.0, maximum=120.0, unit="°C"))
define(SettingDef("health.gpu_temp_warn_celsius", float, 83.0, "GPU temperature warning",
                  "GPU temperature at which ARIES warns. GPUs run hotter than CPUs by design.",
                  S, control="number", minimum=40.0, maximum=110.0, unit="°C"))
define(SettingDef("health.gpu_temp_critical_celsius", float, 90.0, "GPU temperature critical",
                  "GPU temperature at which ARIES treats overheating as an emergency.",
                  S, control="number", minimum=40.0, maximum=120.0, unit="°C"))

# ── uptime ───────────────────────────────────────────────────────────────────
define(SettingDef("health.uptime_notice_days", float, 21.0, "Long uptime notice",
                  "Days of uptime after which ARIES mentions that a reboot may be overdue.",
                  S, control="number", minimum=1.0, maximum=365.0, unit="days", advanced=True))

# ── baselines (the learning half of specification 13/08) ─────────────────────
define(SettingDef("health.baseline_enabled", bool, True, "Learn what is normal",
                  "Whether ARIES learns this machine's normal ranges and uses them to suppress "
                  "alerts that are normal here.", S, control="toggle"))
define(SettingDef("health.baseline_window_days", int, 14, "Baseline window",
                  "How far back the normal range is computed from.",
                  S, control="number", minimum=1, maximum=180, unit="days", advanced=True))
define(SettingDef("health.baseline_min_samples", int, 30, "Baseline minimum samples",
                  "How many observations a metric needs before its learned range is trusted enough "
                  "to suppress anything. Below this, thresholds alone decide.",
                  S, control="number", minimum=5, maximum=1000, unit="samples", advanced=True))
define(SettingDef("health.baseline_suppress_max_severity", str, "warning",
                  "Baselines may suppress up to",
                  "The most severe finding a learned baseline is allowed to downgrade. A critical "
                  "finding is never suppressed by default: a disk that is always 95% full is still "
                  "about to fail.",
                  S, control="select", choices=("notice", "warning", "critical"), advanced=True))
