"""Tool definitions: what a tool is, what it may do, and how risky it is.

The marketing backend had two registries this merges: `connectors/` (a
capability-declaring interface per channel, routed by a registry) and
`agent/workspace.py::ACTIONS` (named actions the chat could call, each routed
to the same handler the dashboard used). A Tool here is:

  name, description, input_schema, output_schema — for the model and the API
  permission        — the RBAC permission a caller must hold
  risk              — low (read) | medium (reversible write) | high (irreversible)
  side_effect       — False = safe to call any time; True = goes through the
                      dry-run / live-tools / policy / idempotency gates
  requires_approval — always needs a human even when live
  capabilities()    — what this instance can do RIGHT NOW (credentials present,
                      binary installed) — read, not assumed
  run(payload, ctx) — the implementation; returns {success, details, ...}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from agentic_core.security.permissions import Permission

RunFn = Callable[[dict, dict], Awaitable[dict]]


class NotSupported(RuntimeError):
    def __init__(self, tool: str, operation: str):
        super().__init__(f"{tool} does not support '{operation}'.")
        self.tool, self.operation = tool, operation


@dataclass
class ToolSpec:
    name: str
    description: str
    run: RunFn
    input_schema: dict = field(default_factory=dict)      # {field: {"type": str, "required": bool, "enum": [...]}}
    output_schema: dict = field(default_factory=dict)
    permission: Permission = Permission.RUN_AGENT
    risk: str = "low"                                      # low | medium | high
    side_effect: bool = False
    requires_approval: bool = False
    idempotent: bool = True                                # False → every call is a new operation
    timeout_s: float | None = None
    capabilities: Callable[[], dict] = field(default_factory=lambda: (lambda: {"available": True}))
    tags: list[str] = field(default_factory=list)

    def describe(self) -> dict:
        caps = {}
        try:
            caps = self.capabilities() or {}
        except Exception as e:
            caps = {"available": False, "reason": f"{type(e).__name__}: {e}"}
        return {"name": self.name, "description": self.description, "input_schema": _schema(self.input_schema),
                "output_schema": _schema(self.output_schema), "permission": self.permission.value,
                "risk": self.risk, "side_effect": self.side_effect, "requires_approval": self.requires_approval,
                "idempotent": self.idempotent, "timeout_s": self.timeout_s, "capabilities": caps, "tags": self.tags}


def _schema(s: dict) -> dict:
    out = {}
    for k, v in (s or {}).items():
        t = v.get("type")
        out[k] = {**v, "type": getattr(t, "__name__", str(t)) if t is not None else None}
    return out


def validate_payload(spec: ToolSpec, payload: dict) -> list[str]:
    from agentic_core.llm.structured import validate
    return validate(payload if isinstance(payload, dict) else None, spec.input_schema)
