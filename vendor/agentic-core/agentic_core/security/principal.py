"""Who is making this request. Lifted from backend/app/core/principal.py,
single-tenant. Two ways in: a personal token (a real user with a role) or the
shared API key (mapped to an OWNER principal)."""
from __future__ import annotations

import hashlib
import logging
import secrets
from contextvars import ContextVar
from dataclasses import dataclass, field

from agentic_core.security.permissions import Permission, Role, permissions_for

logger = logging.getLogger(__name__)
TOKEN_PREFIX = "agc_"


@dataclass(frozen=True)
class Principal:
    user_id: int | None
    role: Role
    email: str | None = None
    via: str = "token"
    permissions: frozenset = field(default_factory=frozenset)

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    def describe(self) -> str:
        who = self.email or (f"user:{self.user_id}" if self.user_id else "shared-key")
        return f"{who} as {self.role.value}"


def build(user_id, role: Role, *, email=None, via="token") -> Principal:
    return Principal(user_id=user_id, role=role, email=email, via=via,
                     permissions=frozenset(permissions_for(role)))


_principal: ContextVar[Principal | None] = ContextVar("principal", default=None)


def current() -> Principal | None:
    return _principal.get()


def require() -> Principal:
    p = _principal.get()
    if p is None:
        raise PermissionError("No principal in context.")
    return p


def set_current(p):
    return _principal.set(p)


def reset(token) -> None:
    _principal.reset(token)


def generate_token() -> tuple[str, str, str]:
    """(plaintext, sha256 digest, hint). The plaintext is shown once and dropped."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest(), raw[:len(TOKEN_PREFIX) + 6]


async def from_token(raw: str, session_factory) -> Principal | None:
    from sqlalchemy import select
    from agentic_core.database.models import ApiToken, User
    digest = hashlib.sha256(raw.encode()).hexdigest()
    async with session_factory() as db:
        row = (await db.execute(select(ApiToken, User).join(User, User.id == ApiToken.user_id)
                                .where(ApiToken.token_hash == digest, ApiToken.revoked_at.is_(None)))).first()
    if row is None:
        return None
    token, user = row
    if not user.is_active:
        return None
    try:
        role = Role(user.role)
    except ValueError:
        return None
    return build(user.id, role, email=user.email, via="token")


def shared_key_owner() -> Principal:
    return build(None, Role.OWNER, via="shared_key")
