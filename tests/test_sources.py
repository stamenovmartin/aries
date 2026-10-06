"""The Sources Registry (§24): what may be registered, what is refused, and in
what order an agent is given them."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-sources")

from datetime import datetime, timedelta  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.settings import SettingsService  # noqa: E402
from aries.sources import safety, service as src, types  # noqa: E402
from aries.sources.safety import SourceRejected  # noqa: E402
from aries.sources.types import Priority, Trust  # noqa: E402

TMP = tempfile.mkdtemp(prefix="aries-sources-")
DOCS = os.path.join(TMP, "docs")
os.makedirs(DOCS, exist_ok=True)


async def test_types_are_declared():
    names = types.names()
    for expected in ("rss", "website", "api", "directory", "documents", "repository",
                     "database", "email", "calendar"):
        check(f"the '{expected}' source type exists", expected in names)
    check("a local folder is not outbound", types.require("directory").outbound is False)
    check("an RSS feed is outbound", types.require("rss").outbound is True)
    check("types not yet usable say so rather than pretending",
          types.require("email").needs_connector is True)
    check("an unknown type raises with the list of known ones",
          _raises_value(lambda: types.require("telepathy")))


# ── safety: paths ───────────────────────────────────────────────────────────

async def test_symlink_is_resolved_before_it_is_judged():
    """The case a string comparison would miss: a link that points somewhere
    forbidden. Resolution turns 'where they said' into 'where it actually is'."""
    link = os.path.join(TMP, "sneaky")
    secret = os.path.join(TMP, "secrets")
    os.makedirs(secret, exist_ok=True)
    if not os.path.islink(link):
        os.symlink(secret, link)
    ok = _raises(lambda: safety.check_path(link, excluded=[secret]))
    check("a symlink into an excluded path is refused", ok)
    c = safety.check_path(link, excluded=[])
    check("and a permitted symlink is stored resolved, not as the link",
          c.location == os.path.realpath(secret) and c.detail["followed_symlink"] is True)


async def test_excluded_and_system_paths():
    check("a path inside privacy.excluded_paths is refused",
          _raises(lambda: safety.check_path(DOCS, excluded=[TMP])))
    check("traversal back into an excluded path is refused",
          _raises(lambda: safety.check_path(os.path.join(DOCS, "..", "secrets"),
                                            excluded=[os.path.join(TMP, "secrets")])))
    for sysdir in ("/etc", "/proc", "/sys"):
        check(f"{sysdir} is refused as a source", _raises(lambda d=sysdir: safety.check_path(d, excluded=[])))
    check("a relative path is refused — it has no single meaning",
          _raises(lambda: safety.check_path("Documents", excluded=[])))
    check("a path that does not exist is refused",
          _raises(lambda: safety.check_path(os.path.join(TMP, "nope"), excluded=[])))
    check("a file is not a folder", _raises(lambda: safety.check_path(__file__, excluded=[])))
    check("a good folder is accepted", safety.check_path(DOCS, excluded=[]).location == DOCS)


# ── safety: URLs ────────────────────────────────────────────────────────────

async def test_url_rules():
    HTTP = ("http", "https")
    check("a normal https feed is accepted",
          safety.check_url("https://example.com/f.xml", schemes=HTTP).outbound is True)
    check("file:// is refused", _raises(lambda: safety.check_url("file:///etc/passwd", schemes=HTTP)))
    check("a URL with no scheme is refused", _raises(lambda: safety.check_url("example.com", schemes=HTTP)))
    check("credentials embedded in a URL are refused — they would be stored in plain text",
          _raises(lambda: safety.check_url("https://u:p@example.com/f", schemes=HTTP)))
    for host in ("localhost", "127.0.0.1", "192.168.1.5", "10.0.0.1", "169.254.169.254", "[::1]"):
        check(f"'{host}' is refused by default",
              _raises(lambda h=host: safety.check_url(f"http://{h}/f", schemes=HTTP)))
    check("the cloud metadata address is named as such",
          "metadata" in (safety._private_address_reason("169.254.169.254") or ""))
    check("but a private address is allowed when the user explicitly allows it",
          safety.check_url("http://192.168.1.5/f", schemes=HTTP, allow_private=True).detail["private"] is True)
    check("a public hostname passes (it is not resolved here — see the docstring)",
          safety.check_url("https://example.com/f", schemes=HTTP).detail["host"] == "example.com")


async def test_connector_form():
    c = safety.check_connector("gmail:me@example.com")
    check("a connector source splits into connector and target",
          c.detail["connector"] == "gmail" and c.detail["target"] == "me@example.com")
    check("a connector source without a target is refused",
          _raises(lambda: safety.check_connector("gmail:")))
    check("and one without a connector is refused", _raises(lambda: safety.check_connector("nocolon")))


# ── registry ────────────────────────────────────────────────────────────────

async def test_add_and_refuse():
    await reset_db()
    async with async_session() as db:
        r = await src.add(db, name="Reuters AI", type="rss",
                          location="https://example.com/ai.xml", topics=["AI", " Agents "],
                          priority="high", trust="trusted")
        check("a source gets a readable slug", r.source_id == "reuters-ai")
        check("topics are normalised", r.topics == ["agents", "ai"])
        check("the type's default poll interval is applied", r.poll_interval_minutes == 120)

        r2 = await src.add(db, name="Reuters AI", type="rss", location="https://other.com/b.xml")
        check("a second source with the same name gets a distinct slug", r2.source_id == "reuters-ai-2")

        check("the same location cannot be registered twice",
              await _araises(src.add(db, name="Dup", type="rss", location="https://example.com/ai.xml")))
        check("a folder outside the exclusions is accepted",
              (await src.add(db, name="Docs", type="directory", location=DOCS)).type == "directory")
        check("a capability the type does not have is refused",
              await _araises(src.add(db, name="X", type="rss", location="https://x.com/f",
                                     permissions=["listen"])))


async def test_privacy_excluded_paths_are_enforced_by_the_registry():
    """The setting from Entry 002 gets its first real enforcement here."""
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set("privacy.excluded_paths", [TMP], set_by="user")
        check("a folder inside privacy.excluded_paths cannot be registered",
              await _araises(src.add(db, name="Secret", type="directory", location=DOCS)))
        await SettingsService(db).set("privacy.excluded_paths", [], set_by="user")
        check("and can once the user removes the exclusion",
              (await src.add(db, name="Secret", type="directory", location=DOCS)) is not None)


async def test_max_sources():
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set("sources.max_sources", 1, set_by="user")
        await src.add(db, name="One", type="rss", location="https://a.com/f")
        check("the source limit is enforced",
              await _araises(src.add(db, name="Two", type="rss", location="https://b.com/f")))


async def test_update_and_remove():
    await reset_db()
    async with async_session() as db:
        await src.add(db, name="Feed", type="rss", location="https://a.com/f")
        r = await src.update(db, "feed", priority="high", topics=["ai"], enabled=False)
        check("priority can be changed", Priority(r.priority) is Priority.HIGH)
        check("topics can be changed", r.topics == ["ai"])
        check("a source can be disabled", r.enabled is False)
        check("moving a source to a forbidden location is refused",
              await _araises(src.update(db, "feed", location="http://127.0.0.1/f")))
        check("the location is unchanged after a refused move",
              (await src.get(db, "feed")).location == "https://a.com/f")
        check("a source can be removed", await src.remove(db, "feed") is True)
        check("removing an unknown source reports false", await src.remove(db, "feed") is False)


# ── ordering: the §20 rule ──────────────────────────────────────────────────

async def test_user_priority_beats_observed_performance():
    """§20: 'explicit user source preferences must override learned preferences.'"""
    await reset_db()
    async with async_session() as db:
        await src.add(db, name="Excellent but low", type="rss", location="https://good.com/f",
                      priority="low")
        await src.add(db, name="Poor but high", type="rss", location="https://bad.com/f",
                      priority="high")
        await src.record_sync(db, "excellent-but-low", ok=True, items_seen=100, items_useful=100)
        await src.record_sync(db, "poor-but-high", ok=True, items_seen=100, items_useful=1)

        order = [r.source_id for r in await src.for_agent(db, type="rss")]
        check("a source the user ranked HIGH comes first despite a terrible record",
              order[0] == "poor-but-high")
        check("and the excellent one the user ranked LOW comes second",
              order[1] == "excellent-but-low")


async def test_observation_decides_ties_only():
    await reset_db()
    async with async_session() as db:
        await src.add(db, name="Useful", type="rss", location="https://u.com/f")
        await src.add(db, name="Useless", type="rss", location="https://n.com/f")
        await src.record_sync(db, "useful", ok=True, items_seen=50, items_useful=45)
        await src.record_sync(db, "useless", ok=True, items_seen=50, items_useful=2)
        order = [r.source_id for r in await src.for_agent(db, type="rss")]
        check("among equally-ranked sources, the more useful one is preferred",
              order == ["useful", "useless"])


async def test_unproven_sources_are_not_buried():
    """The cold-start trap: unknown must not be treated as zero, or a new source
    is never consulted and so never gets a record."""
    await reset_db()
    async with async_session() as db:
        await src.add(db, name="Proven bad", type="rss", location="https://bad.com/f")
        await src.add(db, name="Brand new", type="rss", location="https://new.com/f")
        await src.record_sync(db, "proven-bad", ok=True, items_seen=100, items_useful=2)
        order = [r.source_id for r in await src.for_agent(db, type="rss")]
        check("an unproven source outranks one with a proven bad record",
              order[0] == "brand-new")
        check("its useful rate is reported as unknown, not as zero",
              (await src.get(db, "brand-new")).useful_rate is None)


# ── what for_agent() excludes ───────────────────────────────────────────────

async def test_for_agent_filters():
    await reset_db()
    async with async_session() as db:
        await src.add(db, name="Good", type="rss", location="https://a.com/f", topics=["ai"])
        await src.add(db, name="Blocked", type="rss", location="https://b.com/f", trust="blocked")
        await src.add(db, name="Off", type="rss", location="https://c.com/f", enabled=False)
        await src.add(db, name="Other topic", type="rss", location="https://d.com/f", topics=["cooking"])
        await src.add(db, name="Mail", type="email", location="gmail:me@example.com")
        await src.add(db, name="Folder", type="directory", location=DOCS)

        got = [r.source_id for r in await src.for_agent(db)]
        check("a blocked source is absent, not flagged", "blocked" not in got)
        check("a disabled source is absent", "off" not in got)
        check("a type whose connector does not exist yet is absent", "mail" not in got)

        got = [r.source_id for r in await src.for_agent(db, topics=["ai"])]
        check("a source tagged with another topic is excluded", "other-topic" not in got)
        check("a source tagged with the topic is included", "good" in got)
        check("an untagged source is treated as general purpose", "folder" in got)

        got = [r.source_id for r in await src.for_agent(db, capability="search")]
        check("a source not permitted for the capability is excluded", "good" not in got)

        got = [r.source_id for r in await src.for_agent(db, type="directory")]
        check("filtering by type works", got == ["folder"])


async def test_privacy_mode_keeps_work_local():
    await reset_db()
    async with async_session() as db:
        await src.add(db, name="Feed", type="rss", location="https://a.com/f")
        await src.add(db, name="Folder", type="directory", location=DOCS)
        check("both are offered normally", len(await src.for_agent(db)) == 2)
        await SettingsService(db).set("privacy.mode", True, set_by="user")
        got = [r.source_id for r in await src.for_agent(db)]
        check("privacy mode removes every outbound source", got == ["folder"])
        check("and a caller can still ask for local only explicitly",
              [r.source_id for r in await src.for_agent(db, allow_outbound=False)] == ["folder"])


# ── health and performance (§20) ────────────────────────────────────────────

async def test_health_states():
    await reset_db()
    async with async_session() as db:
        r = await src.add(db, name="Feed", type="rss", location="https://a.com/f")
        check("a source that has never been read is 'unused'", r.health()["state"] == "unused")
        check("and its reliability is unknown, not zero", r.reliability is None)

        await src.record_sync(db, "feed", ok=True, items_seen=10, items_useful=4, items_duplicate=2)
        r = await src.get(db, "feed")
        check("after a good read it is 'ok'", r.health()["state"] == "ok")
        check("the useful rate is computed", r.useful_rate == 0.4)
        check("the duplicate rate is computed", r.duplicate_rate == 0.2)

        for _ in range(3):
            await src.record_sync(db, "feed", ok=False, error="connection refused")
        r = await src.get(db, "feed")
        check("three consecutive failures make it 'failing'", r.health()["state"] == "failing")
        check("the reason quotes the error", "connection refused" in r.health()["reason"])
        check("reliability reflects the failures", r.reliability == 0.25)

        await src.record_sync(db, "feed", ok=True, items_seen=1)
        r = await src.get(db, "feed")
        check("one success clears the failure streak",
              r.consecutive_failures == 0 and r.health()["state"] == "ok")

        r.last_sync_at = datetime.utcnow() - timedelta(minutes=r.poll_interval_minutes * 5)
        await db.commit()
        check("a source not read for far longer than its interval is 'stale'",
              (await src.get(db, "feed")).health()["state"] == "stale")


async def test_feedback_signals():
    await reset_db()
    async with async_session() as db:
        await src.add(db, name="Feed", type="rss", location="https://a.com/f")
        await src.record_feedback(db, "feed", engaged=True)
        await src.record_feedback(db, "feed", corrected=True)
        r = await src.get(db, "feed")
        check("engagement is counted", r.engagements == 1)
        check("a correction is counted", r.corrections == 1)
        check("feedback for an unknown source is reported, not raised",
              await src.record_feedback(db, "ghost", engaged=True) is None)


async def test_summary():
    await reset_db()
    async with async_session() as db:
        await src.add(db, name="Feed", type="rss", location="https://a.com/f")
        await src.add(db, name="Folder", type="directory", location=DOCS)
        s = await src.summary(db)
        check("the summary counts sources", s["total"] == 2)
        check("and says how many reach off the machine", s["outbound"] == 1)
        check("and groups by type", s["by_type"] == {"directory": 1, "rss": 1})


# ── helpers ─────────────────────────────────────────────────────────────────

def _raises(fn) -> bool:
    try:
        fn(); return False
    except SourceRejected:
        return True


def _raises_value(fn) -> bool:
    try:
        fn(); return False
    except ValueError:
        return True


async def _araises(coro) -> bool:
    try:
        await coro; return False
    except (SourceRejected, ValueError):
        return True


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
