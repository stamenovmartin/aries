"""Learning what is normal for THIS machine.

Specification §13/08 asks the health monitor to "learn normal machine baselines
and reduce false alarms". That is the whole difficulty of monitoring: a fixed
threshold is either so loose it misses real problems or so tight it cries wolf,
and which one it is depends on hardware nobody configured it for. A laptop that
idles at 72 °C under a normal desktop load is fine. A fixed 70 °C warning turns
that machine into a permanent alarm, and a permanent alarm is the same as no
alarm — the user learns to dismiss it.

So ARIES records what it measures, and after enough observations it knows this
machine's normal range and can say "72 °C, which is ordinary here" instead of
"72 °C, WARNING".

CONCEPT — robust statistics. The obvious summary is mean and standard deviation,
and it is the wrong one. Both are pulled badly by outliers: one compile that
pins every core for a minute drags the mean up and inflates the deviation, so
the "normal" range silently widens to include genuinely abnormal values. This
module uses the MEDIAN (the middle observation, which a single extreme value
cannot move) and PERCENTILES (p95 = the value 95% of observations fall below).
These are called robust statistics precisely because a minority of extreme
values cannot distort them.

CONCEPT — why some metrics must never be suppressed. A baseline says "this is
usual", not "this is fine", and the two come apart for any metric that only ever
climbs. A disk that has been 96% full for a month has a beautifully stable
baseline of 96% — and is still about to fail. Suppression is therefore allowed
only for metrics that genuinely fluctuate (temperature, load, pressure, memory),
and is refused for accumulating or binary ones (disk usage, failed units, a
pending reboot). That list is `SUPPRESSIBLE` below, and it is a safety property,
not a tuning knob.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import DateTime, Float, Integer, String, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

from aries.health.findings import Reading

# Metrics whose "normal" is a statement about health, so a learned range may
# soften a finding. Everything else is judged on thresholds alone.
SUPPRESSIBLE: frozenset[str] = frozenset({
    "cpu.load_per_core", "cpu.pressure",
    "memory.used_pct", "memory.pressure", "memory.swap_used_pct",
    "thermal.celsius", "gpu.temp_celsius", "gpu.utilization_pct", "gpu.memory_used_pct",
})


class AriesHealthSample(Base):
    """One measured value at one moment. The raw material of every baseline."""

    __tablename__ = "aries_health_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # metric:subject — "thermal.celsius:x86_pkg_temp". Indexed because every
    # baseline query filters on it.
    key: Mapped[str] = mapped_column(String(200), index=True)
    metric: Mapped[str] = mapped_column(String(120), index=True)
    subject: Mapped[str] = mapped_column(String(160), default="")
    value: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


@dataclass
class Baseline:
    """What normal looks like for one metric on this machine."""

    key: str
    n: int
    median: float
    p05: float
    p95: float
    minimum: float
    maximum: float
    window_days: int
    trusted: bool           # enough samples to be allowed to suppress anything

    def contains(self, value: float) -> bool:
        """Is this value ordinary here? Judged against p95, not the maximum —
        the maximum is by definition the worst thing ever seen, which would make
        every repeat of a bad event look normal."""
        return value <= self.p95

    def as_dict(self) -> dict:
        return {"key": self.key, "n": self.n, "median": round(self.median, 2),
                "p05": round(self.p05, 2), "p95": round(self.p95, 2),
                "min": round(self.minimum, 2), "max": round(self.maximum, 2),
                "window_days": self.window_days, "trusted": self.trusted}


def _percentile(ordered: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list. q in [0, 1]."""
    if not ordered:
        raise ValueError("empty sample")
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


async def record(db: AsyncSession, readings: list[Reading]) -> int:
    """Store every measurable reading. Unavailable ones are skipped: a baseline
    built from absent measurements would be a baseline of nothing."""
    n = 0
    for r in readings:
        if r.value is None:
            continue
        db.add(AriesHealthSample(key=r.key, metric=r.metric, subject=r.subject, value=float(r.value)))
        n += 1
    await db.flush()
    return n


async def compute(db: AsyncSession, key: str, *, window_days: int = 14,
                  min_samples: int = 30) -> Baseline | None:
    """The learned normal range for one metric, or None if nothing is recorded."""
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    rows = (await db.execute(
        select(AriesHealthSample.value)
        .where(AriesHealthSample.key == key, AriesHealthSample.recorded_at >= cutoff)
    )).scalars().all()
    if not rows:
        return None
    vals = sorted(float(v) for v in rows)
    return Baseline(key=key, n=len(vals), median=_percentile(vals, 0.50),
                    p05=_percentile(vals, 0.05), p95=_percentile(vals, 0.95),
                    minimum=vals[0], maximum=vals[-1], window_days=window_days,
                    trusted=len(vals) >= min_samples)


async def compute_many(db: AsyncSession, keys: list[str], *, window_days: int = 14,
                       min_samples: int = 30) -> dict[str, Baseline]:
    """Baselines for many metrics in ONE query.

    A health pass judges every reading at once, so the alternative is a query per
    metric — roughly twenty round trips per pass, every pass, forever. The rows
    are fetched together and grouped in Python.
    """
    if not keys:
        return {}
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    rows = (await db.execute(
        select(AriesHealthSample.key, AriesHealthSample.value)
        .where(AriesHealthSample.key.in_(keys), AriesHealthSample.recorded_at >= cutoff)
    )).all()
    grouped: dict[str, list[float]] = {}
    for k, v in rows:
        grouped.setdefault(k, []).append(float(v))
    out: dict[str, Baseline] = {}
    for k, vals in grouped.items():
        vals.sort()
        out[k] = Baseline(key=k, n=len(vals), median=_percentile(vals, 0.50),
                          p05=_percentile(vals, 0.05), p95=_percentile(vals, 0.95),
                          minimum=vals[0], maximum=vals[-1], window_days=window_days,
                          trusted=len(vals) >= min_samples)
    return out


async def prune(db: AsyncSession, *, keep_days: int = 90) -> int:
    """Drop samples older than the retention window.

    Without this the table grows without bound: seven probes, roughly twenty
    readings, every fifteen minutes is about two million rows a year. The
    baseline window is much shorter than the retention window so there is always
    history to widen the window with if needed.
    """
    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    res = await db.execute(delete(AriesHealthSample).where(AriesHealthSample.recorded_at < cutoff))
    await db.flush()
    return res.rowcount or 0
