"""Connecting, reading, and understanding — with every rule in one path.

WHAT THIS FILE IS FOR
---------------------
There must be exactly one way for external content to enter ARIES, because
every guarantee in this package is a property of that path:

    the switch is checked            connect.enabled, per read
    the credential never appears     only `secrets.read` touches it, at the
                                     moment of use, and it is not returned
    the content is Untrusted         from the connector outward, always
    it lands in the working set      released when the task ends (DATA.md)
    injection attempts are reported  never filtered, never followed
    understanding is LOCAL           or it does not happen
    the model may only classify      `untrusted.answerable()` is the schema
    everything is audited            what was read, how much, and from where —
                                     never what it said

A second path would be a second set of answers to all of those, and the second
one would be wrong.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
Any write to any source. v0.1 reads. The connector protocol has no write method,
so this is enforced by there being nothing to call rather than by everyone
remembering not to.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from aries.connect import base, secrets, untrusted
from aries.connect.base import Health, Item

logger = logging.getLogger(__name__)


class NotConnected(RuntimeError):
    """The source cannot be read, and the reason is a sentence for a person."""


# ── connecting ──────────────────────────────────────────────────────────────

async def connect(db: AsyncSession, *, type: str, name: str, location: str,
                  secret: str | None = None, topics: list[str] | None = None,
                  created_by: str = "user") -> dict:
    """Register a source and, if it needs one, store its credential.

    The credential goes to the keyring and a REFERENCE goes to the database.
    Nothing else in ARIES ever holds the secret — and if there is no keyring,
    this refuses rather than writing the password into a source row, which is
    exactly what the source validator already forbids for URLs.
    """
    from aries.sources import service as sources, types

    source_type = types.require(type)
    connector = base.get(type)
    if connector is None:
        raise NotConnected(
            f"ARIES can describe a '{type}' source but has no connector for it yet — "
            f"it would be registered and unreadable")

    ref = None
    if source_type.requires_credentials:
        if not secret:
            raise NotConnected(f"a {source_type.title} needs a credential")
        account = _account_for(type, location)
        ref = secrets.store(type, account, secret)
        # The secret is now the keyring's problem. This local name is rebound so
        # it does not sit in a frame that an exception below would render.
        secret = None

    source = await sources.add(db, name=name, type=type, location=location,
                               topics=topics or [], created_by=created_by)
    if ref is not None:
        await _remember_reference(db, source, ref)

    health = await connector.check(source)
    await _audit(db, "connect.added", {"source_id": source.source_id, "type": type,
                                       "credential": str(ref) if ref else None,
                                       "reachable": health.reachable,
                                       "detail": health.detail})
    return {"source": source.as_dict(), "health": health.as_dict(),
            "credential": secrets.describe(ref)}


def _account_for(type: str, location: str) -> str:
    if type == "email":
        from aries.connect.mail import parse_location
        return parse_location(location)[1]
    return location


async def _remember_reference(db: AsyncSession, source, ref: secrets.SecretRef) -> None:
    """Store the REFERENCE on the source — never the credential.

    `metadata_json` is the source's own free-form field, and a reference is safe
    to put in it: it is meaningless without the keyring, which is the property
    that makes it safe in the database, the audit log, a screenshot and a
    prompt.
    """
    import json
    meta = {}
    try:
        meta = json.loads(source.metadata_json or "{}")
    except ValueError:
        meta = {}
    meta["credential"] = str(ref)
    source.metadata_json = json.dumps(meta)
    await db.commit()


async def credential_ref(source) -> str | None:
    import json
    try:
        return (json.loads(source.metadata_json or "{}") or {}).get("credential")
    except ValueError:
        return None


async def disconnect(db: AsyncSession, source_id: str, *, forget: bool = True) -> dict:
    """Remove a source and, unless told otherwise, its credential.

    Deliberate, never on a timer — a credential that expired because a cleaner
    ran would break a connection with no explanation (DATA.md).
    """
    from aries.sources import service as sources

    source = await sources.get(db, source_id)
    if source is None:
        raise NotConnected(f"no source called '{source_id}'")
    ref = await credential_ref(source)
    forgotten = bool(ref) and forget and secrets.forget(ref)
    await sources.remove(db, source_id)
    await _audit(db, "connect.removed",
                 {"source_id": source_id, "credential_forgotten": forgotten})
    return {"removed": source_id, "credential_forgotten": forgotten}


# ── reading ─────────────────────────────────────────────────────────────────

async def check(db: AsyncSession, source_id: str) -> dict:
    from aries.sources import service as sources

    source = await sources.get(db, source_id)
    if source is None:
        raise NotConnected(f"no source called '{source_id}'")
    connector = base.get(source.type)
    if connector is None:
        return Health(False, f"no connector for '{source.type}'").as_dict()
    return (await connector.check(source)).as_dict()


async def read(db: AsyncSession, source_id: str, *, task_id: str,
               since: datetime | None = None, limit: int | None = None) -> dict:
    """Read a source into the working set. The single door for external content.

    Returns descriptions, never bodies. The bodies are in the working set under
    `task_id` and are released when the task ends — the whole point of the
    browser analogy, and the reason this signature demands a task id rather than
    making one up.
    """
    from aries.lifecycle import working
    from aries.settings import SettingsService
    from aries.sources import service as sources

    settings = SettingsService(db)
    if not bool(await settings.get("connect.enabled")):
        raise NotConnected(
            "reading connected sources is switched off — turn on connect.enabled")

    source = await sources.get(db, source_id)
    if source is None:
        raise NotConnected(f"no source called '{source_id}'")
    if not source.enabled:
        raise NotConnected(f"'{source_id}' is registered but switched off")
    connector = base.get(source.type)
    if connector is None:
        raise NotConnected(f"ARIES has no connector for a '{source.type}' source")

    limit = int(limit or await settings.get("connect.max_items_per_read"))
    if since is None and source.type == "email":
        days = int(await settings.get("connect.mail_days"))
        since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        items = await connector.read(source, since=since, limit=limit)
    except Exception as exc:                          # noqa: BLE001
        await sources.record_sync(db, source_id, ok=False, error=str(exc)[:300])
        await _audit(db, "connect.read_failed",
                     {"source_id": source_id, "error": f"{type(exc).__name__}"})
        raise NotConnected(f"could not read {source.name}: {type(exc).__name__}: "
                           f"{str(exc)[:160]}") from None

    flagged = []
    report = bool(await settings.get("connect.report_injection_attempts"))
    for item in items:
        # Held for the duration of the task, marked sensitive so nothing that
        # respects that flag can send it anywhere.
        await working.put(db, task_id, label=item.title[:200],
                          source=item.body.source, content=item.body.text,
                          sensitive=True)
        if report:
            found = untrusted.suspicious(item.body.text)
            if found:
                flagged.append({"item_id": item.item_id, "title": item.title,
                                "attempts": found})

    await sources.record_sync(db, source_id, ok=True, items_seen=len(items))
    await db.commit()

    # WHAT was read, never what it said. An audit log that quoted mail bodies
    # would be a second copy of the inbox in a file nobody thinks of as one.
    await _audit(db, "connect.read", {"source_id": source_id, "type": source.type,
                                      "items": len(items), "task_id": task_id,
                                      "injection_attempts": len(flagged)})
    if flagged:
        logger.warning("%d item(s) from %s contain text aimed at the assistant",
                       len(flagged), source_id)

    return {"source": source_id, "items": [i.as_dict() for i in items],
            "count": len(items), "task_id": task_id,
            "injection_attempts": flagged,
            "note": "bodies are in the working set and are released when the task ends"}


async def search(db: AsyncSession, source_id: str, query: str, *, task_id: str,
                 limit: int = 25) -> dict:
    from aries.sources import service as sources
    from aries.settings import SettingsService

    if not bool(await SettingsService(db).get("connect.enabled")):
        raise NotConnected("reading connected sources is switched off")
    source = await sources.get(db, source_id)
    connector = base.get(source.type) if source else None
    if source is None or connector is None:
        raise NotConnected(f"'{source_id}' cannot be searched")
    if "search" not in connector.capabilities():
        raise NotConnected(f"a '{source.type}' source cannot be searched")

    items = await connector.search(source, query, limit=limit)
    from aries.lifecycle import working
    for item in items:
        await working.put(db, task_id, label=item.title[:200], source=item.body.source,
                          content=item.body.text, sensitive=True)
    await db.commit()
    await _audit(db, "connect.searched", {"source_id": source_id, "hits": len(items),
                                          "task_id": task_id})
    return {"source": source_id, "query": query, "count": len(items),
            "items": [i.as_dict() for i in items], "task_id": task_id}


# ── understanding ───────────────────────────────────────────────────────────

async def understand(db: AsyncSession, item: Item) -> dict:
    """Ask the local model what one piece of content is.

    THE TWO RULES THIS ENFORCES, IN CODE RATHER THAN IN A PROMPT:

    1. **It happens here or not at all.** With `connect.understand_locally` on
       and a non-local provider configured, this refuses. It does not quietly
       send the user's mail somewhere else because the local model was busy.
    2. **The reply may only classify.** `untrusted.answerable()` is the schema,
       and a reply carrying anything outside it is rejected before any caller
       reads it. There is no field through which content could become an action.
    """
    from agentic_core.config import runtime
    from agentic_core.llm import providers
    from agentic_core.llm.structured import extract_json, validate

    from aries import intelligence
    from aries.settings import SettingsService

    await intelligence.arm(db)
    local_only = bool(await SettingsService(db).get("connect.understand_locally"))
    provider = runtime.get_ai_provider()
    if local_only and provider not in ("ollama",):
        return {"understood": False,
                "why": (f"ARIES is set to understand content only on this machine and the "
                        f"model provider is '{provider}'. Nothing was sent anywhere."),
                "attempts": untrusted.suspicious(item.body.text)}
    if not providers.available():
        return {"understood": False, "why": "no local model is reachable",
                "attempts": untrusted.suspicious(item.body.text)}

    messages = [{"role": "system", "content": untrusted.SYSTEM_PROMPT},
                {"role": "user", "content": untrusted.fence(item.body)}]
    try:
        raw = await providers.chat(messages, purpose="connect.understand")
    except Exception as exc:                          # noqa: BLE001
        return {"understood": False, "why": f"the model failed: {type(exc).__name__}",
                "attempts": untrusted.suspicious(item.body.text)}

    obj = extract_json(raw) or {}
    problems = validate(obj, untrusted.answerable())
    extra = [k for k in obj if k not in untrusted.answerable()]
    if extra:
        # A reply with fields nobody asked for is the shape an injection takes
        # when it half-works. Dropped, and recorded.
        logger.warning("the model answered with unexpected field(s) %s — dropped", extra)
        obj = {k: v for k, v in obj.items() if k in untrusted.answerable()}
    if problems:
        return {"understood": False, "why": f"the model's answer was unusable: {problems[0]}",
                "attempts": untrusted.suspicious(item.body.text)}

    return {"understood": True, **obj,
            "extra_fields_dropped": extra,
            "attempts": untrusted.suspicious(item.body.text)}


async def _audit(db: AsyncSession, action: str, detail: dict) -> None:
    from agentic_core.observability.audit import log_event
    try:
        await log_event(db, actor_type="system", actor="aries:connect",
                        action=action, detail=detail)
        await db.commit()
    except Exception:                                 # noqa: BLE001
        logger.exception("could not record %s", action)
