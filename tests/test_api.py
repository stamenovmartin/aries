"""The ARIES Control Centre over HTTP (§27, §29, §31), in-process."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-api")

import httpx  # noqa: E402

from aries.api.app import app  # noqa: E402


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_engine_routes_still_work():
    """ARIES mounts beside the engine; it must not displace it."""
    await reset_db()
    async with await _client() as c:
        r = await c.get("/api/health")
        check("the engine's own health route still answers", r.status_code == 200)
        r = await c.get("/api/tasks")
        check("and so do its task routes", r.status_code == 200)


async def test_automation_list_and_detail():
    await reset_db()
    async with await _client() as c:
        r = await c.get("/api/aries/automations")
        body = r.json()
        check("the Control Centre lists automations", r.status_code == 200 and body["automations"])
        a = body["automations"][0]
        for field in ("enabled", "version", "purpose", "trigger", "last_run", "next_run",
                      "health", "agents", "permissions", "evolution_history", "due_now", "risk"):
            check(f"the list shows '{field}' as section 27 requires", field in a)
        check("it reports the dispatcher's state too", "worker" in body)

        r = await c.get("/api/aries/automations/aries.health")
        d = r.json()
        check("inspect returns the full genome", d["genome"]["automation_id"] == "aries.health")
        check("inspect includes the learning status", "learning_status" in d)
        check("inspect includes the declared reward signals", d["reward_signals"])

        r = await c.get("/api/aries/automations/nope")
        check("an unknown automation is a 404", r.status_code == 404)


async def test_pause_and_resume():
    await reset_db()
    async with await _client() as c:
        r = await c.post("/api/aries/automations/aries.health/enabled", json={"enabled": True})
        check("an automation can be enabled over the API", r.json()["enabled"] is True)
        r = await c.get("/api/aries/settings/health.enabled")
        check("and it went through the settings layer as a user value",
              r.json()["source"] == "user" and r.json()["value"] is True)

        r = await c.post("/api/aries/automations/aries.health/enabled", json={"enabled": False})
        check("pausing works the same way", r.json()["enabled"] is False)
        check("a paused automation has no next run", r.json()["next_run"] is None)


async def test_run_now():
    await reset_db()
    async with await _client() as c:
        r = await c.post("/api/aries/automations/aries.health/run", json={"force": False})
        check("running a disabled automation is refused with 409", r.status_code == 409)

        r = await c.post("/api/aries/automations/aries.health/run", json={"force": True})
        body = r.json()
        check("but 'Run now' with force runs it without enabling it",
              r.status_code == 200 and body["ran"] is True)
        check("the run went through the task lifecycle", body["task_id"] and body["verdict"] == "pass")

        r = await c.get("/api/aries/settings/health.enabled")
        check("forcing a run did not quietly enable the automation", r.json()["value"] is False)

        r = await c.get("/api/aries/automations/aries.health/runs")
        check("the run appears in the history", len(r.json()["runs"]) >= 1)


async def test_metrics_and_latest_health():
    await reset_db()
    async with await _client() as c:
        r = await c.get("/api/aries/automations/aries.health/metrics")
        check("metrics are honest before any run", r.json()["health"]["success_rate"] is None)

        await c.post("/api/aries/automations/aries.health/run", json={"force": True})
        r = await c.get("/api/aries/automations/aries.health/metrics")
        check("and become a real rate after one", r.json()["health"]["success_rate"] == 1.0)
        ls = r.json()["learning_status"]
        check("the learning status counts tracked metrics", ls["metrics_tracked"] > 0)
        check("and says how many baselines are trusted yet", "baselines_trusted" in ls)
        check("and explains itself in words", "trusted" in ls["explanation"])

        r = await c.get("/api/aries/health/latest")
        check("the latest health pass is retrievable", r.json()["ran"] is True)
        check("with every finding, not only the problems", len(r.json()["findings"]) > 5)


async def test_settings_surface():
    await reset_db()
    async with await _client() as c:
        r = await c.get("/api/aries/settings", params={"section": "health"})
        check("settings can be listed by section", all(s["section"] == "health" for s in r.json()["settings"]))
        check("each carries the control a UI should render",
              all(s["control"] for s in r.json()["settings"]))

        r = await c.put("/api/aries/settings/news.relevance_threshold", json={"value": 0.5})
        check("a setting can be written over the API", r.json()["effective"] == 0.5)

        r = await c.put("/api/aries/settings/news.relevance_threshold", json={"value": 3.0})
        check("an invalid value is a 400, not a stored mistake", r.status_code == 400)

        r = await c.get("/api/aries/settings/news.relevance_threshold")
        check("explain names the winning layer", r.json()["source"] == "user")

        r = await c.delete("/api/aries/settings/news.relevance_threshold")
        check("clearing it falls back to the default", r.json()["effective"] == 0.6)

        r = await c.get("/api/aries/settings/not.a.setting")
        check("an unknown key is a 404", r.status_code == 404)


async def test_learned_values_are_not_writable_as_user():
    """§30 over HTTP: the author is the server's word, not the caller's."""
    await reset_db()
    from agentic_core.database.base import async_session

    from aries.settings import SettingsService
    async with async_session() as db:
        await SettingsService(db).learn("news.relevance_threshold", 0.72,
                                        confidence=0.8, rationale="inferred")
    async with await _client() as c:
        r = await c.get("/api/aries/settings/news.relevance_threshold")
        check("a learned value applies when the user has said nothing",
              r.json()["value"] == 0.72 and r.json()["source"] == "learned")

        await c.put("/api/aries/settings/news.relevance_threshold", json={"value": 0.4})
        r = await c.get("/api/aries/settings/news.relevance_threshold")
        check("a user value written over the API outranks it", r.json()["value"] == 0.4)
        check("and the learned one stays visible underneath",
              any(x["layer"] == "learned" for x in r.json()["stack"]))


async def test_notifications_show_what_was_held():
    await reset_db()
    async with await _client() as c:
        await c.put("/api/aries/settings/health.temp_critical_celsius", json={"value": 40.0})
        await c.put("/api/aries/settings/health.temp_warn_celsius", json={"value": 40.0})
        await c.post("/api/aries/automations/aries.health/run", json={"force": True})

        r = await c.get("/api/aries/notifications")
        rows = r.json()["notifications"]
        check("notifications are recorded", len(rows) > 0)
        check("each says what happened to it", all(x["disposition"] for x in rows))
        check("and why", all(x["reason"] for x in rows))

        await c.post("/api/aries/automations/aries.health/run", json={"force": True})
        r = await c.get("/api/aries/notifications", params={"disposition": "suppressed_repeat"})
        check("a repeat is recorded as suppressed rather than vanishing",
              len(r.json()["notifications"]) > 0)


async def test_sources_over_http():
    await reset_db()
    import os, tempfile
    folder = tempfile.mkdtemp(prefix="aries-api-src-")
    async with await _client() as c:
        r = await c.get("/api/aries/sources/types")
        names = [t["name"] for t in r.json()["types"]]
        check("the add-source form can be rendered from the type list", "rss" in names)
        check("and each type says whether it leaves the machine",
              all("outbound" in t for t in r.json()["types"]))

        r = await c.post("/api/aries/sources", json={
            "name": "Reuters AI", "type": "rss", "location": "https://example.com/ai.xml",
            "topics": ["ai"], "priority": "high", "trust": "trusted"})
        check("a source can be added over HTTP", r.status_code == 201)
        check("it comes back with its health", r.json()["health"]["state"] == "unused")

        r = await c.post("/api/aries/sources", json={
            "name": "Metadata", "type": "rss", "location": "http://169.254.169.254/latest"})
        check("a source aimed at the metadata endpoint is a 400, not a stored row",
              r.status_code == 400 and "link-local" in r.json()["detail"])

        r = await c.post("/api/aries/sources", json={
            "name": "Keys", "type": "directory", "location": "~/.ssh"})
        check("a folder inside privacy.excluded_paths is refused over HTTP",
              r.status_code == 400 and "privacy.excluded_paths" in r.json()["detail"])

        r = await c.post("/api/aries/sources", json={
            "name": "Docs", "type": "directory", "location": folder})
        check("a legitimate folder is accepted", r.status_code == 201)

        r = await c.get("/api/aries/sources")
        check("sources are listed with a summary", r.json()["summary"]["total"] == 2)

        r = await c.get("/api/aries/sources/resolve", params={"topics": "ai"})
        check("resolve shows what an agent would consult, in order",
              r.json()["sources"][0]["source_id"] == "reuters-ai")
        check("and states the ordering rule", "priority" in r.json()["ordering"])

        r = await c.patch("/api/aries/sources/reuters-ai", json={"enabled": False})
        check("a source can be paused", r.json()["enabled"] is False)
        r = await c.get("/api/aries/sources/resolve", params={"topics": "ai"})
        check("a paused source is absent from what an agent gets",
              all(s["source_id"] != "reuters-ai" for s in r.json()["sources"]))

        r = await c.post("/api/aries/sources/docs/feedback", json={"engaged": True})
        check("feedback is recorded", r.json()["performance"]["engagements"] == 1)

        r = await c.delete("/api/aries/sources/docs")
        check("a source can be removed", r.status_code == 200)
        r = await c.get("/api/aries/sources/docs")
        check("and is then a 404", r.status_code == 404)


async def test_source_route_permissions():
    from agentic_core.security.permissions import permission_for
    check("reading the registry needs only view_data",
          permission_for("GET", "/api/aries/sources").value == "view_data")
    check("adding a source needs manage_tools — it names somewhere ARIES will go",
          permission_for("POST", "/api/aries/sources").value == "manage_tools")
    check("removing one does too",
          permission_for("DELETE", "/api/aries/sources/x").value == "manage_tools")


async def test_interests_over_http():
    await reset_db()
    async with await _client() as c:
        r = await c.post("/api/aries/interests", json={
            "topic": "LLM Agents", "synonyms": ["agentic"], "weight": 0.9})
        check("a topic can be added over HTTP", r.status_code == 201)
        check("it is stored canonically", r.json()["topic"] == "llm agents")

        r = await c.post("/api/aries/interests", json={"topic": "crypto", "stance": "avoid"})
        check("a topic to ignore can be added", r.json()["stance"] == "avoid")

        r = await c.post("/api/aries/interests", json={"topic": "bad", "weight": 5.0})
        check("an impossible weight is a 400", r.status_code == 400)

        r = await c.post("/api/aries/interests/score", json={"text": "agentic tooling ships"})
        check("text can be scored over HTTP", r.json()["score"] == 0.9)
        check("and the score explains which topic matched",
              r.json()["matched"][0]["topic"] == "llm agents")

        r = await c.post("/api/aries/interests/score", json={"text": "crypto and agentic bots"})
        check("an avoided topic disqualifies, and says so",
              r.json()["score"] == 0.0 and r.json()["excluded_by"]["topic"] == "crypto")

        # §25 over HTTP: learning is visible, and overridden by the user.
        from agentic_core.database.base import async_session
        from aries.interests import service as ints
        async with async_session() as db:
            await ints.learn(db, "llm agents", 0.1, confidence=0.9, rationale="ignored 9 of 10")

        r = await c.get("/api/aries/interests")
        row = [x for x in r.json()["interests"] if x["topic"] == "llm agents"][0]
        check("the user's weight still decides", row["weight"] == 0.9)
        check("what ARIES learned stays visible", row["learned"]["weight"] == 0.1)
        check("with its reasoning", "9 of 10" in row["learned"]["rationale"])
        check("and marked as overridden", row["learned"]["shadowed"] is True)

        r = await c.patch("/api/aries/interests/llm agents", json={"clear_weight": True})
        check("clearing the user weight promotes the learned one", r.json()["weight"] == 0.1)
        check("and the origin is reported", r.json()["weight_source"] == "learned")

        r = await c.delete("/api/aries/interests/crypto")
        check("a topic can be removed", r.status_code == 200)
        r = await c.patch("/api/aries/interests/crypto", json={"weight": 0.5})
        check("and is then a 404", r.status_code == 404)


async def test_worker_surface():
    await reset_db()
    async with await _client() as c:
        r = await c.get("/api/aries/worker")
        body = r.json()
        check("the dispatcher's registration is visible", body["name"] == "aries.automations")
        check("the user's switch is reported separately from the task's state",
              body["switch_on"] is False and "state" in body)

        r = await c.post("/api/aries/worker/tick")
        check("a tick with the switch off does nothing", "skipped" in r.json())

        await c.put("/api/aries/settings/automations.worker_enabled", json={"value": True})
        await c.post("/api/aries/automations/aries.health/enabled", json={"enabled": True})
        r = await c.post("/api/aries/worker/tick")
        ran = [x["automation_id"] for x in r.json()["runs"]]
        check("with the switch on, the enabled automation runs", "aries.health" in ran)
        check("and a disabled one is left alone",
              "aries.news" in [x["automation_id"] for x in r.json()["skips"]])

        r = await c.post("/api/aries/worker/tick")
        check("the next tick leaves it alone until its interval elapses",
              r.json()["ran"] == 0)
        check("and says why for each",
              all(s_.get("why") or s_.get("reason") for s_ in r.json()["skips"]))


async def test_route_permissions():
    """The engine's table decides; ARIES only registers what each route needs."""
    from agentic_core.security.permissions import permission_for
    check("reading the Control Centre needs only view_data",
          permission_for("GET", "/api/aries/automations").value == "view_data")
    check("running an automation needs execute, not schedule",
          permission_for("POST", "/api/aries/automations/x/run").value == "execute")
    check("pausing one needs schedule",
          permission_for("POST", "/api/aries/automations/x/enabled").value == "schedule")
    check("changing a setting needs manage_tools",
          permission_for("PUT", "/api/aries/settings/k").value == "manage_tools")
    check("an unregistered ARIES path still fails closed on a mutation",
          permission_for("POST", "/api/aries/something/new").value != "view_data")


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
