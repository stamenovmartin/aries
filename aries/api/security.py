"""ARIES's own security controls on top of the engine's.

The engine already provides authentication, a role/permission table, audit,
secret encryption and log redaction. This module closes the gaps that are
ARIES's own, found by auditing the running system rather than by reading the
design:

  1. AN EMPTY API KEY MEANS AN OPEN API — and an open API means OWNER.
     Verified: with `API_KEY` unset, `principal.shared_key_owner()` grants all
     eleven permissions, including MANAGE_USERS. The engine refuses to boot like
     that under `FASTAPI_ENV=production`, but ARIES's normal mode is a personal
     machine in development mode, where nothing stopped it. `scripts/start.sh`
     binds to 127.0.0.1, but a shell script is a convention, not a control: one
     `--host 0.0.0.0`, one container port mapping, one `uvicorn` invocation
     typed by hand, and the whole system is administrable by the local network.
     So: WITH NO API KEY, ONLY LOOPBACK IS SERVED. Enforced in the process, at
     every request, regardless of how it was started.

  2. THE AUDIT TRAIL SAID "user" FOR EVERYONE.
     ARIES's routes hard-coded `set_by="user"`, so every settings change, source
     addition and interest edit was attributed to a literal string. With one
     person and a shared key that is merely useless; the moment per-person tokens
     exist it is actively misleading — the log would name "user" while a specific
     token made the change. The actor now comes from the authenticated principal.

  3. UNBOUNDED USER INPUT REACHED A REGEX COMPILER.
     Interest terms become compiled regular expressions. `re.escape` removes the
     ReDoS risk from metacharacters, but nothing bounded LENGTH or COUNT: a
     100,000-character synonym, or ten thousand of them in one request, is CPU
     and memory spent before any of it is stored. Bounded here, at the edge.

The engine's rule is inherited: fail closed, and say why.
"""
from __future__ import annotations

import ipaddress
import logging

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from agentic_core.config.settings import settings
from agentic_core.security import principal as principal_ctx

logger = logging.getLogger(__name__)

# ── input bounds ────────────────────────────────────────────────────────────
# Everything a caller can send that later becomes a regex, a filesystem path or
# a stored row. Generous for a human, fatal to a script.
MAX_TERM_LEN = 120           # one topic or synonym
MAX_TERMS = 50               # synonyms per topic
MAX_TOPICS_PER_REQUEST = 50
MAX_NAME_LEN = 200
MAX_LOCATION_LEN = 2000
MAX_TEXT_LEN = 20_000        # text submitted for relevance scoring


def bound_text(value: str, limit: int, field: str) -> str:
    if value is None:
        return ""
    if len(value) > limit:
        raise HTTPException(400, f"{field} is longer than {limit} characters")
    return value


def bound_list(values: list | None, *, max_items: int, max_len: int, field: str) -> list:
    if not values:
        return []
    if len(values) > max_items:
        raise HTTPException(400, f"{field}: at most {max_items} entries (got {len(values)})")
    for v in values:
        if isinstance(v, str) and len(v) > max_len:
            raise HTTPException(400, f"{field}: an entry is longer than {max_len} characters")
    return list(values)


# ── who is acting ───────────────────────────────────────────────────────────

def actor(default: str = "user") -> str:
    """The audit actor for this request: `user:<who>`.

    The `user:` prefix is load-bearing, not decoration. The Settings Service
    decides whether a write may reach a user layer by inspecting the author
    string (`HUMAN_AUTHORS`), and an HTTP request that authenticated as a
    principal IS the user speaking — the engine's roles already decided what
    they may do. Returning a bare `shared-key as owner` made every settings
    write over the API fail as a machine write, which is the §30 rule working
    correctly on a badly-formed author rather than a bug in the rule.

    The identity is kept after the prefix, so the audit trail names who acted
    instead of the literal string "user" it recorded before.

    Falls back to `default` when there is no principal — the CLI and in-process
    callers, where "user" is accurate.
    """
    who = principal_ctx.current()
    if who is None:
        return default
    return f"user:{who.describe()}"


# ── loopback enforcement ────────────────────────────────────────────────────

def _is_local(host: str | None) -> bool:
    if not host:
        return False
    if host in ("localhost", "testclient", "unix"):
        return True           # 'testclient' is httpx's ASGI transport, in-process
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def local_only_middleware(request, call_next):
    """With no API key configured, serve only loopback.

    This is the control that makes `scripts/start.sh`'s `--host 127.0.0.1` a
    guarantee rather than a habit. It runs before anything else ARIES does, and
    it fails closed: an unknown client address is treated as remote.
    """
    if settings.api_key:
        return await call_next(request)
    client = request.client.host if request.client else None
    if _is_local(client):
        return await call_next(request)
    logger.warning("Refused a non-loopback request from %s: no API_KEY is configured", client)
    return JSONResponse(
        {"detail": "ARIES has no API_KEY configured, so it serves only this machine. "
                   "Set API_KEY (and mint per-person tokens) before exposing it.",
         "client": client, "required": "API_KEY"},
        status_code=403)


def startup_report() -> dict:
    """What the security posture actually is, for the health surface and the logs."""
    return {
        "api_key_configured": bool(settings.api_key),
        "serves": "loopback only" if not settings.api_key else "any host that presents a key",
        "credentials_key_configured": bool(settings.credentials_key),
        "secret_storage": "available" if settings.credentials_key
                          else "refused — no CREDENTIALS_KEY, so no secret can be stored",
        "dry_run": settings.dry_run,
        "live_tools": [t for t in (settings.live_tools or "").split(",") if t.strip()],
        "environment": settings.fastapi_env,
    }
