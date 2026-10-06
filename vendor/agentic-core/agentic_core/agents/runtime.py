"""Running one agent: prompt → provider → parse → validate → (tool loop) → out.

This is the shape every original agent shared (research.py, strategy.py,
learning.py, chat_agent.py): build a user prompt from the context, call
`complete`, extract JSON, validate against a schema, fall back to a
deterministic result when the model is unreachable or answers unusably, and
record a schema failure when it does. Plus the tool-calling loop the chat
agent had in `workspace.run_action` — bounded by Termination.
"""
from __future__ import annotations

import json
import logging
import time

from agentic_core.agents.base import AgentSpec
from agentic_core.llm import providers, telemetry
from agentic_core.llm.structured import extract_json, validate
from agentic_core.observability import metrics
from agentic_core.observability.logging_setup import log_context
from agentic_core.tools import registry as tool_registry

logger = logging.getLogger(__name__)


def build_user_prompt(spec: AgentSpec, ctx: dict, *, learned: str | None = None) -> str:
    parts = []
    for key in spec.reads:
        if ctx.get(key) is not None:
            v = ctx[key]
            parts.append(f"{key.upper()}:\n{v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)[:4000]}")
    if ctx.get("brief"):
        parts.append(f"TASK:\n{ctx['brief']}")
    if ctx.get("corrective_note"):
        parts.append(ctx["corrective_note"])
    if learned:
        parts.append(learned)
    if spec.tools and spec.termination.max_turns > 1:
        parts.append("TOOLS you may call (answer with {\"tool\": name, \"payload\": {...}} to call one, "
                     "or with your final JSON when done):\n"
                     + json.dumps(tool_registry.for_model(spec.tools), ensure_ascii=False))
    if spec.output_schema:
        shape = ", ".join(f'"{k}": <{getattr(v.get("type"), "__name__", "any")}>' for k, v in spec.output_schema.items())
        parts.append(f"Answer ONLY with a JSON object of the shape {{{shape}}}.")
    return "\n\n".join(parts) or "Proceed."


async def run_agent(spec: AgentSpec, ctx: dict, *, db=None, task_id: int | None = None) -> dict:
    """Returns {"ok", "output", "provider", "problems", "tool_calls", "fallback"}."""
    t0 = time.monotonic()
    with log_context(agent=spec.name, task_id=task_id):
        learned = None
        if spec.learn_scope and db is not None:
            try:
                from agentic_core.memory.feedback import load_rules_context
                learned = await load_rules_context(db, spec.learn_scope)
            except Exception:
                logger.exception("Learned rules unavailable for %s", spec.name)
        system = providers.system_prompt(spec.system_prompt)
        user = build_user_prompt(spec, ctx, learned=learned)
        tool_calls: list[dict] = []
        output, problems, provider = None, [], "template"

        if providers.available():
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            for turn in range(max(1, spec.termination.max_turns)):
                try:
                    raw = await providers.chat(messages, purpose=spec.name)
                except Exception as e:
                    problems = [f"provider failed: {e}"]
                    break
                obj = extract_json(raw) if spec.output_schema or spec.tools else None
                # A tool call?
                if obj and obj.get("tool") and spec.tools and db is not None:
                    if obj["tool"] not in spec.tools:
                        messages.append({"role": "user", "content": f"Tool '{obj['tool']}' is not allowed. Allowed: {spec.tools}."})
                        continue
                    if len(tool_calls) >= spec.termination.max_tool_calls:
                        problems = ["too many tool calls"]; break
                    from agentic_core.tools.calling import call_tool
                    res = await call_tool(db, obj["tool"], obj.get("payload") or {}, ctx=ctx, task_id=task_id)
                    tool_calls.append({"tool": obj["tool"], "payload": obj.get("payload"), "result": res})
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": "TOOL RESULT:\n" + json.dumps(res, default=str)[:6000]})
                    continue
                if spec.output_schema:
                    problems = validate(obj, spec.output_schema)
                    if problems:
                        telemetry.record_schema_failure(purpose=spec.name, problems=problems)
                        if turn == 0 and spec.termination.max_turns == 1:
                            # one corrective retry, as structured.py does
                            messages.append({"role": "assistant", "content": raw})
                            messages.append({"role": "user", "content": "That was not the required shape: "
                                             + "; ".join(problems) + ". Return ONLY the JSON object."})
                            try:
                                raw = await providers.chat(messages, purpose=spec.name)
                                obj = extract_json(raw); problems = validate(obj, spec.output_schema)
                            except Exception as e:
                                problems = [f"provider failed: {e}"]
                        if problems:
                            break
                    output = obj
                else:
                    output = {"content": (raw or "").strip()}
                if spec.termination.stop_when and isinstance(output, dict) and not output.get(spec.termination.stop_when):
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": f"Continue until '{spec.termination.stop_when}' is set."})
                    continue
                break
            provider = providers.describe()["provider"]

        fallback_used = False
        if output is None:
            if providers.strict():
                raise providers.AIGenerationError(f"{spec.name}: {'; '.join(problems) or 'no usable output'}")
            if spec.fallback is not None:
                output = await spec.fallback(ctx)
                fallback_used, provider = True, "template"
            else:
                output = {"content": "", "note": "no provider and no fallback"}
        ms = int((time.monotonic() - t0) * 1000)
        metrics.record_ai_generation(provider, spec.name, ms, output is not None)
        return {"ok": output is not None and not (spec.output_schema and validate(output, spec.output_schema) and not fallback_used),
                "output": output, "provider": provider, "problems": problems, "tool_calls": tool_calls,
                "fallback": fallback_used, "duration_ms": ms, "prompt_version": spec.prompt_version}
