"""One place that knows every tool. Lifted from the pattern in
backend/app/connectors/registry.py + compilers/registry.py: adding a tool is
adding a registration here and nothing else — the call path, the capability
endpoint and the tests all read from this map."""
from __future__ import annotations

from agentic_core.tools.base import ToolSpec

_TOOLS: dict[str, ToolSpec] = {}


def register(spec: ToolSpec, *, replace: bool = False) -> ToolSpec:
    if spec.name in _TOOLS and not replace:
        raise ValueError(f"tool '{spec.name}' is already registered")
    _TOOLS[spec.name] = spec
    return spec


def tool(name: str, description: str, **kw):
    """Decorator: @tool("fs.read", "Read a file", risk="low") on an async fn(payload, ctx)."""
    def deco(fn):
        register(ToolSpec(name=name, description=description, run=fn, **kw))
        return fn
    return deco


def get(name: str) -> ToolSpec | None:
    return _TOOLS.get(name)


def all_tools() -> list[ToolSpec]:
    return [_TOOLS[k] for k in sorted(_TOOLS)]


def describe_all() -> list[dict]:
    return [t.describe() for t in all_tools()]


def for_model(names: list[str] | None = None) -> list[dict]:
    """The compact tool list an agent prompt carries."""
    out = []
    for t in all_tools():
        if names and t.name not in names:
            continue
        out.append({"name": t.name, "description": t.description, "input": _short(t.input_schema),
                    "risk": t.risk, "side_effect": t.side_effect})
    return out


def _short(schema: dict) -> dict:
    return {k: (getattr(v.get("type"), "__name__", "any") + ("" if v.get("required") else "?")) for k, v in (schema or {}).items()}


def clear() -> None:
    _TOOLS.clear()
