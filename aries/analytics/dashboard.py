"""One call that returns everything, and the accounting for what it cost.

The metrics are independent and each one is callable on its own — that is the
point of the package. This module exists so the Control Centre does not have to
make nine round trips, and so the cost of a full refresh is a number the user can
see rather than a feeling.

RUN SEQUENTIALLY, ON PURPOSE
---------------------------
`asyncio.gather` over nine metrics would be faster on paper and wrong here. They
share one `AsyncSession`, which is not safe for concurrent use, and `aries.db` is
a single file that `aries-core.service` is writing to right now — nine concurrent
readers plus the service's writer is how you turn a dashboard into the
`database is locked` failure of 2026-09-29, which this very dashboard reports 154
instances of. Sequential, each metric releasing its snapshot as it finishes, is
the shape that does not participate.

ONE METRIC FAILING IS NOT THE DASHBOARD FAILING
-----------------------------------------------
Each metric is caught individually and reported as `{"error": ...}` in its slot.
A dashboard that goes blank because one aggregate hit a schema it did not expect
is less useful than one that shows eight numbers and names the ninth as broken —
and a swallowed exception would be worse than both, so the type and message are
kept.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from aries.analytics import automations, failures, integrity, latency, outcomes, usage
from aries.analytics.core import Window

logger = logging.getLogger(__name__)

# Ordered cheapest-first so a caller watching the log sees the expensive ones
# last, and so the three result_json parses sit together and are easy to drop if
# a caller wants a cheap refresh.
METRICS = (
    outcomes.task_outcomes,
    outcomes.engine_task_outcomes,
    latency.latency,
    latency.goal_elapsed,
    automations.automation_health,
    usage.model_usage,
    usage.attention,
    failures.locking_failures,
    # ── from here down, each one parses result_json ──────────────────────────
    outcomes.outcomes_by_capability,
    integrity.verification_honesty,
    integrity.verification_contradictions,
    failures.failure_shapes,
    usage.capability_usage,
)

# The subset that never opens `result_json`. Measured at ~25 ms in total on the
# live database, against ~250 ms for the full set — offered because a panel that
# refreshes every few seconds should not be parsing 10 MB of JSON to do it.
CHEAP = tuple(m for m in METRICS[:8])


async def dashboard(db: AsyncSession, window: Window | None = None, *,
                    cheap_only: bool = False) -> dict:
    """Everything a dashboard needs, with the wall time of every part of it."""
    w = window or Window()
    chosen = CHEAP if cheap_only else METRICS
    out: dict = {}
    t0 = time.perf_counter()
    for fn in chosen:
        name = getattr(fn, "metric_name", fn.__name__)
        try:
            out[name] = await fn(db, w)
        except Exception as exc:                                     # noqa: BLE001
            logger.warning("analytics metric %s failed: %s", name, exc)
            out[name] = {"error": type(exc).__name__, "detail": str(exc)[:400],
                         "metric": name,
                         "reason": "this metric failed; the rest of the dashboard is unaffected"}
            # The failed metric may have left a transaction open.
            try:
                await db.rollback()
            except Exception:                                        # noqa: BLE001
                pass
    total = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "metrics": out,
        "window": w.as_dict(),
        "cheap_only": cheap_only,
        "timing": {"total_ms": total,
                   "per_metric_ms": {k: v.get("query_ms") for k, v in out.items()},
                   "slowest": max(((v.get("query_ms") or 0, k) for k, v in out.items()),
                                  default=(0, None))[1]},
        "failed_metrics": [k for k, v in out.items() if "error" in v] or None,
        "database": "the session's own database — read-only aggregation, no writes, and each "
                    "metric releases its read snapshot before the next begins",
        "honesty": "a metric with `n: 0` found nothing in the window and says so; it does not "
                   "report 0% or 100%. Every rate carries a Wilson 95% interval, and `confident` "
                   "is false while that interval is wider than 0.2",
    }
