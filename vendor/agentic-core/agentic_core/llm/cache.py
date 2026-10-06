"""A cache for model calls that are safe to repeat — and only those.
Lifted from backend/app/services/ai/cache.py. Opt-in per call site: judging a
fixed text against a fixed rubric is idempotent; generation is not."""
from __future__ import annotations

import hashlib
import threading
import time

_LOCK = threading.Lock()
_MAX_ENTRIES = 200
DEFAULT_TTL_S = 6 * 3600
_STORE: dict[str, tuple[str, float]] = {}


def key_for(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="replace")); h.update(b"\x00")
    return h.hexdigest()


def get(key: str) -> str | None:
    now = time.time()
    with _LOCK:
        hit = _STORE.get(key)
        if not hit:
            return None
        value, expires = hit
        if expires < now:
            _STORE.pop(key, None); return None
        return value


def put(key: str, value: str, ttl_s: int = DEFAULT_TTL_S) -> None:
    if not value:
        return
    with _LOCK:
        if len(_STORE) >= _MAX_ENTRIES:
            _STORE.pop(min(_STORE.items(), key=lambda kv: kv[1][1])[0], None)
        _STORE[key] = (value, time.time() + ttl_s)


def stats() -> dict:
    with _LOCK:
        return {"entries": len(_STORE), "max": _MAX_ENTRIES}


def clear() -> None:
    with _LOCK:
        _STORE.clear()
