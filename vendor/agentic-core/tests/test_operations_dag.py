"""Idempotent operations + resumable plans."""
from _harness import bootstrap, check, reset_db, run_module
bootstrap("dag")

from agentic_core.database.base import async_session  # noqa: E402
from agentic_core.orchestrator import operations  # noqa: E402
from agentic_core.orchestrator.dag import StepSpec, reconcile_step, run_plan  # noqa: E402


async def test_operation_states():
    await reset_db()
    async with async_session() as db:
        op, action = await operations.begin(db, key="k1", operation_type="tool")
        check("new op executes", action == "execute")
        await operations.mark_sent(db, op)
        await operations.record(db, op, {"success": True, "external_id": "x1"})
        await db.commit()
        op2, action2 = await operations.begin(db, key="k1", operation_type="tool")
        check("succeeded op is 'done' — never sent twice", action2 == "done" and op2.external_id == "x1")
        op3, _ = await operations.begin(db, key="k2", operation_type="tool")
        await operations.mark_sent(db, op3); await db.commit()
        _, action3 = await operations.begin(db, key="k2", operation_type="tool")
        check("sent-but-unrecorded op reconciles", action3 == "reconcile")
        op4, _ = await operations.begin(db, key="k3", operation_type="tool")
        await operations.mark_sent(db, op4)
        await operations.record(db, op4, {"success": False, "details": "HTTP 503 temporarily unavailable"})
        await db.commit()
        check("transient failure classified", op4.state == "failed" and op4.error_class == "transient")
        _, action4 = await operations.begin(db, key="k3", operation_type="tool")
        check("failed op is retriable", action4 == "execute")
        n = await operations.count_for_prefix(db, "k")
        check("prefix count sees three", n == 3)


async def test_plan_resumes_not_restarts():
    await reset_db()
    calls = {"stage": 0, "post": 0}

    async def stage(ctx):
        calls["stage"] += 1
        return {"success": True, "output": {"cdn": "img-x"}}

    async def post(ctx):
        calls["post"] += 1
        assert ctx["stage"]["cdn"] == "img-x", ctx
        if calls["post"] == 1:
            return {"success": False, "details": "HTTP 500 upstream"}
        return {"success": True, "output": {"post_id": "p-1"}}
    specs = [StepSpec("stage", stage), StepSpec("post", post, depends_on=["stage"])]
    async with async_session() as db:
        r1 = await run_plan(db, plan_key="plan-1", plan_type="media", specs=specs)
    check("first run fails at post", r1["state"] == "failed")
    async with async_session() as db:
        r2 = await run_plan(db, plan_key="plan-1", plan_type="media", specs=specs)
    check("retry succeeds", r2["state"] == "succeeded")
    check("stage ran ONCE ever, post twice", calls == {"stage": 1, "post": 2})
    async with async_session() as db:
        r3 = await run_plan(db, plan_key="plan-1", plan_type="media", specs=specs)
    check("a succeeded plan reruns nothing", r3["state"] == "succeeded" and calls == {"stage": 1, "post": 2})


async def test_uncertain_blocks_and_reconcile_unblocks():
    await reset_db()
    n = {"v": 0}

    async def send(ctx):
        n["v"] += 1
        if n["v"] == 1:
            return {"success": False, "uncertain": True, "details": "confirmation timed out"}
        return {"success": True, "output": {"id": "done"}}
    specs = [StepSpec("send", send)]
    async with async_session() as db:
        r1 = await run_plan(db, plan_key="p2", plan_type="x", specs=specs)
        check("uncertain step blocks the plan", r1["state"] == "blocked" and r1["steps"][0]["state"] == "uncertain")
        r2 = await run_plan(db, plan_key="p2", plan_type="x", specs=specs)
        check("re-run does NOT re-send (still blocked)", r2["state"] == "blocked" and n["v"] == 1)
        rr = await reconcile_step(db, plan_key="p2", step_name="send", found=False)
        check("reconcile(found=False) → retriable", rr["ok"] and rr["state"] == "failed")
        r3 = await run_plan(db, plan_key="p2", plan_type="x", specs=specs)
        check("after reconcile the step re-runs and succeeds", r3["state"] == "succeeded" and n["v"] == 2)


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
