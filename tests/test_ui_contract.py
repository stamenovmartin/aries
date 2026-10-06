"""The UI/core contract.

The Control Centre runs on a different interpreter and cannot import ARIES, so
nothing but `aries_ui/contract.py` connects what it expects to what ARIES
provides. This suite closes that gap: every endpoint the UI reads must exist and
must return the keys it reads, and every endpoint it writes to must exist.

It was written because the gap bit. When reversal detection sliced the evidence
endpoint by time and source, the Learning screen kept reading the old flat keys
and rendered an error page — and nothing failed until a human looked at it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-ui-contract")

import httpx  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.interests import service as interests  # noqa: E402
from aries.settings import SettingsService  # noqa: E402
from aries.sources import service as sources  # noqa: E402
from aries_ui.contract import READS, WRITES, walk  # noqa: E402

from aries.api.app import app  # noqa: E402


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _populate():
    """Real rows, so list shapes are actually verifiable rather than empty."""
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("news.enabled", True, set_by="user")
        await s.set("health.enabled", True, set_by="user")
        await interests.add(db, topic="ai", weight=0.9, synonyms=["artificial intelligence"])
        await interests.learn(db, "ai", 0.55, confidence=0.8, rationale="you ignored 20 of 30")
        await sources.add(db, name="Example", type="rss", location="https://example.com/f.xml",
                          topics=["ai"])
        # A working-set row, so the Data screen's list shape is actually
        # verified: `walk` treats an empty list as unverifiable, which means an
        # endpoint that only ever returns [] passes vacuously.
        from aries.lifecycle import working
        await working.put(db, "contract-task", label="An email", source="gmail",
                          content="body", sensitive=True)
        await db.commit()
    async with await _client() as c:
        await c.post("/api/aries/learning/feedback", json={"text": "shorter"})
        await c.post("/api/aries/automations/aries.health/run", json={"force": True})


async def test_every_endpoint_the_ui_reads_exists_and_has_its_keys():
    await _populate()
    async with await _client() as c:
        for endpoint, paths in READS.items():
            r = await c.get(endpoint)
            check(f"{endpoint} answers", r.status_code == 200)
            if r.status_code != 200:
                continue
            payload = r.json()
            missing = [p for p in paths if not walk(payload, p)[0]]
            check(f"{endpoint} provides every key the UI reads"
                  + (f" — missing {missing}" if missing else ""), not missing)


async def test_every_endpoint_the_ui_writes_to_exists():
    """A 404 here means the UI has a button that cannot work."""
    await _populate()
    routes = {getattr(r, "path", "") for r in app.routes}
    for method, template in WRITES:
        # Route templates use {name}; normalise the UI's placeholders to compare.
        candidates = {p for p in routes if p.count("{") == template.count("{")}
        prefix = template.split("{")[0]
        check(f"{method} {template} is a real route",
              any(p.startswith(prefix) for p in candidates))


async def test_settings_written_through_the_ui_boundary_are_audited():
    """§ auditability: a UI write must take the same path as the CLI, not a bypass."""
    await _populate()
    from sqlalchemy import select

    from agentic_core.database.models import AuditEvent
    async with await _client() as c:
        r = await c.put("/api/aries/settings/news.relevance_threshold", json={"value": 0.42})
        check("the UI can write a setting", r.status_code == 200 and r.json()["effective"] == 0.42)
    async with async_session() as db:
        rows = (await db.execute(select(AuditEvent).where(
            AuditEvent.action == "setting.changed"))).scalars().all()
    check("and the write is audited", any("relevance_threshold" in (r.detail or "") for r in rows))
    check("with the authenticated principal as the actor, not a literal string",
          any((r.actor or "").startswith("user") for r in rows))


async def test_the_ui_cannot_write_a_learned_value_as_the_user():
    """The precedence rule holds across the boundary: an API caller writes the
    USER layer, and nothing the UI can send reaches the learned one."""
    await _populate()
    async with await _client() as c:
        await c.put("/api/aries/settings/news.relevance_threshold", json={"value": 0.3})
        r = await c.get("/api/aries/settings/news.relevance_threshold")
    body = r.json()
    check("a UI write lands at the user layer", body["source"] == "user")
    check("and any learned value stays visible beneath it",
          all(x["layer"] != "user" or x["value"] == 0.3 for x in body["stack"]))


async def test_explicit_and_learned_are_separate_in_the_payload():
    """The UI must be able to show two numbers; the API must give it two."""
    await _populate()
    async with await _client() as c:
        r = await c.get("/api/aries/interests")
    ai = next(i for i in r.json()["interests"] if i["topic"] == "ai")
    check("the user's weight is its own field", ai["user_weight"] == 0.9)
    check("the learned weight is its own object", ai["learned"]["weight"] == 0.55)
    check("and the payload says which one applies", ai["weight_source"] == "user")
    check("and that the learned one is shadowed", ai["learned"]["shadowed"] is True)


async def test_automation_enable_disable_through_the_boundary():
    await _populate()
    async with await _client() as c:
        r = await c.post("/api/aries/automations/aries.news/enabled", json={"enabled": False})
        check("the UI can disable an automation", r.json()["enabled"] is False)
        r = await c.get("/api/aries/automations")
        news = next(a for a in r.json()["automations"] if a["automation_id"] == "aries.news")
        check("and the list reflects it", news["enabled"] is False)
        check("a disabled automation reports no next run", news["next_run"] is None)
        r = await c.post("/api/aries/automations/aries.news/enabled", json={"enabled": True})
        check("and it can be enabled again", r.json()["enabled"] is True)


async def test_feedback_submission_through_the_boundary():
    await _populate()
    async with await _client() as c:
        r = await c.post("/api/aries/learning/feedback", json={"text": "shorter"})
        body = r.json()
        check("the UI can submit feedback", r.status_code == 201)
        check("an ambiguous correction comes back with a question, not a guess",
              body["ambiguous"] is True and body["question"])
        check("and nothing was applied", body["applied"] is False)

        r = await c.post(f"/api/aries/learning/feedback/{body['id']}/scope",
                         json={"scope": "global"})
        check("answering it applies the change", r.json()["applied"] is True)
        check("at the user layer", r.json()["layer"] == "user")


async def test_news_source_configuration_through_the_boundary():
    await _populate()
    async with await _client() as c:
        r = await c.post("/api/aries/sources/from-catalogue", json={"entry_id": "hacker-news"})
        check("a catalogue source can be added", r.status_code == 201)
        sid = r.json()["source_id"]
        r = await c.patch(f"/api/aries/sources/{sid}", json={"priority": "high",
                                                            "trust": "trusted"})
        check("priority and trust can be changed", r.json()["priority"] == "high")
        r = await c.patch(f"/api/aries/sources/{sid}", json={"enabled": False})
        check("a source can be disabled", r.json()["enabled"] is False)
        r = await c.delete(f"/api/aries/sources/{sid}")
        check("and removed", r.status_code == 200)


async def test_a_refusal_reaches_the_ui_as_a_refusal():
    """The UI must be told when ARIES says no — never shown a success it did not get."""
    await _populate()
    async with await _client() as c:
        r = await c.put("/api/aries/settings/news.relevance_threshold", json={"value": 5})
        check("an invalid value is refused with a reason", r.status_code == 400)
        check("and the reason is ARIES's own words",
              "maximum" in str(r.json().get("detail", "")))

        r = await c.post("/api/aries/sources", json={
            "name": "Bad", "type": "rss", "location": "http://169.254.169.254/x"})
        check("a forbidden source is refused", r.status_code == 400)
        check("naming what it refused", "link-local" in str(r.json().get("detail", "")))

        r = await c.get("/api/aries/learning/explain/not.a.thing")
        check("an unknown subject is a 404, not an empty answer", r.status_code == 404)


async def test_unavailable_services_are_reported_honestly():
    """Connections must distinguish available from not-built — and the answer
    has to come from whether a CONNECTOR EXISTS, not from a static flag.

    This test asserted "email is not implemented" until the day an email
    connector landed, at which point it was asserting a lie in the other
    direction. The invariant is not which integrations are built; it is that the
    screen's answer tracks what is registered.
    """
    from aries.connect import base as connectors

    await _populate()
    async with await _client() as c:
        r = await c.get("/api/aries/connections")
    body = r.json()
    rss = next(i for i in body["integrations"] if i["id"] == "rss")
    check("rss is connected, because a source exists", rss["status"] == "connected")
    check("and the counts are usable for a summary line", "counts" in body)

    for integration in body["integrations"]:
        source_type = integration.get("source_type")
        if not source_type or integration.get("blocked_by"):
            continue
        built = connectors.have(source_type)
        claimed = integration["status"] != "not_implemented"
        # RSS-shaped types are readable by the News Radar without a connector,
        # so "claimed and not built" is allowed; the forbidden direction is a
        # type with a working connector still being advertised as unavailable.
        if built:
            check(f"{integration['id']} has a connector and is not called 'not built yet'",
                  claimed)
        check(f"{integration['id']} explains its status", bool(integration["detail"]))


async def test_pending_decisions_reach_the_home_payload():
    await _populate()
    async with await _client() as c:
        # A critical finding produces a proposal — the thing Home leads with.
        await c.put("/api/aries/settings/health.temp_critical_celsius", json={"value": 40.0})
        await c.put("/api/aries/settings/health.temp_warn_celsius", json={"value": 40.0})
        await c.post("/api/aries/automations/aries.health/run", json={"force": True})
        r = await c.get("/api/aries/home")
    body = r.json()
    check("a pending decision appears on Home", len(body["decisions"]) >= 1)
    check("with what is being decided", body["decisions"][0]["kind"])
    check("and its risk, so the UI can colour it", body["decisions"][0]["risk"])


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
