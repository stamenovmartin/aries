"""The failure taxonomy — because treating every failure the same is how a
retry doubles a side effect. Lifted from backend/app/execution/errors.py.

Only TRANSIENT retries blindly. UNCERTAIN (request left the machine, response
lost) must be RECONCILED before any retry. The rest need a fix or a human.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ErrorClass(str, Enum):
    TRANSIENT = "transient"      # timeout, 429, temporary 5xx → retry
    AUTH = "auth"                # expired token, missing scope → reconnect
    VALIDATION = "validation"    # bad input/output → fix (replan), don't retry
    POLICY = "policy"            # refused by a rule → human
    CAPABILITY = "capability"    # feature unavailable → disable
    UNCERTAIN = "uncertain"      # maybe succeeded → RECONCILE first
    UNKNOWN = "unknown"


# What the lifecycle does with each class (orchestrator/lifecycle.py).
ACTION = {
    ErrorClass.TRANSIENT: "retry",
    ErrorClass.AUTH: "reconnect",
    ErrorClass.VALIDATION: "replan",
    ErrorClass.POLICY: "escalate",
    ErrorClass.CAPABILITY: "disable",
    ErrorClass.UNCERTAIN: "reconcile",
    ErrorClass.UNKNOWN: "escalate",
}


@dataclass
class Classified:
    cls: ErrorClass
    action: str
    reason: str

    @property
    def retryable(self) -> bool:
        return self.cls is ErrorClass.TRANSIENT


_AUTH = re.compile(r"\b(expired|invalid.*token|permission denied|unauthori[sz]ed|forbidden|oauth|401|403)\b", re.I)
_TRANSIENT = re.compile(r"\b(timeout|timed out|429|rate.?limit|temporarily|try again|50[234]|connection reset|econnreset|resource temporarily unavailable|busy)\b", re.I)
_VALIDATION = re.compile(r"\b(invalid|must be|required|not.*accepted|unsupported|too long|does not meet|400|no such file|command not found|syntax error)\b", re.I)
_POLICY = re.compile(r"\b(rejected|disapprov|restricted|policy|not allowed|prohibited|blocked by)\b", re.I)
_CAPABILITY = re.compile(r"\b(not available|not supported for|unavailable in|not eligible|not installed)\b", re.I)


def classify(message: str, *, sent: bool = False, got_response: bool = True) -> Classified:
    """Read a failure and say what kind it is.

    `sent`/`got_response` carry the one distinction text cannot: a request that
    left the machine and whose response never came is UNCERTAIN regardless of
    the message.
    """
    if sent and not got_response:
        return Classified(ErrorClass.UNCERTAIN, ACTION[ErrorClass.UNCERTAIN],
                          "request was sent but the response was lost — reconcile first")
    m = message or ""
    for rx, cls in ((_AUTH, ErrorClass.AUTH), (_TRANSIENT, ErrorClass.TRANSIENT),
                    (_CAPABILITY, ErrorClass.CAPABILITY), (_POLICY, ErrorClass.POLICY),
                    (_VALIDATION, ErrorClass.VALIDATION)):
        if rx.search(m):
            return Classified(cls, ACTION[cls], m[:160])
    return Classified(ErrorClass.UNKNOWN, ACTION[ErrorClass.UNKNOWN], m[:160])
