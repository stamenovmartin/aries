"""The FastAPI surface. Lifted from backend/app/main.py + api/audit.py.

Middleware order (Starlette runs the LAST registered OUTERMOST):
  1. correlation  — an id exists before anything logs or audits
  2. auth         — establishes the principal, checks the route permission
  3. audit        — one line per state-changing request, INSIDE auth so it
                    can name the actor
Startup: schema, immutability guard, crash recovery, production sanity checks,
workers (never in APP_ENV=test)."""
from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from agentic_core.config.settings import settings
from agentic_core.observability.logging_setup import setup_logging
from agentic_core.security import environments

setup_logging(service=settings.app_name)
logger = logging.getLogger(__name__)

_OPEN_PREFIXES = ("/api/health", "/docs", "/openapi.json", "/redoc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from agentic_core.database import models  # noqa: F401
    from agentic_core.database.migrate import run_migrations
    from agentic_core.memory.recovery import recover_stuck
    from agentic_core.observability.audit import install_immutability
    from agentic_core.scheduler import registry as workers
    from agentic_core.security import crypto
    import agentic_core.agents.builtin  # noqa: F401  registers the roster
    import agentic_core.tools.builtin   # noqa: F401  registers the tools
    import agentic_core.workflows.examples  # noqa: F401
    import agentic_core.scheduler.builtin   # noqa: F401  registers the workers
    # An application package (e.g. examples.linux_agent) registers its own
    # agents, tools, task kinds, triggers and autopilot on import.
    app_pkg = os.environ.get("AGENTIC_APP", "").strip()
    if app_pkg:
        import importlib
        importlib.import_module(app_pkg)
        logger.info("Application package '%s' loaded", app_pkg)

    install_immutability()
    if settings.credentials_key.strip() and not os.environ.get(crypto.ENV_VAR):
        os.environ[crypto.ENV_VAR] = settings.credentials_key.strip()
    os.makedirs(settings.data_dir, exist_ok=True)
    await run_migrations()
    try:
        await recover_stuck()
    except Exception:
        logger.exception("Startup recovery failed")
    if settings.fastapi_env == "production":
        insecure = []
        if not settings.api_key:
            insecure.append("API_KEY is empty — the whole API is open")
        if not settings.secret_key:
            insecure.append("SECRET_KEY is empty")
        if insecure:
            raise RuntimeError("Insecure production configuration: " + "; ".join(insecure))
    app.state.workers_started = workers.start_all()
    yield
    await workers.stop_all()
    from agentic_core.database.base import engine
    await engine.dispose()


app = FastAPI(title="agentic-core API", description="Orchestration engine: tasks, agents, tools, evaluation, approvals",
              version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

from agentic_core.api.middleware import audit_middleware, correlation_middleware, record_refusal  # noqa: E402
from agentic_core.observability.metrics import RequestMetricsMiddleware  # noqa: E402

app.add_middleware(BaseHTTPMiddleware, dispatch=audit_middleware)


@app.middleware("http")
async def _authenticate_and_authorize(request, call_next):
    from agentic_core.database.base import async_session
    from agentic_core.security import principal as principal_ctx
    from agentic_core.security.permissions import permission_for
    from agentic_core.security.principal import TOKEN_PREFIX

    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api") or path.startswith(_OPEN_PREFIXES):
        return await call_next(request)
    who = None
    presented = request.headers.get("x-api-key", "")
    if presented.startswith(TOKEN_PREFIX):
        who = await principal_ctx.from_token(presented, async_session)
    elif settings.api_key and hmac.compare_digest(presented, settings.api_key):
        who = principal_ctx.shared_key_owner()
    elif not settings.api_key:
        who = principal_ctx.shared_key_owner()      # open API; startup warns in production
    if who is None:
        await record_refusal(request, status_code=401)
        return JSONResponse({"detail": "Invalid or missing X-API-Key"}, status_code=401)
    needed = permission_for(request.method, path)
    if not who.can(needed):
        await record_refusal(request, status_code=403, permission=needed.value, role=who.role.value, actor=who.describe())
        return JSONResponse({"detail": f"Role '{who.role.value}' lacks permission '{needed.value}' for {request.method} {path}.",
                             "required_permission": needed.value, "your_role": who.role.value}, status_code=403)
    token = principal_ctx.set_current(who)
    try:
        return await call_next(request)
    finally:
        principal_ctx.reset(token)


app.add_middleware(BaseHTTPMiddleware, dispatch=correlation_middleware)
app.add_middleware(RequestMetricsMiddleware)

from agentic_core.api import routes  # noqa: E402
app.include_router(routes.router, prefix="/api")
