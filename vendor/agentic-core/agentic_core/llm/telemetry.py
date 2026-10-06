"""What the model layer is actually doing — counted, not guessed.
Lifted from backend/app/services/ai/telemetry.py. Tokens/cost are reported as
unavailable rather than estimated when the provider does not return them."""
from __future__ import annotations

import threading
import time
from collections import deque

_LOCK = threading.Lock()
_COUNTERS: dict[str, dict] = {}
_RECENT: deque = deque(maxlen=50)
_SCHEMA: dict[str, int] = {}
_SCHEMA_LAST: dict[str, str] = {}
_CACHE = {"hits": 0, "misses": 0}


def record_schema_failure(*, purpose: str, problems: list[str]) -> None:
    try:
        with _LOCK:
            _SCHEMA[purpose] = _SCHEMA.get(purpose, 0) + 1
            _SCHEMA_LAST[purpose] = "; ".join(problems)[:200]
    except Exception:
        pass


def record_cache(*, hit: bool) -> None:
    try:
        with _LOCK:
            _CACHE["hits" if hit else "misses"] += 1
    except Exception:
        pass


def record(*, provider: str, purpose: str, ms: int, ok: bool, error_class: str | None = None,
           attempt: int = 1, tokens: int | None = None) -> None:
    try:
        with _LOCK:
            c = _COUNTERS.setdefault(provider, {"calls": 0, "failures": 0, "total_ms": 0, "tokens": 0, "tokens_known": False})
            c["calls"] += 1; c["total_ms"] += max(0, int(ms))
            if not ok:
                c["failures"] += 1
            if tokens is not None:
                c["tokens"] += int(tokens); c["tokens_known"] = True
            _RECENT.appendleft({"provider": provider, "purpose": purpose, "ms": int(ms), "ok": ok,
                                "error_class": error_class, "attempt": attempt, "tokens": tokens, "at": time.time()})
    except Exception:
        pass


def snapshot() -> dict:
    with _LOCK:
        providers = {p: {"calls": c["calls"], "failures": c["failures"],
                         "avg_ms": round(c["total_ms"] / c["calls"]) if c["calls"] else 0,
                         "failure_rate": round(c["failures"] / c["calls"], 3) if c["calls"] else 0.0,
                         "tokens": c["tokens"] if c["tokens_known"] else None}
                     for p, c in _COUNTERS.items()}
        recent = list(_RECENT)
        schema = {p: {"failures": n, "last": _SCHEMA_LAST.get(p, "")} for p, n in _SCHEMA.items()}
        cache = dict(_CACHE)
    looks = cache["hits"] + cache["misses"]
    cache["hit_rate"] = round(cache["hits"] / looks, 3) if looks else 0.0
    return {"providers": providers, "total_calls": sum(v["calls"] for v in providers.values()),
            "recent": recent, "schema_failures": schema, "cache": cache,
            "note": "Token counts appear only when the provider returned them; CLI agents do not."}


def reset() -> None:
    with _LOCK:
        _COUNTERS.clear(); _RECENT.clear(); _SCHEMA.clear(); _SCHEMA_LAST.clear()
        _CACHE.update({"hits": 0, "misses": 0})
