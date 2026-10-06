"""Focused OFFLINE construction checks, not agent performance or a live smoke."""
import json
from copy import deepcopy
from feedback import CONDITIONS, decode_text, project


def main():
    n = 0
    for verdict in ("VERIFIED", "FAILED", "UNVERIFIABLE"):
        for observed in (None, {"text": "line one\nline two", "x": 42}):
            sample = {"tool_output": {"ok": True}, "handles": ["opaque-17"],
                      "verification": {"verdict": verdict, "expected": {"x": 0},
                                       "observed": observed, "error_code": None}}
            before = deepcopy(sample)
            arms = {c: project(condition=c, **sample) for c in CONDITIONS}
            assert sample == before
            assert set(arms["tool_only"]) == {"tool_output", "evidence_handles"}
            assert arms["binary"]["verification"] == {"verdict": verdict}
            assert decode_text(arms["text"]["verification_text"]) == arms["structured"]["verification"]
            assert all(a["evidence_handles"] == ["opaque-17"] for a in arms.values())
            assert all(a["tool_output"] == {"ok": True} for a in arms.values())
            arms["structured"]["tool_output"]["ok"] = False
            assert sample == before and arms["tool_only"]["tool_output"]["ok"] is True
            n += 1
    try:
        project(condition="unknown", **sample)
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown condition accepted")
    print(json.dumps({"surface": "offline_projection", "cases": n,
                      "status": "passed", "live_integration": False,
                      "agent_performance_measured": False}))


if __name__ == "__main__":
    main()
