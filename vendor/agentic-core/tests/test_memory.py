from _harness import bootstrap, check, reset_db, run_module
bootstrap("memory")

from agentic_core.database.base import async_session  # noqa: E402
from agentic_core.memory import checkpoints, context_layer, feedback, vector  # noqa: E402
from agentic_core.memory.chat_history import history, record  # noqa: E402


def test_context_layer_digest():
    context_layer.write("intelligence", "Disk Trends", title="Disk trends", body="long body", summary="/var grows 2GB/day", author="analyst")
    context_layer.write("intelligence", "disk-trends", title="Disk trends", body="v2", summary="/var grows 3GB/day", author="analyst")
    context_layer.append_line("director", "task-log", "routed x")
    d = context_layer.digest()
    check("digest carries the newest summary, once", d.count("disk-trends") == 1 and "3GB" in d)
    check("listing shows author", context_layer.listing()["intelligence"][0]["author"] == "analyst")
    check("log readable", context_layer.read_log("director", "task-log")[-1].endswith("routed x"))


async def test_vector_recall():
    await reset_db()
    async with async_session() as db:
        await vector.remember(db, kind="fact", title="nginx", content="nginx listens on port 8080 behind haproxy")
        await vector.remember(db, kind="fact", title="db", content="postgres runs on the data volume /srv/pg")
        hits = await vector.recall(db, "which port does nginx use", top_k=1)
        check("lexical recall finds the nginx fact", hits and hits[0][0].title == "nginx")
        ctx = await vector.recall_context(db, "postgres volume")
        check("recall_context renders a prompt block", ctx and "/srv/pg" in ctx)
        st = await vector.stats(db)
        check("stats count", st["total"] == 2)


async def test_feedback_distill_and_retrieval():
    await reset_db()
    async with async_session() as db:
        await feedback.capture_edit(db, task_id=None, scope="executor", before="long verbose", after="short", op="shorten")
        await feedback.capture_reject(db, task_id=None, scope="", reason="never touch /etc directly")
        await db.commit()
        out = await feedback.distill(db)
        check("template distillation processed both rows", out["processed"] == 2 and out["provider"] == "template")
        ctx = await feedback.load_rules_context(db, "executor")
        check("rules injected: global + scope", ctx and "concise" in ctx and "/etc" in ctx)
        out2 = await feedback.distill(db)
        check("idempotent", out2["processed"] == 0)


async def test_chat_history_and_cursors():
    await reset_db()
    async with async_session() as db:
        await record(db, "user", "hello"); await record(db, "bot", "hi")
        rows = await history(db)
        check("history oldest-first", [r.role for r in rows] == ["user", "bot"])
    checkpoints.save_cursor("telegram_offset", 42)
    check("cursor survives", checkpoints.load_cursor("telegram_offset") == "42")


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
