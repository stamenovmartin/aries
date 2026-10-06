"""The HTTP surface, in-process, with the template provider."""
from _harness import bootstrap, check, reset_db, run_module
bootstrap("api")

import httpx  # noqa: E402

from agentic_core.api.main import app  # noqa: E402
from agentic_core.config.settings import settings  # noqa: E402


async def _client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_end_to_end():
    await reset_db()
    from agentic_core.evaluators import deterministic as det
    from agentic_core.scheduler.queue import register_kind
    import agentic_core.agents.builtin  # noqa: F401
    import agentic_core.tools.builtin  # noqa: F401
    import agentic_core.workflows.examples  # noqa: F401
    register_kind("generic", workflow="plan_execute_verify", evaluators=[det.not_empty("content")])
    async with await _client() as c:
        r = await c.get("/api/health")
        check("health answers with components", r.status_code == 200 and r.json()["status"] == "healthy" and "components" in r.json())
        r = await c.get("/api/agents")
        check("agents listed", r.status_code == 200 and len(r.json()["agents"]) >= 6)
        r = await c.get("/api/tools")
        check("tools listed with schemas", any(t["name"] == "shell.exec" and t["risk"] == "high" for t in r.json()["tools"]))
        r = await c.post("/api/route", json={"task": "investigate the failing cron"})
        check("route endpoint", r.json()["agent"] == "researcher")
        r = await c.get("/api/orchestration/plan", params={"review_errors": "true"})
        check("director plan preview shows repair would run", any(d["node"] == "repair" and d["ran"] for d in r.json()["decisions"]))
        r = await c.post("/api/tasks", json={"kind": "generic", "title": "Check disk", "brief": "check disk usage", "run_now": True})
        body = r.json()
        check("task created and run", r.status_code == 201 and body["run"]["success"] and body["assigned_agent"])
        tid = body["id"]
        r = await c.get(f"/api/tasks/{tid}")
        check("task detail has traced runs", r.json()["status"] == "done" and r.json()["runs"][0]["steps"])
        r = await c.post("/api/execution/tool", json={"tool": "shell.exec", "payload": {"command": "echo hi"}})
        check("side-effect tool is dry-run by default", r.json().get("dry_run") is True)
        r = await c.get("/api/audit")
        check("audit log has the requests", r.status_code == 200 and r.json()["total"] >= 2)
        r = await c.get("/api/environment")
        check("environment reports gates", r.json()["executing_live"] is False)
        r = await c.get("/api/observability/metrics")
        check("metrics snapshot with honest nulls", "uninstrumented" in r.json())


async def test_api_key_and_roles():
    await reset_db()
    settings.api_key = "k-secret"
    try:
        async with await _client() as c:
            r = await c.get("/api/tasks")
            check("no key → 401", r.status_code == 401)
            r = await c.get("/api/tasks", headers={"x-api-key": "k-secret"})
            check("shared key → owner", r.status_code == 200)
            # a personal token with a read-only role
            from agentic_core.database.base import async_session
            from agentic_core.database.models import ApiToken, User
            from agentic_core.security.principal import generate_token
            plain, digest, hint = generate_token()
            async with async_session() as db:
                u = User(email="ro@example.test", role="read_only"); db.add(u); await db.flush()
                db.add(ApiToken(user_id=u.id, token_hash=digest, hint=hint)); await db.commit()
            r = await c.post("/api/tasks", json={"title": "x"}, headers={"x-api-key": plain})
            check("read-only token cannot create tasks (403)", r.status_code == 403 and r.json()["required_permission"] == "create_task")
            r = await c.get("/api/tasks", headers={"x-api-key": plain})
            check("read-only token can read", r.status_code == 200)
            r = await c.get("/api/audit", headers={"x-api-key": "k-secret"})
            check("refusals audited", any(i["action"] in ("auth.refused", "authz.refused") for i in r.json()["items"]))
    finally:
        settings.api_key = ""


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
