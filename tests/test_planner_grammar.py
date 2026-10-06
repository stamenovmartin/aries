"""The planner's schema must be something the local grammar compiler will accept.

Why this exists. On 2026-09-30 `aries/analytics/` measured that
`local/qwen2.5:7b/workspace.m14-planner` had succeeded **0 times out of 18**, while
`cloud/cli-default` was 77 of 77. ARIES was advertised as local-first and its
planning brain was 0% local, silently falling through to the cloud — 1,397,433
input tokens on 77 calls.

The cause was not the model. Every local call returned HTTP 503 "Local inference
failed", because the generated schema contained forms the installed grammar
compiler refuses. Measured one keyword at a time against the live gateway:

    {"type": "string"}                                REJECTED   <- unbounded
    {"type": "string", "title": "Value"}              REJECTED
    {"type": "string", "maxLength": 2000}             REJECTED   <- too large
    {"type": "string", "maxLength": 80}               OK
    {"type": "string", "minLength": 1, "maxLength": 2048}   OK
    {"type": "string", "pattern": "^[a-f0-9]{64}$"}   REJECTED
    integer, integer with bounds, boolean, enum, array of string   OK

The planner schema carried `reason` and `summary` as bare `{"type": "string"}`,
plus a `value` at `maxLength: 2000` and an `expected_sha256` with a `pattern`. Any
one of those alone kills the whole grammar. After bounding them the same request
went **503 → 200**.

These checks are static on purpose: they hold the shape without needing the model
running, so they fail in CI rather than silently in production. They are the reason
a capability added later — with a `pattern`, or an unbounded string — cannot take
local planning down again without someone noticing.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-planner-grammar')
from aries.workspace import agent_planner as planner

FORBIDDEN = ("pattern", "title", "format", "additionalProperties_schema",
             "anyOf", "oneOf", "allOf", "$ref", "const")


def walk(node, path="$"):
    """Every SCHEMA mapping, with the path that reached it.

    The keys inside a `properties` map are FIELD NAMES, not schema keywords, and
    some capabilities have fields literally called `title` and `pattern` —
    `notification.send` takes a `title`. An earlier version of this walker treated
    those as the refused keywords and failed on a schema that was correct, which is
    a good reminder that a test can be the thing that is wrong.
    """
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                # Descend into each field's schema, never into the name itself.
                for field, sub in value.items():
                    yield from walk(sub, f"{path}.properties[{field}]")
                continue
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk(value, f"{path}[{i}]")


async def test_no_string_in_the_planner_schema_is_unbounded():
    """An unbounded string is the specific form that returned 503 every time."""
    schema = planner.generation_schema()
    loose = [p for p, n in walk(schema)
             if n.get("type") == "string" and "enum" not in n and "maxLength" not in n]
    check("every string is bounded, or an enum: " + (", ".join(loose) or "all bounded"), not loose)
    big = [f"{p}={n['maxLength']}" for p, n in walk(schema)
           if n.get("type") == "string" and n.get("maxLength", 0) > planner.GRAMMAR_STRING_MAX]
    check(f"no bound exceeds GRAMMAR_STRING_MAX={planner.GRAMMAR_STRING_MAX}: "
          + (", ".join(big) or "none"), not big)


async def test_no_keyword_the_compiler_refuses():
    schema = planner.generation_schema()
    found = [f"{p}.{k}" for p, n in walk(schema) for k in n if k in FORBIDDEN]
    check("no refused keyword survives into the grammar: " + (", ".join(found) or "none"), not found)


async def test_grammar_safe_neutralises_the_forms_that_broke_it():
    """The four shapes measured as rejected, each one made acceptable."""
    cases = {
        "bare string": {"type": "string"},
        "titled": {"type": "string", "title": "Value"},
        "oversized": {"type": "string", "maxLength": 2000},
        "patterned": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    }
    for label, original in cases.items():
        safe = planner.grammar_safe(original)
        check(f"{label}: bounded", safe.get("maxLength", 0) <= planner.GRAMMAR_STRING_MAX
              and safe.get("maxLength") is not None)
        check(f"{label}: no refused keyword", not any(k in safe for k in FORBIDDEN))
    # Forms that were measured as acceptable must survive untouched in substance.
    check("an enum keeps its choices",
          planner.grammar_safe({"type": "string", "enum": ["a", "b"]})["enum"] == ["a", "b"])
    check("an integer keeps its bounds",
          planner.grammar_safe({"type": "integer", "minimum": 1, "maximum": 9})["maximum"] == 9)
    check("a boolean is left alone", planner.grammar_safe({"type": "boolean"})["type"] == "boolean")
    inner = planner.grammar_safe({"type": "array", "items": {"type": "string"}})["items"]
    check("an array's items are bounded too", inner.get("maxLength") is not None)
    check("a non-dict is not a crash", planner.grammar_safe(None).get("type") == "string")


async def test_the_planner_can_still_name_every_capability_it_may_use():
    """Bounding strings must not have narrowed what the planner is allowed to do —
    the capability list is an enum and enums were measured as acceptable."""
    from aries.workspace.registry import registry
    schema = planner.generation_schema()
    allowed = {c["name"] for c in registry.describe_allowed()}
    offered = set(schema["properties"]["capability"]["enum"])
    check(f"every allowed capability is offered ({len(offered)} of {len(allowed)})", offered == allowed)
    actions = set(schema["properties"]["action"]["enum"])
    check("the action verbs survive", {"execute", "ask_approval"} <= actions)
    narrowed = planner.generation_schema(allow_finish=False, allow_fail=False)
    check("finish and fail can still be withheld",
          set(narrowed["properties"]["action"]["enum"]) == {"execute", "ask_approval"})


async def test_the_schema_stays_small_enough_to_expand():
    """A grammar is expanded, not merely parsed: `maxLength: 2000` was refused for
    being too large to expand, so total size is a real constraint, not tidiness."""
    import json
    size = len(json.dumps(planner.generation_schema()))
    check(f"schema is {size} chars, under 16000", size < 16000)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
