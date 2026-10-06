"""Durable workspace rows — and the memory split the whole project turns on.

WHAT THE USER SAID and WHAT ARIES CONCLUDED live in two different tables.

`aries_workspace_memories` holds **utterances**: verbatim, in the language they
were spoken in, always layer USER. It has no `confidence` and no `rationale`
columns, because a thing the user said is not a guess and there is nothing to
justify. `aries_workspace_conclusions` holds what ARIES decided about those
utterances: layer LEARNED, always with a confidence and a rationale, and joined
back to the utterances it was drawn from by a real foreign key through
`aries_workspace_conclusion_sources`.

The separation is therefore STRUCTURAL, exactly as it is for `aries_interests`
(user `weight` and machine `learned_weight` in separate columns). A machine
writer cannot smuggle an inference into the user layer, because the user table
has nowhere to put the confidence that would make it an inference, and
`aries.workspace.memory.store` refuses the layer outright. The two meet only in
`aries.workspace.retrieval`, at resolution.

FOUR TIMESTAMPS, NEVER A DELETE
-------------------------------
Zep (arXiv:2501.13956) separates *world time* from *system time*, and this
schema copies it:

    valid_at     when the fact became true in the world
    invalid_at   when it stopped being true in the world
    created_at   when this row was written
    expired_at   when ARIES stopped believing it

Forgetting sets `expired_at`; contradiction sets `invalid_at` and
`superseded_by`. Nothing is ever deleted, so "why did you stop thinking that?"
always has an answer, and a wrong expiry is recoverable.
"""
import json
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base
from aries.settings.layers import Layer

# How fast one kind of memory should stop mattering, as a half-life in hours.
# Park et al. (arXiv:2304.03442) score retrieval with a single global decay; a
# single constant is wrong here because the kinds are not comparable. "I am
# doing a master's" should still be true next year; "open YouTube" should not
# outrank anything tomorrow. The constant is therefore per kind.
KINDS = ("identity", "preference", "fact", "plan", "episodic", "utterance")
HALF_LIFE_HOURS = {
    "identity": 24 * 3650.,     # who the user is — effectively permanent
    "preference": 24 * 180.,    # tastes drift over months
    "fact": 24 * 365.,          # a stated fact about the world or the machine
    "plan": 24 * 14.,           # an intention, stale within a fortnight
    "episodic": 24 * 30.,       # something that happened
    "utterance": 24 * 3.,       # a raw command; almost immediately uninteresting
}
# Not Park's LLM "poignancy" score, and deliberately not called that: no model is
# asked how important a memory is, because that is one model call per turn for a
# number nobody can check. This is a fixed prior per kind, and an explicit
# `remember ...` overrides it to 1.0 in the store.
IMPORTANCE = {"identity": .9, "preference": .7, "fact": .6, "plan": .5,
              "episodic": .35, "utterance": .2}


class WorkspaceGoal(Base):
    __tablename__ = "aries_workspace_goals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    def as_dict(self):
        return {"id": self.id, "request": self.request, "state": self.state,
                "updated_at": self.updated_at.isoformat(),
                "created_at": self.created_at.isoformat(), **json.loads(self.result_json)}


class WorkspaceMemory(Base):
    """One thing the user said, kept word for word and in their own language.

    Never written by a machine author. `text` is never rewritten, never
    translated and never summarised — mem0 v2 dropped its same-language
    guarantee and now stores Macedonian speech as English, which is precisely
    the failure this column forbids by never being generated at all.
    """
    __tablename__ = "aries_workspace_memories"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(120), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # ── added with semantic memory; every one is nullable or defaulted so that
    # `create_all` on a new database and the ALTER path on an existing one
    # produce the same shape (aries/workspace/memory/migration.py).
    lang: Mapped[str] = mapped_column(String(8), default="")
    kind: Mapped[str] = mapped_column(String(24), default="fact")
    layer: Mapped[int] = mapped_column(Integer, default=int(Layer.USER))
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(64), default="")
    importance: Mapped[float] = mapped_column(Float, default=0.)
    valid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    retrievals: Mapped[int] = mapped_column(Integer, default=0)
    last_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def as_dict(self):
        # Additive: `id`, `text`, `source` and `created_at` are what the Control
        # Centre and the shell already read, and they keep their meaning.
        return {"id": self.id, "text": self.text, "source": self.source,
                "created_at": self.created_at.isoformat(),
                "lang": self.lang or "", "kind": self.kind or "fact",
                "layer": int(self.layer or Layer.USER), "layer_name": Layer(int(self.layer or Layer.USER)).label,
                "importance": float(self.importance or 0.),
                "retrievals": int(self.retrievals or 0),
                "valid_at": self.valid_at.isoformat() if self.valid_at else None,
                "invalid_at": self.invalid_at.isoformat() if self.invalid_at else None,
                "expired_at": self.expired_at.isoformat() if self.expired_at else None,
                "superseded_by": self.superseded_by,
                "embedded": bool(self.embedding)}


class WorkspaceConclusion(Base):
    """One thing ARIES decided on its own, and why.

    Layer is LEARNED and the store refuses anything stronger, so this row can
    never outrank what the user said. `text` is a *copy* of the utterance it was
    drawn from rather than a model's paraphrase — see `decision`/`rationale` for
    what the model actually contributed, which is a label and a number.
    """
    __tablename__ = "aries_workspace_conclusions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(8), default="")
    kind: Mapped[str] = mapped_column(String(24), default="fact", index=True)
    layer: Mapped[int] = mapped_column(Integer, default=int(Layer.LEARNED))
    author: Mapped[str] = mapped_column(String(120), default="aries:memory")

    # What every inferred row in this project is required to carry.
    confidence: Mapped[float] = mapped_column(Float, default=0.)
    rationale: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(String(16), default="APPEND", index=True)
    stage: Mapped[str] = mapped_column(String(16), default="novelty")
    related_to: Mapped[str | None] = mapped_column(String(40), nullable=True)

    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(64), default="")
    importance: Mapped[float] = mapped_column(Float, default=0.)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    valid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    retrievals: Mapped[int] = mapped_column(Integer, default=0)
    last_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def as_dict(self):
        return {"id": self.id, "text": self.text, "lang": self.lang or "",
                "kind": self.kind, "layer": int(self.layer), "layer_name": Layer(int(self.layer)).label,
                "source": self.author, "confidence": round(float(self.confidence or 0.), 4),
                "rationale": self.rationale or "", "decision": self.decision,
                "stage": self.stage, "related_to": self.related_to,
                "importance": float(self.importance or 0.),
                "retrievals": int(self.retrievals or 0),
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "valid_at": self.valid_at.isoformat() if self.valid_at else None,
                "invalid_at": self.invalid_at.isoformat() if self.invalid_at else None,
                "expired_at": self.expired_at.isoformat() if self.expired_at else None,
                "superseded_by": self.superseded_by,
                "embedded": bool(self.embedding)}


class WorkspaceConclusionSource(Base):
    """The join that makes provenance a foreign key rather than a convention.

    A conclusion with no row here cannot be explained, so `store.conclude`
    refuses to write one.
    """
    __tablename__ = "aries_workspace_conclusion_sources"
    conclusion_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("aries_workspace_conclusions.id"), primary_key=True)
    memory_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("aries_workspace_memories.id"), primary_key=True)
    # When the link was made — a conclusion can gain a source later, and the
    # retention register requires every table to name a timestamp it could be
    # pruned by, even the ones that are never pruned.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
