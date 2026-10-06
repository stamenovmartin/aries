"""TASK → EXECUTION → RESULT → EVALUATION → PASS/FAIL → RETRY / REPLAN / ESCALATE."""
from _harness import bootstrap, check, reset_db, run_module
bootstrap("lifecycle")

from sqlalchemy import select  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402
from agentic_core.database.models import ActionProposal, AgentStep, Task  # noqa: E402
from agentic_core.evaluators import deterministic as det  # noqa: E402
from agentic_core.orchestrator.lifecycle import LifecyclePolicy, run_cycle  # noqa: E402


async def _task(db, title="t"):
    t = Task(kind="generic", title=title, brief="do the thing", status="draft")
    db.add(t); await db.commit(); await db.refresh(t)
    return t


async def test_pass_path():
    await reset_db()
    async with async_session() as db:
        t = await _task(db)

        async def ex(task, ctx):
            return {"success": True, "content": "done properly"}
        out = await run_cycle(db, t, executor=ex, evaluators=[det.not_empty("content")])
        check("verdict pass", out.verdict == "pass" and out.attempts == 1)
        await db.refresh(t)
        check("task is done", t.status == "done" and t.result)
        steps = (await db.execute(select(AgentStep))).scalars().all()
        check("executor + evaluator steps traced", {s.agent for s in steps} >= {"executor", "evaluator"})


async def test_retry_with_corrective_note_then_pass():
    await reset_db()
    async with async_session() as db:
        t = await _task(db)
        seen = []

        async def ex(task, ctx):
            seen.append(ctx.get("corrective_note"))
            return {"success": True, "content": "" if ctx["attempt"] == 1 else "fixed"}
        out = await run_cycle(db, t, executor=ex, evaluators=[det.not_empty("content")],
                              policy=LifecyclePolicy(max_retries=2))
        check("retried once then passed", out.verdict == "pass" and out.attempts == 2)
        check("second attempt carried the corrective note", seen[0] is None and seen[1] and "CORRECTION" in seen[1])


async def test_retry_exhausted_escalates_with_proposal():
    await reset_db()
    async with async_session() as db:
        t = await _task(db)

        async def ex(task, ctx):
            return {"success": True, "content": ""}
        out = await run_cycle(db, t, executor=ex, evaluators=[det.not_empty("content")],
                              policy=LifecyclePolicy(max_retries=1))
        check("retry exhausted", out.verdict == "retry_exhausted" and out.attempts == 2)
        p = await db.get(ActionProposal, out.proposal_id)
        check("an escalation proposal exists for a human", p is not None and p.status == "proposed" and "escalation" in p.kind)
        await db.refresh(t)
        check("task parked in validation_failed", t.status == "validation_failed")


async def test_replan_on_expectation_failure():
    await reset_db()
    async with async_session() as db:
        t = await _task(db)
        plans = []

        async def ex(task, ctx):
            return {"success": True, "state": "active" if ctx.get("plan", {}).get("v") == 2 else "inactive"}

        async def pred(result, task, ctx):
            return result.get("state") == "active", f"state={result.get('state')}"

        async def replan(task, ctx):
            plans.append(ctx.get("issues")); return {"v": 2}
        out = await run_cycle(db, t, executor=ex, evaluators=[det.expected_state("active", pred)],
                              replanner=replan, policy=LifecyclePolicy(max_retries=0, max_replans=1))
        check("replanned once then passed", out.verdict == "pass" and out.replans == 1 and len(plans) == 1)


async def test_policy_error_escalates_immediately():
    await reset_db()
    async with async_session() as db:
        t = await _task(db)
        n = {"v": 0}

        async def ex(task, ctx):
            n["v"] += 1
            return {"success": False, "details": "action rejected by policy"}
        out = await run_cycle(db, t, executor=ex, evaluators=[det.not_empty("content")],
                              policy=LifecyclePolicy(max_retries=3))
        check("policy failure is not retried", n["v"] == 1 and out.verdict == "escalated")
        await db.refresh(t)
        check("task failed with class policy", t.status == "failed" and t.error_class == "policy")


async def test_uncertain_never_reruns():
    await reset_db()
    async with async_session() as db:
        t = await _task(db)
        n = {"v": 0}

        async def ex(task, ctx):
            n["v"] += 1
            return {"success": False, "uncertain": True, "details": "timed out after start"}
        out = await run_cycle(db, t, executor=ex, evaluators=[det.not_empty("content")],
                              policy=LifecyclePolicy(max_retries=3))
        check("uncertain outcome is reconciled, not retried", n["v"] == 1 and out.verdict == "reconcile")


async def test_require_approval_parks_a_pass():
    await reset_db()
    async with async_session() as db:
        t = await _task(db)

        async def ex(task, ctx):
            return {"success": True, "content": "ok", "risk": "high"}
        out = await run_cycle(db, t, executor=ex, evaluators=[det.not_empty("content")],
                              policy=LifecyclePolicy(require_approval=True))
        await db.refresh(t)
        check("passed but awaiting approval", out.verdict == "pass" and t.status == "awaiting_approval" and out.proposal_id)


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
