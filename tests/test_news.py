"""The News Radar (§13/03): the workflow, the pipeline, and what it refuses to do.

Run against a local feed server so the results are deterministic — the point is
the pipeline's behaviour, not any particular publisher's headlines.
"""
from __future__ import annotations

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-news")

from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import select  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.automations import last_run, run_automation  # noqa: E402
from aries.interests import add as add_interest  # noqa: E402
from aries.news.models import AriesNewsItem  # noqa: E402
from aries.settings import SettingsService  # noqa: E402
from aries.sources import add as add_source  # noqa: E402
from aries.sources import service as sources  # noqa: E402


def _rfc822(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _feed(items: list[tuple[str, str, str]], *, now=None) -> bytes:
    now = now or datetime.utcnow()
    body = "".join(
        f"<item><title>{t}</title><link>{l}</link><description>{d}</description>"
        f"<pubDate>{_rfc822(now - timedelta(minutes=5))}</pubDate></item>"
        for t, l, d in items)
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>Test</title>'
            f"{body}</channel></rss>").encode()


FEEDS: dict[str, bytes] = {}
STATUS: dict[str, int] = {}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path
        code = STATUS.get(path, 200)
        if path not in FEEDS or code != 200:
            self.send_response(code if code != 200 else 404)
            self.end_headers()
            return
        body = FEEDS[path]
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_server = HTTPServer(("127.0.0.1", 0), _Handler)
BASE = f"http://127.0.0.1:{_server.server_address[1]}"
threading.Thread(target=_server.serve_forever, daemon=True).start()


async def _setup(*, topics=(("ai", 0.9, None),), feeds=None, **settings_kw):
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("news.enabled", True, set_by="user")
        await s.set("notifications.minimum_level", "briefing", set_by="user")
        # The test server is on loopback, which the fetcher refuses by default.
        # Turning this on is itself the escape hatch working as designed.
        await s.set("sources.allow_private_addresses", True, set_by="user")
        # Quiet hours OFF (start == end disables them). These tests are about the
        # pipeline — collect, cluster, verify, rank, deliver — and the delivery
        # decision has its own suite. Left on, they depended on the wall clock:
        # every assertion about an item being "delivered" failed after 22:00,
        # because the notification policy was correctly holding it until morning.
        await s.set("notifications.quiet_hours_start", "00:00", set_by="user")
        await s.set("notifications.quiet_hours_end", "00:00", set_by="user")
        for key, value in settings_kw.items():
            await s.set(key.replace("__", "."), value, set_by="user")
        for topic, weight, stance in topics:
            await add_interest(db, topic=topic, weight=weight,
                               stance=stance or "want",
                               synonyms=["artificial intelligence"] if topic == "ai" else None)
        for name, path in (feeds or {}).items():
            await add_source(db, name=name, type="rss", location=f"{BASE}{path}")


async def test_workflow_runs_as_a_graph():
    FEEDS["/a"] = _feed([("AI breakthrough announced", "https://x.com/1", "An AI model"),
                         ("Gardening tips for autumn", "https://x.com/2", "Mulch")])
    await _setup(feeds={"A": "/a"})
    out = await run_automation("aries.news", trigger="manual")
    check("the pass succeeds", out["ran"] and out["verdict"] == "pass")

    import json

    from agentic_core.database.models import TaskRun
    async with async_session() as db:
        run = (await db.execute(select(TaskRun).order_by(TaskRun.id.desc()).limit(1))).scalar_one()
        decisions = json.loads(run.decisions or "[]")
    names = [d["node"] for d in decisions]
    check("every workflow node is recorded as a decision",
          names == ["collect", "cluster", "verify", "rank", "deliver"])
    check("and each says whether it ran and why", all(d["reason"] for d in decisions))


async def test_a_gate_skips_the_rest_when_nothing_is_collected():
    FEEDS["/empty"] = _feed([])
    await _setup(feeds={"Empty": "/empty"})
    out = await run_automation("aries.news", trigger="manual")
    import json

    from agentic_core.database.models import TaskRun
    async with async_session() as db:
        run = (await db.execute(select(TaskRun).order_by(TaskRun.id.desc()).limit(1))).scalar_one()
        decisions = {d["node"]: d for d in json.loads(run.decisions or "[]")}
    check("the cluster gate closes when no item was collected",
          decisions["cluster"]["ran"] is False)
    check("and says so in words", "no source returned anything" in decisions["cluster"]["reason"])
    check("dependent nodes skip rather than crash", decisions["rank"]["ran"] is False)
    check("the pass still completes", out["verdict"] == "pass")


async def test_relevance_decides_delivery():
    FEEDS["/mix"] = _feed([
        ("AI model released", "https://x.com/1", "artificial intelligence"),
        ("Local bakery opens", "https://x.com/2", "bread and pastries"),
    ])
    await _setup(feeds={"Mix": "/mix"})
    out = await run_automation("aries.news", trigger="manual")
    async with async_session() as db:
        rows = {r.title: r for r in (await db.execute(select(AriesNewsItem))).scalars().all()}
    check("a relevant item is delivered", rows["AI model released"].disposition == "delivered")
    check("an irrelevant one is stored but not shown",
          rows["Local bakery opens"].disposition == "below_threshold")
    check("and every item records why", all(r.explanation for r in rows.values()))
    check("the delivered one names the topic that matched",
          rows["AI model released"].topics == ["ai"])


async def test_an_avoided_topic_is_never_delivered():
    FEEDS["/avoid"] = _feed([("AI crypto trading bot launches", "https://x.com/1", "bitcoin AI")])
    await _setup(topics=(("ai", 0.9, None), ("crypto", None, "avoid")), feeds={"A": "/avoid"})
    out = await run_automation("aries.news", trigger="manual")
    async with async_session() as db:
        row = (await db.execute(select(AriesNewsItem))).scalar_one()
    check("an item matching an avoided topic is excluded despite a strong match",
          row.disposition == "excluded")
    check("and the exclusion names the topic", row.excluded_by == "crypto")
    check("nothing was delivered", out["summary"].startswith("0 delivered"))


async def test_duplicates_are_merged_across_sources():
    FEEDS["/s1"] = _feed([("OpenAI releases GPT-5", "https://a.com/1", "AI news")])
    FEEDS["/s2"] = _feed([("GPT-5 released by OpenAI", "https://b.com/2", "AI news")])
    await _setup(feeds={"S1": "/s1", "S2": "/s2"})
    out = await run_automation("aries.news", trigger="manual")
    async with async_session() as db:
        rows = (await db.execute(select(AriesNewsItem))).scalars().all()
    reps = [r for r in rows if r.is_representative]
    dupes = [r for r in rows if not r.is_representative]
    check("both items are stored", len(rows) == 2)
    check("one represents the story", len(reps) == 1)
    check("the other is recorded as a duplicate of it",
          len(dupes) == 1 and dupes[0].duplicate_of == reps[0].item_id)
    check("the user is told once", out["summary"].startswith("1 delivered"))


async def test_the_briefing_cap_applies_to_everything():
    """Regression: highly relevant items used to bypass the cap, so a pass with
    two strong interests delivered 26 items against a cap of 8."""
    FEEDS["/many"] = _feed([(f"AI agents story {i}", f"https://x.com/{i}", "artificial intelligence agents")
                            for i in range(30)])
    await _setup(topics=(("ai", 0.9, None), ("agents", 0.85, None)),
                 feeds={"Many": "/many"}, news__max_items_per_briefing=5)
    out = await run_automation("aries.news", trigger="manual")
    async with async_session() as db:
        delivered = (await db.execute(select(AriesNewsItem).where(
            AriesNewsItem.disposition == "delivered"))).scalars().all()
    check("no more than the cap is delivered, however relevant", len(delivered) <= 5)
    check("the rest are stored, not discarded",
          (await _count_all()) == 30)


async def _count_all() -> int:
    from sqlalchemy import func
    async with async_session() as db:
        return (await db.execute(select(func.count(AriesNewsItem.id)))).scalar() or 0


async def test_an_item_is_delivered_only_once():
    FEEDS["/repeat"] = _feed([("AI model released", "https://x.com/1", "artificial intelligence")])
    await _setup(feeds={"R": "/repeat"})
    first = await run_automation("aries.news", trigger="manual")
    second = await run_automation("aries.news", trigger="manual")
    check("the first pass delivers it", first["summary"].startswith("1 delivered"))
    check("the second pass does not deliver it again", second["summary"].startswith("0 delivered"))
    check("and it is stored once", await _count_all() == 1)


async def test_one_dead_source_does_not_cost_the_others():
    FEEDS["/good"] = _feed([("AI model released", "https://x.com/1", "artificial intelligence")])
    STATUS["/bad"] = 500
    FEEDS["/bad"] = b"x"
    await _setup(feeds={"Good": "/good", "Bad": "/bad"})
    out = await run_automation("aries.news", trigger="manual")
    check("the pass still succeeds", out["verdict"] == "pass")
    check("the working source still delivered", out["summary"].startswith("1 delivered"))
    async with async_session() as db:
        bad = await sources.get(db, "bad")
        good = await sources.get(db, "good")
    check("the failure is recorded against the source that failed",
          bad.consecutive_failures == 1 and bad.health()["state"] == "degraded")
    check("and not against the healthy one", good.consecutive_failures == 0)
    STATUS.pop("/bad", None)


async def test_every_source_failing_is_a_failed_pass():
    STATUS["/dead"] = 500
    FEEDS["/dead"] = b"x"
    await _setup(feeds={"Dead": "/dead"})
    out = await run_automation("aries.news", trigger="manual")
    check("a pass where every source failed does not report success",
          out["verdict"] != "pass")
    async with async_session() as db:
        row = await last_run(db, "aries.news")
    check("and the run is recorded as failed", row.status == "failed")
    STATUS.pop("/dead", None)


async def test_the_circuit_breaker_opens_after_repeated_failures():
    """Entry 004's debt, now load-bearing: the News Radar talks to a network."""
    STATUS["/dead"] = 500
    FEEDS["/dead"] = b"x"
    await _setup(feeds={"Dead": "/dead"}, automations__breaker_threshold=2)
    await run_automation("aries.news", trigger="manual")
    await run_automation("aries.news", trigger="manual")
    third = await run_automation("aries.news", trigger="manual")
    check("after enough consecutive failures the automation is paused",
          third["ran"] is False and third["reason"] == "circuit_breaker_open")
    check("and it says how long it waited", third["breaker"]["state"] == "open")
    check("force does not bypass a broken automation",
          (await run_automation("aries.news", trigger="manual", force=True))["ran"] is False)
    STATUS.pop("/dead", None)


async def test_items_older_than_the_window_are_rejected():
    old = datetime.utcnow() - timedelta(days=30)
    FEEDS["/old"] = _feed([("AI model released", "https://x.com/1", "artificial intelligence")], now=old)
    await _setup(feeds={"Old": "/old"})
    out = await run_automation("aries.news", trigger="manual")
    check("a stale item is not treated as news", "1 rejected" in out["summary"])
    check("and nothing is delivered", out["summary"].startswith("0 delivered"))


async def test_source_performance_is_recorded():
    FEEDS["/perf"] = _feed([("AI model released", "https://x.com/1", "artificial intelligence"),
                            ("Bakery opens", "https://x.com/2", "bread")])
    await _setup(feeds={"Perf": "/perf"})
    await run_automation("aries.news", trigger="manual")
    async with async_session() as db:
        s = await sources.get(db, "perf")
    check("items seen are counted against the source", s.items_seen == 2)
    check("and items that reached the user are counted separately", s.items_useful == 1)
    check("so a useful rate exists", s.useful_rate == 0.5)
    check("and the source is healthy", s.health()["state"] == "ok")


async def test_an_item_already_stored_is_not_stored_again():
    """The bug that opened this automation's circuit breaker in production.

    The outer loop skips a `ranked` entry whose item is already known, but a
    cluster's MEMBERS are a different set: a new article clusters with one
    stored a pass ago, and that member was inserted again. `item_id` is unique,
    so the flush raised, the session was poisoned, and every later statement in
    the pass failed with `PendingRollbackError`. Three passes of that opened the
    breaker and the News Radar stopped running entirely.

    It hid because the pass returned `success: True` from its own body while the
    lifecycle recorded `failed` — two different answers about one run, and
    nothing compared them until the Operator's verifier did.
    """
    from aries.news.models import AriesNewsItem
    from sqlalchemy import func, select as _select

    items = [("AI model released", "https://x.com/1", "artificial intelligence"),
             ("AI model is released", "https://x.com/2", "artificial intelligence"),
             ("New AI model released today", "https://x.com/3", "artificial intelligence")]
    FEEDS["/dupes"] = _feed(items)
    await _setup(feeds={"Dupes": "/dupes"})

    first = await run_automation("aries.news", trigger="manual")
    check(f"the first pass succeeds ({first.get('status')})", first.get("status") == "ok")

    # The same feed again: every item is known, and every cluster member with it.
    second = await run_automation("aries.news", trigger="manual")
    check(f"the second pass succeeds too ({second.get('status')})",
          second.get("status") == "ok")
    check("and does not fail on a duplicate insert",
          "PendingRollback" not in str(second.get("summary") or ""))

    async with async_session() as db:
        total = (await db.execute(_select(func.count()).select_from(AriesNewsItem))).scalar()
        distinct = (await db.execute(
            _select(func.count(func.distinct(AriesNewsItem.item_id))))).scalar()
    check(f"every stored item is stored once ({total} rows, {distinct} distinct)",
          total == distinct)


async def test_topic_diversity_and_held_cap():
    from aries.news.selection import diverse
    items = [("ai", "a", i) for i in range(20)] + [("real madrid", "r", 1), ("macedonia news", "m", 1)]
    selected = diverse(items, topics=lambda x: [x[0]], source=lambda x: x[1], limit=3)
    check("three interests survive unequal topic volume", {x[0] for x in selected} == {"ai", "real madrid", "macedonia news"})
    FEEDS["/held"] = _feed([(f"AI {word}", f"https://x.com/{i}", "AI") for i, word in enumerate(["robotics", "vision", "training", "inference", "datasets"])])
    await _setup(feeds={"Held": "/held"}, notifications__minimum_level="important", news__max_items_per_briefing=2)
    await run_automation("aries.news", trigger="manual")
    async with async_session() as db:
        rows = (await db.execute(select(AriesNewsItem))).scalars().all()
    check("relevance alone never interrupts", not any(r.disposition == "delivered" for r in rows))
    check("held items count against cap", sum(r.disposition == "held" for r in rows) == 2)


async def test_briefing_rejects_stale_and_dismissed():
    from aries.news.selection import briefing_rows
    await reset_db()
    now = datetime.utcnow()
    async with async_session() as db:
        for key, published, dismissed in [("fresh", now, False), ("stale", now-timedelta(days=5), False), ("dismissed", now, True)]:
            db.add(AriesNewsItem(item_id=key, source_id="test", title=key,
                                first_seen_at=now, published_at=published,
                                relevance=0.9, disposition="held", dismissed=dismissed))
        await db.commit()
        rows = await briefing_rows(db)
        check("stale publication and dismissed items cannot fill briefing", [r.item_id for r in rows] == ["fresh"])


async def test_curated_coverage_does_not_override_avoid():
    from aries.news.automation import cluster, rank
    await _setup(topics=(("ai", 0.9, None),))
    async with async_session() as db:
        ctx={"db":db,"collected":[{"item_id":"coverage", "source_id":"curated", "source_weight":1,
            "title":"Training a new visual encoder", "summary":"", "link":"https://example.org/article",
            "guid":"coverage", "coverage_topics":["ai"]}]}
        grouped=await cluster(ctx)
        ctx["verified"]=grouped["clusters"]
        out=await rank(ctx)
        rel=out["ranked"][0]["relevance"]
        check("curated subject feed covers implicit ML article",rel.score==0.9 and rel.matched[0]["source"]=="curated_feed_coverage")
        await add_interest(db,topic="crypto",stance="avoid")
        ctx["verified"][0].representative.extra["title"]="crypto training"
        out=await rank(ctx)
        check("avoided subject overrides curated coverage",out["ranked"][0]["relevance"].excluded)


if __name__ == "__main__":
    code = run_module(sys.modules[__name__])
    # Shut the test server down explicitly. As a daemon thread it was being
    # killed mid-request at interpreter shutdown, which raised BrokenPipeError
    # on stderr and made the process exit non-zero even though every assertion
    # had passed — a green suite that reports failure is worse than a red one,
    # because it trains you to ignore the exit code.
    try:
        _server.shutdown()
        _server.server_close()
    except Exception:
        pass
    sys.exit(code)
