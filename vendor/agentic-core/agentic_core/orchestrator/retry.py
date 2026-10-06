"""Retry policy: attempt, classify, and only repeat what a repeat can fix.

The original pattern (backend/app/services/ai/__init__.py generate_* loops and
scheduling.py backoff) written once:

    for attempt in range(n):
        try: return await fn()
        except Exception as e:
            verdict = classify(str(e))
            if not verdict.retryable: break
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from agentic_core.observability import metrics
from agentic_core.orchestrator.errors import Classified, classify

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 0.0      # 0 = immediate; scheduler uses minutes-level backoff instead
    backoff_multiplier: float = 2.0
    retry_on_unknown: bool = False    # UNKNOWN is escalated by default, never looped


@dataclass
class Attempted:
    ok: bool
    value: object = None
    attempts: int = 0
    last_error: str | None = None
    verdict: Classified | None = None


async def with_retry(fn: Callable[[], Awaitable], *, policy: RetryPolicy | None = None,
                     operation: str = "call") -> Attempted:
    policy = policy or RetryPolicy()
    last_err, verdict = None, None
    delay = policy.backoff_seconds
    for attempt in range(1, max(1, policy.max_attempts) + 1):
        try:
            value = await fn()
            return Attempted(ok=True, value=value, attempts=attempt)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            last_err, verdict = str(e), classify(str(e))
            logger.warning("%s failed, attempt %d/%d [%s]: %s", operation, attempt,
                           policy.max_attempts, verdict.cls.value, e)
            retry = verdict.retryable or (policy.retry_on_unknown and verdict.cls.value == "unknown")
            if not retry or attempt >= policy.max_attempts:
                break
            metrics.record_retry(operation)
            if delay > 0:
                await asyncio.sleep(delay)
                delay *= policy.backoff_multiplier
    return Attempted(ok=False, attempts=attempt, last_error=last_err, verdict=verdict)
