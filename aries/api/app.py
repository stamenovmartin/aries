"""The ARIES ASGI application.

    uvicorn aries.api.app:app

ARIES does not build its own FastAPI app. It imports the ENGINE's — with its
middleware stack, lifespan, health routes and every task, proposal, execution and
audit route already wired — and adds its own router beside them. One process,
one auth path, one audit trail, one place where workers start and stop.

The alternative, a second app proxying or duplicating the first, would mean two
middleware stacks and two ideas of who the caller is. The engine's own comment
on middleware ordering explains why that matters: a correlation id must exist
before anything logs, and the audit layer must sit inside auth so it can name the
actor. Re-creating that correctly twice is not worth the separation.

Importing `aries` at module scope — before the lifespan runs — is what registers
ARIES's tables on the shared `Base`, so the engine's `run_migrations()` creates
them without needing to know ARIES exists.
"""
from __future__ import annotations

import logging

import aries  # noqa: F401  registers tables, settings, automations, the worker
from agentic_core.api.main import app
from aries.api import permissions as _permissions  # noqa: F401  route permission policy
from aries.api import routes, security

logger = logging.getLogger(__name__)

app.include_router(routes.router, prefix="/api/aries", tags=["aries"])

# Registered LAST so Starlette runs it OUTERMOST — before authentication, before
# correlation, before anything else looks at the request. A request from off this
# machine with no API key configured must be refused, not authenticated as owner.
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

app.add_middleware(BaseHTTPMiddleware, dispatch=security.local_only_middleware)

@app.on_event("startup")
async def _arm_intelligence() -> None:
    """Point the engine at the model ARIES's settings name.

    Needed in EVERY process that might use a model, not only the Operator's
    code path: `ai_provider` is persisted in the engine's runtime state and
    survives a restart, while `ollama_model` is a pydantic settings field and
    does not. So a process that armed the provider elsewhere and never armed the
    model asked Ollama for the default `qwen2.5:3b`, which is not pulled, and
    got a 404 that looked like the model server being broken.
    """
    from agentic_core.database.base import async_session

    from aries import intelligence
    try:
        async with async_session() as db:
            state = await intelligence.arm(db)
        logger.info("ARIES intelligence: %s", state)
    except Exception:                                # noqa: BLE001
        logger.exception("could not arm the model provider; ARIES still serves")


_posture = security.startup_report()
logger.info("ARIES routes mounted at /api/aries; security posture: %s", _posture)
if not _posture["api_key_configured"]:
    logger.warning("No API_KEY configured — ARIES serves loopback only. "
                   "Set API_KEY before exposing it to any network.")

__all__ = ["app"]
