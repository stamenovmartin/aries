# ADR-0005 — ARIES is a user-level systemd service, in one process

**Status:** accepted · **Date:** 2026-09-12 · **Journal:** Entry 012

## Context

ARIES was being launched by hand. That makes it an application, and it is meant to be part of
the operating environment: automations should run whether or not anyone is looking, the
Control Centre should be an optional window onto a system that is already running, and closing
that window should change nothing.

The requirement suggests up to six services (`aries-core`, `aries-api`, `aries-dispatcher`,
`aries-learning`, `aries-integrations`, `aries-background`) under an `aries.target`, and adds
the qualification that decided this: *do not create unnecessary processes if a smaller
architecture is cleaner, but the lifecycle must be managed centrally.*

## What is actually true today

The API process **already hosts every background component**. Six workers run in its asyncio
loop, started by the FastAPI lifespan:

```
scheduler       fires due tasks, sweeps crashed runs
learning        nightly feedback distillation (engine)
triggers        events → proposed tasks
housekeeping    expires undecided proposals
autopilot       runtime-gated self-proposed work
aries.automations  ARIES's own dispatcher (health · news · learning · brief)
```

Splitting those into separate services would not separate anything that is currently together
by accident. It would separate things that are together *by design*.

## Options

**A. Six services under a target**, as sketched in the requirement.
*Pros:* isolated restarts; per-service status comes free from systemd; matches the sketch.
*Cons:* each would need its own process, its own database connections, and its own copy of the
registries. And two of them would be **wrong**, not merely wasteful:

* **The overlap lock is per-process.** It is an `asyncio.Lock` per automation id, and it is what
  stops a pass being started while the previous one is still running. Recorded as a known limit
  since Entry 004 and repeated in `SECURITY.md`. With `aries-dispatcher` and `aries-core` as
  separate processes, both could start the News Radar at the same time — double-fetching every
  source, double-delivering, and double-counting the engagement evidence the learning loop reads.
* **SQLite has one writer at a time.** Several writer processes on one file means contention
  and, under load, `database is locked`. Multi-process needs PostgreSQL *and* a database-level
  lease to replace the in-process lock.

**B. One service under a target.** One process, all workers, lifecycle managed by systemd
through `aries.target`.
*Pros:* correct today with the locking and storage ARIES actually has; one thing to start, stop
and watch; failure isolation is already provided *inside* the process by the circuit breaker
(Entry 007) and the overlap lock, which are per-automation rather than per-process.
*Cons:* a crash takes everything down together — bounded by `Restart=on-failure` and, more
importantly, by the fact that a crash is a bug rather than a routine event.

## Decision

**Option B.** `aries.target` is the unit that means "ARIES is running"; `aries-core.service` is
the single process beneath it.

The target is not ceremony. It is the central lifecycle handle the requirement asks for:
`systemctl --user start aries.target` starts ARIES, `stop` stops it, and a second service can
be attached later by adding `WantedBy=aries.target` — without changing how ARIES is started,
stopped or reasoned about.

**Per-service health becomes per-component health**, which is more useful at this size: every
worker already reports `state`, `alive` and `last_tick`, and `/api/aries/runtime` surfaces them
alongside the systemd unit state, the database, and each automation's circuit breaker.

**No lingering.** `Linger` stays off, so ARIES starts at login and stops at logout — which is
exactly what the requirement asks for, and means ARIES does not run while nobody is logged in.
Enabling it later is one command and needs no change here.

## What would have to change to split it

Recorded so the decision can be revisited on evidence rather than taste:

1. PostgreSQL instead of SQLite (`DATABASE_URL` already supports it).
2. A database-level lease replacing the in-process overlap lock.
3. A shared registry of automations and settings across processes, or each service reloading
   its own.

Until those exist, more services would be less correct, not more robust.

## Consequences

**Positive.** ARIES behaves like part of the environment; the Control Centre connects to
something already running; automations survive closing every window; the restart policy is
systemd's rather than hand-rolled; no `sudo` is needed, because user units live in
`~/.config/systemd/user`.

**Negative.** One process is one blast radius. Mitigated by the circuit breaker, the overlap
lock and a bounded restart policy — and honestly, by the fact that if a worker can take the
process down, that is a bug to fix rather than a topology to design around.
