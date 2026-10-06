# ADR-0001 — Build ARIES on the `agentic_core` engine

**Status:** accepted · **Date:** 2026-09-12 · **Journal:** Entry 001

## Context

ARIES needs orchestration semantics that are expensive to get right: resumable plans, a
failure taxonomy that distinguishes "retry is safe" from "retry would double-execute",
at-most-once side effects, durable approval gates, and state machines whose illegal
transitions cannot be expressed. Every component built above these assumes them, so
retrofitting is not realistic.

An existing asset was available: `agentic-orchestration-export`, a domain-neutral engine
extracted from a production marketing system, shipping all of the above with 13 passing test
files, a migration guide explicitly aimed at "an Agentic Linux Operating Environment", and a
working `examples/linux_agent` starter.

## Options

1. **Build from scratch** — exactly the specified architecture; but re-learns, at production
   cost, lessons the engine already encodes.
2. **Adopt LangGraph / AutoGen / CrewAI** — mature and well documented, but they are graph
   and conversation frameworks. None ships a durable approval lifecycle, a dry-run/live
   gate, an operations ledger or a per-task audit trail. Those would still have to be built,
   now inside someone else's abstractions. §3 warns against adopting for popularity.
3. **Build on `agentic_core`** — the needed semantics exist and are tested.

## Decision

Option 3, with a strict boundary. The engine is vendored **unmodified** at
`vendor/agentic-core`; ARIES is a separate package extending it only through published
extension points (`register_kind`, agent/workflow/tool registries, triggers, the shared
`Base`).

Its `MIGRATION_GUIDE.md` §3 list is treated as an inherited constraint, not advice: the
lifecycle decision table, the error taxonomy, `sent` before the call, never auto-retrying an
`uncertain` operation, deterministic checks as the backbone, the two-switch live gate,
workers paced by last run, honest observability.

## Consequences

**Positive.** The hardest semantics work on day one, verified on this machine before any
ARIES code existed. `examples/linux_agent` is a working precedent for the system-facing
automations. The engine's tests keep pinning the engine's behaviour.

**Negative.** An inherited design vocabulary (`Task`, `ActionProposal`, `ExecutionPlan`)
that ARIES concepts must map onto; a vendored snapshot that will drift from upstream —
accepted, since ARIES is its intended consumer.

**The boundary must hold.** If ARIES logic is ever added to `agentic_core`, the engine's
tests stop being a guarantee. ARIES-specific behaviour goes in the `aries` package.
