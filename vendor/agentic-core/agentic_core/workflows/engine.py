"""Run a WorkflowSpec through the Director, inside the lifecycle.

Each NodeSpec becomes an AgentNode whose `run` is one of:
  agent  → agents.runtime.run_agent(spec, ctx) ; output merged under node.writes
  tool   → tools.calling.call_tool(db, name, ctx[payload_from])
  fn     → the callable
  evaluators → evaluators.base.evaluate_all over ctx["result"]; sets
               ctx["review"], ctx["review_hard_errors"], ctx["issues"]
Every Director decision is persisted on the TaskRun and traced as an AgentStep.
"""
from __future__ import annotations

import json
import logging

from agentic_core.agents import registry as agent_registry
from agentic_core.agents.runtime import run_agent
from agentic_core.evaluators.base import evaluate_all
from agentic_core.observability import trace
from agentic_core.orchestrator.graph import AgentNode, Director
from agentic_core.workflows.spec import NodeSpec, WorkflowSpec, get_gate

logger = logging.getLogger(__name__)


def _make_run(db, node: NodeSpec, task, run_id_ref: dict):
    async def _run(ctx: dict) -> dict:
        key = node.writes or node.name
        if node.agent:
            spec = agent_registry.get(node.agent)
            if spec is None:
                raise RuntimeError(f"unknown agent '{node.agent}'")
            res = await run_agent(spec, ctx, db=db, task_id=task.id if task else None)
            out = res["output"] if isinstance(res["output"], dict) else {"content": res["output"]}
            if run_id_ref.get("id"):
                await trace.record(db, run_id_ref["id"], node.agent, label=node.label or node.name,
                                   summary=(out.get("summary") or out.get("content") or json.dumps(out, default=str))[:300],
                                   detail=out, ok=res["ok"], confidence=out.get("confidence"),
                                   evidence={"provider": res["provider"], "fallback": res["fallback"],
                                             "tool_calls": res["tool_calls"], "problems": res["problems"]},
                                   duration_ms=res["duration_ms"])
            merged = {key: out}
            if key == "result" or node.name == "execute":
                merged["result"] = out
            if node.agent == "planner":
                merged["plan"] = out
            if node.agent == "researcher":
                merged["facts"] = (ctx.get("facts") or []) + list(out.get("facts") or [])
            return merged
        if node.tool:
            from agentic_core.tools.calling import call_tool
            payload = ctx.get(node.payload_from) if node.payload_from else ctx.get("payload") or {}
            res = await call_tool(db, node.tool, payload or {}, ctx=ctx, task_id=task.id if task else None)
            if run_id_ref.get("id"):
                await trace.record(db, run_id_ref["id"], f"tool:{node.tool}", label=node.label or node.name,
                                   summary=str(res.get("details") or "")[:300], detail=res, ok=bool(res.get("success")),
                                   duration_ms=res.get("duration_ms"))
            return {key: res, "result": res}
        if node.evaluators:
            v = await evaluate_all(node.evaluators, ctx.get("result") or {}, task, ctx)
            if run_id_ref.get("id"):
                await trace.record(db, run_id_ref["id"], "reviewer", label=node.label or node.name,
                                   summary=v.summary(), detail=v.as_dict(), ok=v.passed, confidence=v.score)
            return {key: v.as_dict(), "review_hard_errors": bool(v.hard_errors), "issues": v.issues,
                    "corrective_note": v.corrective_note() if v.hard_errors else None}
        if node.fn:
            out = await node.fn(ctx)
            return out if isinstance(out, dict) else {key: out}
        return {}
    return _run


def to_nodes(db, wf: WorkflowSpec, task, run_id_ref: dict) -> list[AgentNode]:
    nodes = []
    for n in wf.nodes:
        g = get_gate(n.gate)

        def _gate(ctx, _g=g, _name=n.name):
            ctx["_node"] = _name
            return _g(ctx)
        nodes.append(AgentNode(n.name, _make_run(db, n, task, run_id_ref), n.label or n.name,
                               depends_on=list(n.depends_on), gate=_gate))
    return nodes


async def run_workflow(db, wf: WorkflowSpec, task, ctx: dict | None = None, *, run_id: int | None = None) -> dict:
    """Execute the graph once. Returns the final ctx (+ 'decisions')."""
    ctx = dict(ctx or {})
    ctx.setdefault("brief", getattr(task, "brief", None) or getattr(task, "title", None))
    ctx.setdefault("workflow", wf.name)
    run_id_ref = {"id": run_id}
    nodes = to_nodes(db, wf, task, run_id_ref)
    ctx, decisions = await Director().execute(nodes, ctx, parallel=wf.parallel)
    ctx["decisions"] = [d.as_dict() for d in decisions]
    return ctx


def as_executor(wf: WorkflowSpec):
    """Wrap a workflow as a lifecycle executor: executor(task, ctx) -> result."""
    async def _exec(task, ctx):
        db = ctx["db"]
        out = await run_workflow(db, wf, task, ctx, run_id=ctx.get("run_id"))
        ctx["decisions"] = out.get("decisions")
        for k in ("plan", "facts", "research", "review", "issues"):
            if k in out:
                ctx[k] = out[k]
        result = out.get("result") or {}
        if not isinstance(result, dict):
            result = {"content": result}
        result.setdefault("success", True)
        result["decisions"] = out.get("decisions")
        return result
    return _exec
