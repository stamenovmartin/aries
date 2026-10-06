"""Declarative workflows: a named list of nodes with gates and dependencies,
executed through the Director. Lifted from backend/app/orchestration/
{campaign,pipeline}.py, with the nodes made data instead of code:

    WorkflowSpec("plan_execute_verify", nodes=[
        NodeSpec("research", agent="researcher", gate="has_brief"),
        NodeSpec("plan", agent="planner", depends_on=["research"]),
        NodeSpec("execute", agent="executor", depends_on=["plan"]),
        NodeSpec("review", evaluators=[...], depends_on=["execute"]),
        NodeSpec("repair", agent="repairer", depends_on=["review"], gate="review_found_errors"),
    ])

A node runs an agent (by name), a tool (by name), or a Python callable. Gates
are named predicates over the live context, registered with `gate()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

GateFn = Callable[[dict], tuple[bool, str]]
_GATES: dict[str, GateFn] = {}


def gate(name: str):
    def deco(fn: GateFn):
        _GATES[name] = fn
        return fn
    return deco


def get_gate(name: str) -> GateFn:
    if name not in _GATES:
        raise KeyError(f"unknown gate '{name}'")
    return _GATES[name]


@gate("always")
def _always(ctx):
    return True, "default"


@gate("has_brief")
def _has_brief(ctx):
    ok = bool(ctx.get("brief"))
    return ok, "has a brief" if ok else "no brief"


@gate("has_facts")
def _has_facts(ctx):
    ok = bool(ctx.get("facts") or ctx.get("research"))
    return ok, "facts present" if ok else "no facts gathered"


@gate("review_found_errors")
def _review_found_errors(ctx):
    ok = bool(ctx.get("review_hard_errors"))
    return ok, "review found hard errors — repair" if ok else "no hard errors to repair"


@gate("caller_allows")
def _caller_allows(ctx):
    """Explicit caller flags always win over the Director's defaults."""
    node = ctx.get("_node")
    flags = ctx.get("caller") or {}
    ok = flags.get(f"run_{node}", True)
    return ok, "default" if ok else "disabled by the caller"


@dataclass
class NodeSpec:
    name: str
    label: str = ""
    agent: str | None = None
    tool: str | None = None
    fn: Callable[[dict], Awaitable[dict]] | None = None
    evaluators: list = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    gate: str = "always"
    payload_from: str | None = None       # ctx key whose value is the tool payload
    writes: str | None = None             # ctx key the node's output lands in (default: node name)


@dataclass
class WorkflowSpec:
    name: str
    nodes: list[NodeSpec]
    description: str = ""
    parallel: bool = False
    lifecycle: bool = True                # wrap the whole run in the TASK→…→ESCALATE lifecycle

    def describe(self) -> dict:
        return {"name": self.name, "description": self.description, "parallel": self.parallel,
                "nodes": [{"name": n.name, "label": n.label or n.name, "agent": n.agent, "tool": n.tool,
                           "fn": getattr(n.fn, "__name__", None) if n.fn else None,
                           "evaluators": [getattr(e, "name", str(e)) for e in n.evaluators],
                           "depends_on": n.depends_on, "gate": n.gate} for n in self.nodes]}


_WORKFLOWS: dict[str, WorkflowSpec] = {}


def register(spec: WorkflowSpec, *, replace: bool = False) -> WorkflowSpec:
    if spec.name in _WORKFLOWS and not replace:
        raise ValueError(f"workflow '{spec.name}' already registered")
    _WORKFLOWS[spec.name] = spec
    return spec


def get(name: str) -> WorkflowSpec | None:
    return _WORKFLOWS.get(name)


def all_workflows() -> list[WorkflowSpec]:
    return [_WORKFLOWS[k] for k in sorted(_WORKFLOWS)]
