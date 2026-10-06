"""One task → one agent + whether a human must sign off + a written trace.
Lifted from backend/app/orchestration/router.py.

Order: rules first (deterministic, cheap, always available) → LLM when the
rules say nothing → fallback to the planner. A confidence below
`MIN_CONFIDENCE` is not trusted: the task goes to the planner AND the
decision says so. Every decision is appended to the director's task-log in
the context layer so the routing is inspectable after the fact.
"""
from __future__ import annotations

import logging

from agentic_core.router.llm import route_llm
from agentic_core.router.rules import DEFAULT_AGENT, needs_human, route_rules

logger = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.5


def _agents() -> dict:
    from agentic_core.agents import registry
    return {a.name: a for a in registry.all_agents()}


async def route(task: str, *, kind: str | None = None, allowed: list[str] | None = None) -> dict:
    agents = _agents()
    names = [n for n in agents if (allowed is None or n in allowed) and n not in ("router",)]
    if not names:
        names = [DEFAULT_AGENT]
    agent, how, conf = None, "", 0.0

    # 0. a task kind that names its agent directly ("linux.repair" → executor of that kind)
    if kind and kind in agents:
        agent, how, conf = kind, "kind", 1.0
    # 1. rules
    if agent is None:
        hit = route_rules(task)
        if hit and hit[0] in names:
            agent, conf, how = hit[0], hit[1], "rule"
    # 2. LLM
    if agent is None:
        hit = await route_llm(task, names)
        if hit:
            agent, why, conf = hit
            how = f"llm: {why}"
    # 3. fallback
    if agent is None or agent not in names:
        agent, how, conf = (DEFAULT_AGENT if DEFAULT_AGENT in names else names[0]), "fallback: unclear task — the planner breaks it down", 0.3
    low_confidence = conf < MIN_CONFIDENCE
    if low_confidence and agent != DEFAULT_AGENT and DEFAULT_AGENT in names:
        how = f"{how} (confidence {conf:.2f} < {MIN_CONFIDENCE} → planner)"
        agent = DEFAULT_AGENT

    spec = agents.get(agent)
    human, why_human = needs_human(task, agent, ships_without_human=(spec.ships_without_human if spec else True))
    decision = {"task": task[:300], "agent": agent, "role": spec.role if spec else None, "how": how,
                "confidence": round(conf, 2), "low_confidence": low_confidence,
                "needs_human": human, "why_human": why_human}
    try:
        from agentic_core.memory import context_layer
        context_layer.append_line("director", "task-log",
                                  f"{task[:120]} → {agent} [{how[:60]}]" + (" (needs human)" if human else ""))
    except Exception:
        logger.exception("Director task-log write failed")
    return decision
