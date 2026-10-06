# ADR-0003 — Precedence enforced on the write path, not only the read path

**Status:** accepted · **Date:** 2026-09-12 · **Journal:** Entry 002

## Context

§30 fixes an eight-level precedence order and states: *never allow learned behaviour to
override an explicit user preference.* §25 requires that the user can inspect and override
anything ARIES infers. §31 requires a typed service that agents read through.

A system that merely *reads* in the right order has implemented a convention. A learning loop
that writes into the user's layer defeats it entirely — and worse, destroys provenance:
afterwards nobody can tell whether the user asked for a value or the machine decided it.

## Options

1. **Read-side precedence only.** Simple; relies on every writer behaving. The first
   over-confident learner violates it silently.
2. **One row per key.** Simplest schema, but a learned value must be destroyed the moment the
   user types one — throwing away information the system paid for, and making "what would
   ARIES do if I cleared this?" unanswerable.
3. **One row per (key, layer, scope), plus write-side authorisation.**

## Decision

Option 3.

**Storage.** One row per `(key, layer, scope)`. Overridden values are kept, not overwritten,
each carrying `set_by`, `confidence` and `rationale`.

**Read.** `max()` over the layers present, after keeping the strongest scope per layer.

**Write, which is what makes the read honest:**

1. An author not recognised as human may write only `DEFAULT`, `HISTORICAL`, `LEARNED`.
   Attempting a user layer raises.
2. A setting marked `user_only` refuses every machine write outright — `autonomy.level`,
   `ai.daily_cost_limit`, `ai.send_file_contents`, `privacy.*`.

`SettingsService.learn()` is the learning loops' only entry point and cannot reach a user
layer even by mistake. When what it writes is shadowed by a user value, it is told so in the
return value rather than silently ignored.

## Consequences

**Positive.** "ARIES changed what you asked for" is unrepresentable rather than discouraged.
Provenance survives: the Settings app can show "you set 0.5; ARIES had learned 0.72, because
12 of 15 low scorers were ignored". Clearing a user value promotes the learned one rather
than falling all the way back to the default. Every change is audited with before and after.

**Negative.** More rows than a flat store, and hand-written validation in `SettingDef.coerce`
instead of leaning on pydantic — accepted as the cost of runtime introspectability.

**Open risk.** The write rules currently trust the `set_by` string. Acceptable while all
callers are in-process; before settings become writable over the API, the author must be
derived from the authenticated principal.

**Pinned by** `tests/test_settings.py::test_user_beats_learned`,
`::test_machine_cannot_write_user_layers`, `::test_security_layer_is_absolute`.
