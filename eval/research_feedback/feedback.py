"""Offline, pure feedback projection for a proposed controlled study.

No production imports, environment mutation, model calls or state changes. Callers
must provide genuinely separate tool output and verifier evidence; this function
cannot recover provenance from an already mixed production observation.
"""
from copy import deepcopy
import json

CONDITIONS = ("tool_only", "binary", "structured", "text")
VERDICTS = ("VERIFIED", "FAILED", "UNVERIFIABLE")
DETAIL_FIELDS = ("verdict", "expected", "observed", "error_code")


def project(*, condition, tool_output, handles, verification):
    if condition not in CONDITIONS:
        raise ValueError("Unknown feedback condition")
    if not isinstance(handles, list) or any(not isinstance(x, str) for x in handles):
        raise ValueError("Handles must be a list of opaque strings")
    if not isinstance(verification, dict) or set(verification) != set(DETAIL_FIELDS):
        raise ValueError("Supply exactly verdict, expected, observed and error_code")
    if verification["verdict"] not in VERDICTS:
        raise ValueError("Unknown verification verdict")
    # Reject unsupported/nonfinite data instead of silently changing the facts.
    json.dumps([tool_output, handles, verification], allow_nan=False)
    out = {"tool_output": deepcopy(tool_output), "evidence_handles": list(handles)}
    if condition == "binary":
        out["verification"] = {"verdict": verification["verdict"]}
    elif condition == "structured":
        out["verification"] = deepcopy(verification)
    elif condition == "text":
        # JSON-encoded values preserve exact types/content, including embedded
        # newlines. The surrounding representation is labeled lines, not an object.
        out["verification_text"] = "\n".join(
            f"{key}: {json.dumps(verification[key], ensure_ascii=False, allow_nan=False)}"
            for key in DETAIL_FIELDS)
    return out


def decode_text(text):
    """Content-equivalence helper for the labeled-text control; not a planner."""
    result = {}
    for line in text.splitlines():
        key, separator, value = line.partition(": ")
        if not separator or key not in DETAIL_FIELDS or key in result:
            raise ValueError("Invalid text packet")
        result[key] = json.loads(value)
    if set(result) != set(DETAIL_FIELDS):
        raise ValueError("Incomplete text packet")
    return result
