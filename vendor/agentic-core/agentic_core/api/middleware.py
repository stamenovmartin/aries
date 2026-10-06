"""Correlation + audit middleware. Lifted from backend/app/api/audit.py."""
from __future__ import annotations

import logging

from agentic_core.observability import audit, correlation
from agentic_core.security import principal as principal_ctx
from agentic_core.security.permissions import permission_for

logger = logging.getLogger(__name__)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _client_ip(request):
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", None) if client else None


def _is_id(segment: str) -> bool:
    return segment.isdigit() or len(segment) > 20


def _action_for(method: str, path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if parts and parts[0] == "api":
        parts = parts[1:]
    return f"{method.lower()}." + (".".join(":id" if _is_id(p) else p for p in parts) or "root")


def _entity_type(path: str):
    parts = [p for p in path.split("/") if p]
    if parts and parts[0] == "api":
        parts = parts[1:]
    return parts[0] if parts else None


async def _write(request, status_code: int, *, outcome: str) -> None:
    from agentic_core.database.base import async_session
    path = request.url.path
    try:
        p = principal_ctx.current()
        async with async_session() as db:
            await audit.log_event(db, actor_type="human" if (p and p.user_id) else "system",
                                  action=_action_for(request.method, path), entity_type=_entity_type(path),
                                  entity_id=path, permission=permission_for(request.method, path).value,
                                  detail={"method": request.method, "path": path, "status": status_code,
                                          "outcome": outcome, "role": p.role.value if p else None, "via": p.via if p else None},
                                  source_ip=_client_ip(request))
            await db.commit()
    except Exception:
        logger.exception("Audit middleware could not record %s %s", request.method, path)


async def correlation_middleware(request, call_next):
    cid = correlation.accept(request.headers.get("x-request-id"))
    ctoken = correlation.set_current(cid)
    itoken = audit.set_source_ip(_client_ip(request))
    try:
        response = await call_next(request)
        response.headers["X-Request-Id"] = cid
        return response
    finally:
        correlation.reset(ctoken); audit.reset_source_ip(itoken)


async def audit_middleware(request, call_next):
    if request.method in _SAFE_METHODS or not request.url.path.startswith("/api"):
        return await call_next(request)
    ctoken = correlation.set_current(correlation.accept(request.headers.get("x-request-id"))) if correlation.current() is None else None
    itoken = audit.set_source_ip(_client_ip(request)) if audit.source_ip() is None else None
    try:
        try:
            response = await call_next(request)
        except Exception:
            await _write(request, 500, outcome="error"); raise
        await _write(request, response.status_code, outcome="ok" if response.status_code < 400 else "refused")
        return response
    finally:
        if ctoken is not None:
            correlation.reset(ctoken)
        if itoken is not None:
            audit.reset_source_ip(itoken)


async def record_refusal(request, *, status_code: int, permission=None, role=None, actor=None) -> None:
    from agentic_core.database.base import async_session
    path = request.url.path
    try:
        async with async_session() as db:
            await audit.log_event(db, actor_type="system", actor=actor or "unknown",
                                  action="auth.refused" if status_code == 401 else "authz.refused",
                                  entity_type=_entity_type(path), entity_id=path, permission=permission,
                                  detail={"method": request.method, "path": path, "status": status_code, "role": role,
                                          "outcome": "refused"},
                                  source_ip=_client_ip(request), correlation_id=correlation.current())
            await db.commit()
    except Exception:
        logger.exception("Could not record refusal of %s %s", request.method, path)
