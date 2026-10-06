"""Agents run with the template fallback; workflows route through the Director."""
from _harness import bootstrap, check, reset_db, run_module
bootstrap("workflow")

import agentic_core.agents.builtin  # noqa: E402,F401
import agentic_core.tools.builtin  # noqa: E402,F401
import agentic_core.workflows.examples  # noqa: E402,F401
from agentic_core.agents import registry  # noqa: E402
from agentic_core.agents.runtime import run_agent  # noqa: E402
from agentic_core.database.base import async_session  # noqa: E402
from agentic_core.database.models import Task  # noqa: E402
from agentic_core.scheduler.queue import register_kind, run_task_now  # noqa: E402
from agentic_core.workflows import spec  # noqa: E402
from agentic_core.workflows.engine import run_workflow  # noqa: E402


async def test_agent_fallback_and_describe():
    res = await run_agent(registry.get("planner"), {"brief": "fix disk"})
    check("template provider → fallback plan", res["fallback"] and res["output"]["steps"] and res["provider"] == "template")
    d = registry.get("executor").describe()
    check("describe carries prompt, schema, permission", d["system_prompt"] and "content" in d["output_schema"] and d["permission"] == "run_agent")
    check("roster has the generic team", {a.name for a in registry.all_agents()} >= {"planner", "researcher", "executor", "reviewer", "repairer", "judge"} - {"judge"})


async def test_workflow_runs_and_repairs_dynamically():
    await reset_db()
    async with async_session() as db:
        t = Task(kind="generic", title="w", brief="write a note", status="draft"); db.add(t); await db.commit(); await db.refresh(t)
        out = await run_workflow(db, spec.get("plan_execute_verify"), t)
        d = {x["node"]: x for x in out["decisions"]}
        check("research/plan/execute/review ran", all(d[n]["ran"] for n in ("research", "plan", "execute", "review")))
        check("repair skipped: no hard errors", d["repair"]["ran"] is False and "no hard errors" in d["repair"]["reason"])
        check("result produced by executor fallback", out["result"]["content"].startswith("[template]"))
        # force a hard error: an executor whose fallback returns empty content
        ex = registry.get("executor")
        orig = ex.fallback

        async def empty(ctx):
            return {"content": "", "summary": "empty"}
        ex.fallback = empty
        try:
            out2 = await run_workflow(db, spec.get("plan_execute_verify"), t)
        finally:
            ex.fallback = orig
        d2 = {x["node"]: x for x in out2["decisions"]}
        check("repair ran when review found a hard error", d2["repair"]["ran"] is True)


async def test_run_task_now_through_lifecycle():
    await reset_db()
    from agentic_core.evaluators import deterministic as det
    register_kind("generic", workflow="direct", evaluators=[det.not_empty("content")])
    async with async_session() as db:
        t = Task(kind="generic", title="w", brief="hello", status="draft"); db.add(t); await db.commit(); tid = t.id
    r = await run_task_now(tid)
    check("task ran through the workflow + lifecycle and passed", r["attempted"] and r["success"] and r["outcome"]["verdict"] == "pass")
    async with async_session() as db:
        t = await db.get(Task, tid)
        check("task done with a result", t.status == "done" and t.result)
    r2 = await run_task_now(9999)
    check("missing task is a non-attempt", not r2["attempted"])


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
