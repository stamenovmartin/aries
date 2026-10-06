"""Notice when ARIES is being driven by something that is not the person.

On 2026-09-29 the microphone heard the music ARIES had just started, Whisper
turned the song into "Ari, play some music." — a sentence from its own prompt —
and each command started another song. 44 goals in 20 minutes, none spoken by
anyone, and a window for every one of them. Every individual command looked
legitimate; only the PATTERN was wrong. That pattern is what this watches.

Three signals, each cheap and each explainable in one sentence to the user:

  repeat — the same request several times in a short window. A person who
           wants music says it once; a loop says it every few seconds.
  rate   — more goals from one source per minute than a person speaks.
  trip   — once either fires for a source, that source is paused for a while
           rather than refused one request at a time, because a loop that is
           refused once simply produces the next request.

State is in memory on purpose: it describes the last few minutes of this
process, and a restart is itself a reasonable reset.
"""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass

REPEAT_WINDOW_S = 120
REPEAT_LIMIT = {"voice": 3, "default": 6}   # typed retries are legitimate more often
RATE_WINDOW_S = 60
RATE_LIMIT = {"voice": 6, "default": 15}
PAUSE_S = 600

_recent: dict[str, deque] = {}
_paused_until: dict[str, float] = {}
_reason: dict[str, str] = {}


@dataclass
class Verdict:
    allowed: bool
    reason: str = ""
    tripped: bool = False        # True only on the request that caused the pause

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "tripped": self.tripped}


def normalise(text: str) -> str:
    return re.sub(r"[\W_]+", " ", (text or "").casefold()).strip()


def check(text: str, source: str = "default", *, now: float | None = None) -> Verdict:
    """Record one request and say whether it may run."""
    now = time.monotonic() if now is None else now
    source = source or "default"
    until = _paused_until.get(source, 0.0)
    if now < until:
        return Verdict(False, f"{source} paused for {int(until - now)}s more: {_reason.get(source, '')}")

    q = _recent.setdefault(source, deque())
    while q and now - q[0][0] > max(REPEAT_WINDOW_S, RATE_WINDOW_S):
        q.popleft()
    key = normalise(text)
    q.append((now, key))

    same = sum(1 for t, k in q if k == key and now - t <= REPEAT_WINDOW_S)
    rate = sum(1 for t, _ in q if now - t <= RATE_WINDOW_S)
    limit = RATE_LIMIT.get(source, RATE_LIMIT["default"])
    why = ""
    if same >= REPEAT_LIMIT.get(source, REPEAT_LIMIT["default"]):
        why = f"'{text.strip()[:60]}' was asked {same} times in {REPEAT_WINDOW_S // 60} minutes"
    elif rate > limit:
        why = f"{rate} requests in a minute from {source}, more than a person speaks"
    if not why:
        return Verdict(True)
    _paused_until[source] = now + PAUSE_S
    _reason[source] = why
    q.clear()
    return Verdict(False, f"loop suspected — {why}; {source} paused for {PAUSE_S // 60} minutes", tripped=True)


def resume(source: str | None = None) -> None:
    """Lift a pause — for the person, who knows it was them."""
    for s in ([source] if source else list(_paused_until)):
        _paused_until.pop(s, None)
        _reason.pop(s, None)
        _recent.pop(s, None)


def status(now: float | None = None) -> dict:
    now = time.monotonic() if now is None else now
    return {s: {"paused_for_s": int(u - now), "reason": _reason.get(s, "")}
            for s, u in _paused_until.items() if u > now}
