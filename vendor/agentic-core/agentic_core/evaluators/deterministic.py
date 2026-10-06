"""Deterministic checks — cheap, reproducible, no model call. The backbone.

The marketing reviewer (backend/app/services/agent/review.py) checked: empty
output, length limits, banned characters, claims the source data cannot back
(price mismatch, invented discount, invented warranty). The generic versions:

  not_empty            the result carries content
  schema               required keys exist and have the right type
  length               soft/hard character limits
  banned_patterns      regexes that must not appear (forbidden claims)
  required_patterns    regexes that must appear
  grounded_facts       every number/claim of a declared kind in the output
                       exists in the provided facts (the "no invented price" rule)
  exit_code            a command-style result exited 0
  expected_state       a predicate over the result/ctx, written as a callable
                       (the Linux verifier: "service is active", "disk < 90%")
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable

from agentic_core.evaluators.base import Evaluator, issue


def _text(result) -> str:
    if isinstance(result, dict):
        for k in ("content", "text", "output", "stdout", "summary"):
            if isinstance(result.get(k), str):
                return result[k]
        return ""
    return str(result or "")


def not_empty(field: str | None = None, *, min_len: int = 1) -> Evaluator:
    async def fn(result, task, ctx):
        t = (result.get(field) if field and isinstance(result, dict) else _text(result)) or ""
        if not str(t).strip():
            return [issue("error", "empty", "The result is empty.")]
        if len(str(t).strip()) < min_len:
            return [issue("warn", "too_short", f"The result is very short ({len(str(t))} chars).")]
        return []
    return Evaluator("not_empty", fn, weight=0.5)


def schema(required: dict[str, type], *, weight: float = 1.0) -> Evaluator:
    async def fn(result, task, ctx):
        out = []
        if not isinstance(result, dict):
            return [issue("error", "not_object", "The result is not an object.")]
        for k, t in required.items():
            if k not in result or result[k] is None:
                out.append(issue("error", "missing_field", f"Missing required field '{k}'."))
            elif not isinstance(result[k], t):
                out.append(issue("error", "wrong_type", f"Field '{k}' must be {getattr(t, '__name__', t)}."))
        return out
    return Evaluator("schema", fn, weight=weight)


def length(*, soft: int | None = None, hard: int | None = None, field: str | None = None) -> Evaluator:
    async def fn(result, task, ctx):
        t = (result.get(field) if field and isinstance(result, dict) else _text(result)) or ""
        n = len(str(t))
        if hard and n > hard:
            return [issue("error", "too_long", f"{n} chars > hard limit {hard}.")]
        if soft and n > soft:
            return [issue("warn", "too_long", f"{n} chars > recommended {soft}.")]
        return []
    return Evaluator("length", fn, weight=0.5)


def banned_patterns(patterns: dict[str, str], *, severity: str = "error", field: str | None = None) -> Evaluator:
    """patterns: {code: regex}. Each hit is one issue with that code."""
    compiled = {c: re.compile(p, re.I) for c, p in patterns.items()}

    async def fn(result, task, ctx):
        t = (result.get(field) if field and isinstance(result, dict) else _text(result)) or ""
        return [issue(severity, code, f"Forbidden pattern '{code}' found.") for code, rx in compiled.items() if rx.search(str(t))]
    return Evaluator("banned_patterns", fn, weight=1.0)


def required_patterns(patterns: dict[str, str], *, severity: str = "warn", field: str | None = None) -> Evaluator:
    compiled = {c: re.compile(p, re.I) for c, p in patterns.items()}

    async def fn(result, task, ctx):
        t = (result.get(field) if field and isinstance(result, dict) else _text(result)) or ""
        return [issue(severity, code, f"Required pattern '{code}' not found.") for code, rx in compiled.items() if not rx.search(str(t))]
    return Evaluator("required_patterns", fn, weight=0.5)


def grounded_facts(*, extract: Callable[[str], list], facts_key: str = "facts",
                   label: str = "value", severity: str = "error") -> Evaluator:
    """Every value `extract` finds in the output must be present in ctx[facts_key]
    (a list/set of allowed values). The generic form of 'price_mismatch'."""
    async def fn(result, task, ctx):
        t = _text(result)
        stated = set(extract(str(t)))
        known = set(ctx.get(facts_key) or [])
        if not stated:
            return []
        wrong = sorted(str(v) for v in stated - known)
        if wrong:
            return [issue(severity, "ungrounded_claim",
                          f"The output states {label}(s) not present in the facts: {', '.join(wrong)[:200]}.")]
        return []
    return Evaluator("grounded_facts", fn, weight=1.5)


def exit_code(*, expect: int = 0) -> Evaluator:
    async def fn(result, task, ctx):
        if not isinstance(result, dict):
            return [issue("error", "no_exit_code", "No exit code in the result.")]
        if result.get("refused"):
            return [issue("error", "refused", f"Refused: {result['refused']}")]
        if result.get("uncertain"):
            return [issue("error", "uncertain", "Outcome uncertain (timed out after start).")]
        code = result.get("exit_code")
        if code is None:
            return [issue("error", "no_exit_code", "The command did not report an exit code.")]
        if code != expect:
            return [issue("error", "nonzero_exit", f"Exit code {code} (expected {expect}): {(result.get('stderr') or '')[-200:]}")]
        return []
    return Evaluator("exit_code", fn, weight=1.0)


def expected_state(name: str, predicate: Callable[[dict, object, dict], Awaitable[tuple[bool, str]]],
                   *, replan: bool = True, weight: float = 1.5) -> Evaluator:
    """A verification predicate: (ok, explanation). A failed expectation usually
    means the PLAN was wrong (the fix did not fix it), so it replans by default."""
    async def fn(result, task, ctx):
        ok, why = await predicate(result, task, ctx)
        return [] if ok else [issue("error", "expectation_failed", f"{name}: {why}")]
    return Evaluator(f"expect:{name}", fn, weight=weight, replan_codes={"expectation_failed"} if replan else set())
