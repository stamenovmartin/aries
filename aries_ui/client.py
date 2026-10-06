"""Talking to ARIES over HTTP — the only way this application reaches it.

This module is the whole architectural boundary (ADR-0004). The Control Centre
runs on the system interpreter with GTK; ARIES runs in its own virtual
environment. There is no shared import, no shared object, and no database
handle here — only a URL. A future contributor cannot reach past the API from
the UI, because there is nothing on this interpreter's path to reach with.

Standard library only. Nothing is installed into the system Python, which is
externally managed (PEP 668), so `urllib.request` rather than `httpx`.

RESPONSIVENESS
--------------
GTK has one main loop and every widget touch must happen on it. A blocking HTTP
call on that thread freezes the window — and ARIES calls are exactly the kind
that block: a health probe shells out, a news scan fetches the internet, a
learning pass reads thirty days of rows.

So every request runs on a worker thread and its result is marshalled back with
`GLib.idle_add`, which is the one supported way to touch GTK from another
thread. Callbacks therefore always run on the main loop, and a page never has to
think about locking.

STALE RESPONSES
---------------
Clicking Home → News → Home starts three requests that may land in any order. A
late reply from the first would overwrite the screen with older data — a bug
that looks like flickering and is actually a correctness problem. Every request
carries a generation number from its caller; a reply whose generation has been
superseded is dropped before it reaches a widget.
"""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from gi.repository import GLib

DEFAULT_BASE = "http://127.0.0.1:8000"
TIMEOUT = 30.0


class ApiUnreachable(Exception):
    """ARIES is not answering. Carries the command that starts it."""

    def __init__(self, base: str, detail: str = ""):
        self.base, self.detail = base, detail
        super().__init__(f"ARIES is not answering at {base}")


class ApiError(Exception):
    """ARIES answered with a refusal. `detail` is its own explanation."""

    def __init__(self, status: int, detail: str, payload: Any = None):
        self.status, self.detail, self.payload = status, detail, payload
        super().__init__(f"{status}: {detail}")


@dataclass
class Client:
    base: str = DEFAULT_BASE
    api_key: str = ""
    timeout: float = TIMEOUT
    _generation: dict = field(default_factory=dict)

    # ── blocking, worker-thread side ────────────────────────────────────────
    def request(self, method: str, path: str, *, params: dict | None = None,
                body: Any = None) -> Any:
        url = self.base.rstrip("/") + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw)
                detail = payload.get("detail") if isinstance(payload, dict) else str(payload)
            except (ValueError, AttributeError):
                payload, detail = None, raw.decode(errors="replace")[:300]
            if isinstance(detail, dict):
                detail = detail.get("detail") or json.dumps(detail)
            raise ApiError(e.code, str(detail or e.reason), payload) from None
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            raise ApiUnreachable(self.base, str(getattr(e, "reason", e))) from None

    def get(self, path, **params):
        return self.request("GET", path, params=params or None)

    def post(self, path, body=None, **params):
        return self.request("POST", path, params=params or None, body=body if body is not None else {})

    def patch(self, path, body=None, **params):
        return self.request("PATCH", path, params=params or None, body=body or {})

    def put(self, path, body=None, **params):
        return self.request("PUT", path, params=params or None, body=body or {})

    def delete(self, path, **params):
        return self.request("DELETE", path, params=params or None)

    # ── non-blocking, main-loop side ────────────────────────────────────────
    def call(self, work: Callable[["Client"], Any], *, on_ok: Callable[[Any], None],
             on_error: Callable[[Exception], None] | None = None,
             key: str = "", generation: int | None = None) -> None:
        """Run `work(client)` on a thread; deliver the result on the main loop.

        `key` + `generation` implement the staleness guard: pass a counter that
        increments whenever the caller's context changes (a page switch, a
        filter change), and a reply from a superseded generation is discarded.
        """
        if key and generation is not None:
            self._generation[key] = generation

        def _run():
            try:
                result = work(self)
            except Exception as exc:                     # noqa: BLE001
                GLib.idle_add(_deliver_error, exc)
                return
            GLib.idle_add(_deliver_ok, result)

        def _fresh() -> bool:
            return not key or generation is None or self._generation.get(key) == generation

        def _deliver_ok(result):
            if _fresh():
                on_ok(result)
            return GLib.SOURCE_REMOVE

        def _deliver_error(exc):
            if _fresh():
                (on_error or _default_error)(exc)
            return GLib.SOURCE_REMOVE

        threading.Thread(target=_run, daemon=True).start()

    def bump(self, key: str) -> int:
        """Invalidate anything in flight for `key` and return the new generation."""
        self._generation[key] = self._generation.get(key, 0) + 1
        return self._generation[key]


def _default_error(exc: Exception) -> None:
    import sys
    print(f"[aries-ui] unhandled: {type(exc).__name__}: {exc}", file=sys.stderr)


def describe(exc: Exception) -> tuple[str, str, str]:
    """(title, explanation, suggested command) for any failure, in plain words."""
    if isinstance(exc, ApiUnreachable):
        return ("ARIES is not running",
                "The Control Centre talks to ARIES over its API, and nothing is answering "
                f"at {exc.base}.",
                "cd ~/aries && ./scripts/start.sh")
    if isinstance(exc, ApiError):
        if exc.status == 403:
            return ("Not permitted", exc.detail, "")
        if exc.status == 404:
            return ("Not found", exc.detail, "")
        if exc.status == 400:
            return ("ARIES refused that", exc.detail, "")
        return (f"ARIES returned {exc.status}", exc.detail, "")
    return (type(exc).__name__, str(exc), "")
