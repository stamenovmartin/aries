"""The roster. Lifted from backend/app/orchestration/router.py::SPECIALISTS +
services/agent/trace.py::AGENTS, as a registry of AgentSpec."""
from __future__ import annotations

from agentic_core.agents.base import AgentSpec

_AGENTS: dict[str, AgentSpec] = {}


def register(spec: AgentSpec, *, replace: bool = False) -> AgentSpec:
    if spec.name in _AGENTS and not replace:
        raise ValueError(f"agent '{spec.name}' is already registered")
    _AGENTS[spec.name] = spec
    return spec


def get(name: str) -> AgentSpec | None:
    return _AGENTS.get(name)


def all_agents() -> list[AgentSpec]:
    return [_AGENTS[k] for k in sorted(_AGENTS)]


def describe_all() -> list[dict]:
    return [a.describe() for a in all_agents()]


def clear() -> None:
    _AGENTS.clear()
