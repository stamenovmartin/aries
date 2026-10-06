from _harness import bootstrap, check, run_module
bootstrap("evaluators")

import re  # noqa: E402

from agentic_core.evaluators import deterministic as det  # noqa: E402
from agentic_core.evaluators.base import evaluate_all  # noqa: E402
from agentic_core.evaluators.gate import gate_and_repair  # noqa: E402
from agentic_core.evaluators.scorers import default_suite  # noqa: E402

PRICES = lambda t: [int(x.replace(".", "")) for x in re.findall(r"(\d{1,3}(?:\.\d{3})+|\d{4,6})\s*(?:den|EUR)", t)]  # noqa: E731


async def test_hard_error_caps_score():
    evs = [det.not_empty("content"), det.grounded_facts(extract=PRICES, facts_key="facts", label="price"),
           det.length(soft=100, field="content")]
    good = await evaluate_all(evs, {"content": "Great PC for 48.990 den. Order now."}, None, {"facts": [48990]})
    check("grounded, non-empty passes", good.passed and good.score >= 0.7)
    bad = await evaluate_all(evs, {"content": "Great PC for 47.990 den."}, None, {"facts": [48990]})
    check("ungrounded claim is a hard error", not bad.passed and bad.hard_errors)
    check("hard error caps the score at 0.4", bad.score <= 0.4)
    check("corrective note names the problem", "price" in bad.corrective_note())


async def test_judge_adjusts_but_never_overrides():
    async def judge(result, task, ctx):
        return {"scores": {"correct": 1.0, "clear": 1.0}, "note": "great", "suggestions": ["tighten"]}
    evs = [det.grounded_facts(extract=PRICES, facts_key="facts")]
    v = await evaluate_all(evs, {"content": "Only 9.999 den"}, None, {"facts": [1]}, judge=judge)
    check("a perfect judge cannot rescue a hard error", not v.passed and v.score <= 0.4)
    check("judge suggestion attached as 'suggest'", any(i["severity"] == "suggest" for i in v.issues))
    ok = await evaluate_all([det.not_empty("content")], {"content": "fine"}, None, {}, judge=judge)
    check("judge raises a clean score", ok.passed and "judge_correct" in ok.scores)


async def test_expected_state_replans():
    async def pred(result, task, ctx):
        return (result.get("state") == "active", f"state is {result.get('state')}")
    v = await evaluate_all([det.expected_state("service active", pred)], {"state": "inactive"}, None, {})
    check("failed expectation → needs_replan", (not v.passed) and v.needs_replan)


def test_scorer_suite():
    suite = default_suite(subject_key="subject", extract=PRICES, forbidden=[r"free shipping"])
    facts = {"subject": "RTX 4070 gaming PC", "allowed": [48990]}
    good = suite.score_all("RTX 4070 gaming PC — smooth 1440p for 48.990 den. Order today and pick it up in store.", facts)
    check("honest specific copy passes", good["passed"])
    wrong = suite.score_all("RTX 4070 gaming PC for 47.990 den. Order now!", facts)
    check("wrong price tanks 'grounded' and caps overall", wrong["scores"]["grounded"] < 0.5 and wrong["overall"] <= 0.4 and not wrong["passed"])
    dashes = suite.score_all("- RTX 4070\n- 32GB\n- 1TB", facts)
    check("list-only loses prose points", dashes["scores"]["prose"] < 0.5)


async def test_gate_and_repair_adopts_only_improvements():
    items = [{"name": "a", "content": ""}, {"name": "b", "content": "ok text"}]

    def hard(it):
        return [] if it["content"].strip() else [{"severity": "error", "code": "empty", "message": "empty"}]
    attempts = {"n": 0}

    async def regen(it, prior, issues):
        attempts["n"] += 1
        return "" if attempts["n"] == 1 else "repaired"
    out = await gate_and_repair(items, hard_errors=hard, regenerate=regen, rounds=2)
    check("only the failing item attempted", out["attempted"] == ["a", "a"] or out["attempted"][0] == "a")
    check("empty regen NOT adopted, later one adopted", items[0]["content"] == "repaired" and "a" in out["repaired"])
    check("nothing remains", out["remaining"] == {})


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
