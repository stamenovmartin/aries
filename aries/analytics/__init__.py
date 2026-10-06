"""ARIES analytics — reading the recorded history back as insight.

ARIES records a great deal and reads almost none of it back. `automation_logs`
holds 288,491 rows, `aries_workspace_goals` holds 118 MB of JSON across 6,637
recorded requests, and until this package nothing aggregated any of it.

Every function here is async, takes an `AsyncSession`, and is STRICTLY READ-ONLY.
Three rules are enforced throughout, and `core.py` explains each one at length:

  BOUNDED    every metric is windowed, every scan of the JSON column is row-capped,
             and every metric reports its own `query_ms`.
  HONEST     an empty window returns `n: 0` and a reason, never 0% or 100%.
  UNCERTAIN  every rate carries a Wilson 95% interval from
             `aries.learning.statistics`, so "3 of 3" reads as 0.44-1.00 and not
             as perfect.

Usage:

    from aries.analytics import dashboard, Window
    everything = await dashboard(db, Window(days=7, goal_scan=500))

    from aries.analytics import failure_shapes
    just_the_failures = await failure_shapes(db, Window(days=30))
"""
from __future__ import annotations

from aries.analytics.automations import automation_health
from aries.analytics.core import MAX_GOAL_SCAN, MAX_WINDOW_DAYS, Window
from aries.analytics.dashboard import CHEAP, METRICS, dashboard
from aries.analytics.failures import failure_shapes, locking_failures
from aries.analytics.integrity import (approval_discipline, verification_contradictions,
                                       verification_honesty)
from aries.analytics.latency import goal_elapsed, latency
from aries.analytics.outcomes import (engine_task_outcomes, outcomes_by_capability,
                                      task_outcomes)
from aries.analytics.usage import attention, capability_usage, model_usage

__all__ = [
    "Window", "MAX_WINDOW_DAYS", "MAX_GOAL_SCAN",
    "dashboard", "METRICS", "CHEAP",
    "task_outcomes", "outcomes_by_capability", "engine_task_outcomes",
    "latency", "goal_elapsed",
    "failure_shapes", "locking_failures",
    "verification_honesty", "verification_contradictions", "approval_discipline",
    "automation_health",
    "capability_usage", "model_usage", "attention",
]
