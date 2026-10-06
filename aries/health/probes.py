"""Reading the machine. Measurement only — no probe decides anything is wrong.

Each probe is async, strictly read-only, and degrades honestly: if it cannot
measure something it returns a Reading with `value=None` and a reason, never a
zero. A monitoring system that reports 0 °C for a sensor it failed to read is
worse than one that reports nothing, because the zero looks like data.

TWO WAYS OF READING, AND WHY

  * `/proc` and `/sys` are read directly with Python file I/O. They are virtual
    files: reading them has no side effects, cannot block on a device, and needs
    no shell. Spawning `cat` to read /proc/meminfo would cost a process, add
    locale-dependent parsing, and gain nothing in safety.
  * `systemctl` and `nvidia-smi` have no file interface, so they go through the
    engine's sandbox (`security/sandbox.run_command`) with an explicit,
    health-specific allowlist — not the global one. §4.2 of the engine's
    migration guide asks each application to define its own allowlist; this is
    ARIES's, and it contains exactly the four read-only commands the probes need.
    Least privilege means a compromised or confused probe cannot reach further.

Disk usage uses `os.statvfs` rather than parsing `df`, for the same reason: a
syscall is cheaper and unambiguous where a command's output is neither.

CONCEPT — PSI (Pressure Stall Information). `/proc/pressure/{cpu,memory,io}` is
a Linux facility that reports the percentage of time tasks were *stalled*
waiting for a resource, averaged over 10, 60 and 300 seconds. It answers "is
this machine actually suffering?", which load average does not: a load of 12 on
12 cores is fully busy and perfectly healthy, while memory pressure of 20% means
work is genuinely being delayed. ARIES prefers pressure over utilisation
wherever both exist, because utilisation measures how busy a machine is and
pressure measures whether that busyness is hurting.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Awaitable, Callable

from aries.health.findings import ProbeResult, Reading

# The ONLY commands the health probes may run. Read-only, no arguments that
# mutate anything. Passed explicitly to the sandbox rather than relying on the
# engine's global allowlist, which is broader than this needs.
HEALTH_ALLOWLIST = [
    "systemctl list-units",
    "systemctl is-system-running",
    "nvidia-smi",
    "journalctl",
]

# Temperatures outside this band are not believed. ACPI thermal zones routinely
# report placeholder values — this machine's `thermal_zone0` reads 16.8 °C in a
# room that is not 16.8 °C — and a monitoring system that alarms on, or builds a
# baseline from, a fictional number trains the user to ignore it.
PLAUSIBLE_TEMP_C = (5.0, 125.0)

# Filesystems that are not real storage. Reporting that tmpfs is "93% full" is
# noise: it is RAM, it is supposed to be used, and nothing can be freed on it.
PSEUDO_FS = {
    "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "securityfs", "cgroup", "cgroup2",
    "pstore", "efivarfs", "bpf", "autofs", "hugetlbfs", "mqueue", "debugfs", "tracefs",
    "fusectl", "configfs", "ramfs", "binfmt_misc", "squashfs", "overlay", "nsfs",
    "fuse.gvfsd-fuse", "fuse.portal", "rpc_pipefs",
}


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, PermissionError):
        return None


def _psi(resource: str) -> tuple[float | None, str | None]:
    """`some avg60` for a PSI resource: the share of time at least one task was
    stalled on it over the last minute."""
    raw = _read(f"/proc/pressure/{resource}")
    if raw is None:
        return None, "PSI not available (kernel built without CONFIG_PSI, or restricted)"
    for line in raw.splitlines():
        if line.startswith("some"):
            for part in line.split():
                if part.startswith("avg60="):
                    try:
                        return float(part.split("=", 1)[1]), None
                    except ValueError:
                        return None, "unparsable PSI line"
    return None, "no 'some' line in PSI output"


# ── probes ──────────────────────────────────────────────────────────────────
def _cpu_ticks(raw):
    """Aggregate counters; guest time is already included in user/nice."""
    try:
        fields = raw.splitlines()[0].split()
        if fields[0] != 'cpu' or len(fields) < 9:
            return None
        values = tuple(int(v) for v in fields[1:9])
        return values if min(values) >= 0 else None
    except (AttributeError, IndexError, ValueError):
        return None


async def _cpu_usage():
    start = time.monotonic()
    before = _cpu_ticks(_read('/proc/stat'))
    if before is None:
        return Reading('cpu.used_pct', None, '%', unavailable='CPU counters unavailable')
    await asyncio.sleep(0.1)  # Sample without blocking API or other probes.
    after = _cpu_ticks(_read('/proc/stat'))
    if after is None or any(a < b for a, b in zip(after, before)):
        return Reading('cpu.used_pct', None, '%', unavailable='CPU counters changed or became unavailable')
    delta = [a - b for a, b in zip(after, before)]
    total = sum(delta)
    if not total:
        return Reading('cpu.used_pct', None, '%', unavailable='CPU sample has no elapsed ticks')
    # idle and iowait do not execute work. Regressing counters (including Linux
    # iowait corrections) are unavailable above, never fabricated as zero use.
    used = 100 * (total - delta[3] - delta[4]) / total
    return Reading('cpu.used_pct', round(used, 1), '%', detail={
        'sample_seconds': round(time.monotonic() - start, 3), 'source': '/proc/stat',
        'iowait_is_idle': True})


async def probe_cpu() -> ProbeResult:
    """Sampled utilisation, load normalised per core, and CPU pressure."""
    t0 = time.monotonic()
    out: list[Reading] = []
    cores = os.cpu_count() or 1

    raw = _read("/proc/loadavg")
    if raw:
        try:
            one = float(raw.split()[0])
            out.append(Reading("cpu.load_per_core", round(one / cores, 3), "", "",
                               {"load1": one, "cores": cores}))
        except (ValueError, IndexError):
            out.append(Reading("cpu.load_per_core", None, "", "", unavailable="unparsable /proc/loadavg"))
    else:
        out.append(Reading("cpu.load_per_core", None, "", "", unavailable="/proc/loadavg unreadable"))

    val, why = _psi("cpu")
    out.append(Reading("cpu.pressure", val, "%", "", {"window": "60s"}, unavailable=why))
    out.append(await _cpu_usage())
    return ProbeResult("cpu", out, duration_ms=int((time.monotonic() - t0) * 1000))


async def probe_memory() -> ProbeResult:
    """Memory in use as a share of total, swap, and memory pressure.

    'Used' is computed from MemAvailable, not from MemFree. MemFree excludes the
    page cache, which Linux deliberately fills with reclaimable data — judging by
    MemFree reports a healthy machine as nearly out of memory. MemAvailable is
    the kernel's own estimate of what a new workload could actually obtain.
    """
    t0 = time.monotonic()
    out: list[Reading] = []
    raw = _read("/proc/meminfo")
    if raw is None:
        return ProbeResult("memory", [], ok=False, unavailable="/proc/meminfo unreadable",
                           duration_ms=int((time.monotonic() - t0) * 1000))
    vals: dict[str, float] = {}
    for line in raw.splitlines():
        parts = line.split(":")
        if len(parts) == 2:
            try:
                vals[parts[0].strip()] = float(parts[1].strip().split()[0])   # kB
            except (ValueError, IndexError):
                continue

    total, avail = vals.get("MemTotal"), vals.get("MemAvailable")
    if total and avail is not None:
        used_pct = (total - avail) / total * 100
        out.append(Reading("memory.used_pct", round(used_pct, 1), "%", "",
                           {"total_gib": round(total / 1048576, 2),
                            "available_gib": round(avail / 1048576, 2)}))
    else:
        out.append(Reading("memory.used_pct", None, "%", "", unavailable="MemTotal/MemAvailable missing"))

    sw_total, sw_free = vals.get("SwapTotal"), vals.get("SwapFree")
    if sw_total and sw_total > 0 and sw_free is not None:
        out.append(Reading("memory.swap_used_pct", round((sw_total - sw_free) / sw_total * 100, 1), "%", "",
                           {"total_gib": round(sw_total / 1048576, 2)}))
    else:
        out.append(Reading("memory.swap_used_pct", None, "%", "",
                           unavailable="no swap configured" if sw_total == 0 else "swap figures missing"))

    val, why = _psi("memory")
    out.append(Reading("memory.pressure", val, "%", "", {"window": "60s"}, unavailable=why))
    return ProbeResult("memory", out, duration_ms=int((time.monotonic() - t0) * 1000))


async def probe_disk() -> ProbeResult:
    """Used percentage for every real filesystem, via statvfs.

    Capacity is computed against blocks available to an unprivileged user, not
    against total blocks. Ext4 reserves ~5% for root, so a filesystem reporting
    "95% full" by total blocks is already full for every normal process — which
    is the number that matters to the user.
    """
    t0 = time.monotonic()
    out: list[Reading] = []
    mounts = _read("/proc/mounts")
    if mounts is None:
        return ProbeResult("disk", [], ok=False, unavailable="/proc/mounts unreadable",
                           duration_ms=int((time.monotonic() - t0) * 1000))
    seen: set[str] = set()
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mountpoint, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fstype in PSEUDO_FS or not device.startswith("/") or mountpoint in seen:
            continue
        seen.add(mountpoint)
        try:
            st = os.statvfs(mountpoint)
        except OSError as e:
            out.append(Reading("disk.used_pct", None, "%", mountpoint, unavailable=f"statvfs failed: {e}"))
            continue
        usable = st.f_blocks - (st.f_bfree - st.f_bavail)     # exclude root's reserve
        if usable <= 0:
            continue
        used = usable - st.f_bavail
        free_gib = st.f_bavail * st.f_frsize / 1073741824
        out.append(Reading("disk.used_pct", round(used / usable * 100, 1), "%", mountpoint,
                           {"free_gib": round(free_gib, 2),
                            "size_gib": round(usable * st.f_frsize / 1073741824, 2),
                            "fstype": fstype, "device": device}))
    return ProbeResult("disk", out, duration_ms=int((time.monotonic() - t0) * 1000))


async def probe_thermal() -> ProbeResult:
    """Temperature per thermal zone, implausible readings discarded with a reason."""
    t0 = time.monotonic()
    out: list[Reading] = []
    base = "/sys/class/thermal"
    try:
        zones = sorted(z for z in os.listdir(base) if z.startswith("thermal_zone"))
    except OSError as e:
        return ProbeResult("thermal", [], ok=False, unavailable=f"no thermal zones: {e}",
                           duration_ms=int((time.monotonic() - t0) * 1000))
    # Zone TYPE is not unique — this machine has two zones both called "acpitz".
    # Subjects must be, or two different sensors share one baseline and one alert
    # identity. Only the ambiguous types get a suffix, so the common case stays
    # readable ("x86_pkg_temp", not "x86_pkg_temp0").
    types = [(_read(f"{base}/{z}/type") or z).strip() for z in zones]
    duplicated = {t for t in types if types.count(t) > 1}
    for z, ztype in zip(zones, types):
        if ztype in duplicated:
            ztype = f"{ztype}{z.removeprefix('thermal_zone')}"
        raw = _read(f"{base}/{z}/temp")
        if raw is None:
            out.append(Reading("thermal.celsius", None, "°C", ztype, unavailable="temp unreadable"))
            continue
        try:
            celsius = int(raw.strip()) / 1000.0
        except ValueError:
            out.append(Reading("thermal.celsius", None, "°C", ztype, unavailable="unparsable temperature"))
            continue
        lo, hi = PLAUSIBLE_TEMP_C
        if not (lo <= celsius <= hi):
            out.append(Reading("thermal.celsius", None, "°C", ztype, {"raw_celsius": celsius},
                               unavailable=f"implausible reading {celsius:.1f} °C — zone ignored"))
            continue
        out.append(Reading("thermal.celsius", round(celsius, 1), "°C", ztype, {"zone": z}))
    return ProbeResult("thermal", out, duration_ms=int((time.monotonic() - t0) * 1000))


async def probe_gpu() -> ProbeResult:
    """NVIDIA GPU temperature, utilisation and memory. Absent GPU is not a fault."""
    from agentic_core.security import sandbox
    t0 = time.monotonic()
    cmd = ("nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total "
           "--format=csv,noheader,nounits")
    r = await sandbox.run_command(cmd, read_only=True, allowlist=HEALTH_ALLOWLIST, timeout=15)
    if not r.ok:
        return ProbeResult("gpu", [], ok=True,
                           unavailable=r.refused or (r.stderr.strip()[:200] or "nvidia-smi unavailable"),
                           duration_ms=int((time.monotonic() - t0) * 1000))
    out: list[Reading] = []
    for idx, line in enumerate(x for x in r.stdout.splitlines() if x.strip()):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        name, subject = parts[0], f"gpu{idx}"
        try:
            temp, util, used, total = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        except ValueError:
            out.append(Reading("gpu.temp_celsius", None, "°C", subject, unavailable="unparsable nvidia-smi row"))
            continue
        out.append(Reading("gpu.temp_celsius", temp, "°C", subject, {"name": name}))
        out.append(Reading("gpu.utilization_pct", util, "%", subject, {"name": name}))
        if total > 0:
            out.append(Reading("gpu.memory_used_pct", round(used / total * 100, 1), "%", subject,
                               {"name": name, "used_mib": used, "total_mib": total}))
    return ProbeResult("gpu", out, duration_ms=int((time.monotonic() - t0) * 1000))


async def probe_services() -> ProbeResult:
    """How many systemd units are in the failed state, and which."""
    from agentic_core.security import sandbox
    t0 = time.monotonic()
    r = await sandbox.run_command("systemctl list-units --state=failed --no-legend --no-pager --plain",
                                  read_only=True, allowlist=HEALTH_ALLOWLIST, timeout=20)
    if not r.ok and r.refused:
        return ProbeResult("services", [], ok=False, unavailable=r.refused,
                           duration_ms=int((time.monotonic() - t0) * 1000))
    units = [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip() and not ln.startswith(" ")]
    units = [u for u in units if u.endswith((".service", ".socket", ".timer", ".mount", ".target"))]
    return ProbeResult("services",
                       [Reading("services.failed_count", float(len(units)), "", "", {"units": units})],
                       duration_ms=int((time.monotonic() - t0) * 1000))


async def probe_uptime() -> ProbeResult:
    """Days since boot, and whether a package update is waiting for a reboot."""
    t0 = time.monotonic()
    out: list[Reading] = []
    raw = _read("/proc/uptime")
    if raw:
        try:
            out.append(Reading("uptime.days", round(float(raw.split()[0]) / 86400, 2), "days"))
        except (ValueError, IndexError):
            out.append(Reading("uptime.days", None, "days", unavailable="unparsable /proc/uptime"))
    else:
        out.append(Reading("uptime.days", None, "days", unavailable="/proc/uptime unreadable"))

    pending = os.path.exists("/var/run/reboot-required") or os.path.exists("/run/reboot-required")
    pkgs = _read("/run/reboot-required.pkgs") or _read("/var/run/reboot-required.pkgs") or ""
    out.append(Reading("uptime.reboot_required", 1.0 if pending else 0.0, "", "",
                       {"packages": sorted({p.strip() for p in pkgs.splitlines() if p.strip()})}))
    return ProbeResult("uptime", out, duration_ms=int((time.monotonic() - t0) * 1000))


# Registry, so the automation iterates rather than hard-coding a call list, and
# a future probe is one entry here plus its thresholds.
PROBES: dict[str, Callable[[], Awaitable[ProbeResult]]] = {
    "cpu": probe_cpu,
    "memory": probe_memory,
    "disk": probe_disk,
    "thermal": probe_thermal,
    "gpu": probe_gpu,
    "services": probe_services,
    "uptime": probe_uptime,
}


async def run_all(names: list[str] | None = None) -> list[ProbeResult]:
    """Run every enabled probe concurrently.

    Concurrency is safe and worthwhile here: the probes share no state, write
    nothing, and the two that spawn a subprocess would otherwise serialise the
    whole pass behind their own latency. A probe that raises is reported as
    unavailable rather than taking the pass down with it — one broken sensor
    must never cost the user their disk warning.
    """
    chosen = [(n, PROBES[n]) for n in (names or list(PROBES)) if n in PROBES]
    results = await asyncio.gather(*(fn() for _, fn in chosen), return_exceptions=True)
    out: list[ProbeResult] = []
    for (name, _), res in zip(chosen, results):
        if isinstance(res, BaseException):
            out.append(ProbeResult(name, [], ok=False,
                                   unavailable=f"probe raised {type(res).__name__}: {res}"))
        else:
            out.append(res)
    return out
