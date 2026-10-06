"""How much evidence is enough to change something.

The medium loop of §16 adjusts preferences from observed behaviour. The whole
difficulty is in one question: the user opened 1 of 3 items about a topic — is
that a 33% engagement rate, or is it nothing at all?

A raw rate says 33%, confidently, and is wrong. With three observations almost
any true rate is plausible, and a system that acts on it will lurch after every
handful of clicks, "learning" noise and then unlearning it. The user experiences
this as a system with opinions that change for no reason, which is worse than one
that never learns.

CONCEPT — the Wilson score interval. Given `k` successes out of `n` trials, it
gives a RANGE the true rate plausibly lies in, and — unlike the textbook normal
approximation — it stays sensible when `n` is small or the rate is near 0 or 1,
which is exactly the regime here. ARIES acts on the interval, never on the point
estimate:

    lower bound high  → even pessimistically this topic is engaging  → raise it
    upper bound low   → even optimistically it is not               → lower it
    otherwise         → not enough evidence yet                     → leave it

With 1 of 3 the interval is roughly 0.06–0.79 — wide enough that neither test
fires, so nothing happens, which is the correct answer. With 2 of 40 the upper
bound is about 0.17: even optimistically it is noise, and the system may act.

This is the same instinct as the health baselines' robust statistics, applied to
a different question: prefer the estimator that refuses to overreact.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# 1.96 ≈ the 97.5th percentile of the normal distribution, giving a two-sided
# 95% interval. Kept as a named constant so the confidence level is visible
# rather than buried as a magic number.
Z_95 = 1.959963984540054


@dataclass
class Interval:
    """A range the true rate plausibly lies in, from `successes` of `trials`."""

    successes: int
    trials: int
    lower: float
    upper: float

    @property
    def point(self) -> float | None:
        """The raw rate — reported for display, never used for a decision.
        None when nothing has been observed: unknown is not zero."""
        return self.successes / self.trials if self.trials else None

    @property
    def width(self) -> float:
        return self.upper - self.lower

    def as_dict(self) -> dict:
        return {"successes": self.successes, "trials": self.trials,
                "rate": None if self.point is None else round(self.point, 3),
                "lower": round(self.lower, 3), "upper": round(self.upper, 3),
                "width": round(self.width, 3)}


def wilson(successes: int, trials: int, *, z: float = Z_95) -> Interval:
    """The Wilson score interval for a proportion."""
    k, n = max(0, int(successes)), max(0, int(trials))
    if n == 0:
        # No evidence at all: the rate could be anything.
        return Interval(k, n, 0.0, 1.0)
    k = min(k, n)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return Interval(k, n, max(0.0, centre - margin), min(1.0, centre + margin))


def step_toward(current: float, target: float, *, confidence: float, max_step: float) -> float:
    """Move `current` toward `target`, bounded by evidence and by a hard cap.

    Two brakes, both deliberate. `confidence` scales the move by how much
    evidence there is, so a marginal case moves a little and an overwhelming one
    moves more. `max_step` caps it regardless, so no single run can swing a
    preference from one end to the other — a bug in the evidence should cost the
    user a nudge, not their configuration.
    """
    confidence = max(0.0, min(1.0, confidence))
    delta = (target - current) * confidence
    delta = max(-max_step, min(max_step, delta))
    # Rounded to three places. A weight of 0.7885944107755797 is not more precise
    # than 0.789, it is just unreadable — it appears in the Settings UI, in the
    # explanation of why an item was shown, and in every comparison against a
    # relevance score (which is itself rounded). Precision the system cannot
    # justify is noise, and noise that reaches the user is a bug.
    return round(max(0.0, min(1.0, current + delta)), 3)
