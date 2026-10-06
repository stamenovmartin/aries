"""Weighted scorer suites for the eval harness.
Lifted from backend/app/evals/scorers.py: each scorer is (name, fn, weight)
with fn(text, facts) -> (score in [0,1], note). Weights sum to 1; a failing
`factual`-type scorer caps the overall (honesty is not tradeable)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

Scorer = tuple[str, Callable[[str, dict], tuple[float, str]], float]


@dataclass
class ScorerSuite:
    scorers: list[Scorer]
    cap_on: str | None = None          # a scorer whose score < cap_below caps the overall
    cap_below: float = 0.5
    cap_to: float = 0.4
    pass_threshold: float = 0.7
    extra: dict = field(default_factory=dict)

    def score_all(self, text: str, facts: dict) -> dict:
        scores, notes, overall = {}, {}, 0.0
        for name, fn, weight in self.scorers:
            s, note = fn(text, facts)
            scores[name] = round(s, 3); notes[name] = note; overall += weight * s
        if self.cap_on and scores.get(self.cap_on, 1.0) < self.cap_below:
            overall = min(overall, self.cap_to)
        passed = overall >= self.pass_threshold and (self.cap_on is None or scores.get(self.cap_on, 1.0) >= self.cap_below)
        return {"scores": scores, "notes": notes, "overall": round(overall, 3), "passed": passed}


# ── generic scorers ──────────────────────────────────────────────────────────

def score_not_empty(text: str, facts: dict) -> tuple[float, str]:
    t = (text or "").strip()
    return (1.0, "has content") if t else (0.0, "empty")


_SENTENCE = re.compile(r"[A-Za-zÀ-ž][^.!?\n]{18,}[.!?]")


def score_prose(text: str, facts: dict) -> tuple[float, str]:
    """At least one real sentence, not only a bullet list."""
    t = (text or "").strip()
    if not t:
        return 0.0, "empty"
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    bulletish = sum(1 for ln in lines if ln[:1] in "-–—•*·")
    prose = _SENTENCE.findall(t)
    if not prose:
        return 0.2, "no full sentence — only a list"
    if lines and bulletish / len(lines) > 0.7:
        return 0.6, "mostly a list"
    return 1.0, f"{len(prose)} sentences"


def score_length_fit(lo: int, hi: int):
    def fn(text: str, facts: dict) -> tuple[float, str]:
        n = len((text or "").strip())
        if n < lo:
            return max(0.0, n / lo), f"too short ({n} < {lo})"
        if n > hi:
            return max(0.3, hi / n), f"too long ({n} > {hi})"
        return 1.0, f"length ok ({n})"
    return fn


def score_mentions(key: str, min_frac: float = 0.4):
    """Does the output name the subject in facts[key] (token overlap)?"""
    def fn(text: str, facts: dict) -> tuple[float, str]:
        subject = str(facts.get(key) or "")
        toks = [w for w in re.split(r"\W+", subject.lower()) if len(w) > 2]
        if not toks:
            return 1.0, "nothing to check"
        low = (text or "").lower()
        hit = sum(1 for w in toks if w in low)
        frac = hit / len(toks)
        if frac >= min_frac:
            return 1.0, f"names the subject ({hit}/{len(toks)})"
        if frac > 0:
            return 0.6, f"partially specific ({hit}/{len(toks)})"
        return 0.3, "generic — never names the subject"
    return fn


def score_grounded(extract: Callable[[str], list], facts_key: str = "allowed"):
    """The 'factual' scorer: values the output states must be in facts[facts_key]."""
    def fn(text: str, facts: dict) -> tuple[float, str]:
        stated = set(extract(text or ""))
        known = set(facts.get(facts_key) or [])
        if not stated:
            return 1.0, "no claims to check"
        wrong = stated - known
        if wrong:
            return max(0.0, 0.4 - 0.2 * (len(wrong) - 1)), f"ungrounded: {sorted(map(str, wrong))[:3]}"
        return 1.0, "every claim is grounded"
    return fn


def score_forbidden(patterns: list[str]):
    rxs = [re.compile(p, re.I) for p in patterns]

    def fn(text: str, facts: dict) -> tuple[float, str]:
        hits = [rx.pattern for rx in rxs if rx.search(text or "")]
        return (0.0, f"forbidden: {hits[:3]}") if hits else (1.0, "no forbidden content")
    return fn


def default_suite(*, subject_key: str = "subject", lo: int = 30, hi: int = 2000,
                  extract=None, forbidden: list[str] | None = None) -> ScorerSuite:
    scorers: list[Scorer] = [
        ("grounded", score_grounded(extract or (lambda t: [])), 0.35),
        ("prose", score_prose, 0.25),
        ("specificity", score_mentions(subject_key), 0.20),
        ("length_fit", score_length_fit(lo, hi), 0.10),
        ("forbidden", score_forbidden(forbidden or []), 0.10),
    ]
    return ScorerSuite(scorers=scorers, cap_on="grounded")
