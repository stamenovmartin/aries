"""Structured model output — validated against a shape, with ONE corrective
retry that shows the model its own error. Lifted from
backend/app/services/ai/structured.py."""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)
Schema = dict


def extract_json(text: str) -> dict | None:
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start:end + 1] if start != -1 and end > start else None
    if not candidate:
        return None
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def validate(obj, schema: Schema) -> list[str]:
    """Field spec: {"type": str|int|float|bool|list|dict|tuple, "required": bool,
    "enum": [...], "min_len": int}. Returns human-readable problems."""
    if not isinstance(obj, dict):
        return ["reply is not a JSON object"]
    problems = []
    for field, spec in schema.items():
        present = field in obj and obj[field] is not None
        if not present:
            if spec.get("required"):
                problems.append(f"missing required field '{field}'")
            continue
        value = obj[field]
        want = spec.get("type")
        if want is not None and not isinstance(value, want):
            problems.append(f"'{field}' must be {getattr(want, '__name__', want)}, got {type(value).__name__}")
            continue
        enum = spec.get("enum")
        if enum and value not in enum:
            problems.append(f"'{field}' must be one of {enum}, got '{value}'")
        min_len = spec.get("min_len")
        if min_len and hasattr(value, "__len__") and len(value) < min_len:
            problems.append(f"'{field}' is too short (min {min_len})")
    return problems


def parse_structured(text: str, schema: Schema):
    obj = extract_json(text)
    problems = validate(obj, schema)
    return (obj if not problems else None), problems


_CORRECTION = ("The previous reply was not in the required shape: {problems}. "
               "Return ONLY a valid JSON object satisfying the shape, no explanation, no ```.")


async def generate_structured(system_prompt: str, user_prompt: str, schema: Schema, *,
                              purpose: str = "structured", retries: int = 1) -> tuple[dict | None, list[str]]:
    from agentic_core.llm import providers, telemetry
    problems: list[str] = []
    prompt = user_prompt
    for attempt in range(retries + 1):
        try:
            raw = await providers.chat([{"role": "system", "content": system_prompt},
                                        {"role": "user", "content": prompt}], purpose=purpose)
        except Exception:
            logger.exception("Structured generation call failed (%s)", purpose)
            return None, ["the model call failed"]
        obj, problems = parse_structured(raw or "", schema)
        if obj is not None:
            return obj, []
        telemetry.record_schema_failure(purpose=purpose, problems=problems)
        if attempt >= retries:
            break
        prompt = f"{user_prompt}\n\n{_CORRECTION.format(problems='; '.join(problems))}"
    logger.warning("Structured output for %s failed schema: %s", purpose, problems)
    return None, problems
