"""Is each part working, and if not, which part and why.
Lifted from backend/app/api/health.py, minus the marketing integrations.
Probe depths are labelled: local | db. An unverified component is `unknown`,
never `ok`; `not_configured` is not a fault."""
from __future__ import annotations

import asyncio
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from agentic_core.config import runtime
from agentic_core.config.settings import settings
from agentic_core.database.base import async_session
from agentic_core.observability import metrics
from agentic_core.observability.logging_setup import redact_text
from agentic_core.security import environments

OK, DEGRADED, DOWN, UNKNOWN, NOT_CONFIGURED, DISABLED = "ok", "degraded", "down", "unknown", "not_configured", "disabled"
_STARTED_MONO = time.monotonic()


def _c(component, status, detail, *, probe, reason=None, **extra):
    out = {"component": component, "status": status, "detail": detail, "probe": probe,
           "checked_at": datetime.now(timezone.utc).isoformat()}
    if status != OK:
        out["reason"] = reason or detail
    out.update(extra)
    return out


def _why(e) -> str:
    return redact_text(f"{type(e).__name__}: {e}")[:300]


def probe_application(request) -> dict:
    env = environments.describe()
    detail = f"process answers · env {env['env']}"
    if not env["explicit"]:
        return _c("application", DEGRADED, detail + " · APP_ENV not set explicitly", probe="local",
                  reason="APP_ENV not set — assuming production", uptime_seconds=round(time.monotonic() - _STARTED_MONO, 1), pid=os.getpid())
    return _c("application", OK, detail, probe="local", uptime_seconds=round(time.monotonic() - _STARTED_MONO, 1), pid=os.getpid())


async def probe_database() -> dict:
    async def _ping():
        async with async_session() as s:
            await s.execute(text("SELECT 1"))
    started = time.perf_counter()
    try:
        await asyncio.wait_for(_ping(), timeout=5)
    except asyncio.TimeoutError:
        return _c("database", DOWN, "database did not answer within 5s", probe="db", reason="timeout")
    except Exception as e:
        return _c("database", DOWN, f"database unreachable: {_why(e)}", probe="db", reason=_why(e))
    return _c("database", OK, f"answers in {(time.perf_counter() - started) * 1000:.0f} ms", probe="db")


async def probe_queue() -> dict:
    from agentic_core.database.models import ActionProposal, ScheduledTask
    try:
        async with async_session() as db:
            queued = int((await db.execute(select(func.count()).select_from(ScheduledTask).where(ScheduledTask.status == "queued"))).scalar() or 0)
            overdue = int((await db.execute(select(func.count()).select_from(ScheduledTask).where(
                ScheduledTask.status == "queued", ScheduledTask.run_at < datetime.utcnow() - timedelta(minutes=15)))).scalar() or 0)
            proposed = int((await db.execute(select(func.count()).select_from(ActionProposal).where(ActionProposal.status == "proposed"))).scalar() or 0)
    except Exception as e:
        metrics.set_queue_depth("scheduled_tasks", None, reason=_why(e))
        return _c("queue", UNKNOWN, f"queue unreadable: {_why(e)}", probe="db", reason=_why(e))
    metrics.set_queue_depth("scheduled_tasks", queued); metrics.set_queue_depth("proposals", proposed)
    counts = {"scheduled_queued": queued, "scheduled_overdue": overdue, "proposals_open": proposed}
    if overdue:
        return _c("queue", DEGRADED, f"{overdue} scheduled tasks are >15 min past due", probe="db", reason="backlog", counts=counts)
    return _c("queue", OK, f"{queued} scheduled, {proposed} awaiting a human", probe="db", counts=counts)


def probe_workers(request) -> dict:
    from agentic_core.scheduler import registry
    if environments.is_test():
        return _c("workers", DISABLED, "APP_ENV=test — workers deliberately not started", probe="local", reason="APP_ENV=test")
    st = registry.status()
    crashed = [w["name"] for w in st if w["state"] == "crashed"]
    missing = [w["name"] for w in st if w["state"] in ("not started", "cancelled")]
    if crashed:
        return _c("workers", DOWN, "crashed: " + ", ".join(crashed), probe="local", reason="worker crashed", workers=st)
    if missing:
        return _c("workers", DEGRADED, "not running: " + ", ".join(missing), probe="local", reason="not started", workers=st)
    return _c("workers", OK, f"{len(st)} workers running", probe="local", workers=st)


def probe_ai_provider() -> dict:
    p = runtime.get_ai_provider()
    from agentic_core.llm.telemetry import snapshot
    observed = {"calls": snapshot().get("total_calls", 0)}
    if p == "cli":
        path = shutil.which(settings.cli_agent_bin)
        if not path:
            return _c("ai_provider", DOWN, f"provider 'cli' but '{settings.cli_agent_bin}' is not on PATH", probe="local",
                      reason="binary missing", provider=p, observed=observed)
        return _c("ai_provider", OK, f"CLI agent '{settings.cli_agent_bin}' at {path}", probe="local", provider=p, observed=observed)
    if p == "openai":
        if not settings.openai_api_key and "localhost" not in settings.openai_base_url:
            return _c("ai_provider", NOT_CONFIGURED, "provider 'openai' but no OPENAI_API_KEY", probe="local", reason="key missing", provider=p)
        return _c("ai_provider", UNKNOWN, f"OpenAI-compatible at {settings.openai_base_url} · not verified live", probe="local",
                  reason="no live probe on the hot path", provider=p, observed=observed)
    if p == "ollama":
        return _c("ai_provider", UNKNOWN, f"Ollama at {settings.ollama_base_url} · not verified live", probe="local",
                  reason="no live probe on the hot path", provider=p, observed=observed)
    if p == "template":
        return _c("ai_provider", DEGRADED, "provider 'template' — deterministic output, no model", probe="local",
                  reason="no model connected", provider=p, observed=observed)
    return _c("ai_provider", UNKNOWN, f"unknown provider '{p}'", probe="local", reason="AI_PROVIDER not recognised", provider=p)


def probe_execution_gates() -> dict:
    live = [t for t in (runtime.get_live_tools() or "").split(",") if t.strip()]
    dry = runtime.get_dry_run()
    return _c("execution_gates", OK, f"dry_run={dry} · live_tools={live or 'none'}", probe="local",
              dry_run=dry, live_tools=live, executing_live=(not dry) and bool(live))


async def collect(request) -> list[dict]:
    out = [probe_application(request)]
    db, queue = await asyncio.gather(probe_database(), probe_queue(), return_exceptions=True)
    for name, r in (("database", db), ("queue", queue)):
        out.append(r if isinstance(r, dict) else _c(name, UNKNOWN, "probe crashed", probe="db", reason=_why(r)))
    out.append(probe_workers(request))
    out.append(probe_ai_provider())
    out.append(probe_execution_gates())
    return out


def summarise(components: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for c in components:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    faults = [c for c in components if c["status"] in (DOWN, DEGRADED)]
    worst = OK
    for cand in (DOWN, DEGRADED):
        if any(c["status"] == cand for c in faults):
            worst = cand; break
    return {"counts": counts, "worst": worst,
            "unverified": [c["component"] for c in components if c["status"] == UNKNOWN],
            "failing": [{"component": c["component"], "status": c["status"], "reason": c.get("reason")} for c in faults]}
