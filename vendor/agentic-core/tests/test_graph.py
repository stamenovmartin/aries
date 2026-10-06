"""The Director routes; it does not run a fixed sequence."""
from _harness import bootstrap, check, run_module
bootstrap("graph")

from agentic_core.orchestrator.graph import AgentNode, Director  # noqa: E402


async def test_engine():
    order = []

    def named(name):
        async def _r(ctx):
            order.append(name); return {f"{name}_done": True}
        return _r

    async def review(ctx):
        order.append("review"); return {"review_hard_errors": True}
    nodes = [
        AgentNode("research", named("research"), "R"),
        AgentNode("competitor", named("competitor"), "C", gate=lambda ctx: (False, "no subject")),
        AgentNode("strategy", named("strategy"), "S", depends_on=["research"]),
        AgentNode("copy", named("copy"), "W", depends_on=["strategy", "competitor"]),
        AgentNode("review", review, "Q", depends_on=["copy"]),
        AgentNode("repair", named("repair"), "F", depends_on=["review"],
                  gate=lambda ctx: (bool(ctx.get("review_hard_errors")), "errors?")),
    ]
    ctx, decisions = await Director().execute(nodes, {})
    ran = {d.node: d.ran for d in decisions}
    check("dependency before dependent", order.index("research") < order.index("strategy"))
    check("false gate skips", ran["competitor"] is False)
    check("skipped dependency propagates", ran["copy"] is False and "copy" not in order)
    check("repair skipped because review skipped", ran["repair"] is False)
    plan = Director().plan(nodes, {})
    check("plan() is a dry run with the same shape", [d.node for d in plan] == [d.node for d in decisions])


async def test_dynamic_repair_gate():
    async def go(errs):
        hit = {"v": False}

        async def review(ctx):
            return {"review_hard_errors": errs}

        async def repair(ctx):
            hit["v"] = True; return {}
        await Director().execute([AgentNode("review", review), AgentNode("repair", repair, depends_on=["review"],
                                  gate=lambda c: (bool(c.get("review_hard_errors")), "?"))], {})
        return hit["v"]
    check("repair runs when review found errors", await go(True) is True)
    check("repair does NOT run when review clean", await go(False) is False)


async def test_failed_node_does_not_crash_graph():
    async def boom(ctx):
        raise RuntimeError("kaput")

    async def after(ctx):
        return {"after": True}
    ctx, dec = await Director().execute([AgentNode("a", boom), AgentNode("b", after, depends_on=["a"]),
                                         AgentNode("c", after)], {})
    d = {x.node: x for x in dec}
    check("failed node recorded with error", d["a"].ran is False and "kaput" in (d["a"].error or ""))
    check("dependent skipped, independent ran", d["b"].ran is False and d["c"].ran is True)


async def test_parallel_levels():
    import asyncio
    t = []

    def slow(name):
        async def _r(ctx):
            t.append((name, "start")); await asyncio.sleep(0.05); t.append((name, "end")); return {name: 1}
        return _r
    nodes = [AgentNode("a", slow("a")), AgentNode("b", slow("b")), AgentNode("c", slow("c"), depends_on=["a", "b"])]
    ctx, dec = await Director().execute(nodes, {}, parallel=True)
    starts = [n for n, s in t if s == "start"]
    check("a and b overlap (both start before either ends)", t[0][1] == "start" and t[1][1] == "start" and starts[:2] == ["a", "b"])
    check("c ran after both and sees both outputs", ctx.get("a") == 1 and ctx.get("b") == 1 and ctx.get("c") == 1)


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
