"""A workflow graph with a Director that routes it.
Lifted from backend/app/orchestration/graph.py.

* AgentNode — one agent with dependencies and a `gate(ctx) -> (run?, why)`.
* Director.plan — a dry decision: which nodes would run and why.
* Director.execute — runs the graph in dependency order, evaluating each gate
  against the LIVE context, threading outputs forward, recording every decision.
  A failed node does not crash the graph; it is recorded and dependents skip.

Two additions over the original, both opt-in and behaviour-preserving:
* `parallel=True` on execute() runs nodes that share no dependency edge at the
  same depth concurrently with asyncio.gather (the original is sequential and
  says so). Sequential remains the default.
* `on_decision` callback, so a run can persist decisions as they happen.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

RunFn = Callable[[dict], Awaitable[dict]]
GateFn = Callable[[dict], "tuple[bool, str]"]


@dataclass
class AgentNode:
    name: str
    run: RunFn
    label: str = ""
    depends_on: list[str] = field(default_factory=list)
    gate: GateFn | None = None


@dataclass
class Decision:
    node: str
    label: str
    ran: bool
    reason: str
    error: str | None = None

    def as_dict(self) -> dict:
        d = {"node": self.node, "label": self.label, "ran": self.ran, "reason": self.reason}
        if self.error:
            d["error"] = self.error
        return d


def _order(nodes: list[AgentNode]) -> list[AgentNode]:
    """Topological order; a missing/backward dependency is tolerated (treated as skip)."""
    by_name = {n.name: n for n in nodes}
    seen: set[str] = set()
    out: list[AgentNode] = []

    def visit(n: AgentNode, stack: set[str]):
        if n.name in seen or n.name in stack:
            return
        stack.add(n.name)
        for d in n.depends_on:
            if d in by_name:
                visit(by_name[d], stack)
        stack.discard(n.name)
        seen.add(n.name)
        out.append(n)

    for n in nodes:
        visit(n, set())
    return out


def _levels(nodes: list[AgentNode]) -> list[list[AgentNode]]:
    """Group a topological order into depth levels for parallel execution."""
    depth: dict[str, int] = {}
    levels: list[list[AgentNode]] = []
    for n in _order(nodes):
        d = 1 + max([depth.get(x, -1) for x in n.depends_on] or [-1])
        depth[n.name] = d
        while len(levels) <= d:
            levels.append([])
        levels[d].append(n)
    return levels


class Director:
    """Routes a graph of agents by evaluating each node's gate."""

    def plan(self, nodes: list[AgentNode], ctx: dict) -> list[Decision]:
        decisions: list[Decision] = []
        skipped: set[str] = set()
        for n in _order(nodes):
            dep_skipped = [d for d in n.depends_on if d in skipped]
            if dep_skipped:
                decisions.append(Decision(n.name, n.label or n.name, False,
                                          f"depends on skipped: {', '.join(dep_skipped)}"))
                skipped.add(n.name)
                continue
            run, why = n.gate(ctx) if n.gate else (True, "default")
            decisions.append(Decision(n.name, n.label or n.name, run, why))
            if not run:
                skipped.add(n.name)
        return decisions

    async def _run_node(self, n: AgentNode, ctx: dict, skipped: set[str],
                        decisions: list[Decision], on_decision) -> None:
        dep_skipped = [d for d in n.depends_on if d in skipped]
        if dep_skipped:
            d = Decision(n.name, n.label or n.name, False, f"depends on skipped: {', '.join(dep_skipped)}")
            decisions.append(d); skipped.add(n.name)
            if on_decision: await on_decision(d, ctx)
            return
        run, why = n.gate(ctx) if n.gate else (True, "default")
        if not run:
            d = Decision(n.name, n.label or n.name, False, why)
            decisions.append(d); skipped.add(n.name)
            if on_decision: await on_decision(d, ctx)
            return
        try:
            out = await n.run(ctx)
            if isinstance(out, dict):
                ctx.update(out)
            d = Decision(n.name, n.label or n.name, True, why)
        except Exception as e:
            d = Decision(n.name, n.label or n.name, False, f"failed: {type(e).__name__}", error=str(e)[:500])
            skipped.add(n.name)
        decisions.append(d)
        if on_decision:
            await on_decision(d, ctx)

    async def execute(self, nodes: list[AgentNode], ctx: dict, *, parallel: bool = False,
                      on_decision: Callable[[Decision, dict], Awaitable[None]] | None = None
                      ) -> tuple[dict, list[Decision]]:
        decisions: list[Decision] = []
        skipped: set[str] = set()
        if not parallel:
            for n in _order(nodes):
                await self._run_node(n, ctx, skipped, decisions, on_decision)
            return ctx, decisions
        for level in _levels(nodes):
            if len(level) == 1:
                await self._run_node(level[0], ctx, skipped, decisions, on_decision)
                continue
            # Nodes at one depth share no edge; each gets a snapshot and writes
            # are merged afterwards so two coroutines never mutate one dict.
            snapshots = [dict(ctx) for _ in level]
            await asyncio.gather(*[self._run_node(n, s, skipped, decisions, on_decision)
                                   for n, s in zip(level, snapshots)])
            for s in snapshots:
                for k, v in s.items():
                    if k not in ctx or ctx[k] != v:
                        ctx[k] = v
        return ctx, decisions
