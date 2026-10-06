"""The evaluation contract.

An Evaluator reads a result (plus the task and context) and returns a list of
issues, each {severity: error|warn|suggest, code, message}. This is the shape
backend/app/services/agent/review.py returns, generalised:

  * `error`   — blocking; a hard error fails the evaluation and drives the
                repair/retry loop.
  * `warn`    — advisory; costs score, never blocks.
  * `suggest` — a second opinion (usually the LLM judge); never blocks.

`evaluate_all` runs every deterministic evaluator, optionally the judge, and
folds the results into one Verdict with a score in [0, 1] and a pass flag.
Honesty rule preserved from the original: a hard error caps the score at 0.4
no matter how the rest reads.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

Issue = dict


def issue(severity: str, code: str, message: str, **extra) -> Issue:
    return {"severity": severity, "code": code, "message": message, **extra}


@dataclass
class Evaluator:
    """name + an async fn(result, task, ctx) -> list[Issue]. `weight` is the
    share of the deterministic score this evaluator carries; `replan_codes`
    are issue codes that mean 'the plan was wrong' rather than 'the output was
    wrong', so the lifecycle replans instead of retrying."""
    name: str
    fn: Callable[[dict, object, dict], Awaitable[list[Issue]]]
    weight: float = 1.0
    replan_codes: set[str] = field(default_factory=set)


@dataclass
class Verdict:
    passed: bool
    score: float
    issues: list[Issue]
    scores: dict[str, float]
    notes: dict[str, str]
    judge: dict | None = None
    needs_replan: bool = False

    @property
    def hard_errors(self) -> list[Issue]:
        return [i for i in self.issues if i.get("severity") == "error"]

    def summary(self) -> str:
        n_err = len(self.hard_errors)
        n_warn = sum(1 for i in self.issues if i.get("severity") == "warn")
        head = f"{'PASS' if self.passed else 'FAIL'} score={self.score:.2f} ({n_err} errors, {n_warn} warnings)"
        if self.issues:
            head += " — " + "; ".join(i["message"] for i in self.issues[:4])
        return head

    def corrective_note(self) -> str:
        """The instruction a retry carries — the gate_and_repair pattern."""
        problems = "; ".join(i["message"] for i in self.hard_errors) or "the result did not pass evaluation"
        return (f"CORRECTION: the previous attempt had problems — {problems}. "
                "Produce a result that resolves them without changing the goal.")

    def as_dict(self) -> dict:
        return {"passed": self.passed, "score": round(self.score, 3), "issues": self.issues,
                "scores": self.scores, "notes": self.notes, "judge": self.judge,
                "needs_replan": self.needs_replan}


JUDGE_WEIGHT = 0.3


async def evaluate_all(evaluators: list[Evaluator], result: dict, task, ctx: dict, *,
                       judge=None, pass_threshold: float = 0.7) -> Verdict:
    issues: list[Issue] = []
    scores: dict[str, float] = {}
    notes: dict[str, str] = {}
    total_w = sum(max(0.0, e.weight) for e in evaluators) or 1.0
    overall = 0.0
    needs_replan = False
    for ev in evaluators:
        try:
            found = list(await ev.fn(result, task, ctx) or [])
        except Exception as e:
            logger.exception("Evaluator %s crashed", ev.name)
            found = [issue("error", "evaluator_crashed", f"{ev.name}: {type(e).__name__}: {e}")]
        for i in found:
            i.setdefault("evaluator", ev.name)
        errors = [i for i in found if i.get("severity") == "error"]
        warns = [i for i in found if i.get("severity") == "warn"]
        if errors:
            s = max(0.0, 0.4 - 0.2 * (len(errors) - 1) - 0.1 * len(warns))
        else:
            s = max(0.5, 1.0 - 0.15 * len(warns)) if warns else 1.0
        scores[ev.name] = round(s, 3)
        notes[ev.name] = "; ".join(i["message"] for i in (errors + warns)[:3]) or "ok"
        overall += (ev.weight / total_w) * s
        issues.extend(found)
        if any(i.get("code") in ev.replan_codes for i in errors):
            needs_replan = True
    if any(i.get("severity") == "error" for i in issues):
        overall = min(overall, 0.4)
    judge_data = None
    if judge is not None:
        try:
            judge_data = await judge(result, task, ctx)
        except Exception:
            logger.exception("Judge failed; keeping the deterministic verdict")
        if judge_data and judge_data.get("scores"):
            js = judge_data["scores"]
            scores.update({f"judge_{k}": v for k, v in js.items()})
            notes["judge"] = judge_data.get("note", "")
            judge_avg = sum(js.values()) / len(js)
            # The judge adjusts; it does not overrule a hard error.
            capped = min(overall, 0.4) if any(i.get("severity") == "error" for i in issues) else overall
            overall = round((1 - JUDGE_WEIGHT) * capped + JUDGE_WEIGHT * judge_avg, 3)
            if any(i.get("severity") == "error" for i in issues):
                overall = min(overall, 0.4)
            for tip in judge_data.get("suggestions") or []:
                issues.append(issue("suggest", "judge_suggestion", str(tip)[:300], evaluator="judge"))
    passed = overall >= pass_threshold and not any(i.get("severity") == "error" for i in issues)
    return Verdict(passed=passed, score=round(overall, 3), issues=issues, scores=scores,
                   notes=notes, judge=judge_data, needs_replan=needs_replan)
