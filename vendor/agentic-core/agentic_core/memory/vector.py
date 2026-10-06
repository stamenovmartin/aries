"""Vector memory (RAG) — long-term memory with cosine retrieval.
Lifted from backend/app/services/memory/__init__.py. Default embedding is a
deterministic lexical hash (char trigrams + words, L2-normalised) so retrieval
works with no model; Ollama embeddings are opt-in. Similarity is computed in
Python (fine to thousands of items); pgvector is the documented scale-up."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.config.settings import settings
from agentic_core.database.models import MemoryItem

logger = logging.getLogger(__name__)
KINDS = ("fact", "rule", "task", "tool", "incident", "note")
_LEX_DIM = 512
_ollama_ok: bool | None = None


def _normalize(vec):
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n > 0 else vec


def lexical_embed(text: str) -> list[float]:
    t = re.sub(r"\s+", " ", (text or "").lower()).strip()
    vec = [0.0] * _LEX_DIM
    if not t:
        return vec
    grams = []
    for w in re.findall(r"\w+", t):
        grams.append(f"w:{w}")
        padded = f"#{w}#"
        grams += [padded[i:i + 3] for i in range(len(padded) - 2)]
    for g in grams:
        vec[int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % _LEX_DIM] += 1.0
    return _normalize(vec)


async def _ollama_embed(text: str):
    global _ollama_ok
    if _ollama_ok is False:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(f"{settings.ollama_base_url.rstrip('/')}/api/embeddings",
                                  json={"model": settings.ollama_model, "prompt": text})
            if r.status_code == 200:
                emb = r.json().get("embedding")
                if isinstance(emb, list) and emb:
                    _ollama_ok = True
                    return _normalize([float(x) for x in emb])
    except Exception:
        pass
    _ollama_ok = False
    return None


async def embed(text: str) -> tuple[list[float], str]:
    if settings.memory_embeddings == "ollama":
        v = await _ollama_embed(text)
        if v is not None:
            return v, f"ollama:{settings.ollama_model}"
    return lexical_embed(text), "lexical"


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


async def remember(db: AsyncSession, *, kind: str, title: str, content: str, ref_id: int | None = None,
                   meta: dict | None = None) -> MemoryItem:
    vec, backend = await embed(content)
    row = MemoryItem(kind=kind, ref_id=ref_id, title=title[:255], content=content, embedding=json.dumps(vec),
                     dim=len(vec), backend=backend, meta=json.dumps(meta or {}, ensure_ascii=False))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def recall(db: AsyncSession, query: str, *, kinds: list[str] | None = None, top_k: int = 5,
                 min_score: float = 0.0) -> list[tuple[MemoryItem, float]]:
    qvec, _ = await embed(query)
    dim = len(qvec)
    stmt = select(MemoryItem).where(MemoryItem.dim == dim)
    if kinds:
        stmt = stmt.where(MemoryItem.kind.in_(kinds))
    scored = []
    for r in (await db.execute(stmt)).scalars().all():
        try:
            v = json.loads(r.embedding)
        except (json.JSONDecodeError, TypeError):
            continue
        if len(v) != dim:
            continue
        s = _cosine(qvec, v)
        if s >= min_score:
            scored.append((r, s))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


async def recall_context(db: AsyncSession, query: str, *, kinds=None, top_k: int = 4, min_score: float = 0.12) -> str | None:
    """The prompt block the marketing 'memory' node produced."""
    hits = await recall(db, query, kinds=kinds, top_k=top_k, min_score=min_score)
    if not hits:
        return None
    return "Relevant knowledge from memory (use if it helps, do not repeat verbatim):\n" + "\n".join(f"- {m.content}" for m, _ in hits)


async def ask(db: AsyncSession, question: str, *, kinds=None, top_k: int = 5) -> dict:
    """RAG: recall, then let the model answer grounded ONLY in what was recalled."""
    from agentic_core.llm import providers
    hits = await recall(db, question, kinds=kinds, top_k=top_k)
    sources = [{"id": m.id, "kind": m.kind, "title": m.title, "content": m.content, "score": round(s, 3)} for m, s in hits]
    if not sources:
        return {"answer": "No relevant memory for this question.", "sources": [], "provider": None}
    context = "\n\n".join(f"[{i + 1}] ({s['kind']}) {s['title']}: {s['content']}" for i, s in enumerate(sources))
    answer = await providers.complete("Answer using ONLY the given context. If it is insufficient, say what is missing.",
                                      f"Context:\n{context}\n\nQuestion: {question}", purpose="memory_ask")
    return {"answer": (answer or "").strip() or "No provider was available to synthesise an answer.",
            "sources": [{k: v for k, v in s.items() if k != "content"} | {"snippet": s["content"][:180]} for s in sources],
            "provider": providers.describe()["provider"] if answer else None}


async def forget_seeded(db: AsyncSession) -> int:
    n = 0
    for m in (await db.execute(select(MemoryItem))).scalars().all():
        try:
            meta = json.loads(m.meta) if m.meta else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        if meta.get("seeded"):
            await db.delete(m); n += 1
    await db.commit()
    return n


async def stats(db: AsyncSession) -> dict:
    by_kind = {k or "?": c for k, c in (await db.execute(select(MemoryItem.kind, func.count()).group_by(MemoryItem.kind))).all()}
    return {"total": sum(by_kind.values()), "by_kind": by_kind}
