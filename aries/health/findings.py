"""The vocabulary of system health: a Reading is measured, a Finding is judged.

Keeping these apart is the central design choice of the health automation.

    Reading    "mount / is 71.2% full"          — a fact, no opinion
    Finding    "disk / at 71.2% — WARNING"      — a judgement about that fact

A probe may only produce Readings. It never decides whether a number is bad,
because what counts as bad depends on thresholds the user configures (§20), on
what is normal for THIS machine (§13/08's "learn normal machine baselines"),
and on whether the same thing was already reported an hour ago. All of that is
judgement, all of it changes over time, and none of it belongs in the code that
reads /proc.

The practical payoff: probes stay trivially testable against fixed sample text,
and the baseline learning of §13/08 can lower the false-alarm rate without a
single probe being modified.

CONCEPT — severity as a deliberate ladder. Four levels that map exactly onto the
notification levels of §26, so a finding's severity IS its delivery decision and
no second, drifting translation table exists:

    CRITICAL    act now; interrupts the user even during quiet hours
    WARNING     real, not urgent; normal notification
    NOTICE      worth knowing at the next briefing
    OK          healthy; recorded for the baseline, never shown

A probe that cannot run produces UNKNOWN, which is deliberately NOT a severity.
"The disk is fine" and "I could not read the disk" are different claims, and
collapsing them is how monitoring systems learn to lie. §13/20 calls this
honest observability: null with a reason, never 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Severity(IntEnum):
    """How much a finding matters. Higher is worse; ordering is meaningful."""

    OK = 0
    NOTICE = 1
    WARNING = 2
    CRITICAL = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class Reading:
    """One measured value. No judgement, no thresholds."""

    metric: str                     # dotted id, e.g. "disk.used_pct" — the baseline key
    value: float | None             # None means "could not be measured"
    unit: str = ""                  # "%", "°C", "GiB", "" for dimensionless
    subject: str = ""               # what it is about: "/", "nvme0n1", "x86_pkg_temp"
    detail: dict = field(default_factory=dict)
    unavailable: str | None = None  # why value is None — an honest reason, never a zero

    @property
    def key(self) -> str:
        """The identity used for baselines and deduplication."""
        return f"{self.metric}:{self.subject}" if self.subject else self.metric

    def as_dict(self) -> dict:
        return {"metric": self.metric, "subject": self.subject or None, "value": self.value,
                "unit": self.unit, "detail": self.detail, "unavailable": self.unavailable}


@dataclass
class Finding:
    """A judgement about one or more readings."""

    code: str                       # stable id, e.g. "disk.full" — what the user recognises
    severity: Severity
    subject: str
    summary: str                    # one line, written for a human
    value: float | None = None
    unit: str = ""
    threshold: float | None = None
    baseline: dict | None = None    # what is normal here, when a baseline informed this
    suppressed: str | None = None   # set when a baseline or a rule downgraded it, with the reason
    evidence: dict = field(default_factory=dict)
    advice: str = ""                # what a human would do about it

    @property
    def key(self) -> str:
        return f"{self.code}:{self.subject}" if self.subject else self.code

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity.label, "subject": self.subject or None,
                "summary": self.summary, "value": self.value, "unit": self.unit,
                "threshold": self.threshold, "baseline": self.baseline, "suppressed": self.suppressed,
                "evidence": self.evidence, "advice": self.advice}


@dataclass
class ProbeResult:
    """What one probe returns: what it measured, and honestly, what it could not."""

    probe: str
    readings: list[Reading] = field(default_factory=list)
    ok: bool = True
    unavailable: str | None = None   # the probe itself could not run
    duration_ms: int = 0

    def as_dict(self) -> dict:
        return {"probe": self.probe, "ok": self.ok, "unavailable": self.unavailable,
                "duration_ms": self.duration_ms, "readings": [r.as_dict() for r in self.readings]}


def worst(findings: list[Finding]) -> Severity:
    """The severity of a set of findings is the worst one in it."""
    return max((f.severity for f in findings), default=Severity.OK)
