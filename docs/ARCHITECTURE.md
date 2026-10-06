# ARIES — Architecture

## The layering

```
┌─────────────────────────────────────────────────────────────┐
│  ARIES Control Centre   (separate process, system Python)    │
│  GTK4 + libadwaita · 9 screens · command bar (Ctrl+Space)    │
│                          │ HTTP, loopback — the only path    │
├──────────────────────────▼──────────────────────────────────┤
│  ARIES environment  (package `aries`)                        │
│    settings · sources · interests · notifications            │
│    automations · ARIES agents · memory layers                │
├─────────────────────────────────────────────────────────────┤
│  agentic_core  (vendored engine, unmodified)                 │
│    orchestrator · router · agents · tools · workflows        │
│    evaluators · memory · scheduler · security · api          │
├─────────────────────────────────────────────────────────────┤
│  Ubuntu · systemd · Wayland · hardware                       │
└─────────────────────────────────────────────────────────────┘
```

**The boundary is load-bearing.** Nothing in `agentic_core` knows about ARIES, exactly as
nothing in it knows about the marketing system it was extracted from. The engine's tests pin
the engine's behaviour; the moment ARIES logic leaks into it, they stop meaning anything.
ARIES extends the engine only through its published extension points:

| extension point | what it registers |
|---|---|
| `scheduler.queue.register_kind` | how a task kind is executed, evaluated, replanned |
| `agents.registry.register` | an `AgentSpec` — ARIES's Agent Genome (§8) |
| `workflows.spec.register` | a `WorkflowSpec` — ARIES's Workflow Genome (§10) |
| `tools.registry` | a `ToolSpec` with a risk tier and permissions |
| `scheduler.triggers.register` | an event → task rule |
| `database.base.Base` | ARIES's own tables, created by the same migration |

## What the engine already provides

Inherited whole, and not to be re-implemented:

* **The task lifecycle** — `EXECUTE → EVALUATE → VERDICT → {pass, retry, replan, reconcile,
  escalate}`, with the failure taxonomy that decides which move is safe.
* **`uncertain` as a first-class outcome** — an action that was dispatched but whose result
  was lost is never retried and never marked failed; it is reconciled by evidence.
* **At-most-once side effects** — intent is recorded before the call, keyed by tool +
  payload + task.
* **Resumable plans** — a crash at step 3 of 5 resumes at step 3.
* **The two-switch live gate** — `DRY_RUN` off *and* the tool named in `LIVE_TOOLS`.
  Credentials are not consent.
* **Approval as a durable object** — the machine proposes, a human approves, an executor
  acts; an edit revokes an approval.
* **Deterministic evaluation as the backbone**, with an LLM judge that may lower a score but
  never overrule a hard error.
* **Agents that degrade** to a deterministic fallback instead of hard-failing.
* Audit, metrics, tracing, RBAC, encrypted credentials, scheduler with backoff and
  dead-lettering, FastAPI surface.

## What ARIES adds

| component | specification | status |
|---|---|---|
| Settings Service | §20, §30, §31 | **built** (Entry 002) |
| Automation Genome + registry | §12 | **built** (Entry 003) |
| Notification policy | §26 | **built** (Entry 003) |
| System Health automation | §13/08 | **built** (Entry 003) |
| Automations dispatcher | §11 | **built** (Entry 004) |
| Automation Control Centre | §27 | **built** (Entry 004) — CLI and API |
| Settings / notification API | §29, §31 | **built** (Entry 004) |
| Sources Registry | §24 | **built** (Entry 005) |
| News Radar | §13/03 | **built** (Entry 007) |
| Circuit breaker | — | **built** (Entry 007) |
| Medium learning loop | §16 | **built** (Entry 008) |
| Morning Brief | §13/01 | **built** (Entry 009) |
| Reversal detection | §16 | **built** (Entry 010) — hysteresis, five diagnoses, pending confirmation |
| Fast learning loop | §15, §16 | **built** (Entry 010) — classify, scope, ask rather than guess |
| Connection Hub | §23 | **built** (Entry 011) — status derived, never declared |
| Control Centre | §27–§29, §20 | **built** (Entry 011) — GTK4, 9 screens, generated settings |
| Command interface | §5 | **v0.1** (Entry 011) — 16 real intents, honest refusal |
| Source catalogue | §20, §34 | **built** (Entry 008) |
| Interest Profile | §25 | **built** (Entry 006) |
| ARIES memory layers | §14 | planned |
| Orchestrator intent layer | §5, §6 | planned |
| Control centres (automations, agents, memory) | §27–29 | planned |
| Shell / command bar | §5, §34 | later |

## The runtime (Entry 012)

```
login → default.target → aries.target → aries-core.service   (one process)
                                          ├─ API 127.0.0.1:8000
                                          ├─ scheduler · triggers · housekeeping
                                          ├─ learning · autopilot
                                          └─ aries.automations dispatcher
```

ARIES is a user-level systemd service, not an application. One service rather than six because
the overlap lock is per-process and SQLite has one writer — splitting would be less correct, not
more robust (ADR-0005). Status is derived from systemd, the API, and component health, and
answers when ARIES is stopped. See `RUNTIME.md`.

**Background Mode (Entry 013)** adds the only place ARIES reaches outside its own boundary: a
`sleep`/`block` logind inhibitor so the machine will not suspend while it works, and — because
there is no scoped equivalent — one borrowed GNOME key for the display timeout, recorded before it
is changed and restored when Background Mode is switched off. The inhibitor is held as an open file
descriptor rather than as a record, so it cannot outlive the process holding it (ADR-0006). The
reconcile that keeps the machine and the setting in agreement runs at startup, on the toggle, and
on every dispatcher tick — idempotent, so all three cost nothing.

Alongside it, the **resource policy**: Background Mode promises the machine stays awake, so
something has to say what it may *do* while it is. Automations declare a workload class in their
genome (`light` · `inference_light` · `heavy_cpu` · `heavy_gpu`); the governor answers "may this
run now?" from two separate gates — permission (static, from settings, default-closed for heavy
work) and condition (live, from `/proc/stat`, the thermal zones and the GPU). Lightweight work is
never deferred, because the health check is how ARIES learns the machine is hot. Thermal
deferrals take a hold with a resume margin and a streak; the state is read back from the
append-only event log rather than kept beside it. Nothing is ever killed: the budget raises a
flag a cooperating job reads, and stateful work is not even asked. See `POWER.md`.

## The shell (Entry 014)

```
GNOME Shell (mutter) ─ the session the user already logs into
  └── aries@aries.local        ARIES Shell, GJS, inside gnome-shell
        │  HTTP only, asynchronous, 127.0.0.1:8000
        ▼
   /api/aries/shell/{status,config,act} · /api/aries/command
        ▼
   ARIES runtime
```

A GNOME Shell extension because Mutter does not implement `wlr-layer-shell`, so
no GTK window can anchor to a screen edge on this session — measured, not assumed
(ADR-0008). The shell holds no state and decides nothing: no settings of its own,
no copy of the command router, no file index, no opinion about ARIES's health.
Two tests scan every shell source to enforce that, one for database access and
one for synchronous calls.

The command router moved from `aries_ui/command.py` into `aries/shell/intents.py`
so the Control Centre's palette and the shell's search bar call one endpoint and
cannot diverge. It returns *actions* — data — which each surface carries out in
its own medium. GNOME's workspace overview is the third front end: ARIES
registers as a search provider and calls the same endpoint, so a capability added
to the router appears in all three without any of them changing.

## The session (Entry 015)

```
GDM  ──  Ubuntu  │  ARIES          both offered, permanently
                 └─ gnome-session --session=aries
                      └─ gnome-shell --mode=aries
                           └─ modes/aries.json → enabledExtensions
```

An ARIES session is a GNOME session in an ARIES *session mode* — the mechanism
Ubuntu uses for its own, read out of the installed files rather than guessed at.
Five new files, none of them belonging to a package; Ubuntu's session untouched
and still on the login screen, which `PRODUCT_IDENTITY.md` makes a standing
constraint.

Two findings shaped it. GNOME refuses to load a per-user extension as part of a
session mode — correctly, since a session mode is system configuration — so the
shell is installed system-wide. And `disabled-extensions` takes precedence over a
session mode, so a uuid left there makes a correct install silently do nothing.

The whole arrangement is proved in a nested headless GNOME Shell *before* it is
installed, because a broken session definition is the one failure in this system
that a user cannot recover from inside it. See `SESSION.md`.

## The UI boundary (Entry 011)

```
aries_ui  (system Python 3.14 · GTK4 · stdlib only · imports nothing from `aries`)
    │  HTTP
    ▼
ARIES API → permissions → audit → services → database
```

Two interpreters, because GTK's bindings belong to the system one. The split is the
architecture: the UI is *structurally* incapable of bypassing permissions or the audit log,
since `aries` is not on its path. `aries_ui/contract.py` declares what the UI reads and
`tests/test_ui_contract.py` enforces it — a process boundary removes the compiler, and what it
takes away has to be replaced deliberately. See `decisions/ADR-0004`.

## The three learning loops (§16)

```
fast    (seconds)  you say something ─→ classify ─→ scope ─→ apply at INSTRUCTION/PROJECT/USER
                                                  └─→ ambiguous? ASK, write nothing
medium  (days)     delivered + held items ─→ Wilson intervals ─→ LEARNED layer
                                           └─→ contradicts an established value?
                                                 └─→ hysteresis ─→ pending ─→ confirm ─→ reverse
slow    (weeks)    not built (§18)
```

The fast loop reaches layers the medium loop cannot, and that asymmetry is the design: a person
stating a rule outranks a machine inferring one (§30).

## The precedence model (§30)

Encoded once, in `aries/settings/layers.py`, as an `IntEnum` where higher wins:

```
SECURITY 80   security policy — absolute
RESTRICTION 70  explicit user prohibition
USER 60         explicit user setting
INSTRUCTION 50  "for this task, do Y"
PROJECT 40      preference scoped to one project
LEARNED 30      inferred, carries a confidence and a rationale
HISTORICAL 20   weak statistical prior
DEFAULT 10      what ships in the schema
```

Resolution is `max()` over the layers stored for a key. **Read-side precedence alone is only
a convention**, so the write path enforces it too: a non-human author may write only
`DEFAULT`, `HISTORICAL` and `LEARNED`, and settings marked `user_only` refuse machine writes
entirely. See `decisions/ADR-0003`.

## Data flow, end to end

```
user intent · event · schedule
        ↓
  create_task ──→ router  (rules → LLM → planner fallback; flags needs_human)
        ↓
  run_task_now  ──→ dependencies met? ──no──→ deferred
        ↓ yes
  lifecycle.run_cycle
        ↓
  executor: workflow Director → agents → guarded tool calls
             (dry-run gate → live allowlist → policy → approval → idempotency)
        ↓
  evaluators (deterministic) + optional LLM judge
        ↓
  verdict ──→ pass → done │ awaiting_approval
           └─→ retry │ replan │ reconcile │ escalate → ActionProposal → human
        ↓
  audit · metrics · trace  (always)
        ↓
  feedback → memory → the three learning loops (§16)
```

## Storage

SQLite by default, one file, zero infrastructure — correct for a single-user desktop
environment. PostgreSQL with `pgvector` becomes necessary when vector memory grows; the
engine already supports both through `DATABASE_URL`, so the move is configuration rather
than migration of code.

ARIES tables are declared on the engine's shared `Base` and created by the same
`run_migrations()` call. Importing the `aries` package *is* the registration.

## Runtime

Python 3.12.14 in `~/aries/.venv`, managed by `uv`, entirely in user space. `asyncio`
throughout, because §4 makes responsiveness a defining property: the UI must never block on
an agent. The workflow Director runs sequentially by default, with `parallel=True` available
per workflow — and the inherited rule that no database write happens inside a concurrent
`gather`.

## M14 — Registry agent within the existing workspace

M14 retains `WorkspaceGoal`, queue claims, resource reservations, supervisor,
API and GTK task windows. New `registry.py` describes permitted capabilities;
`agent_planner.py` obtains and validates one local model proposal; `agent.py`
persists the step state machine and dispatches execution followed by independent
verification. `contracts.py` rechecks conditions derived from user text before a
task can become done. Model/executor prose is never a completion oracle.

No SQL table replacement is required: schema-versioned JSON adds decisions,
steps, metrics and evidence to the existing result column. Legacy rows and
bounded recovery remain supported. New dynamic uncertain actions are recorded
as interrupted and are not replayed automatically. See
[AGENT_EXECUTION.md](AGENT_EXECUTION.md) for state transitions, policy,
completion-oracle scope and runtime metrics, and [CAPABILITIES.md](CAPABILITIES.md)
for the single registry used by the model.


## Three-level intelligence

`aries.intelligence` is now a compatible package containing typed schemas,
rules/local/cloud decision providers, inference transport adapters, gateway,
accounting and safe routing cache. Known workspace plans stay deterministic.
M14 routes a goal once, then uses the selected model for its bounded capability
loop. Existing legacy and background inference remains local via the gateway's
engine-compatible transport. Cloud access is an explicit foreground policy, not
a global replacement of the engine provider. Existing execution, independent
verification, queue and UI → API → persistence boundaries remain authoritative.
See [INTELLIGENCE.md](INTELLIGENCE.md) for the call-site audit and Mermaid flow.

### Background evidence and local news summaries (2026-09-19)

The existing Morning Brief news collector uses `aries/news/summaries.py` for
bounded, local-only, strict-schema summaries. An expendable content-addressed working
cache avoids repeat inference; failures retain original feed content. Summary text is
not verification evidence. `scripts/aries-endurance` and its temporary user timer
sample the existing service/API boundaries without model calls or direct database
access. See `docs/BACKGROUND_VALIDATION.md` for verdict coverage limits.
