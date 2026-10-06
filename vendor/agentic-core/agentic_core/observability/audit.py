"""The append-only record of every consequential act.
Lifted from backend/app/execution/audit.py.

* The actor is filled in from the principal/correlation context, not asked for.
* Immutability is enforced: a flush guard refuses UPDATE/DELETE on AuditEvent.
* Nothing here may break its caller: values are truncated to column width.
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from agentic_core.database.models import AuditEvent
from agentic_core.observability import correlation

logger = logging.getLogger(__name__)
_MAX_STATE = 16_000
_request_ip: ContextVar[str | None] = ContextVar("request_source_ip", default=None)


def source_ip():
    return _request_ip.get()


def set_source_ip(value):
    return _request_ip.set(value)


def reset_source_ip(token):
    _request_ip.reset(token)


class AuditEventImmutable(RuntimeError):
    """An attempt to change or delete a row of the audit log."""


def _fit(value, length):
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= length else text[:length]


def _dump(payload):
    if payload is None:
        return None
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > _MAX_STATE:
        return json.dumps({"_truncated": True, "_original_chars": len(text)})
    return text


def describe(p) -> str:
    if p is None:
        return "system"
    return p.email or (f"user:{p.user_id}" if p.user_id else "shared-key")


async def log_event(db: AsyncSession, *, actor_type: str, action: str,
                    actor: str | None = None, entity_type: str | None = None,
                    entity_id=None, detail: dict | None = None,
                    before: dict | None = None, after: dict | None = None,
                    user_id: int | None = None, correlation_id: str | None = None,
                    source_ip: str | None = None, permission: str | None = None) -> None:
    """Write one immutable audit row. Never raises. Does not commit — the line
    rides in the caller's transaction so it commits with the act it records."""
    try:
        from agentic_core.security import principal as principal_ctx
        p = principal_ctx.current()
        if actor is None:
            actor = describe(p)
        if user_id is None and p is not None:
            user_id = p.user_id
        if correlation_id is None:
            correlation_id = correlation.current()
        if source_ip is None:
            source_ip = _request_ip.get()
        db.add(AuditEvent(
            actor_type=_fit(actor_type, 20), actor=_fit(actor, 80), action=_fit(action, 60),
            entity_type=_fit(entity_type, 40), entity_id=_fit(entity_id, 80),
            detail=_dump(detail), before_state=_dump(before), after_state=_dump(after),
            user_id=user_id, correlation_id=_fit(correlation_id, 36),
            source_ip=_fit(source_ip, 45), permission=_fit(permission, 40)))
    except Exception:
        logger.exception("Could not write audit event %s", action)


_installed = False


def install_immutability() -> None:
    """Refuse, at the session level, to change or remove an audit row. This
    covers the ORM; revoking UPDATE/DELETE on the table from the app role is
    the database-level half and belongs to deployment."""
    global _installed
    if _installed:
        return

    @event.listens_for(Session, "before_flush")
    def _refuse_object_mutation(session, flush_context, instances):
        for obj in session.dirty:
            if isinstance(obj, AuditEvent) and session.is_modified(obj, include_collections=False):
                raise AuditEventImmutable(f"Audit row {getattr(obj, 'id', '?')} may not be changed; "
                                          "the log is append-only — write a correction as a new row.")
        for obj in session.deleted:
            if isinstance(obj, AuditEvent):
                raise AuditEventImmutable(f"Audit row {getattr(obj, 'id', '?')} may not be deleted.")

    @event.listens_for(Session, "do_orm_execute")
    def _refuse_bulk_mutation(state):
        if not (state.is_update or state.is_delete):
            return
        if any(m.class_ is AuditEvent for m in state.all_mappers):
            raise AuditEventImmutable("Bulk update/delete against the audit log is refused.")

    _installed = True


install_immutability()
