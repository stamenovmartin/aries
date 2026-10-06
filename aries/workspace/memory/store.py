"""The write path — and the place the layer rule is enforced.

Two tables, two authors, one rule:

    aries_workspace_memories      only text a HUMAN produced, layer USER
    aries_workspace_conclusions   only what ARIES inferred, layer LEARNED

`record` refuses a source that is not a human channel. `conclude` refuses any
layer outside `MACHINE_WRITABLE`. Both refusals happen before the row exists,
so the rule is enforced on the write path and not by the order somebody happens
to read the tables in — which is the same thing `SettingsService.set` does for
settings and the same thing the `weight` / `learned_weight` split does for
interests.

NOTHING IS EVER DELETED
-----------------------
`forget` sets `expired_at`. A contradiction sets the loser's `invalid_at` and
`superseded_by`. "Why did you stop thinking that?" therefore always has an
answer, and an expiry made in error is one UPDATE from being undone.

REPLACEMENTS REQUIRE EXPLICIT REVIEW
--------------------------------------
A proposed contradiction involving USER evidence remains pending until the user
reviews the old and new fact. The clock only orders a confirmed replacement.
Superseding a LEARNED conclusion never expires or suppresses its USER source.
Explicit forgetting and privacy exclusions still apply independently.

THE CONCLUSION TEXT IS NOT GENERATED
------------------------------------
`WorkspaceConclusion.text` is a copy of the utterance it came from, normalised
and nothing else. mem0 v2 dropped its same-language guarantee and now stores
Macedonian speech as English; that cannot happen here, because no model is ever
asked to produce the words. The model contributes a label, a probability and
nothing that gets stored as prose. That is a stronger guarantee than a prompt
asking it to keep the language, and it is checkable — `test_memory.py` asserts
the stored script matches the spoken one.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update

from aries.settings.layers import MACHINE_WRITABLE, Layer
from aries.workspace.memory import embedding, extraction, migration, vectors
from aries.workspace.models import (
    IMPORTANCE, WorkspaceConclusion, WorkspaceConclusionSource, WorkspaceMemory,
)

log = logging.getLogger("aries.workspace.memory")

# Channels through which a human speaks. Anything else may not write an
# utterance, whatever it claims about itself.
USER_SOURCES = frozenset({"user", "voice", "chat", "shell", "ui"})
MEMORY, CONCLUSION = "m", "c"          # cache key prefixes; one matrix, two tables
DEBOUNCE_SECONDS = 3.


class MemoryRefused(ValueError):
    """A write the schema's own rule does not permit."""


# ── the cached matrix ────────────────────────────────────────────────────────

class _Cache:
    def __init__(self, embedder):
        self.embedder = embedder
        self.vectors = vectors.VectorCache(embedder.dim)
        self.texts: dict[str, str] = {}

    def put(self, key, text, vector):
        self.vectors.add(key, vector)
        self.texts[key] = text

    def drop(self, key):
        self.vectors.drop(key)
        self.texts.pop(key, None)

    def neighbours(self, vector, limit=5):
        return [(key, score, self.texts.get(key, "")) for key, score in self.vectors.search(vector, limit)]


_cache: _Cache | None = None
_cache_lock = asyncio.Lock()


def reset_cache():
    """Drop the in-RAM index. Tests that recreate the database call this."""
    global _cache
    _cache = None


async def warm(db, *, embedder=None, name=None):
    """Load every live embedding into RAM once, and return the cache.

    Reading the blobs per query instead of once costs 64.2 ms against 1.0 ms
    measured here — the cache is the design, so it is built eagerly and kept.
    """
    global _cache
    async with _cache_lock:
        if _cache is not None:
            return _cache
        await migration.ensure()
        if embedder is None:
            model_name = name or await _setting(db, "workspace.memory_embedder", embedding.DEFAULT)
            embedder = await asyncio.to_thread(embedding.get, model_name)
        cache = _Cache(embedder)
        for prefix, model in ((MEMORY, WorkspaceMemory), (CONCLUSION, WorkspaceConclusion)):
            rows = (await db.execute(select(model).where(model.expired_at.is_(None)))).scalars().all()
            for row in rows:
                if not row.embedding or row.embedding_model != embedder.name:
                    continue
                vector = embedding.unpack(row.embedding, embedder.dim)
                if vector is not None:
                    cache.put(f"{prefix}:{row.id}", row.text, vector)
        _cache = cache
        return cache


async def _setting(db, key, fallback):
    from aries.settings import SettingsService
    try:
        return await SettingsService(db).get(key)
    except Exception:                                   # noqa: BLE001
        return fallback


async def _privacy_rules(db, *, observing=False):
    """Privacy is mandatory policy, never a best-effort tuning default."""
    from aries.settings import SettingsService
    try:
        settings=SettingsService(db)
        excluded=await settings.get("privacy.excluded_memory_topics")
        if not isinstance(excluded,list) or any(not isinstance(t,str) for t in excluded):
            raise ValueError("Invalid excluded topics")
        allowed=await settings.get("privacy.remember_conversations") if observing else True
        if type(allowed) is not bool:
            raise ValueError("Invalid conversation memory policy")
        return [t.casefold() for t in excluded if t],allowed
    except Exception as exc:
        raise MemoryRefused("Memory privacy policy is unavailable; no context or memory write is permitted") from exc


def _matches_exclusion(text, topics):
    return any(topic in (text or "").casefold() for topic in topics)


async def _excluded_keys(db, topics):
    """Reversible exclusion, including conclusions drawn from excluded sources."""
    if not topics:
        return set()
    memories=(await db.execute(select(WorkspaceMemory.id,WorkspaceMemory.text))).all()
    hidden_memories={row.id for row in memories if _matches_exclusion(row.text,topics)}
    conclusions=(await db.execute(select(WorkspaceConclusion.id,WorkspaceConclusion.text))).all()
    hidden_conclusions={row.id for row in conclusions if _matches_exclusion(row.text,topics)}
    if hidden_memories:
        links=(await db.execute(select(WorkspaceConclusionSource.conclusion_id,
                                       WorkspaceConclusionSource.memory_id))).all()
        hidden_conclusions.update(row.conclusion_id for row in links if row.memory_id in hidden_memories)
    return {f"{MEMORY}:{key}" for key in hidden_memories} | {f"{CONCLUSION}:{key}" for key in hidden_conclusions}


# ── writes ───────────────────────────────────────────────────────────────────

async def record(db, text, *, source="user", kind=None, valid_at=None, importance=None,
                 cache=None, vector=None, commit=True):
    """Write one utterance, verbatim, at layer USER. Never called by an inference."""
    if source not in USER_SOURCES:
        raise MemoryRefused(f"{source!r} is not a human channel; inferences belong in conclusions")
    text = extraction.normalise(text)
    if not 1 <= len(text) <= extraction.MAX_CHARS:
        raise ValueError(f"A memory needs between 1 and {extraction.MAX_CHARS} characters")
    now = datetime.utcnow()
    kind = kind or extraction.classify_kind(text)
    row = WorkspaceMemory(
        id=uuid.uuid4().hex, text=text, source=source, created_at=now,
        lang=extraction.detect_language(text), kind=kind, layer=int(Layer.USER),
        importance=IMPORTANCE.get(kind, .5) if importance is None else float(importance),
        valid_at=valid_at or now, retrievals=0)
    if cache is not None:
        if vector is None:
            vector = (await asyncio.to_thread(cache.embedder.passages, [text]))[0]
        row.embedding, row.embedding_model = embedding.pack(vector), cache.embedder.name
        cache.put(f"{MEMORY}:{row.id}", text, vector)
    db.add(row)
    if commit:
        await db.commit()
        await db.refresh(row)
    return row


async def conclude(db, *, text, sources, decision, confidence, rationale, stage,
                   kind="fact", lang="", related_to=None, layer=Layer.LEARNED,
                   author="aries:memory", valid_at=None, cache=None, vector=None, commit=True):
    """Write one inference at a machine layer, joined to the utterances behind it."""
    if Layer(int(layer)) not in MACHINE_WRITABLE:
        raise MemoryRefused(f"a machine author may not write {Layer(int(layer)).label}")
    if not sources:
        raise MemoryRefused("a conclusion with no source utterance cannot be explained")
    now = datetime.utcnow()
    row = WorkspaceConclusion(
        id=uuid.uuid4().hex, text=extraction.normalise(text), lang=lang, kind=kind,
        layer=int(layer), author=author, confidence=float(confidence), rationale=rationale,
        decision=decision, stage=stage, related_to=related_to,
        importance=IMPORTANCE.get(kind, .5), created_at=now, valid_at=valid_at or now)
    if cache is not None:
        if vector is None:
            vector = (await asyncio.to_thread(cache.embedder.passages, [row.text]))[0]
        row.embedding, row.embedding_model = embedding.pack(vector), cache.embedder.name
        cache.put(f"{CONCLUSION}:{row.id}", row.text, vector)
    db.add(row)
    await db.flush()
    for memory_id in dict.fromkeys(sources):
        db.add(WorkspaceConclusionSource(conclusion_id=row.id, memory_id=memory_id))
    if commit:
        await db.commit()
        await db.refresh(row)
    return row


async def _load(db, key):
    prefix, _, row_id = key.partition(":")
    return await db.get(WorkspaceMemory if prefix == MEMORY else WorkspaceConclusion, row_id)


async def arbitrate(db, winner, loser_key, *, commit=False, confirmed=False):
    """Require review for USER evidence, then order confirmed facts by time."""
    loser = await _load(db, loser_key)
    if loser is None:
        return None, "the contradicted row is gone"
    if isinstance(loser, WorkspaceMemory) or isinstance(winner, WorkspaceMemory):
        return None, "USER statements cannot be superseded; review a learned conclusion instead"
    user_sources = await provenance(db, loser.id)
    if user_sources and not confirmed:
        winner.decision = 'PENDING_REPLACE'
        winner.related_to = loser.id
        _drop_from_cache(f'{CONCLUSION}:{winner.id}')
        if commit:
            await db.commit()
        return None, "Explicit confirmation required before replacing a fact stated by the user"
    now = datetime.utcnow()
    stored_at = loser.valid_at or loser.created_at or now
    fresh_at = winner.valid_at or winner.created_at or now
    if stored_at > fresh_at:
        winner.invalid_at, winner.expired_at = stored_at, now
        winner.superseded_by = loser.id
        outcome = (winner, f"the stored note is newer in world time ({stored_at.isoformat()}), so it stands")
    else:
        loser.invalid_at, loser.expired_at = fresh_at, now
        loser.superseded_by = winner.id
        _drop_from_cache(loser_key)
        outcome = (loser, f"superseded by a later statement ({fresh_at.isoformat()})")
    if commit:
        await db.commit()
    return outcome


def _drop_from_cache(key):
    if _cache is not None:
        _cache.drop(key)


async def _live_conclusion_for(db, key):
    """The unexpired conclusion behind a cache key, or None.

    `c:<id>` is one directly. `m:<id>` is an utterance, so the conclusion drawn
    from it is what a machine is allowed to withdraw.
    """
    prefix, _, row_id = key.partition(":")
    if prefix == CONCLUSION:
        row = await db.get(WorkspaceConclusion, row_id)
        return row if row is not None and row.expired_at is None else None
    rows = (await db.execute(
        select(WorkspaceConclusion)
        .join(WorkspaceConclusionSource, WorkspaceConclusionSource.conclusion_id == WorkspaceConclusion.id)
        .where(WorkspaceConclusionSource.memory_id == row_id,
               WorkspaceConclusion.expired_at.is_(None))
        .order_by(WorkspaceConclusion.created_at.desc()))).scalars().all()
    return rows[0] if rows else None


async def withdrawn_sources(db):
    """Supersession never suppresses USER statements from retrieval."""
    return set()


async def pending_replacements(db):
    excluded, _ = await _privacy_rules(db)
    hidden = await _excluded_keys(db, excluded)
    proposals = []
    for row in await conclusions(db):
        if row.decision != 'PENDING_REPLACE' or not row.related_to:
            continue
        old = await db.get(WorkspaceConclusion, row.related_to)
        if old is None or old.expired_at is not None:
            continue
        if any(f'{CONCLUSION}:{x.id}' in hidden or _matches_exclusion(x.text, excluded) for x in (old, row)):
            continue
        proposals.append({'id': row.id, 'target_id': old.id, 'old': old.text, 'proposed': row.text,
                          'question': 'Да го заменам претходниот факт со предложениот?'})
    return proposals


async def review_replacement(db, proposal_id, target_id, *, approved):
    """Only the explicit review API calls this; model verdicts cannot approve."""
    proposal = next((p for p in await pending_replacements(db)
                     if p['id'] == proposal_id and p['target_id'] == target_id), None)
    if proposal is None:
        raise MemoryRefused('Replacement is stale, unavailable, or not awaiting confirmation')
    if approved is not True and approved is not False:
        raise MemoryRefused('An explicit boolean review decision is required')
    # Claim exactly one still-pending review while its target is still active.
    # SQLite serializes this conditional write; concurrent reviews cannot both
    # approve the same proposal or overwrite an already-replaced target.
    target = WorkspaceConclusion.__table__.alias('review_target')
    active_target = select(target.c.id).where(target.c.id == target_id,
                                              target.c.expired_at.is_(None)).exists()
    claimed = await db.execute(update(WorkspaceConclusion).where(
        WorkspaceConclusion.id == proposal_id,
        WorkspaceConclusion.decision == 'PENDING_REPLACE',
        WorkspaceConclusion.expired_at.is_(None), active_target).values(decision='REVIEWING'))
    if claimed.rowcount != 1:
        await db.rollback()
        raise MemoryRefused('Replacement was already reviewed or its target changed')
    winner = await db.get(WorkspaceConclusion, proposal_id)
    if approved is True:
        row, reason = await arbitrate(db, winner, f'{CONCLUSION}:{target_id}', confirmed=True)
        if row is None:
            raise MemoryRefused(reason)
        winner.decision = 'SUPERSEDE'
    elif approved is False:
        winner.expired_at = datetime.utcnow()
        winner.decision = 'REJECTED_REPLACE'
        _drop_from_cache(f'{CONCLUSION}:{winner.id}')
        reason = 'Kept the previous fact; USER statements remain available'
    else:
        raise MemoryRefused('An explicit boolean review decision is required')
    from agentic_core.observability.audit import log_event
    await log_event(db, actor_type='user', actor='memory-review', action='workspace.memory_replacement_reviewed',
                    detail={'proposal_id': proposal_id, 'target_id': target_id, 'approved': approved})
    await db.commit()
    return {'reviewed': True, 'approved': approved, 'reason': reason}


# ── the two entry points ─────────────────────────────────────────────────────

async def remember(db, text, *, source="user"):
    """What the user explicitly asked ARIES to keep. No cascade: they decided."""
    text = extraction.normalise(text)
    if not text or len(text) > extraction.MAX_CHARS:
        raise ValueError(f"A memory needs between 1 and {extraction.MAX_CHARS} characters")
    excluded,_ = await _privacy_rules(db)
    if _matches_exclusion(text,excluded):
        raise ValueError("This memory matches an excluded topic")
    cache = await _try_cache(db)
    # An explicitly stated fact is maximally important by definition; the
    # per-kind prior is for things ARIES noticed on its own.
    row = await record(db, text, source=source, importance=1., cache=cache)
    return row


async def observe(db, text, *, source="voice", cascade=None, commit=True):
    """The unasked write. Runs the cascade and returns what it decided and why.

    Off the voice path by construction — `observe_later` is what the loop calls,
    and it debounces. Blocking model work runs in threads; database sessions and
    cache mutations stay on this event loop. A background asyncio task alone
    does not prevent synchronous inference from freezing the API.
    """
    text = extraction.normalise(text)
    try:
        excluded,allowed=await _privacy_rules(db,observing=True)
    except MemoryRefused as exc:
        return {"stored":None,"verdict":extraction.Verdict("ABORT","gate",str(exc)).as_dict()}
    enabled = bool(await _setting(db, "workspace.semantic_memory", True))
    if not enabled:
        return {"stored": None, "verdict": extraction.Verdict(
            "ABORT", "gate", "workspace.semantic_memory is off").as_dict()}

    refused = extraction.gate(text, excluded=excluded, allowed=allowed)
    if refused is not None:
        return {"stored": None, "verdict": refused.as_dict()}     # stage 1 only; nothing embedded

    hidden=await _excluded_keys(db,excluded)
    cache = await _try_cache(db)
    if cache is None:
        return {"stored": None, "verdict": extraction.Verdict(
            "ABORT", "gate", "no embedder on this machine; run ./scripts/aries-fetch-embedder").as_dict()}

    if cascade is None:
        cascade = cascade_from_settings(await _cascade_settings(db))
    # Embedded ONCE, as a passage. Novelty asks "have I been told this already",
    # which compares a statement with statements, so both sides must carry the
    # same e5 prefix — `query:` against `passage:` is the asymmetric form meant
    # for a question against a document, and it puts a sentence at 0.95 against
    # a verbatim copy of itself, which is below the redundancy threshold. The
    # same vector is then what gets stored, so this costs one embed, not two.
    vector = (await asyncio.to_thread(cache.embedder.passages, [text]))[0]
    neighbours = [n for n in cache.neighbours(vector, limit=5+len(hidden)) if n[0] not in hidden][:5]
    verdict = await asyncio.to_thread(cascade.run, text, neighbours, excluded=excluded, allowed=allowed)

    # Inference may wait long enough for the user to change privacy preferences.
    # Re-read before any write or recency bump; model output cannot override them.
    try:
        excluded,allowed=await _privacy_rules(db,observing=True)
    except MemoryRefused as exc:
        return {"stored":None,"verdict":extraction.Verdict("ABORT","gate",str(exc)).as_dict()}
    refused=extraction.gate(text,excluded=excluded,allowed=allowed)
    if refused is not None:
        return {"stored":None,"verdict":refused.as_dict()}
    hidden=await _excluded_keys(db,excluded)
    if verdict.related_to in hidden:
        return {"stored":None,"verdict":extraction.Verdict("ABORT","gate","Related memory is excluded by privacy policy").as_dict()}

    if verdict.action == "NOOP":
        # Restating something already known is evidence it still matters, so the
        # neighbour's recency is refreshed. That is the whole write.
        bumped = await _load(db, verdict.related_to) if verdict.related_to else None
        if bumped is not None:
            bumped.retrievals = int(bumped.retrievals or 0) + 1
            bumped.last_retrieved_at = datetime.utcnow()
            if commit:
                await db.commit()
        return {"stored": None, "verdict": verdict.as_dict(), "bumped": verdict.related_to}
    if verdict.action == "ABORT":
        return {"stored": None, "verdict": verdict.as_dict()}

    # The user said it, so the utterance is kept verbatim at layer USER; what
    # ARIES made of it is a separate row at layer LEARNED. Both, or neither.
    utterance = await record(db, text, source=source, kind=verdict.kind, cache=cache,
                             vector=vector, commit=False)
    await db.flush()
    conclusion = await conclude(
        db, text=text, sources=[utterance.id], decision=verdict.action, vector=vector,
        confidence=verdict.confidence, rationale=_rationale(verdict), stage=verdict.stage,
        kind=verdict.kind, lang=verdict.lang,
        related_to=verdict.related_to.partition(":")[2] if verdict.related_to else None,
        cache=cache, commit=False)
    expired = None
    if verdict.action == "SUPERSEDE" and verdict.related_to:
        # An inferred contradiction is a proposal, not permission to replace a
        # user-backed fact. Arbitration retains both until explicit review.
        target = await _live_conclusion_for(db, verdict.related_to)
        if target is None:
            expired = {"id": None, "reason": "nothing to withdraw: the contradicted row is a user "
                                             "utterance with no live conclusion, and a machine may "
                                             "not expire what the user said"}
        else:
            row, reason = await arbitrate(db, conclusion, f"{CONCLUSION}:{target.id}")
            if row is not None:
                expired = {"id": row.id, "reason": reason}
            else:
                expired = {"id": None, "reason": reason, "confirmation_required": conclusion.decision == 'PENDING_REPLACE'}
    if commit:
        await db.commit()
        await db.refresh(utterance)
        await db.refresh(conclusion)
    return {"stored": {"memory": utterance.as_dict(), "conclusion": conclusion.as_dict()},
            "verdict": verdict.as_dict(), "expired": expired}


def _rationale(verdict):
    """Deterministic prose. Nothing here came out of a language model."""
    parts = [f"stage={verdict.stage}", f"decision={verdict.action}",
             f"confidence={verdict.confidence:.3f}", f"kind={verdict.kind}", f"lang={verdict.lang or '?'}"]
    if verdict.similarity is not None:
        parts.append(f"nearest={verdict.similarity:.3f}")
    if verdict.related_to:
        parts.append(f"against={verdict.related_to}")
    return verdict.reason + " · " + " ".join(parts)


def cascade_from_settings(values):
    return extraction.Cascade(**values)


async def _cascade_settings(db):
    return {
        "redundant_above": float(await _setting(db, "workspace.memory_redundant_above", extraction.REDUNDANT_ABOVE)),
        "novel_below": float(await _setting(db, "workspace.memory_novel_below", extraction.NOVEL_BELOW)),
        "model": await _setting(db, "workspace.memory_model", "qwen2.5:7b"),
    }


async def _try_cache(db):
    try:
        return await warm(db)
    except embedding.EmbedderUnavailable:
        return None
    except Exception as exc:                            # noqa: BLE001
        log.warning("semantic memory unavailable: %s", exc)
        return None


# ── the debounce that keeps this off the voice path ──────────────────────────

_pending: list[tuple[str, str]] = []
_flusher: asyncio.Task | None = None


def observe_later(text, *, source="voice", delay=DEBOUNCE_SECONDS):
    """Queue an utterance and return immediately. Never awaited by the caller.

    The voice loop acts in ~25 ms after a ~900 ms transcription. Anything that
    embeds or asks a model belongs after that, not inside it.
    """
    global _flusher
    text = extraction.normalise(text)
    if not text:
        return False
    _pending.append((text, source))
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False                     # no loop: the caller flushes explicitly
    if _flusher is None or _flusher.done():
        _flusher = loop.create_task(_flush(delay))
    return True


async def _flush(delay):
    await asyncio.sleep(delay)
    from agentic_core.database.base import async_session
    while _pending:
        batch, _pending[:] = list(_pending), []
        for text, source in batch:
            # New utterances can arrive while inference is off-thread. Drain
            # them before this task exits; otherwise they wait indefinitely
            # for an unrelated future command to restart the flusher.
            async with async_session() as db:
                try:
                    await observe(db, text, source=source)
                except Exception as exc:                # noqa: BLE001
                    await db.rollback()
                    log.warning("observe(%r) failed: %s", text[:60], exc)


async def drain():
    """Flush anything queued, now. For tests and for shutdown."""
    global _flusher
    if _flusher is not None and not _flusher.done():
        _flusher.cancel()
        _flusher = None
    await _flush(0)


# ── reads and expiry ─────────────────────────────────────────────────────────

async def utterances(db, *, include_expired=False):
    query = select(WorkspaceMemory).order_by(WorkspaceMemory.created_at.desc())
    if not include_expired:
        query = query.where(WorkspaceMemory.expired_at.is_(None))
    return (await db.execute(query)).scalars().all()


async def conclusions(db, *, include_expired=False):
    query = select(WorkspaceConclusion).order_by(WorkspaceConclusion.created_at.desc())
    if not include_expired:
        query = query.where(WorkspaceConclusion.expired_at.is_(None))
    return (await db.execute(query)).scalars().all()


async def provenance(db, conclusion_id):
    """The utterances a conclusion was drawn from — the foreign key, read back."""
    rows = (await db.execute(
        select(WorkspaceMemory)
        .join(WorkspaceConclusionSource, WorkspaceConclusionSource.memory_id == WorkspaceMemory.id)
        .where(WorkspaceConclusionSource.conclusion_id == conclusion_id))).scalars().all()
    return [r.as_dict() for r in rows]


async def expire(db, key_or_id, *, reason="forgotten", commit=True):
    """Stop believing something, without losing it. The only 'delete' there is."""
    key = key_or_id if ":" in key_or_id else f"{MEMORY}:{key_or_id}"
    row = await _load(db, key)
    if row is None:
        return False
    row.expired_at = datetime.utcnow()
    if getattr(row, "invalid_at", None) is None:
        row.invalid_at = row.expired_at
    _drop_from_cache(key)
    if commit:
        await db.commit()
    log.info("expired %s (%s)", key, reason)
    return True


async def forget(db, memory_id, *, commit=True):
    """Expire an utterance AND everything ARIES concluded from it.

    Forgetting the evidence while keeping the inference drawn from it would
    leave a conclusion that can no longer be explained, which the provenance
    rule does not allow to exist.
    """
    row = await db.get(WorkspaceMemory, memory_id)
    if row is None:
        return False
    await expire(db, f"{MEMORY}:{memory_id}", reason="forget", commit=False)
    derived = (await db.execute(
        select(WorkspaceConclusion)
        .join(WorkspaceConclusionSource, WorkspaceConclusionSource.conclusion_id == WorkspaceConclusion.id)
        .where(WorkspaceConclusionSource.memory_id == memory_id,
               WorkspaceConclusion.expired_at.is_(None)))).scalars().all()
    for conclusion in derived:
        await expire(db, f"{CONCLUSION}:{conclusion.id}", reason="source forgotten", commit=False)
    if commit:
        await db.commit()
    return True


async def relevant(db, request, *, version=None, limit=8, touch_retrieved=True):
    """What to put in front of a request — utterances AND conclusions, ranked.

    This is the one place the two tables meet, which is the whole point of
    keeping them apart everywhere else. `layer` is a term in the score, so at
    equal similarity what the user said outranks what ARIES inferred, by
    arithmetic rather than by the order somebody wrote the queries in.
    """
    from aries.workspace import retrieval
    try:
        excluded,_=await _privacy_rules(db)
    except MemoryRefused:
        log.warning("Memory context withheld: privacy policy is unavailable")
        return []
    hidden=await _excluded_keys(db,excluded)
    version = version or await _setting(db, "workspace.memory_retrieval", "semantic-v3")
    cache = await _try_cache(db) if version == "semantic-v3" else None
    rows, query_vector = [], None
    withdrawn = await withdrawn_sources(db)
    for prefix, model in ((MEMORY, WorkspaceMemory), (CONCLUSION, WorkspaceConclusion)):
        for row in (await db.execute(select(model).where(model.expired_at.is_(None)))).scalars().all():
            if prefix == MEMORY and row.id in withdrawn:
                continue        # the user later said otherwise; the row stays, the belief does not
            if prefix == CONCLUSION and row.decision == 'PENDING_REPLACE':
                continue  # A proposed interpretation is not an accepted fact.
            item = row.as_dict()
            item["key"] = f"{prefix}:{row.id}"
            if item["key"] in hidden:
                continue
            item["created_at"] = row.created_at
            item["last_retrieved_at"] = row.last_retrieved_at
            if cache is not None:
                item["vector"] = cache.vectors.vector_for(item["key"])
            rows.append(item)
    if cache is not None:
        query_vector = await asyncio.to_thread(cache.embedder.query, request)
    scored = retrieval.score_memories(rows, request, version if cache is not None else
                                      ("focused-v2" if version == "semantic-v3" else version),
                                      query_vector=query_vector, limit=limit)
    if touch_retrieved and scored:
        await touch(db, [row["key"] for _, row, _ in scored])
    return scored


async def touch(db, keys, *, commit=True):
    """Recency refreshed ON RETRIEVAL, per Park et al. — being useful is the
    evidence that a memory still matters, and it is the only such evidence that
    costs nothing to collect."""
    now = datetime.utcnow()
    changed = 0
    for key in keys:
        row = await _load(db, key)
        if row is None:
            continue
        row.retrievals = int(row.retrievals or 0) + 1
        row.last_retrieved_at = now
        changed += 1
    if commit and changed:
        await db.commit()
    return changed
