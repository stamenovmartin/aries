from _harness import bootstrap, check, run_module
bootstrap("router")

import agentic_core.agents.builtin  # noqa: E402,F401
from agentic_core.router import rules  # noqa: E402
from agentic_core.router.router import route  # noqa: E402


async def test_rules_first_llm_fallback_planner():
    d = await route("Investigate why nginx is down")
    check("rule routes to researcher", d["agent"] == "researcher" and d["how"] == "rule")
    d = await route("Restart the nginx service")
    check("restart → executor and needs a human", d["agent"] == "executor" and d["needs_human"])
    d = await route("zzzz qqqq")
    check("unclear task → planner via fallback (template provider gives no route)", d["agent"] == "planner" and d["confidence"] < 0.5)
    d = await route("anything", kind="reviewer")
    check("a kind naming an agent wins", d["agent"] == "reviewer" and d["how"] == "kind")
    rules.add_rule(("rotate logs",), "executor", 0.9, first=True)
    d = await route("please rotate logs on host")
    check("added rule applies", d["agent"] == "executor")


def test_needs_human():
    check("delete needs human", rules.needs_human("delete the old backups", "executor")[0])
    check("internal work does not", not rules.needs_human("summarise the logs", "researcher")[0])
    check("agent that never ships alone needs human", rules.needs_human("x", "executor", ships_without_human=False)[0])


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
