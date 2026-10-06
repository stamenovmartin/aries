"""The Sources Registry — §24's "agents should query the registry instead of
hard-coding external websites".

That sentence is the whole design brief, and `for_agent()` at the bottom of this
module is the interface it describes: an agent says what KIND of thing it needs
and what it is about, and gets back an ordered list of places it is allowed to
look. It never names a website, never decides whether a source is trustworthy,
and never has to know how the user configured anything.

ORDERING, AND THE RULE IT OBEYS
-------------------------------
§20 says per-source performance may influence ranking, and then says plainly:
"explicit user source preferences must override learned preferences." So the
sort is strictly layered, not a weighted blend:

    1. the user's PRIORITY            (high before normal before low)
    2. the user's TRUST               (trusted before normal before untrusted)
    3. what ARIES has OBSERVED        (usefulness, then reliability)
    4. name                           (a stable tiebreak, so order never wobbles)

A blend would let a long run of mediocre results quietly demote a source the
user marked HIGH, which is exactly the override §20 forbids. Layering makes that
impossible: observation only ever decides ties among sources the user ranked
equally.

THE COLD-START TRAP
-------------------
A source that has never been read has an unknown useful rate. The tempting
shortcut is to treat unknown as zero, which sorts every new source to the bottom
— where it is never consulted, never proves itself, and stays there. A registry
that does this silently freezes its own rankings on the first week of data.
Unproven sources therefore sort at a neutral prior (`sources.unproven_prior`,
default 0.5), placing them mid-pack until there is evidence either way.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.observability import audit

from aries.settings import SettingsService
from aries.sources import safety, types
from aries.sources.models import AriesSource
from aries.sources.safety import SourceRejected
from aries.sources.types import PRIORITY_BY_NAME, TRUST_BY_NAME, Priority, Trust

logger = logging.getLogger(__name__)


# Cyrillic → Latin, so a source named in Macedonian gets a readable id instead of
# a meaningless one. Without this, "Мета.мк" and "МИА" both reduced to nothing and
# became `source` and `source-2` — ids that appear in URLs, in agent prompts and
# in provenance, and that tell the user nothing about which feed they refer to.
# Macedonian first; the Serbian and Russian letters that differ are included so a
# regional source is handled too.
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ѓ": "gj", "е": "e", "ж": "zh",
    "з": "z", "ѕ": "dz", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m",
    "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ќ": "kj",
    "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "џ": "dj", "ш": "sh",
    # Serbian / Russian letters not in the Macedonian alphabet
    "ђ": "dj", "ћ": "c", "ё": "e", "й": "j", "щ": "sht", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "ju", "я": "ja",
}


def transliterate(text: str) -> str:
    """Latinise Cyrillic so a non-Latin name still produces a readable slug."""
    return "".join(_CYRILLIC.get(ch, _CYRILLIC.get(ch.lower(), ch)) if ch.lower() in _CYRILLIC
                   else ch for ch in (text or ""))


def slugify(text: str) -> str:
    import unicodedata

    raw = transliterate((text or "").strip().lower())
    # Fold accents too, so "Zeitung für…" does not lose letters.
    raw = "".join(c for c in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return s[:100] or "source"


async def _unique_slug(db: AsyncSession, base: str) -> str:
    slug = slugify(base)
    existing = set((await db.execute(
        select(AriesSource.source_id).where(AriesSource.source_id.like(f"{slug}%"))
    )).scalars().all())
    if slug not in existing:
        return slug
    for n in range(2, 200):
        candidate = f"{slug}-{n}"
        if candidate not in existing:
            return candidate
    raise SourceRejected(f"too many sources named like '{slug}'")


async def add(db: AsyncSession, *, name: str, type: str, location: str,
              topics: list[str] | None = None, priority: str = "normal", trust: str = "normal",
              scope: str = "", enabled: bool = True, poll_interval_minutes: int | None = None,
              permissions: list[str] | None = None, metadata: dict | None = None,
              created_by: str = "user", slug: str | None = None,
              commit: bool = True) -> AriesSource:
    """Add a source. Validates the location and refuses rather than storing a
    broken or forbidden one."""
    stype = types.require(type)
    settings = SettingsService(db)

    count = (await db.execute(select(func.count(AriesSource.id)))).scalar() or 0
    limit = int(await settings.get("sources.max_sources"))
    if count >= limit:
        raise SourceRejected(f"the source limit of {limit} is reached "
                             f"(raise sources.max_sources, or remove some)")

    checked = safety.check(
        location, stype,
        excluded=list(await settings.get("privacy.excluded_paths")),
        allow_private=bool(await settings.get("sources.allow_private_addresses")),
        must_exist=bool(await settings.get("sources.require_existing_path")))

    clash = (await db.execute(select(AriesSource).where(
        AriesSource.location == checked.location, AriesSource.scope == (scope or "")))).scalar_one_or_none()
    if clash is not None:
        raise SourceRejected(f"'{checked.location}' is already registered as '{clash.source_id}'")

    unknown = set(permissions or ["read"]) - set(stype.capabilities)
    if unknown:
        raise SourceRejected(f"a {stype.name} source cannot do {sorted(unknown)} "
                             f"(it supports {list(stype.capabilities)})")

    row = AriesSource(
        source_id=await _unique_slug(db, slug or name), name=name.strip()[:200], type=stype.name,
        location=checked.location, location_original=checked.original,
        enabled=enabled, scope=scope or "",
        priority=int(PRIORITY_BY_NAME.get(priority, Priority.NORMAL)),
        trust=int(TRUST_BY_NAME.get(trust, Trust.NORMAL)),
        topics_json=json.dumps(sorted({t.strip().lower() for t in (topics or []) if t.strip()})),
        poll_interval_minutes=poll_interval_minutes or stype.default_poll_minutes,
        permissions_json=json.dumps(sorted(set(permissions or ["read"]))),
        metadata_json=json.dumps({**(metadata or {}), **checked.detail}, default=str),
        created_by=created_by)
    db.add(row)
    await db.flush()
    await audit.log_event(db, actor_type="human" if created_by == "user" else "system", actor=created_by,
                          action="source.added", entity_type="source", entity_id=row.id,
                          detail={"source_id": row.source_id, "type": row.type,
                                  "location": row.location, "outbound": stype.outbound})
    if commit:
        await db.commit()
    return row


async def get(db: AsyncSession, source_id: str) -> AriesSource | None:
    return (await db.execute(
        select(AriesSource).where(AriesSource.source_id == source_id))).scalar_one_or_none()


async def update(db: AsyncSession, source_id: str, *, actor: str = "user", commit: bool = True,
                 **fields) -> AriesSource:
    """Change a source. Re-validates the location if it moved."""
    row = await get(db, source_id)
    if row is None:
        raise SourceRejected(f"no source '{source_id}'")
    settings = SettingsService(db)
    before = row.as_dict()

    if "location" in fields and fields["location"]:
        stype = types.require(fields.get("type") or row.type)
        checked = safety.check(
            fields["location"], stype,
            excluded=list(await settings.get("privacy.excluded_paths")),
            allow_private=bool(await settings.get("sources.allow_private_addresses")),
            must_exist=bool(await settings.get("sources.require_existing_path")))
        row.location, row.location_original = checked.location, checked.original
        row.metadata_json = json.dumps({**row.metadata_dict, **checked.detail}, default=str)

    if "name" in fields and fields["name"]:
        row.name = str(fields["name"]).strip()[:200]
    if "enabled" in fields and fields["enabled"] is not None:
        row.enabled = bool(fields["enabled"])
    if "priority" in fields and fields["priority"]:
        row.priority = int(PRIORITY_BY_NAME.get(str(fields["priority"]), Priority.NORMAL))
    if "trust" in fields and fields["trust"]:
        row.trust = int(TRUST_BY_NAME.get(str(fields["trust"]), Trust.NORMAL))
    if "topics" in fields and fields["topics"] is not None:
        row.topics_json = json.dumps(sorted({t.strip().lower() for t in fields["topics"] if t.strip()}))
    if "poll_interval_minutes" in fields and fields["poll_interval_minutes"]:
        row.poll_interval_minutes = max(1, int(fields["poll_interval_minutes"]))
    if "permissions" in fields and fields["permissions"] is not None:
        stype = types.require(row.type)
        unknown = set(fields["permissions"]) - set(stype.capabilities)
        if unknown:
            raise SourceRejected(f"a {stype.name} source cannot do {sorted(unknown)}")
        row.permissions_json = json.dumps(sorted(set(fields["permissions"])))
    if "scope" in fields and fields["scope"] is not None:
        row.scope = str(fields["scope"] or "")

    await db.flush()
    await audit.log_event(db, actor_type="human", actor=actor, action="source.updated",
                          entity_type="source", entity_id=row.id,
                          detail={"source_id": row.source_id,
                                  "changed": sorted(k for k in fields if k in before or k == "location")})
    if commit:
        await db.commit()
    return row


async def remove(db: AsyncSession, source_id: str, *, actor: str = "user", commit: bool = True) -> bool:
    row = await get(db, source_id)
    if row is None:
        return False
    await audit.log_event(db, actor_type="human", actor=actor, action="source.removed",
                          entity_type="source", entity_id=row.id,
                          detail={"source_id": source_id, "location": row.location})
    await db.delete(row)
    if commit:
        await db.commit()
    return True


async def list_sources(db: AsyncSession, *, type: str | None = None, scope: str | None = None,
                       enabled: bool | None = None, topic: str | None = None,
                       include_blocked: bool = True) -> list[AriesSource]:
    q = select(AriesSource)
    if type:
        q = q.where(AriesSource.type == type)
    if scope is not None:
        q = q.where(AriesSource.scope == scope)
    if enabled is not None:
        q = q.where(AriesSource.enabled == enabled)
    if not include_blocked:
        q = q.where(AriesSource.trust > int(Trust.BLOCKED))
    rows = list((await db.execute(q.order_by(AriesSource.source_id))).scalars().all())
    if topic:
        t = topic.strip().lower()
        rows = [r for r in rows if t in r.topics]
    return rows


def effective_rank(row: AriesSource, *, unproven_prior: float = 0.5) -> tuple:
    """The sort key. Strictly layered — see the module docstring.

    Negated because Python sorts ascending and every component here is
    better-when-higher.
    """
    useful = row.useful_rate
    reliability = row.reliability
    return (-row.priority,
            -row.trust,
            -(unproven_prior if useful is None else useful),
            -(unproven_prior if reliability is None else reliability),
            row.source_id)


async def for_agent(db: AsyncSession, *, type: str | None = None, types_: list[str] | None = None,
                    topics: list[str] | None = None, capability: str = "read",
                    scope: str | None = None, limit: int | None = None,
                    allow_outbound: bool | None = None) -> list[AriesSource]:
    """THE interface of §24: what may I consult, and in what order?

    An agent asks for a kind of thing and a subject. It gets back only sources
    that are enabled, not blocked, permitted for the capability it needs, and —
    when privacy mode is on, or it asks for local only — that stay on this
    machine. Disabled, blocked and forbidden sources are simply absent; there is
    no flag for a consumer to check and forget.
    """
    settings = SettingsService(db)
    if allow_outbound is None:
        # Privacy mode (§20) keeps work local wherever a local path exists.
        allow_outbound = not bool(await settings.get("privacy.mode"))
    prior = float(await settings.get("sources.unproven_prior"))

    scopes = [""] if scope is None else ["", scope]
    q = select(AriesSource).where(AriesSource.enabled.is_(True),
                                  AriesSource.trust > int(Trust.BLOCKED),
                                  AriesSource.scope.in_(scopes))
    wanted = [t for t in ([type] if type else []) + (types_ or []) if t]
    if wanted:
        q = q.where(AriesSource.type.in_(wanted))
    rows = list((await db.execute(q)).scalars().all())

    wanted_topics = {t.strip().lower() for t in (topics or []) if t.strip()}
    out = []
    for r in rows:
        if capability not in r.permissions:
            continue
        stype = types.get(r.type)
        if stype is None or stype.needs_connector:
            continue                      # declared but not usable yet — never silently "works"
        if stype.outbound and not allow_outbound:
            continue
        # No topics asked for, or the source is untagged (general purpose), or it overlaps.
        if wanted_topics and r.topics and not (wanted_topics & set(r.topics)):
            continue
        out.append(r)

    out.sort(key=lambda r: effective_rank(r, unproven_prior=prior))
    return out[:limit] if limit else out


# ── what ARIES observed (§20's per-source performance) ──────────────────────

async def record_sync(db: AsyncSession, source_id: str, *, ok: bool, error: str | None = None,
                      items_seen: int = 0, items_useful: int = 0, items_duplicate: int = 0,
                      commit: bool = True) -> AriesSource | None:
    """Record the outcome of reading a source. Whoever reads calls this."""
    row = await get(db, source_id)
    if row is None:
        return None
    now = datetime.utcnow()
    row.last_sync_at = now
    row.items_seen += max(0, items_seen)
    row.items_useful += max(0, items_useful)
    row.items_duplicate += max(0, items_duplicate)
    if ok:
        row.sync_count += 1
        row.consecutive_failures = 0
        row.last_ok_at = now
        row.last_error = None
    else:
        row.fail_count += 1
        row.consecutive_failures += 1
        row.last_error = (error or "unknown error")[:2000]
    await db.flush()
    if commit:
        await db.commit()
    return row


async def record_feedback(db: AsyncSession, source_id: str, *, engaged: bool = False,
                          corrected: bool = False, commit: bool = True) -> AriesSource | None:
    """The user acted on something from this source, or said it was wrong.

    These are §17's reward signals in their simplest form. They move ordering
    only among sources the user ranked equally — never past an explicit priority.
    """
    row = await get(db, source_id)
    if row is None:
        return None
    if engaged:
        row.engagements += 1
    if corrected:
        row.corrections += 1
    await db.flush()
    if commit:
        await db.commit()
    return row


async def summary(db: AsyncSession) -> dict:
    rows = await list_sources(db)
    by_state: dict[str, int] = {}
    for r in rows:
        state = r.health()["state"]
        by_state[state] = by_state.get(state, 0) + 1
    return {"total": len(rows),
            "enabled": sum(1 for r in rows if r.enabled),
            "outbound": sum(1 for r in rows if (types.get(r.type) or types.SourceType(
                "", "", "", "path", False)).outbound),
            "by_type": {t: sum(1 for r in rows if r.type == t) for t in sorted({r.type for r in rows})},
            "by_health": by_state}


async def add_from_catalogue(db: AsyncSession, entry_id: str, *, topics: list[str] | None = None,
                             priority: str | None = None, trust: str | None = None,
                             created_by: str = "user", commit: bool = True) -> AriesSource:
    """Add a suggested source by its catalogue id.

    A catalogue entry is a suggestion, not a privilege: it goes through exactly
    the same validation as a URL typed by hand, so an entry that has gone bad is
    refused like anything else.
    """
    from aries.news import catalogue

    entry = catalogue.get(entry_id)
    if entry is None:
        raise SourceRejected(f"no catalogue entry '{entry_id}'")
    # The catalogue id is already a good slug, and it is stable across renames of
    # the display name — so it is the better base than the name itself.
    return await add(db, name=entry.name, type=entry.type, location=entry.url,
                     slug=entry.id,
                     topics=list(topics if topics is not None else entry.topics),
                     priority=priority or entry.suggested_priority,
                     trust=trust or entry.suggested_trust,
                     metadata={"catalogue_id": entry.id, "language": entry.language},
                     created_by=created_by, commit=commit)
