"""Run the eval suite: generate for each case, score it, store the run.
Lifted from backend/app/evals/runner.py. `generate_fn(case) -> str` so the same
runner serves a live run and a test with a canned generator."""
from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.database.models import EvalCase, EvalResult, EvalRun
from agentic_core.evaluators.scorers import ScorerSuite

logger = logging.getLogger(__name__)
GenerateFn = Callable[[EvalCase], Awaitable[str]]
JUDGE_WEIGHT = 0.3


def score_output(text: str, case: EvalCase, suite: ScorerSuite, judge_data: dict | None = None) -> dict:
    facts = json.loads(case.expected) if case.expected else {}
    base = suite.score_all(text, facts)
    scores, notes, overall = dict(base["scores"]), dict(base["notes"]), base["overall"]
    if judge_data and judge_data.get("scores"):
        js = judge_data["scores"]
        scores.update({f"judge_{k}": v for k, v in js.items()})
        notes["judge"] = judge_data.get("note", "")
        overall = round((1 - JUDGE_WEIGHT) * overall + JUDGE_WEIGHT * (sum(js.values()) / len(js)), 3)
    cap_ok = suite.cap_on is None or scores.get(suite.cap_on, 1.0) >= suite.cap_below
    passed = overall >= suite.pass_threshold and cap_ok
    return {"scores": scores, "notes": notes, "overall": overall, "passed": passed}


async def run_suite(db: AsyncSession, *, label: str | None, generate_fn: GenerateFn, suite: ScorerSuite,
                    judge=None, prompt_version: str | None = None, agent: str | None = None) -> dict:
    q = select(EvalCase).where(EvalCase.active == True)  # noqa: E712
    if agent:
        q = q.where(EvalCase.agent == agent)
    cases = (await db.execute(q.order_by(EvalCase.id))).scalars().all()
    run = EvalRun(label=label, prompt_version=prompt_version, judged=judge is not None, cases=len(cases))
    db.add(run)
    await db.flush()
    dim_sums: dict[str, float] = {}; dim_counts: dict[str, int] = {}
    total, passed = 0.0, 0
    for case in cases:
        try:
            output = await generate_fn(case)
        except Exception:
            logger.exception("Generation failed for eval case %s", case.id)
            output = ""
        judge_data = None
        if judge and output.strip():
            judge_data = await judge({"content": output}, None, {"brief": case.name})
        r = score_output(output, case, suite, judge_data)
        db.add(EvalResult(run_id=run.id, case_id=case.id, case_name=case.name, output=output[:4000],
                          scores=json.dumps(r["scores"]), overall=r["overall"], passed=r["passed"],
                          notes=json.dumps(r["notes"], ensure_ascii=False)))
        total += r["overall"]; passed += 1 if r["passed"] else 0
        for k, v in r["scores"].items():
            dim_sums[k] = dim_sums.get(k, 0.0) + v; dim_counts[k] = dim_counts.get(k, 0) + 1
    n = len(cases) or 1
    run.avg_score = round(total / n, 3); run.passed = passed
    run.dimensions = json.dumps({k: round(dim_sums[k] / dim_counts[k], 3) for k in dim_sums})
    await db.commit()
    return {"run_id": run.id, "label": label, "cases": len(cases), "passed": passed,
            "avg_score": run.avg_score, "dimensions": json.loads(run.dimensions)}
