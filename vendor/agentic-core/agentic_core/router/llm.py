"""LLM-based routing — the reserve for phrasings the rules do not know.
Lifted from backend/app/orchestration/router.py::route (the Codex branch)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def route_llm(task: str, agents: list[str]) -> tuple[str, str, float] | None:
    """(agent, why, confidence) or None when the model is unavailable/unusable."""
    from agentic_core.llm import providers
    from agentic_core.llm.structured import generate_structured
    if not providers.available():
        return None
    try:
        obj, problems = await generate_structured(
            "You route a task to exactly one specialist. Reply JSON: "
            '{"agent": "<name>", "why": "<one sentence>", "confidence": <0.0-1.0>} where agent is one of: '
            + ", ".join(agents),
            f"Task: {task}",
            {"agent": {"type": str, "required": True, "enum": list(agents)},
             "why": {"type": str, "required": True},
             "confidence": {"type": (int, float), "required": False}},
            purpose="router")
        if obj:
            conf = obj.get("confidence")
            try:
                conf = max(0.0, min(1.0, float(conf))) if conf is not None else 0.6
            except (TypeError, ValueError):
                conf = 0.6
            return obj["agent"], obj["why"], conf
    except Exception:
        logger.exception("LLM routing failed")
    return None
