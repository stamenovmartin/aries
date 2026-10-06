"""The typed Settings Service — specification section 31.

Every consumer reads settings HERE. Not from the environment, not from a copy
an agent kept, not from a YAML file: one service, so that when the user changes
a preference in one place the whole system changes with it, and so that the
precedence rules of section 30 are applied exactly once rather than
re-implemented (differently, and wrongly) in each caller.

The service does four things:

  get / get_many   resolve a key through the layer stack for a scope
  explain          the same resolution, but showing its work
  set / clear      write a value at a layer, with the write rules enforced
  digest           a compact, agent-readable view of a whole section

THE WRITE RULES, and why they exist
-----------------------------------
Section 30 says learned behaviour must never override an explicit user
preference. Read-side precedence alone does not achieve that: a learning loop
that is allowed to WRITE the USER layer would launder an inference into a
statement the user never made, and the read rules would then faithfully honour
it. So the write path enforces two constraints:

  1. an author marked as a machine may only write DEFAULT, HISTORICAL or LEARNED
     (`layers.MACHINE_WRITABLE`);
  2. a setting declared `user_only` refuses every machine layer outright, for
     knobs where even a suggestion is inappropriate — security posture,
     autonomy level, anything that spends money or reaches outside.

Together these make "ARIES decided to change what you asked for" unrepresentable
rather than merely discouraged.

CONCEPT — an async service over a database session. Reads hit the database. That
is deliberate: settings must be correct across the API process, the scheduler
workers and any agent, and a per-process cache would let those drift apart the
moment the user changed something. Where a hot path needs many keys, `get_many`
and `digest` fetch them in ONE query rather than N.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from agentic_core.observability import audit

from aries.settings import schema, store
from aries.settings.layers import MACHINE_WRITABLE, Layer
from aries.settings.schema import SettingDef, SettingError

logger = logging.getLogger(__name__)

# Authors that count as a human statement. Anything else is a machine.
HUMAN_AUTHORS = ("user", "human", "ui", "onboarding", "api:user")


class SettingsService:
    """Resolve and change settings for one scope chain."""

    def __init__(self, db: AsyncSession, *, scope: str | None = None):
        self.db = db
        # Weakest first: global, then the scoped override.
        self.scopes: list[str] = [store.GLOBAL] + ([scope] if scope else [])
        self.scope = scope or store.GLOBAL

    # ── read ────────────────────────────────────────────────────────────────
    async def get(self, key: str, fallback: Any = ...) -> Any:
        """The winning value for `key`. Unknown keys raise unless a fallback is given."""
        d = schema.get_def(key)
        if d is None:
            if fallback is not ...:
                return fallback
            raise SettingError(f"unknown setting '{key}'")
        rows = await store.read(self.db, key, scopes=self.scopes)
        if not rows:
            return d.default
        winner = max(rows)
        return rows[winner].decoded()

    async def get_many(self, keys: Iterable[str]) -> dict[str, Any]:
        """Resolve several keys in one query."""
        wanted = [k for k in keys if schema.get_def(k) is not None]
        rows = await store.read_many(self.db, wanted, scopes=self.scopes)
        out: dict[str, Any] = {}
        for k in wanted:
            layers = rows.get(k)
            out[k] = layers[max(layers)].decoded() if layers else schema.require(k).default
        return out

    async def section(self, section: str) -> dict[str, Any]:
        """Every resolved value in a Settings section, keyed by dot path."""
        return await self.get_many([d.key for d in schema.in_section(section)])

    async def explain(self, key: str) -> dict:
        """The resolution, showing its work: the winner, and every layer that lost.

        This is what makes the system inspectable instead of magical — the
        Settings app renders it as "you set 0.5; ARIES had learned 0.72"."""
        d = schema.require(key)
        rows = await store.read(self.db, key, scopes=self.scopes)
        stack = [rows[layer].as_dict() for layer in sorted(rows, reverse=True)]
        if rows:
            winner = max(rows)
            value, source = rows[winner].decoded(), Layer(winner)
        else:
            value, source = d.default, Layer.DEFAULT
        return {"key": key, "value": value, "source": source.name.lower(),
                "source_label": source.label, "definition": d.describe(),
                "scope": self.scope or None, "stack": stack,
                "overridden": [s for s in stack if s["layer"] != source.name.lower()]}

    async def digest(self, prefix: str = "", *, include_advanced: bool = False) -> dict:
        """A compact view for an agent's prompt: {key: value} plus one line of
        description each, so the model knows what the knob MEANS and not only
        what it is set to."""
        defs = schema.matching(prefix) if prefix else schema.all_defs()
        defs = [d for d in defs if include_advanced or not d.advanced]
        values = await self.get_many([d.key for d in defs])
        return {d.key: {"value": values[d.key], "what": d.description} for d in defs}

    # ── write ───────────────────────────────────────────────────────────────
    async def set(self, key: str, value: Any, *, layer: Layer = Layer.USER,
                  set_by: str = "user", scope: str | None = None,
                  confidence: float | None = None, rationale: str | None = None,
                  commit: bool = True) -> dict:
        """Write a value at a layer. Validates, enforces the write rules, audits."""
        d = schema.require(key)
        author_is_human = set_by.split(":")[0] in HUMAN_AUTHORS or set_by in HUMAN_AUTHORS

        if not author_is_human and layer not in MACHINE_WRITABLE:
            raise SettingError(
                f"{key}: '{set_by}' is not a human author and may not write the "
                f"{layer.label} layer — learned behaviour never overrides an explicit preference")
        if d.user_only and layer in MACHINE_WRITABLE and not author_is_human:
            raise SettingError(f"{key}: this setting is user-only and cannot be set by {set_by}")

        coerced = d.coerce(value)
        target_scope = store.GLOBAL if scope is None else scope
        before = await self.get(key)
        row = await store.write(self.db, key, layer, coerced, scope=target_scope,
                                confidence=confidence, rationale=rationale, set_by=set_by)
        await audit.log_event(
            self.db, actor_type="human" if author_is_human else "system", actor=set_by,
            action="setting.changed", entity_type="setting", entity_id=row.id,
            detail={"key": key, "layer": layer.name.lower(), "scope": target_scope or None,
                    "from": before, "to": coerced, "rationale": rationale})
        if commit:
            await self.db.commit()
        after = await self.get(key)
        return {"key": key, "written": coerced, "layer": layer.name.lower(),
                "scope": target_scope or None, "effective": after,
                "shadowed": after != coerced,
                "note": None if after == coerced else
                        f"stored, but a stronger layer still decides this setting (effective: {after!r})"}

    async def clear(self, key: str, *, layer: Layer = Layer.USER, scope: str | None = None,
                    set_by: str = "user", commit: bool = True) -> dict:
        """Remove one layer's value; the next-strongest layer takes over."""
        schema.require(key)
        target_scope = store.GLOBAL if scope is None else scope
        removed = await store.clear(self.db, key, layer, scope=target_scope)
        await audit.log_event(self.db, actor_type="human", actor=set_by, action="setting.cleared",
                              entity_type="setting", detail={"key": key, "layer": layer.name.lower(),
                                                             "scope": target_scope or None, "removed": removed})
        if commit:
            await self.db.commit()
        return {"key": key, "removed": removed, "effective": await self.get(key)}

    async def learn(self, key: str, value: Any, *, confidence: float, rationale: str,
                    set_by: str = "learning", scope: str | None = None, commit: bool = True) -> dict:
        """The learning loops' only entry point (specification section 16).

        It cannot reach a user layer even by mistake, and a value the user has
        explicitly set is reported back as shadowed rather than applied."""
        return await self.set(key, value, layer=Layer.LEARNED, set_by=set_by, scope=scope,
                              confidence=confidence, rationale=rationale, commit=commit)


async def for_request(db: AsyncSession, scope: str | None = None) -> SettingsService:
    return SettingsService(db, scope=scope)
