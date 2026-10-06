"""What an agent is, declared once.

The marketing backend's agents were functions with a system prompt each
(research, strategy, copy, review, distill, chat, judge) and a roster table in
orchestration/router.py::SPECIALISTS saying what each reads/writes and whether
it may ship without a human. AgentSpec is those two things in one object:

  name, role, description
  system_prompt          the prompt (operator instructions + context digest are
                         appended by llm.providers.system_prompt at call time)
  input_schema           what `run` expects in ctx
  output_schema          the JSON shape the model must answer in (validated,
                         one corrective retry — llm/structured.py)
  tools                  tool names this agent may call
  permission             RBAC permission required to invoke it
  model / temperature    per-agent overrides (None = provider default)
  reads / writes         context keys — the Director threads them
  ships_without_human    False → its output always becomes a proposal
  termination            max_turns / stop_when — for the tool-calling loop
  fallback               deterministic function used when no provider is
                         reachable (the "template" path — every original agent
                         had one, so the pipeline never hard-fails)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from agentic_core.security.permissions import Permission

Fallback = Callable[[dict], Awaitable[dict]]


@dataclass
class Termination:
    max_turns: int = 1                  # 1 = single-shot; >1 = tool-calling loop
    stop_when: str | None = None        # a key the output must carry to stop (e.g. "final")
    max_tool_calls: int = 8


@dataclass
class AgentSpec:
    name: str
    role: str
    description: str
    system_prompt: str
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    permission: Permission = Permission.RUN_AGENT
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    ships_without_human: bool = True
    termination: Termination = field(default_factory=Termination)
    fallback: Fallback | None = None
    prompt_version: str = "v1"
    learn_scope: str | None = None      # LearnedRule scope injected into the prompt
    tags: list[str] = field(default_factory=list)

    def describe(self) -> dict:
        from agentic_core.llm.structured import Schema  # noqa: F401
        def _s(s):
            return {k: {**v, "type": getattr(v.get("type"), "__name__", str(v.get("type")))} for k, v in (s or {}).items()}
        return {"name": self.name, "role": self.role, "description": self.description,
                "system_prompt": self.system_prompt, "input_schema": _s(self.input_schema),
                "output_schema": _s(self.output_schema), "tools": self.tools,
                "permission": self.permission.value, "model": self.model, "temperature": self.temperature,
                "max_tokens": self.max_tokens, "reads": self.reads, "writes": self.writes,
                "ships_without_human": self.ships_without_human,
                "termination": {"max_turns": self.termination.max_turns, "stop_when": self.termination.stop_when,
                                "max_tool_calls": self.termination.max_tool_calls},
                "has_fallback": self.fallback is not None, "prompt_version": self.prompt_version,
                "learn_scope": self.learn_scope, "tags": self.tags}
