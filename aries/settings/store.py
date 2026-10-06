"""WHERE setting values live.

One row per (key, layer, scope). That shape is what makes section 30's
precedence inspectable rather than merely implemented: because an overridden
value is still a row, the Settings app can show the user "you set this to 0.5;
ARIES had learned 0.72", and clearing the explicit value promotes the learned
one again without re-learning it.

CONCEPT — why not one row per key? A single-row design would have to destroy the
learned value the moment the user typed one, which loses information the system
paid for, and makes "what would ARIES do if I cleared this?" unanswerable.
Storing every layer separately costs a few rows and buys full auditability. The
uniqueness constraint is therefore on the TRIPLE (key, layer, scope), not on the
key alone.

CONCEPT — scope. The same key can be configured globally and again for one
project ("brief me at 08:00, but for the Insomnia project use 07:00"). `scope`
is the empty string for global values and an identifier such as
`project:insomnia` otherwise. Resolution asks for a scope and falls back to
global, so a scoped value only has to exist where it actually differs.

Values are stored as JSON text. SQLite has no native JSON column and the engine
targets both SQLite and PostgreSQL, so a TEXT column with explicit
serialisation is the portable choice; it also keeps the stored form stable and
diffable, which matters for an audit trail.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

from aries.settings.layers import Layer

GLOBAL = ""          # the scope of a value that applies everywhere


class AriesSetting(Base):
    """One value of one setting, at one layer, in one scope."""

    __tablename__ = "aries_settings"
    __table_args__ = (UniqueConstraint("key", "layer", "scope", name="uq_aries_setting"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(200), index=True)
    layer: Mapped[int] = mapped_column(Integer, index=True)
    scope: Mapped[str] = mapped_column(String(120), default=GLOBAL, index=True)
    # JSON-encoded value. NULL is impossible on purpose: an absent setting is an
    # absent ROW, never a row holding null, so "unset" has exactly one spelling.
    value_json: Mapped[str] = mapped_column(Text)
    # Why this value exists. For a learned layer this is the evidence trail the
    # Memory Control Centre (specification section 29) shows the user.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_by: Mapped[str] = mapped_column(String(120), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    def decoded(self):
        return json.loads(self.value_json)

    def as_dict(self) -> dict:
        layer = Layer(self.layer)
        return {"key": self.key, "layer": layer.name.lower(), "layer_label": layer.label,
                "scope": self.scope or None, "value": self.decoded(),
                "confidence": self.confidence, "rationale": self.rationale, "set_by": self.set_by,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}


async def read(db: AsyncSession, key: str, *, scopes: list[str]) -> dict[Layer, AriesSetting]:
    """Every stored row for one key within the given scopes, strongest scope kept.

    `scopes` is ordered weakest-first (e.g. ["", "project:insomnia"]), so a later
    scope overwrites an earlier one at the same layer.
    """
    rows = (await db.execute(
        select(AriesSetting).where(AriesSetting.key == key, AriesSetting.scope.in_(scopes))
    )).scalars().all()
    rank = {s: i for i, s in enumerate(scopes)}
    best: dict[Layer, AriesSetting] = {}
    for r in rows:
        layer = Layer(r.layer)
        held = best.get(layer)
        if held is None or rank.get(r.scope, -1) >= rank.get(held.scope, -1):
            best[layer] = r
    return best


async def read_many(db: AsyncSession, keys: list[str], *, scopes: list[str]) -> dict[str, dict[Layer, AriesSetting]]:
    """The same as `read`, for many keys in one query — the path the agent
    context digest uses, so building it is one round trip and not one per key."""
    if not keys:
        return {}
    rows = (await db.execute(
        select(AriesSetting).where(AriesSetting.key.in_(keys), AriesSetting.scope.in_(scopes))
    )).scalars().all()
    rank = {s: i for i, s in enumerate(scopes)}
    out: dict[str, dict[Layer, AriesSetting]] = {}
    for r in rows:
        layer = Layer(r.layer)
        held = out.setdefault(r.key, {}).get(layer)
        if held is None or rank.get(r.scope, -1) >= rank.get(held.scope, -1):
            out[r.key][layer] = r
    return out


async def write(db: AsyncSession, key: str, layer: Layer, value, *, scope: str = GLOBAL,
                confidence: float | None = None, rationale: str | None = None,
                set_by: str = "system") -> AriesSetting:
    """Insert or update the row for (key, layer, scope). Does not commit."""
    row = (await db.execute(
        select(AriesSetting).where(AriesSetting.key == key, AriesSetting.layer == int(layer),
                                   AriesSetting.scope == scope)
    )).scalar_one_or_none()
    payload = json.dumps(value, ensure_ascii=False, default=str)
    if row is None:
        row = AriesSetting(key=key, layer=int(layer), scope=scope, value_json=payload,
                           confidence=confidence, rationale=rationale, set_by=set_by)
        db.add(row)
    else:
        row.value_json = payload
        row.confidence = confidence
        row.rationale = rationale
        row.set_by = set_by
    await db.flush()
    return row


async def clear(db: AsyncSession, key: str, layer: Layer, *, scope: str = GLOBAL) -> int:
    """Remove one layer's value so the next-strongest layer takes over."""
    res = await db.execute(delete(AriesSetting).where(
        AriesSetting.key == key, AriesSetting.layer == int(layer), AriesSetting.scope == scope))
    await db.flush()
    return res.rowcount or 0


async def history(db: AsyncSession, key: str) -> list[AriesSetting]:
    """Every stored layer and scope for a key — what the Settings app shows
    under "why is this value what it is?"."""
    rows = (await db.execute(
        select(AriesSetting).where(AriesSetting.key == key).order_by(AriesSetting.layer.desc())
    )).scalars().all()
    return list(rows)
