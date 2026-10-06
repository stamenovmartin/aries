"""Credentials: an allowlisted set of keys, a value goes in and never comes
back out (except to the tool at the moment of use). Lifted from
backend/app/services/connections/store.py.

Two stores, one namespace: the process environment (.env) and the encrypted
table. The table wins; an expired or revoked row does NOT fall through to .env.
Rotation stages a `pending` row beside the `active` one and swaps only after
the new value provably decrypts.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from sqlalchemy import select

from agentic_core.database.models import StoredCredential
from agentic_core.security import crypto

logger = logging.getLogger(__name__)

# The only keys the store may hold. An application registers its own with
# `register(provider, key, label, secret=True)`. A writer that accepts any
# name is a way to set PATH or DATABASE_URL from a web form.
FIELDS: list[dict] = [
    {"provider": "llm", "key": "OPENAI_API_KEY", "label": "OpenAI-compatible API key", "secret": True},
    {"provider": "telegram", "key": "TELEGRAM_BOT_TOKEN", "label": "Bot token", "secret": True},
    {"provider": "telegram", "key": "TELEGRAM_APPROVER_CHAT_ID", "label": "Approver chat id", "secret": False},
]


def register(provider: str, key: str, label: str, *, secret: bool = True) -> None:
    if key not in {f["key"] for f in FIELDS}:
        FIELDS.append({"provider": provider, "key": key, "label": label, "secret": secret})


def allowed() -> set[str]:
    return {f["key"] for f in FIELDS}


def provider_for(key: str) -> str:
    return next((f["provider"] for f in FIELDS if f["key"] == key), "other")


def _aad(provider: str, key: str) -> str:
    return f"{provider}|{key}"


async def _rows(db, key):
    return list((await db.execute(select(StoredCredential).where(StoredCredential.key == key)
                                  .order_by(StoredCredential.id))).scalars().all())


def _usable(row) -> bool:
    expired = row.expires_at is not None and row.expires_at <= datetime.utcnow()
    return row.status == "active" and bool(row.ciphertext) and not expired


def _of(rows, status):
    return next((r for r in rows if r.status == status), None)


async def _audit(db, action, key, **detail):
    from agentic_core.observability.audit import log_event
    await log_event(db, actor_type="human", action=action, entity_type="credential",
                    entity_id=key, detail={"key": key, "provider": provider_for(key), **detail})


async def resolve(db, key: str) -> str | None:
    """The only function that returns a secret."""
    if key not in allowed():
        return None
    rows = await _rows(db, key)
    active = _of(rows, "active")
    if active is not None:
        if not _usable(active):
            return None
        return crypto.decrypt(active.ciphertext, aad=_aad(active.provider, active.key))
    if _of(rows, "revoked") is not None:
        return None
    raw = os.getenv(key, "")
    return raw.strip() or None


async def state(db) -> list[dict]:
    """Each field and whether it has a value. Never the value."""
    stored: dict[str, dict] = {}
    for r in (await db.execute(select(StoredCredential).order_by(StoredCredential.id))).scalars().all():
        e = stored.setdefault(r.key, {"usable": False, "hint": None, "rotation_pending": False, "revoked": False})
        if r.status == "active":
            e["usable"], e["hint"] = _usable(r), r.hint
        elif r.status == "pending":
            e["rotation_pending"] = True
        elif r.status == "revoked":
            e["revoked"] = True
    out = []
    for f in FIELDS:
        db_e = stored.get(f["key"]) or {}
        in_env = bool(os.getenv(f["key"], "").strip())
        if db_e:
            is_set, source = db_e.get("usable", False), ("database" if db_e.get("usable") else None)
        else:
            is_set, source = in_env, ("env" if in_env else None)
        out.append({**f, "set": is_set, "source": source, "hint": db_e.get("hint"),
                    "rotation_pending": db_e.get("rotation_pending", False), "revoked": db_e.get("revoked", False)})
    return out


def _refusal(rejected, why):
    logger.warning("Encrypted credential write refused: %s", why)
    return {"saved": [], "rejected": rejected, "refused": why}


async def save(db, values: dict[str, str], *, expires_at: datetime | None = None) -> dict:
    rejected = sorted(k for k in values if k not in allowed())
    accepted = sorted(k for k in values if k in allowed() and (values[k] or "").strip())
    if not accepted:
        return {"saved": [], "rejected": rejected, "refused": None}
    prepared = []
    try:
        for k in accepted:
            v = values[k].strip(); provider = provider_for(k)
            prepared.append((k, provider, crypto.encrypt(v, aad=_aad(provider, k)), crypto.hint_for(v)))
    except crypto.CryptoRefused as e:
        return _refusal(rejected, str(e))
    for key, provider, blob, hint in prepared:
        rows = await _rows(db, key)
        for r in rows:
            if r.status == "pending":
                await db.delete(r)
        active = _of(rows, "active")
        if active is not None:
            active.ciphertext, active.hint, active.expires_at = blob, hint, expires_at
        else:
            db.add(StoredCredential(provider=provider, key=key, ciphertext=blob, hint=hint,
                                    status="active", expires_at=expires_at))
        await _audit(db, "credential.saved", key, hint=hint)
    await db.commit()
    logger.info("Encrypted credentials stored: %s", ", ".join(accepted))   # names only
    return {"saved": accepted, "rejected": rejected, "refused": None}


async def rotate(db, key: str, new_value: str) -> dict:
    if key not in allowed():
        return _refusal([key], f"'{key}' is not an allowed key.")
    value = (new_value or "").strip()
    if not value:
        return _refusal([], "No new value to rotate to.")
    rows = await _rows(db, key)
    if _of(rows, "active") is None:
        return _refusal([], f"No active secret for '{key}' to rotate. Save it first.")
    provider = provider_for(key)
    try:
        blob = crypto.encrypt(value, aad=_aad(provider, key))
    except crypto.CryptoRefused as e:
        return _refusal([], str(e))
    existing = _of(rows, "pending")
    if existing is not None:
        await db.delete(existing)
    hint = crypto.hint_for(value)
    db.add(StoredCredential(provider=provider, key=key, ciphertext=blob, hint=hint, status="pending"))
    await _audit(db, "credential.rotation_staged", key, hint=hint)
    await db.commit()
    return {"key": key, "state": "pending", "hint": hint, "refused": None}


async def confirm_rotation(db, key: str) -> dict:
    rows = await _rows(db, key)
    pending = _of(rows, "pending")
    if pending is None:
        return _refusal([], f"No staged secret for '{key}'.")
    try:
        crypto.decrypt(pending.ciphertext, aad=_aad(pending.provider, pending.key))
    except crypto.CryptoRefused as e:
        return _refusal([], f"The new secret does not decrypt: {e} The old one stays in force.")
    for r in rows:
        if r.status == "active":
            await db.delete(r)
    pending.status, pending.rotated_at = "active", datetime.utcnow()
    await _audit(db, "credential.rotated", key, hint=pending.hint)
    await db.commit()
    return {"key": key, "state": "active", "hint": pending.hint, "refused": None}


async def revoke(db, key: str, *, reason: str | None = None) -> dict:
    if key not in allowed():
        return _refusal([key], f"'{key}' is not an allowed key.")
    rows = await _rows(db, key)
    now = datetime.utcnow()
    if rows:
        for r in rows:
            r.ciphertext, r.status, r.revoked_at = "", "revoked", now
    else:
        db.add(StoredCredential(provider=provider_for(key), key=key, ciphertext="", hint="••••",
                                status="revoked", revoked_at=now))
    await _audit(db, "credential.revoked", key, reason=reason)
    await db.commit()
    return {"key": key, "state": "revoked", "refused": None}
