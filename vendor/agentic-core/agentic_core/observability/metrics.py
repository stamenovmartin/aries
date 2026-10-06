"""Counters, gauges and histograms in-process, honest about the unknown.
Lifted from backend/app/core/metrics_registry.py.

Three rules: a metric with no observations reports `null` with a reason, never
0; a rate over a zero denominator is `null`; a metric can be marked
unobservable with the reason. JSON output (not Prometheus text) precisely so
`null` can be expressed.
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agentic_core.security import environments

COUNTER, GAUGE, HISTOGRAM = "counter", "gauge", "histogram"
_WINDOW = 512


@dataclass(frozen=True)
class Declared:
    name: str
    kind: str
    unit: str | None
    help: str


CATALOG: dict[str, Declared] = {d.name: d for d in (
    Declared("request_latency_ms", HISTOGRAM, "ms", "HTTP request duration."),
    Declared("requests_total", COUNTER, None, "HTTP requests by outcome."),
    Declared("errors_total", COUNTER, None, "Errors by taxonomy class."),
    Declared("job_latency_ms", HISTOGRAM, "ms", "Background job duration."),
    Declared("jobs_total", COUNTER, None, "Background jobs by outcome."),
    Declared("queue_depth", GAUGE, "items", "How many wait in a queue."),
    Declared("retries_total", COUNTER, None, "Retried attempts."),
    Declared("dead_letter_total", COUNTER, None, "Operations abandoned after exhausted attempts."),
    Declared("ai_generation_latency_ms", HISTOGRAM, "ms", "Model call duration."),
    Declared("ai_generations_total", COUNTER, None, "Model calls by outcome."),
    Declared("validations_total", COUNTER, None, "Evaluations by outcome."),
    Declared("tool_calls_total", COUNTER, None, "Tool executions by outcome."),
    Declared("escalations_total", COUNTER, None, "Tasks handed to a human."),
    Declared("sync_age_seconds", GAUGE, "s", "Seconds since the last successful sync."),
)}


@dataclass
class _Series:
    labels: tuple
    kind: str
    count: int = 0
    total: float = 0.0
    value: float | None = None
    at: float | None = None
    wall: float | None = None
    samples: deque = field(default_factory=lambda: deque(maxlen=_WINDOW))
    unobservable_reason: str | None = None


_LOCK = threading.Lock()
_SERIES: dict = {}
_AD_HOC: set[str] = set()
_STARTED = time.time()
_STARTED_MONO = time.monotonic()


def _key(labels):
    return tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items() if v is not None))


def _series(name, kind, labels):
    declared = CATALOG.get(name)
    if declared is None:
        _AD_HOC.add(name)
    k = (name, _key(labels))
    s = _SERIES.get(k)
    if s is None:
        s = _Series(labels=k[1], kind=(declared.kind if declared else kind))
        _SERIES[k] = s
    return s


def increment(name: str, value: float = 1, **labels) -> None:
    try:
        with _LOCK:
            s = _series(name, COUNTER, labels)
            s.count += 1; s.total += float(value)
            s.at, s.wall = time.monotonic(), time.time(); s.unobservable_reason = None
    except Exception:
        pass


def set_gauge(name: str, value: float | None, *, reason: str | None = None, **labels) -> None:
    try:
        with _LOCK:
            s = _series(name, GAUGE, labels)
            s.at, s.wall = time.monotonic(), time.time()
            if value is None:
                s.value = None; s.unobservable_reason = reason or "value not available"
            else:
                s.value = float(value); s.count += 1; s.unobservable_reason = None
    except Exception:
        pass


def observe(name: str, value: float, **labels) -> None:
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return
        with _LOCK:
            s = _series(name, HISTOGRAM, labels)
            s.count += 1; s.total += v; s.samples.append(v)
            s.at, s.wall = time.monotonic(), time.time(); s.unobservable_reason = None
    except Exception:
        pass


def unobservable(name: str, reason: str, **labels) -> None:
    try:
        with _LOCK:
            s = _series(name, CATALOG[name].kind if name in CATALOG else GAUGE, labels)
            s.unobservable_reason = reason; s.value = None
            s.at, s.wall = time.monotonic(), time.time()
    except Exception:
        pass


def record_request(method, route, status_code, ms):
    outcome = "error" if status_code >= 500 else ("refused" if status_code >= 400 else "ok")
    observe("request_latency_ms", ms, method=method, route=route)
    increment("requests_total", method=method, route=route, outcome=outcome)


def record_error(error_class: str, *, where: str | None = None):
    increment("errors_total", error_class=error_class, where=where)


def record_job(job: str, ms: float, ok: bool):
    observe("job_latency_ms", ms, job=job)
    increment("jobs_total", job=job, outcome="ok" if ok else "failed")


def set_queue_depth(queue: str, depth: int | None, *, reason: str | None = None):
    set_gauge("queue_depth", depth, reason=reason, queue=queue)


def record_retry(operation: str):
    increment("retries_total", operation=operation)


def record_dead_letter(operation: str):
    increment("dead_letter_total", operation=operation)


def record_ai_generation(provider: str, purpose: str, ms: float, ok: bool):
    observe("ai_generation_latency_ms", ms, provider=provider, purpose=purpose)
    increment("ai_generations_total", provider=provider, outcome="ok" if ok else "failed")


def record_validation(kind: str, ok: bool):
    increment("validations_total", kind=kind, outcome="ok" if ok else "failed")


def record_tool_call(tool: str, ok: bool):
    increment("tool_calls_total", tool=tool, outcome="ok" if ok else "failed")


def record_escalation(reason: str):
    increment("escalations_total", reason=reason)


def record_sync(integration: str, *, at: float | None = None):
    try:
        with _LOCK:
            s = _series("sync_age_seconds", GAUGE, {"integration": integration})
            s.wall = at if at is not None else time.time(); s.at = time.monotonic()
            s.count += 1; s.value = 0.0; s.unobservable_reason = None
    except Exception:
        pass


def _percentile(sorted_samples, q):
    if not sorted_samples:
        return 0.0
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    pos = q * (len(sorted_samples) - 1)
    low = int(math.floor(pos)); high = min(low + 1, len(sorted_samples) - 1)
    return sorted_samples[low] + (sorted_samples[high] - sorted_samples[low]) * (pos - low)


_NO_DATA = "no observations — either nothing happened or nothing is instrumented here; those are different facts"


def _iso(wall):
    return datetime.fromtimestamp(wall, timezone.utc).isoformat() if wall else None


def _render(name, entries, now_wall):
    declared = CATALOG.get(name)
    out = {"kind": declared.kind if declared else (entries[0].kind if entries else GAUGE),
           "unit": declared.unit if declared else None, "help": declared.help if declared else None,
           "declared": declared is not None}
    series = []
    for s in entries:
        labels = dict(s.labels)
        if s.unobservable_reason and s.value is None and s.count == 0:
            series.append({"labels": labels, "value": None, "reason": s.unobservable_reason}); continue
        if out["kind"] == COUNTER:
            series.append({"labels": labels, "value": s.total, "last_at": _iso(s.wall)})
        elif out["kind"] == GAUGE:
            if name == "sync_age_seconds":
                age = None if s.wall is None else max(0.0, now_wall - s.wall)
                series.append({"labels": labels, "value": None if age is None else round(age, 1),
                               "last_sync": _iso(s.wall), "reason": None if age is not None else _NO_DATA})
            else:
                series.append({"labels": labels, "value": s.value, "reason": s.unobservable_reason, "last_at": _iso(s.wall)})
        else:
            window = sorted(s.samples)
            series.append({"labels": labels, "count": s.count,
                           "avg": round(s.total / s.count, 2) if s.count else None,
                           "p50": round(_percentile(window, 0.50), 2) if window else None,
                           "p95": round(_percentile(window, 0.95), 2) if window else None,
                           "max": round(max(window), 2) if window else None,
                           "window": len(window), "window_capped": s.count > len(window), "last_at": _iso(s.wall)})
    if not series:
        out["value"] = None; out["reason"] = _NO_DATA
    out["series"] = series
    return out


def _ratio(numerator_outcomes, entries, label):
    total = sum(s.total for s in entries)
    hit = sum(s.total for s in entries if dict(s.labels).get("outcome") in numerator_outcomes)
    if total <= 0:
        return {"value": None, "observed": 0, "reason": f"no observed attempts for {label} — a rate over zero is not zero"}
    return {"value": round(hit / total, 4), "observed": int(total)}


def snapshot() -> dict:
    now_wall = time.time()
    with _LOCK:
        grouped: dict[str, list[_Series]] = {}
        for (name, _l), s in _SERIES.items():
            grouped.setdefault(name, []).append(_Series(labels=s.labels, kind=s.kind, count=s.count, total=s.total,
                                                        value=s.value, at=s.at, wall=s.wall, samples=deque(s.samples),
                                                        unobservable_reason=s.unobservable_reason))
        ad_hoc = sorted(_AD_HOC)
    names = sorted(set(grouped) | set(CATALOG))
    return {
        "env": environments.current(), "process_started_at": _iso(_STARTED),
        "uptime_seconds": round(time.monotonic() - _STARTED_MONO, 1), "scope": "this process",
        "metrics": {n: _render(n, grouped.get(n, []), now_wall) for n in names},
        "rates": {
            "error_rate": _ratio({"error"}, grouped.get("requests_total", []), "HTTP request"),
            "validation_failure_rate": _ratio({"failed"}, grouped.get("validations_total", []), "evaluation"),
            "tool_success_rate": _ratio({"ok"}, grouped.get("tool_calls_total", []), "tool call"),
        },
        "uninstrumented": sorted(n for n in CATALOG if not grouped.get(n)),
        "ad_hoc": ad_hoc,
        "note": "In-memory, lost on restart. A metric with no observation is null with a reason, never zero.",
    }


def last_write(name: str, **labels) -> str | None:
    with _LOCK:
        s = _SERIES.get((name, _key(labels)))
        return _iso(s.wall) if s and s.wall else None


def reset() -> None:
    with _LOCK:
        _SERIES.clear(); _AD_HOC.clear()


_ID_SEGMENT = re.compile(r"^(\d+|[0-9a-fA-F-]{16,36})$")


def route_of(path: str) -> str:
    return "/".join("{id}" if _ID_SEGMENT.match(p) else p for p in path.split("/"))[:120]


class RequestMetricsMiddleware:
    """Pure ASGI middleware timing every HTTP request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send); return
        started = time.perf_counter(); status = {"code": 500}

        async def _send(message):
            if message.get("type") == "http.response.start":
                status["code"] = int(message.get("status", 500))
            await send(message)
        try:
            await self.app(scope, receive, _send)
        except Exception:
            status["code"] = 500; raise
        finally:
            record_request(scope.get("method", "?"), route_of(scope.get("path", "/")),
                           status["code"], (time.perf_counter() - started) * 1000.0)
