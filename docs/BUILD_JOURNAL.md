# ARIES — Build Journal

How ARIES is being built, in order, with the reasoning intact.

This journal follows specification sections 35–38. It has two jobs at once. It is an
**engineering record**, precise enough to rebuild the system from nothing, and it is
**learning material**, written so a Computer Science student can follow not just what was
done but why it was the right thing to do and what it would have cost to do otherwise.
Where a technology appears for the first time, it is explained before it is used.

Entries are append-only. When a later entry supersedes an earlier decision, the earlier
entry stays and the later one says what changed and why.

**Conventions.** `~/aries` is the project root. Commands are shown exactly as run. Every
entry ends with a rollback procedure, because a system that claims to be reversible has to
prove it at each step.

---

# Entry 001 — The foundation: a verified runtime and an inherited engine

**Date:** 2026-09-12

## Objective

Get a working, reproducible Python environment on this machine, and establish what ARIES
is built *on* — proving by execution, not by assumption, that the foundation works before a
single line of ARIES is written.

## Problem being solved

Two problems, and the second is the interesting one.

The mundane problem: this is a clean Ubuntu 26.04 install. Python 3.14.4 is present as the
system interpreter, but `python3 -m venv` fails — Ubuntu ships the standard library's
`ensurepip` in a separate `python3.14-venv` package that is not installed. Without a virtual
environment there is nowhere to install dependencies that does not pollute the system
interpreter.

The real problem: ARIES as specified is enormous. Twenty automations, an evolution engine,
a settings application, a memory architecture with nine layers, eventually a Wayland shell.
A project of that size fails in one of two ways — it is either never started, because the
first step is unclear, or it is started in the wrong place, with a chat loop and a pile of
prompts that has to be thrown away the moment real execution semantics are needed. The
question that decides the whole project is therefore: *what is the smallest thing that has
to be correct first?*

The answer is not the UI and not the agents. It is the **orchestration layer** — what
happens when a task fails halfway, how a retry avoids doing a dangerous thing twice, how a
human gets asked before something irreversible happens. Those are the semantics that are
brutally expensive to retrofit, because every component built above them assumes them.

## Why this step is necessary

Everything else in ARIES is downstream of this. An agent that cannot be retried safely is
not a component, it is a liability. The specification says as much in its own vocabulary:
§18 demands controlled evolution with sandboxing and rollback, §14 demands auditable
memory, §30 demands a precedence model that learned behaviour cannot break. None of those
can be added later to a system that did not start with durable task state.

## Concepts

**Virtual environment.** A Python installation is a directory of an interpreter plus a
`site-packages` folder. Installing a library writes into `site-packages`, which means two
projects on one machine fight over versions. A *virtual environment* is a private copy of
that structure: its own `site-packages`, its own `bin/python`, and a marker that makes the
interpreter look there first. Activating one is nothing more magical than putting its `bin`
directory at the front of `$PATH`. Ubuntu additionally marks its system Python as
"externally managed" (PEP 668), so `pip install` into it is refused outright — the distro's
package manager owns those files, and letting pip overwrite them has historically bricked
systems that use Python for their own tooling. A virtual environment is not a nicety here;
it is the only correct place for project dependencies.

**Wheels, and why a Python version is a compatibility decision.** A wheel is a pre-compiled
binary distribution of a Python package. Pure-Python packages ship one wheel for everything.
Packages with C or Rust extensions — `pydantic-core`, `asyncpg`, `sqlalchemy`'s optional C
accelerators — must ship one wheel *per interpreter version and platform*, tagged `cp312`,
`cp314` and so on for CPython 3.12, 3.14. If no matching wheel exists, pip falls back to
building from source, which needs the full toolchain (for `pydantic-core`, a Rust compiler)
and frequently fails. This makes the choice of Python version a real engineering decision
rather than a preference, and it decided this entry — see Alternatives.

**Orchestration, as distinct from prompting.** Sending text to a model and reading the reply
is an API call. Orchestration is everything around it that makes the result trustworthy:
deciding which agent should handle a task, giving it context, validating what came back,
deciding whether a failure should be retried or escalated, making sure a retried action does
not execute twice, and recording all of it so a human can audit the decision afterwards. The
model is a component inside orchestration, not the other way around.

**Idempotency.** An operation is idempotent when performing it twice has the same effect as
performing it once. This matters enormously for an agentic system, because retries are the
normal response to failure and many real actions — sending a message, restarting a service,
spending money — are not naturally idempotent. The standard fix is to record intent *before*
acting, keyed by a hash of the action, so a repeat of the same action finds the record and
returns the original outcome instead of acting again.

## Alternatives considered

**A. Build ARIES orchestration from scratch.**
*Pros:* exactly the architecture the specification describes, no inherited assumptions.
*Cons:* the specification's hardest requirements — resumable plans, an error taxonomy that
distinguishes "retry is safe" from "retry would double-execute", at-most-once side effects,
approval gates, state machines whose illegal transitions are impossible — are each weeks of
work and, more importantly, are the parts you get wrong *in production, once, expensively*.
Writing them fresh means paying for those lessons again.

**B. Adopt an off-the-shelf agent framework** (LangGraph, AutoGen, CrewAI).
*Pros:* mature, documented, large communities.
*Cons:* they are graph-execution and conversation frameworks. None ships the things this
specification is actually anxious about: a durable approval lifecycle, a dry-run/live
two-switch gate, an operations ledger for at-most-once execution, a per-task audit trail.
Those would still have to be built, now inside someone else's abstractions. The
specification explicitly warns against adopting a framework for popularity (§3).

**C. Build on the existing `agentic-orchestration-export` engine.**
The user had already built and exported a domain-neutral orchestration engine, extracted
from a production marketing system (the "Insomnia Marketing OS"). It contains, as working
and tested code: a task lifecycle with retry/replan/escalate, an error taxonomy, resumable
execution plans, idempotent operations, a workflow Director graph, an agent runtime with
schema-validated output and deterministic fallbacks, evaluators, a scheduler with backoff
and dead-lettering, RBAC and secret storage, audit and metrics, and a FastAPI surface.
*Pros:* the semantics ARIES needs most already exist, and — decisively — they were learned
from a system that shipped. Its own `MIGRATION_GUIDE.md` is literally titled "from the
marketing orchestration to an Agentic Linux Operating Environment", and `examples/linux_agent`
is a working starter for precisely this.
*Cons:* inherited design; a boundary to respect; unverified on this machine.

## Decision

**Option C**, with a strict boundary: the engine is vendored unmodified at
`~/aries/vendor/agentic-core` and ARIES is a separate package at `~/aries/aries` built *on*
it. Nothing in the engine will learn about ARIES, exactly as nothing in it knows about the
marketing system it came from. That boundary is the reason its guarantees keep holding: the
moment application logic leaks into the engine, the engine's tests stop pinning the
engine's behaviour.

The engine's `MIGRATION_GUIDE.md` §3 lists what must be kept exactly as it is — the
lifecycle decision table, the error taxonomy, `sent`-before-call, never auto-retrying an
uncertain operation, deterministic checks as the backbone with the LLM judge only adjusting.
Those are treated as inherited constraints, not suggestions. They encode incidents that
were paid for once already: a "failed" post that was really live, a retry that
double-published.

## Implementation

### Runtime

The pinned dependency set (`fastapi==0.115.6`, `sqlalchemy==2.0.36`, `pydantic-settings==2.7.0`)
dates from late 2024. Checking the wheel tags actually published on PyPI:

```bash
for p in pydantic-core sqlalchemy asyncpg; do
  curl -sS "https://pypi.org/simple/$p/" | grep -oE "cp31[0-9]" | sort -u
done
# → cp310 cp311 cp312 cp313 cp314 cp315
```

`cp314` tags exist, but only on *recent* releases. `pydantic-settings 2.7.0` resolves to
`pydantic ~2.10` → `pydantic-core 2.27`, which predates CPython 3.14 entirely. On system
Python 3.14 that dependency set would attempt a Rust source build and fail.

That left a genuine fork: bump every pin to current releases and run on Python 3.14 with
versions the engine's 13 test files were never run against, or run Python 3.12 and keep the
exact tested pins. The engine's value *is* its tested behaviour, so anything that weakens the
test suite's authority is the wrong trade. Python 3.12 it is.

Since `python3.14-venv` needs `sudo` anyway, `uv` was chosen to supply the interpreter — a
Rust-based Python package and version manager that installs entirely into the user's home
directory, downloads standalone CPython builds, and needs no root at all.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # → ~/.local/bin/uv  (uv 0.12.13)
uv python install 3.12                              # → CPython 3.12.14, user-space
uv venv --python 3.12 ~/aries/.venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Every pin resolved to a wheel; nothing was built from source.

### Files created

```
~/aries/
├── .venv/                          CPython 3.12.14 + the pinned dependencies
├── requirements.txt                copied from the export, unmodified
├── .env.example                    copied from the export, unmodified
├── vendor/
│   ├── agentic-core/               THE ENGINE — vendored, unmodified
│   └── examples/                   marketing + linux_agent, kept as reference
├── aries/                          the ARIES package (empty at this entry)
├── docs/
│   ├── BUILD_JOURNAL.md            this file
│   ├── ENGINE_README.md            the export's README
│   └── ENGINE_MIGRATION_GUIDE.md   the export's migration guide
├── scripts/                        start.sh, init_db.py, test.sh
└── var/                            runtime data (databases, context, cursors)
```

### Packages installed

`fastapi 0.115.6`, `uvicorn 0.34.0`, `sqlalchemy 2.0.36`, `aiosqlite 0.20.0`,
`asyncpg 0.30.0`, `pydantic-settings 2.7.0` (pulling `pydantic 2.13.5`), `httpx 0.28.1`,
`python-multipart 0.0.18`, `python-dateutil 2.9.0`, plus transitive dependencies.
Tooling outside the project: `uv 0.12.13` and CPython 3.12.14, both under `~/.local` and
`~/.local/share/uv`.

## How the inherited engine works internally

Worth understanding before building on it, because ARIES inherits these mechanisms wholesale.

**The single execution path.** The API, the scheduler, an event trigger and the assistant all
call `scheduler/queue.py::run_task_now`. One path means they cannot drift apart — a rule
carried over from the marketing system, where the chat had to call the same handler the
dashboard button did or the two behaved differently under failure.

**The lifecycle** (`orchestrator/lifecycle.py::run_cycle`) is the heart:

```
EXECUTE → EVALUATE → VERDICT → { pass | retry | replan | reconcile | escalate }
```

Execution produces a result. Every deterministic evaluator then runs, and an optional LLM
judge adds a second opinion that can *lower* a score but never overturn a hard error — the
machine's own confidence is never allowed to overrule a check that actually failed. The
verdict maps a failure's *class* to the next move, and the mapping is the part worth
copying:

| class | move | reasoning |
|---|---|---|
| transient | retry | a timeout or a 503 will plausibly succeed next time |
| validation | replan | the input was wrong; retrying the same plan repeats the mistake |
| auth / policy / capability | escalate | no amount of retrying fixes a missing permission |
| **uncertain** | **reconcile** | **the request was sent and the answer was lost** |
| unknown | escalate | never loop on something you cannot classify |

`uncertain` is the subtle one and the reason this engine was worth inheriting. When an
action was dispatched but the outcome never came back, *both* possible responses are
dangerous: retrying may execute it twice, marking it failed may hide that it succeeded. The
only correct move is to stop and establish the truth by evidence — a read-only probe, or a
human. The engine encodes this as a state a retry cannot exit, and crash recovery marks
in-flight operations `uncertain` rather than `failed`, precisely because `failed`
auto-retries.

**Never running a side effect twice.** `orchestrator/operations.py` writes a durable row
keyed by tool + payload + task and marks it `sent` *before* the call. A repeated identical
payload finds that row and returns the recorded result instead of acting.

**Plans resume rather than restart.** A multi-step plan (`orchestrator/dag.py`) records each
step. A crash at step 3 of 5 resumes at step 3; steps 1 and 2 are not repeated.

**Two switches before anything real happens.** `DRY_RUN` must be off *and* the tool must be
named in `LIVE_TOOLS`. Holding a credential is not permission to use it — consent is a
separate, explicit act. High-risk tools additionally require an approved proposal.

**Every agent has a deterministic fallback,** so the pipeline degrades instead of
hard-failing when no model is reachable. Under `REQUIRE_AI=true` it raises instead — useful
in tests, wrong in production.

## Data flow

```
event / API / schedule / user
        ↓
  create_task  ──→ router (rules → LLM → planner fallback; flags needs_human)
        ↓
  run_task_now  ──→ dependencies met? ──no──→ deferred
        ↓ yes
  lifecycle.run_cycle
        ↓
  executor (workflow Director → agents → guarded tool calls)
        ↓
  evaluators (deterministic) + optional judge
        ↓
  verdict ──→ pass → done │ awaiting_approval
           └─→ retry │ replan │ reconcile │ escalate → ActionProposal → human
        ↓
  audit + metrics + trace, always
```

## Security implications

Reviewed before adopting, since ARIES will eventually hold email and calendar access.

*Good:* safe defaults throughout — `dry_run=true`, `live_tools=""`, every credential
defaulting to empty with no working default anywhere. Secrets are encrypted at rest and the
observability layer applies three-layer redaction. A shell sandbox enforces an allowlist and
a denylist. RBAC separates the roles that approve from those that execute. Audit events are
append-only. A `dbguard` refuses `drop_all` against a non-test database.

*Requires attention as ARIES grows:* `api_key` defaults to empty, which is an open API —
acceptable only on loopback, and ARIES must bind to localhost until tokens are minted. The
sandbox allowlist is a starting point that will need ARIES-specific denials (§4 of the
migration guide). Secret storage refuses to operate without `CREDENTIALS_KEY` set, which is
the correct failure direction.

*Newly introduced by this entry:* one third-party installer was fetched and executed from
`astral.sh` over TLS. `uv` is a widely used, open-source tool from Astral; the trade was
accepted against the alternative of granting `sudo` to apt. It is confined to `~/.local`.

## Performance implications

The engine is `asyncio`-based throughout, which matches §4's demand that ARIES stay
responsive while agents work. The Director runs sequentially by default with `parallel=True`
available per workflow; the original's note is worth preserving — it stayed sequential so
that no database write ever happens inside a concurrent `gather`. SQLite is the default
store and is adequate for a single-user desktop system; the move to PostgreSQL with
`pgvector` becomes necessary when vector memory grows, and the engine already supports it
via `DATABASE_URL`.

## Risks

1. **Inherited design constraints.** Mitigated by the boundary: ARIES lives in its own
   package and the engine stays unmodified, so the engine's tests keep meaning something.
2. **Python 3.12 versus the system's 3.14.** Deliberate, and isolated in `.venv`; it costs
   nothing until a dependency drops 3.12 support, which is years away.
3. **A vendored engine drifts from upstream.** Accepted: the export is a snapshot, not a
   dependency, and ARIES is its intended consumer.
4. **Twenty automations is an unbounded scope.** Addressed by `ROADMAP.md` — the
   architecture must *support* all twenty (§13); only a few get built.

## How the result was tested

The engine ships 13 test files plus the Linux example's end-to-end test, each running in its
own process with its own SQLite file and `APP_ENV=test`.

```bash
cd ~/aries
export PYTHONPATH="$PWD/vendor/agentic-core:$PWD/vendor:$PWD"
APP_ENV=test .venv/bin/python vendor/agentic-core/tests/run_tests.py
APP_ENV=test .venv/bin/python vendor/examples/linux_agent/test_linux_agent.py
```

## Test results

All green on the first run, in about six seconds:

```
test_api · test_errors · test_evaluators · test_graph · test_lifecycle · test_memory
test_operations_dag · test_router · test_scheduler · test_security · test_states
test_tools · test_workflow_agents
passed 13 · failed 0 · 6s
```

The Linux example's ten assertions also passed, and two are worth calling out because they
demonstrate the safety properties rather than merely exercising code:

```
PASS  inspector cannot run a dangerous command
PASS  mutation is dry-run by default
PASS  repair with no model → planner needs_human → escalated to a proposal
```

The third is the whole philosophy in one line: with no model available, the planner does not
improvise a fix on a real machine. It declares that a human is needed, and the escalation
becomes a proposal in a queue.

## Errors encountered

**1. `python3 -m venv` failed.**
*Cause:* Debian and Ubuntu split `ensurepip` out of the standard library into
`python3.14-venv`, which is not installed on a fresh system.
*Fix:* `uv`, which brings its own interpreter and needs no root. Recorded as ADR-0002.

**2. `curl https://pypi.org/simple/` timed out**, which briefly looked like a network fault.
*Cause:* not a fault. That endpoint is the index of *every package on PyPI*, tens of
megabytes of HTML. A per-package URL returned `200` immediately.
*Lesson:* a timeout is a symptom, not a diagnosis. Testing the narrower endpoint took
seconds and changed the conclusion completely.

**3. Anticipated and avoided:** the pinned dependencies on Python 3.14. Caught by checking
published wheel tags *before* installing rather than after a failed Rust build.

## What was learned

* Verify a foundation by running its tests on the actual machine before building on it. The
  cost was six seconds; the cost of discovering a broken foundation three subsystems later
  is measured in days.
* The engine's real value is not its code but its *encoded incidents* — the `uncertain`
  class, `sent` before the call, credentials not being consent. Those came from something
  breaking in production once.
* A dependency pin is a statement about which Python versions are reachable. Reading wheel
  tags is faster than debugging a source build.

## Rollback

```bash
rm -rf ~/aries                                   # the whole project
rm -rf ~/.local/share/uv ~/.local/bin/uv ~/.local/bin/uvx   # uv and its interpreters
```
Nothing was installed system-wide, no `sudo` was used, and no file outside `~/aries` and
`~/.local` was modified.

## Git commit

Not yet — `git` is not installed on this machine (`sudo apt install git` is pending). This
entry will be the first commit once it is. See ADR-0002.

## What should happen next

The Settings Service (§31), because it is the dependency nothing else can proceed without:
agents, automations and the notification policy all need a typed way to read user
preferences, and §30's precedence model has to exist before anything starts learning, or
the first learned value will be written somewhere it can overrule the user.

---

# Entry 002 — The Settings Service: making "the user always wins" structural

**Date:** 2026-09-12

## Objective

Build the typed, layered, agent-accessible Settings Service of §31, with §30's precedence
model enforced in the code rather than trusted to convention.

## Problem being solved

§20 asks for a real Settings application; §31 insists settings are "not only UI values" and
that agents must read them through a service rather than each keeping "its own unrelated
preference copy"; §25 says the user must be able to inspect and override anything ARIES
infers; §30 fixes an eight-level precedence order and states flatly: *never allow learned
behaviour to override an explicit user preference.*

That last sentence is the hard part, and it is easy to satisfy only in appearance. A system
that reads preferences in the right order but lets a learning loop *write* wherever it likes
has not implemented the rule — it has implemented a convention that the first buggy or
over-confident learner will violate. Worse, once a learner writes into the user's layer, the
provenance is gone: nobody can tell afterwards whether the user asked for this or the machine
decided it. The requirement is therefore structural, not procedural.

## Why ARIES needs this

Every subsequent component reads settings. The News Radar needs thresholds, the notification
policy needs levels and quiet hours, the orchestrator needs the autonomy level to decide
whether it may act without asking, and the learning loops of §16 need somewhere to put what
they infer that *cannot* be somewhere dangerous. Building any of those first would mean each
inventing its own configuration, which is exactly what §31 forbids.

## Concepts

**Layered configuration.** A single key can hold values from several sources at once: a
default that ships with the system, a value the user typed, a value ARIES inferred from
behaviour. Resolution walks from the strongest source to the weakest and returns the first
value found. The essential design choice is that losing values are **kept, not overwritten**.
That costs a few database rows and buys three things: the UI can show "you set 0.5; ARIES had
learned 0.72", clearing an explicit value promotes the inferred one without re-learning it,
and provenance survives — every value knows who set it and why.

**Precedence as a total order.** §30's eight levels become an `IntEnum` where a higher number
wins, so resolution is `max()` over the stored layers. Encoding the order once, in one enum,
means it cannot be applied inconsistently by different callers. The values are spaced by ten
so a layer can be inserted later without renumbering rows already in the database.

**Schema registry versus a settings class.** The obvious approach is a class with typed
attributes. It is typed, but it is not *introspectable*: a Settings UI cannot ask it what
controls to render, an agent cannot ask what a knob means, and adding a knob means editing
two places. Instead each setting is a `SettingDef` **object** — key, type, default, title,
description, section, control, bounds — registered into a dictionary keyed by a dot path.
From that one declaration we derive validation, the UI control, the API's JSON, and the
sentence an agent reads to understand the setting. The cost is hand-written validation
(`coerce`), which is deliberately strict, because a setting that silently accepts a wrong
type becomes a bug in an agent three layers away.

**Dot paths.** `news.relevance_threshold` namespaces for free: a UI groups by prefix, and
`digest("news")` hands an agent exactly the news configuration and nothing else.

**Why reads hit the database.** Settings must be consistent across the API process, the
scheduler workers and every agent. A per-process cache would let those drift the moment the
user changed something, and "the setting I changed didn't take effect" is a miserable class
of bug. Where a hot path needs many keys, `get_many` and `digest` fetch them in one query.

## Alternatives considered

**A. A pydantic `BaseSettings` class, like the engine's own `config/settings.py`.**
*Pros:* typed, familiar, already in the stack.
*Cons:* environment-variable oriented and fixed at process start. §20 needs values changed
from a UI at runtime, and §30 needs multiple values per key with provenance. `BaseSettings`
models neither. It remains exactly right for what the engine uses it for — process-level
configuration and secrets — so it stays there, and ARIES's user-facing preferences are a
different thing that deserves a different mechanism.

**B. The engine's `config/runtime.py` JSON file.**
*Pros:* already exists, atomic writes, runtime-mutable.
*Cons:* a flat key/value file with no types, no layers, no provenance, no audit. Correct for
the handful of operator switches it holds; far too thin for a user-facing settings system.

**C. One database row per key.**
*Pros:* simplest possible schema.
*Cons:* a learned value would have to be destroyed the instant the user typed one, which
throws away information the system paid to acquire and makes "what would ARIES do if I
cleared this?" unanswerable. Rejected for that reason.

**D. One row per (key, layer, scope) — chosen.** Slightly more storage, full auditability,
and the override relationship is visible rather than implied.

## Decision

Four modules, each with one job:

| module | responsibility |
|---|---|
| `layers.py` | §30's precedence order, and which layers a machine may write |
| `schema.py` | what settings exist: declaration, validation, UI hints |
| `store.py` | where values live: one row per (key, layer, scope) |
| `service.py` | resolution, the write rules, audit — the only public entry point |

`defaults.py` registers the 33 settings ARIES ships with, covering GENERAL, AUTONOMY, AI,
NEWS, BRIEFING, NOTIFICATIONS and PRIVACY.

**The write rules**, which are what make the read rules honest:

1. An author not recognised as human may only write `DEFAULT`, `HISTORICAL` or `LEARNED`.
   Attempting a user layer raises, with a message that says why.
2. A setting marked `user_only` refuses every machine write outright — used for the
   consequential knobs: `autonomy.level`, `ai.daily_cost_limit`, `privacy.mode`,
   `ai.send_file_contents`, and the paths ARIES must never read.

Together these make "ARIES changed what you asked for" *unrepresentable*, not merely
discouraged. `service.learn()` is the learning loops' only entry point and cannot reach a
user layer even by mistake; when what it writes is shadowed by a user value, it is told so in
the return value rather than silently ignored.

## Implementation

### Files created

```
aries/settings/layers.py      85 lines   the precedence order
aries/settings/schema.py     161 lines   SettingDef, validation, the registry
aries/settings/store.py      148 lines   the aries_settings table and its queries
aries/settings/service.py    181 lines   get / get_many / explain / digest / set / clear / learn
aries/settings/defaults.py   128 lines   the 33 shipped settings
aries/settings/__init__.py               the public surface
aries/__init__.py                        the package; registers tables + schema
tests/test_settings.py                   32 assertions
tests/_bootstrap.py, tests/_harness_shim.py
scripts/test.sh                          engine + example + ARIES in one command
```

### The table

```sql
CREATE TABLE aries_settings (
  id INTEGER PRIMARY KEY,
  key VARCHAR(200), layer INTEGER, scope VARCHAR(120),
  value_json TEXT,                    -- JSON; portable across SQLite and PostgreSQL
  confidence FLOAT, rationale TEXT,   -- why a learned value exists — the evidence trail
  set_by VARCHAR(120),
  created_at DATETIME, updated_at DATETIME,
  UNIQUE (key, layer, scope)          -- the triple, not the key alone
);
```

`NULL` is deliberately not a storable value: an unset setting is an **absent row**, so
"unset" has exactly one spelling and no caller has to distinguish two kinds of nothing.
The table is declared on the engine's shared `Base`, so `run_migrations()` creates it with
no ARIES-specific bootstrap.

### Scope

The same key can be set globally and again for one project — "brief me at 07:30, but for the
Insomnia project use 07:00". `scope` is `""` for global values and something like
`project:insomnia` otherwise. Resolution takes an ordered scope chain, weakest first, so a
scoped value need only exist where it actually differs.

## How it works internally

A read resolves in one query:

```
get("news.relevance_threshold")
   └→ store.read(key, scopes=["", "project:insomnia"])
        └→ SELECT * FROM aries_settings WHERE key = ? AND scope IN (?, ?)
             └→ keep the strongest SCOPE per layer      (a project value beats a global one)
                  └→ max() over LAYER                   (§30's order)
                       └→ decode JSON  ·  or the schema default if no row exists
```

A write validates against the schema, checks the author against the layer, writes the row,
and emits an `AuditEvent` carrying the before and after values — so every change to a
preference is in the same append-only audit trail as every action the system takes.

## Data flow

```
Settings UI ─┐
natural language ("only AI news from these five sites")
             ├─→ SettingsService.set(…, layer=USER)     ─┐
learning loop ─→ SettingsService.learn(…, confidence)   ─┤
security policy → SettingsService.set(…, layer=SECURITY)─┤
                                                          ↓
                                                   aries_settings
                                                          ↓
        agents · automations · notification policy · orchestrator
                    ←── get / get_many / digest ──
```

## Dependencies

Depends on the engine's `database.base.Base` (the shared table registry) and
`observability.audit`. Nothing depends on it yet — that is the point of building it first.

## Security implications

The `user_only` flag is a security control, not a UI hint: it is what stops a learning loop
from inferring its way to a higher autonomy level after a run of successes. `privacy.excluded_paths`
defaults to `["~/.ssh", "~/.gnupg"]`, so the denial exists before any component that reads
files does. Every write is audited with its before and after values, which makes an
unexpected change traceable to its author. No secret is ever stored here — credentials belong
in the engine's encrypted store, and settings are readable by agents by design.

## Performance implications

One indexed query per resolution; `get_many` and `digest` collapse a whole section into a
single round trip, which is the path an agent's context digest uses. No cache, deliberately
(see Concepts). Should profiling ever show this matters, the correct fix is a
short-TTL cache with invalidation on write, not a process-lifetime one.

## Risks

1. **Schema drift** — a renamed key orphans its rows. Needs a rename map when it first
   happens; noted in ROADMAP.
2. **Author spoofing** — the write rules trust the `set_by` string. Acceptable while
   everything is in-process; when settings become writable over the API, the author must come
   from the authenticated principal, not from the caller's argument. Recorded as a risk now
   so it is not discovered later.
3. **Over-configuration** — 33 settings is already a lot to present well. `advanced` exists
   for exactly this, and the Settings app must respect §1's progressive disclosure.

## How the result was tested

`tests/test_settings.py`, 32 assertions across eight test functions, run in an isolated
process with its own SQLite database. The suite deliberately attacks §30 from both sides.

```bash
cd ~/aries && ./scripts/test.sh
```

## Test results

All passed. The ones that matter most:

```
--- test_user_beats_learned
PASS  a learned value applies when the user has said nothing
PASS  an explicit user value outranks the learned one
PASS  learning again does not move the effective value
PASS  and the learner is told its value is shadowed
PASS  clearing the user value promotes the learned one, not the default

--- test_machine_cannot_write_user_layers
PASS  a machine author may not write the USER layer
PASS  a machine author may not write a RESTRICTION
PASS  a machine author may write the LEARNED layer
PASS  a user-only setting refuses a machine author entirely
PASS  the user may still set a user-only setting

--- test_security_layer_is_absolute
PASS  a security policy outranks even an explicit user setting
```

The full stack — engine (13 files), the Linux reference example (10 assertions) and ARIES
(32 assertions) — is green: `ALL SUITES PASSED`.

## Errors encountered

**1. The test harness imported `agentic_core` before `bootstrap()` had run.**
*Cause:* Python executes imports top to bottom, and the engine's `database/base.py` reads
`settings.database_url` **at import time** to build the engine. Importing it before
`bootstrap()` sets `DATABASE_URL` means the test binds to the *real* database — the exact
failure the engine's own harness warns about in its docstring.
*Fix:* call `bootstrap()` before any engine import, with `# noqa: E402` on the imports that
follow, and a comment saying why the order is load-bearing.
*Lesson:* import-time side effects turn import *order* into program logic. The engine's
harness documented this; reading that docstring first would have avoided the mistake.

**2. `reset_db()` must import `aries` before `create_all`.**
*Cause:* SQLAlchemy's `Base.metadata` only knows about tables whose classes have been
imported. Without importing `aries`, `aries_settings` does not exist and every test fails on
a missing table.
*Fix:* `reset_db()` imports `aries` explicitly, with a comment explaining that the import
*is* the registration.

## What was learned

* "Never allow X" is a specification sentence; the engineering question is always *what
  makes X unrepresentable?* Read-side precedence is a convention. Read-side precedence plus
  write-side authorisation is a guarantee.
* Keeping overridden values instead of deleting them turned out to buy more than auditability
  — it is what lets clearing a user value fall back to something better than the default.
* Declaring settings as data rather than as class attributes meant the API surface, the
  validation and the UI hints all came from one place, for free.

## Rollback

```bash
rm -rf ~/aries/aries/settings ~/aries/tests/test_settings.py
# and drop the table:
#   DROP TABLE aries_settings;
```
No engine file was modified, so removing ARIES leaves the engine exactly as vendored.

## Git commit

Pending `git` installation, as in Entry 001.

## What should happen next

The Sources Registry (§24), so agents query a registry of user-configured sources instead of
hard-coding external websites — the prerequisite for the News Radar (§13/03) and the first
automation. It also gives the Settings Service its first real consumer, which is the proper
test of whether its interface is right.

---

# Entry 003 — System Health: the first automation, and the first thing ARIES judges

**Date:** 2026-09-12

## Objective

Build automation §13/08, the System Health Monitor, end to end on this machine:
measure CPU, memory, disk, temperature, GPU and systemd units; learn what is normal here;
decide what is worth telling the user; and, when something is genuinely wrong, put a
proposal in a human's queue rather than touching the machine.

Three supporting pieces had to exist for it, and were built with it: the Automation Genome
(§12), the notification policy (§26), and a small command line to see any of it.

## Problem being solved

The stated problem is "watch the machine". The real problem is **watching it without
becoming noise**, and that is much harder.

A monitor that reports everything it notices is read for a week and ignored forever after.
Worse, it trains the user to dismiss its notifications, which means the one that mattered is
dismissed too. Every design decision in this entry is downstream of that: the value of a
monitoring system is not how much it notices, it is how little it says.

There is a second problem underneath, which is that a fixed threshold is wrong for somebody.
A laptop that idles at 72 °C under a normal desktop load is healthy. A 70 °C warning turns
that machine into a permanent alarm — the same failure, arrived at from the other direction.
§13/08 anticipates this and asks the automation to "learn normal machine baselines and
reduce false alarms".

## Why ARIES needs this

It is the first automation, so it is the first thing to exercise the whole path the
specification describes — trigger, task, execution, evaluation, verdict, escalation, audit —
on real hardware rather than in a diagram. It needed no external integration, no OAuth, no
model, and no permission to change anything, which makes it the cheapest possible way to
find out whether the architecture actually works. It also produced the first two components
that every later automation will need (a genome and a notification policy), which is a
better way to discover their interfaces than designing them in the abstract.

## Concepts

**Measurement is not judgement.** A probe produces a `Reading` — "mount / is 71.2% full".
Whether that is *bad* is a separate question whose answer depends on the user's thresholds,
on this machine's history, and on whether they were already told an hour ago. So probes may
only measure, and a single module judges. The payoff is concrete: probes are testable
against fixed text, and the baseline learning improved the false-alarm rate without one
probe being modified.

**PSI — Pressure Stall Information.** `/proc/pressure/{cpu,memory,io}` reports the share of
time tasks were *stalled* waiting for a resource. This is a better health signal than
utilisation, and the difference is the whole point: a load of 12 on 12 cores is fully busy
and perfectly healthy, whereas memory pressure of 20% means work is genuinely being delayed.
Utilisation says how busy the machine is; pressure says whether that busyness is hurting.
ARIES prefers pressure wherever both exist.

**MemAvailable, not MemFree.** Linux deliberately fills unused memory with page cache, which
is reclaimable the instant anything needs it. Judging memory by `MemFree` therefore reports
a perfectly healthy machine as nearly out of memory. `MemAvailable` is the kernel's own
estimate of what a new workload could actually obtain, and is the only honest numerator.

**Robust statistics.** The obvious way to summarise "normal" is mean and standard deviation,
and it is the wrong one: both are dragged by outliers, so one compile that pins every core
silently widens the "normal" band to include genuinely abnormal values. The median cannot be
moved by a single extreme value, and percentiles inherit that property. `p95` — the value
95% of observations fall below — is what ARIES compares against. This is pinned by a test in
which one 400 °C sample is added to sixty 40 °C samples and must not move the median.

**Idempotency of *attention*.** The engine already guarantees a side effect happens at most
once. This entry needed the same idea applied to the user: a disk that is 94% full is still
94% full fifteen minutes later, and telling them each time is how a monitor becomes
wallpaper. A notification's identity is the finding's key, and re-notifying is refused until
either a cooldown expires or the situation *worsens*.

## Alternatives considered

**Thresholds only, no learning.**
*Pros:* simple, predictable, no state, nothing to go wrong.
*Cons:* fails §13/08 explicitly, and produces the permanent-alarm failure above on any
machine whose normal differs from the default. Rejected, but its predictability is preserved
in the design: thresholds still decide first, and learning may only soften the result.

**Full anomaly detection** (a model over the metric history).
*Pros:* catches unusual patterns a threshold never will.
*Cons:* opaque, needs far more history than a new install has, and cannot explain itself —
which §29 forbids, since the user must be able to inspect and correct what ARIES concluded.
§17 also warns against reaching for machine learning by reputation. Deferred: percentiles
give most of the benefit and can be explained in one sentence.

**A model-driven health agent** that reads raw output and describes what is wrong.
*Pros:* flexible, handles metrics nobody anticipated.
*Cons:* non-deterministic, costs a model call every fifteen minutes, and can hallucinate a
problem — or miss a real one. The engine's own rule is that deterministic checks are the
backbone and a model is only ever a second opinion. **This automation therefore uses no
model at all**, which also means it works with the network down, and its `agents` list in
the genome is deliberately empty.

**Baselines that can raise severity as well as lower it.** Rejected. A learning system that
can invent alarms on its own teaches the user to distrust it. Softening is recoverable — the
user sees a NOTICE instead of a WARNING; inventing is not.

## Decision

Five modules, and one distinction that shapes all of them.

| module | responsibility |
|---|---|
| `health/findings.py` | the vocabulary: `Reading` (measured), `Finding` (judged), `Severity` |
| `health/probes.py` | seven probes; measurement only, degrading honestly |
| `health/baseline.py` | samples, robust statistics, and which metrics may ever be softened |
| `health/judge.py` | thresholds, then baselines; the only module that decides anything is wrong |
| `health/automation.py` | the pass, the genome, the task kind, the evaluators |

plus `automations/genome.py` (§12), `notify/policy.py` (§26) and `cli.py`.

### The distinction: did the CHECK work, or is the MACHINE healthy?

These are independent, and conflating them is the mistake this design is built to avoid. A
perfectly functioning health check on a machine whose disk is 97% full has **succeeded** —
it has simply found bad news. If that counts as failure, the automation's reliability metric
collapses exactly when the machine most needs watching, and "failed" stops telling you which
of the two things failed.

So:

* the automation's run status (`ok` / `degraded` / `failed`) describes **the check**;
  `degraded` means a probe could not run, `failed` means the pass itself broke;
* a CRITICAL finding sets `requires_approval` on the result, and the engine's lifecycle turns
  that into an `ActionProposal` and notifies a human — **the task still completes
  successfully**, because it did its job;
* the lifecycle's ESCALATE path is reserved for the check being broken. Every probe
  unavailable means ARIES is blind, and being blind is itself an incident.

This fell out of reading the engine rather than being invented: `lifecycle.run_cycle` already
does exactly the right thing with `requires_approval` on a passing result. The mechanism was
there; the work was recognising which of the engine's paths matched the situation.

**ARIES never repairs anything here.** It measures, judges and asks. §33's autonomy levels
decide whether anything may act on that, and nothing in this module may shortcut them.

### What a baseline may and may not do

Two hard limits, both safety properties rather than tuning knobs:

1. **A ceiling.** `health.baseline_suppress_max_severity` defaults to `warning`, so a
   learned baseline can never silence a CRITICAL.
2. **An eligibility list.** Only metrics that genuinely fluctuate — temperature, load,
   pressure, memory — are in `baseline.SUPPRESSIBLE`. Accumulating and binary ones are not,
   because a baseline says "this is usual", not "this is fine", and the two come apart for
   anything that only climbs. **A disk that has been 96% full for a month has a beautifully
   stable baseline and is still about to fail.**

## Implementation

### Files created

```
aries/health/findings.py       117 lines   Reading · Finding · Severity · ProbeResult
aries/health/probes.py         335 lines   cpu · memory · disk · thermal · gpu · services · uptime
aries/health/baseline.py       179 lines   samples table · robust statistics · SUPPRESSIBLE · prune
aries/health/judge.py          213 lines   the rule table; thresholds then baselines
aries/health/settings.py       128 lines   21 thresholds and switches
aries/health/automation.py     210 lines   the pass · genome · task kind · evaluators
aries/automations/genome.py    223 lines   AutomationSpec (§12) · run history · due · health
aries/notify/policy.py         218 lines   four levels · three gates · the record
aries/cli.py                   190 lines   health · automations · settings
scripts/aries                              the command line entry point
tests/test_health.py                       33 assertions
tests/test_notify.py                       22 assertions
tests/test_automations.py                  43 assertions
```

### Two ways of reading the machine, and why

`/proc` and `/sys` are read directly with Python file I/O. They are virtual files: reading
them has no side effects and cannot block on a device. Spawning `cat` would cost a process
and add locale-dependent parsing for no gain in safety. Disk usage uses `os.statvfs` rather
than parsing `df`, for the same reason.

`systemctl` and `nvidia-smi` have no file interface, so they go through the engine's sandbox
with an explicit, health-specific allowlist of four read-only commands — not the engine's
global one, which is broader than this needs. §4.2 of the migration guide asks each
application to define its own allowlist; this is ARIES's.

Capacity is computed against blocks available to an unprivileged user, not total blocks.
Ext4 reserves about 5% for root, so a filesystem at "95% by total blocks" is already full for
every normal process — which is the number the user cares about.

### The three gates between a finding and the user

1. **Level** — is it at or above `notifications.minimum_level`?
2. **Repeat** — has the user already been told, within the cooldown, without it worsening?
3. **Quiet hours** — is it late, and is this less than critical?

The repeat gate is checked before quiet hours so that the recorded reason is the honest one.
Every decision is written to `aries_notifications` **including the suppressed ones**, because
§29 requires that nothing ARIES does be invisible: "ARIES noticed this at 02:14 and held it
until morning" has to be answerable.

## How it works internally

```
run_pass(ctx)
  ├─ settings.section("health") + section("notifications")      one query each
  ├─ probes.run_all(enabled)                                    concurrent; a raiser is isolated
  ├─ baseline.record(readings)                                  measurable values only
  ├─ baseline.compute_many(keys)                                ONE query for every baseline
  ├─ judge(readings, config, baselines)                         thresholds → then softening
  ├─ notify.emit(finding) for each alert                        the three gates; all recorded
  ├─ triggers.record(...) for delivered criticals               evidence for a future repairer
  └─ record_run(status ok|degraded|failed)                      the check's own verdict
```

Then the lifecycle evaluates the result. `health_check_ran` is a hard error only when no
probe produced a reading; `probe_coverage` warns per unavailable probe. A CRITICAL finding
travels out through `requires_approval`, not through the evaluators — because the check
passed.

## Data flow

```
/proc · /sys · statvfs · systemctl · nvidia-smi
        ↓ Readings (measured, or an honest reason they are not)
   aries_health_samples ──→ baselines (median, p05, p95, n, trusted)
        ↓                        ↓
      judge(thresholds) ←── may only SOFTEN, within a ceiling, for eligible metrics
        ↓ Findings
   notification policy (level → repeat → quiet hours)
        ↓                    ↓                      ↓
   delivered            held for briefing        logged
        ↓
   critical → ActionProposal → a human       (ARIES never acts on the machine)
        ↓
   triggers.record → a future repair automation
```

## Dependencies

On the engine: the sandbox, `register_kind` and the lifecycle, `triggers`, evaluators,
`ActionProposal`, the shared `Base`. On ARIES: the Settings Service from Entry 002, which was
its first real consumer — and the interface held. Nothing needed changing, which is the
evidence that building settings first was the right order.

## Security implications

The automation is read-only and says so in its genome (`risk="low"`, `tools` naming the two
commands it may run). It holds `Permission.VIEW_DATA` and nothing more. The health allowlist
is four read-only commands; everything else is refused by the sandbox and would escalate.
No `sudo`, nothing writable, no network, no model — so no file content leaves the machine.

The one thing it *can* do that matters is create an `ActionProposal`, which is a request, not
an action, and the engine's approval machinery governs what happens to it.

## Performance implications

A full pass is **39–48 ms** on this machine, almost all of it `nvidia-smi` (~34 ms); the
`/proc` and `statvfs` probes are sub-millisecond. Probes run concurrently, which matters only
because of the two subprocess probes. Settings are read in two queries (one per section) and
every baseline in one, rather than one query per metric — at seven probes and roughly twenty
readings, the naive version would be about twenty round trips per pass, forever.

Storage: about 18 samples per pass, every 15 minutes, is roughly 630k rows a year.
`baseline.prune` drops anything past 90 days, while the baseline window is 14 — so there is
always more history than the window uses, if the window is ever widened.

## Risks

1. **Baseline poisoning.** A machine that is unhealthy while the baseline is being learned
   teaches ARIES that unhealthy is normal. Mitigated by the ceiling and the eligibility list,
   which bound the damage to one severity level on fluctuating metrics. A future guard could
   exclude samples taken while a finding was critical.
2. **`ACTIONABLE_CODES` is a hand-maintained set.** A new probe whose code is not added
   silently records no event. Acceptable while the list is short and in one place.
3. **Thresholds are global, not per-subject.** One temperature threshold covers every thermal
   zone; a chipset and a CPU package do not have the same normal. Baselines compensate per
   subject, but the thresholds do not. Worth revisiting when a second machine exists.
4. **No scheduler worker is registered yet.** The automation is due-aware (`due()` works and
   is tested) but nothing calls it on a timer; it runs from the CLI or an explicit task. That
   is the next step and is deliberate — a timer on an automation nobody has watched run is
   how you find out about a bug at 3 a.m.

## How the result was tested

98 new assertions across three suites, plus the existing 32, all in isolated processes.
Where a test needed a CRITICAL finding it lowers a threshold to its schema minimum rather
than filling the disk — the judgement path is identical.

```bash
cd ~/aries && ./scripts/test.sh
```

## Test results

```
=== engine ===                    passed 13 · failed 0 · 6s
=== engine reference example ===  all passed
=== aries ===
test_automations.py   passed  (43 checks)
test_health.py        passed  (33 checks)
test_notify.py        passed  (22 checks)
test_settings.py      passed  (32 checks)
ALL SUITES PASSED
```

The assertions worth quoting, because each pins a decision rather than a line of code:

```
PASS  a machine that is always critically hot is still critically hot
PASS  disk usage is not in SUPPRESSIBLE, so a baseline cannot soften it
PASS  one extreme sample cannot move the median
PASS  an unmeasurable reading becomes a NOTICE, not an OK
PASS  a full USB stick raises nothing — the advice would not apply
PASS  the lifecycle verdict is a pass — the check did its job
PASS  while the machine is reported CRITICAL
PASS  the task waits for the human rather than completing silently
PASS  with no runs the success rate is null, not zero
PASS  a just-delivered notification is suppressed whatever the local offset
```

And the live run on this machine:

```
System health  OK
healthy — 17 checks, nothing above threshold
   ·  load 0.23 across 12 cores (0.019 per core)
   ·  memory is 18.6% used (12.04 GiB available)
   ·  / is 2.9% full (420.58 GiB free)
   ·  x86_pkg_temp at 44 °C
   ·  NVIDIA GeForce RTX 3060 at 39 °C
   ·  no failed systemd units
45 ms · 18 samples recorded · task 1 · pass
```

## Errors encountered

**1. Two thermal zones with the same name collided.**
This machine has two zones both typed `acpitz`, so both produced the subject
`thermal.celsius:acpitz`. Since that string is the baseline key *and* the notification
identity, two physically different sensors would have shared one learned baseline and one
alert — each suppressing the other's notifications.
*Cause:* assuming a sensor's type is its identity. It is not; only the zone number is.
*Fix:* count the types first and suffix only the ambiguous ones, so the common case stays
readable (`x86_pkg_temp`, not `x86_pkg_temp0`).
*Found by:* running the probe against the real machine and reading the output. No unit test
against sample data would have caught it, because I would have written sample data with
unique names.

**2. The notification age was computed in the wrong clock — the worst bug of the entry.**
A second pass, seconds after the first, reported "already delivered **2.0h** ago".
*Cause:* `decide()` used `datetime.now()` (local time, UTC+2 here) while `created_at` is
written by the database with `func.now()` (UTC). The subtraction mixed two clocks.
*Why it mattered far more than the wrong number:* the suppression still *worked* here, by
luck of sign. West of UTC the age would be **negative**, `age < timedelta(hours=6)` would be
true for a different reason, and — with the comparison as originally written — the gate would
misbehave in exactly the situation it exists to prevent. A bug that only appears in certain
time zones, in a gate whose whole purpose is to keep a monitor from becoming noise.
*Fix:* two clocks, named and commented. Quiet hours are a statement about the user's day and
stay in **local** time; the cooldown is arithmetic against a database timestamp and moves to
**UTC**. The comparison is now bounded on both sides (`timedelta(0) <= age < cooldown`), so a
negative age can never satisfy it. Pinned by `test_repeat_gate_uses_utc_not_local`.
*Lesson:* a timestamp without a stated zone is a bug waiting for a plane ticket. When two
clocks legitimately coexist, name them in the code.

**3. Events were recorded once per pass, forever.**
A persistently critical finding wrote a new event every fifteen minutes. The engine's
trigger cooldowns meant it would not have flooded the *task* queue, so this was latent rather
than visible.
*Fix:* record an event only for findings whose notification was actually delivered, so event
recording inherits the repeat gate for free. Three passes produced 6 events before and 2
after.
*Lesson:* when two mechanisms need the same "is this new?" judgement, derive one from the
other rather than implementing it twice.

**4. A circular import.**
`aries.settings` imported `aries.health.settings` to register the thresholds, which triggered
`aries.health.__init__`, which imported the automation, which imported `aries.settings` —
still initialising.
*Cause:* a foundational module reaching up into a feature package.
*Fix:* it does not. Each feature package registers its own settings, and the top-level
`aries/__init__.py` is the single place that orders registration. The comment there says the
order is load-bearing.

**5. My own test was refused by the schema, correctly.**
Forcing a critical by setting `health.disk_critical_pct` to 2.0 raised
`SettingError: 2.0 is below the minimum 50.0`. The validation from Entry 002 did its job on
its first real encounter with a bad value — mine. The test now uses the temperature
threshold, whose schema minimum (40 °C) is below this machine's idle temperature.

**6. ANSI escapes were written to a pipe.**
`_paint()` checked `isatty()` but the `BOLD`/`DIM` constants did not, so piping `aries health`
into a file produced escape codes. Fixed by deciding once, at import, and making every
constant empty when not a terminal.

## What was learned

* **Run it against the real thing early.** Both of the serious bugs — the sensor-name
  collision and the clock mismatch — were found by running the code on this machine and
  reading the output, not by testing. Synthetic test data would have had unique sensor names
  and a single clock, because I would have written it that way.
* **"Is it usual?" and "is it fine?" are different questions,** and a learning system that
  confuses them silences exactly the alerts that matter. That one sentence produced both
  safety limits on baselines.
* **The engine had the right mechanism already.** `requires_approval` on a *passing* result
  was precisely the "the check worked, but a human is needed" path. The work was recognising
  which existing path fit, not inventing one.
* **Building the Settings Service first paid off immediately.** Health needed 21 settings and
  the interface needed no changes — which is the only real test of an interface.

## Rollback

```bash
rm -rf ~/aries/aries/health ~/aries/aries/notify ~/aries/aries/automations
rm -f  ~/aries/tests/test_health.py ~/aries/tests/test_notify.py ~/aries/tests/test_automations.py
rm -f  ~/aries/aries/cli.py ~/aries/scripts/aries
# then remove the imports from aries/__init__.py, and drop:
#   DROP TABLE aries_health_samples; DROP TABLE aries_notifications;
#   DROP TABLE aries_automation_runs;
```
No engine file was modified. Entry 002's Settings Service is untouched and still passes.

## Git commit

Still pending — `git` is not installed (`sudo apt install git`). Entries 001–003 will be the
first commits.

## What should happen next

1. **A scheduler worker**, so the automation runs on its interval instead of on demand. The
   engine's `scheduler/builtin.py` is the pattern, and `due()` already exists and is tested.
   Deliberately not done in this entry: putting an unwatched automation on a timer is how you
   meet its first bug at 3 a.m.
2. **The Automation Control Centre (§27)** as an API surface. `aries automations` already
   prints everything the specification asks it to show, so this is a route, not a redesign.
3. **The Sources Registry (§24)** and then the News Radar, which is the branch this entry
   stepped in front of.

---

# Entry 004 — The dispatcher and the Control Centre: making automation visible before making it autonomous

**Date:** 2026-09-12

## Objective

Let automations run on their own schedule (§11), and give the user one place to see and
control them (§27) — plus the settings and notification surfaces that §29 and §31 require.

## Problem being solved

Entry 003 built an automation that had to be asked to run. Two things were missing, and the
order in which they were added is the point of this entry.

The obvious one is a **scheduler**: something that notices an automation is due and runs it.

The important one is **visibility**. A background process that acts on its own while the
user has no way to see what it did, when it will do it next, or how to stop it, is not a
feature — it is a thing happening to them. §27 exists for exactly this reason and asks for
one graphical place showing enabled, version, purpose, trigger, last run, next run, last
result, health, agents, permissions, learning status and evolution history, with controls to
run, pause and inspect.

So the Control Centre was built **with** the worker, not after it, and the worker ships
switched off. The sequencing is deliberate: an unattended process should not exist before the
means to watch it.

## Why ARIES needs this

Without a dispatcher, §13's twenty automations are twenty things the user must remember to
run, which defeats the premise. Without the Control Centre, turning the dispatcher on would
mean handing over control of the machine in exchange for a log file.

There is also a structural reason. This entry is the first time two different callers — a
background worker and an HTTP route — run the same work. That is exactly where systems drift:
the scheduled path and the "Run now" button diverge, and the one that runs unattended at
03:00 is the one nobody tested.

## Concepts

**One dispatcher, not one timer per automation.** Each automation already knows its interval,
and `due()` answers "should this run now?" from its last recorded run. So the worker is a
*dispatcher* that wakes on a short cadence and asks each automation whether it is due. Twenty
automations do not become twenty asyncio tasks; an interval changed in Settings takes effect
on the next tick with no worker to restart; and pacing lives in the durable run history
rather than in a timer's memory.

**Last-run pacing, not a sleeping timer.** Inherited from the engine, and worth restating
because it is unintuitive: a timer restarts from zero on every reload, so a daily job on a
machine that reboots or suspends never fires. Reading the last recorded run means a missed
cycle is caught up late instead of skipped. The check is one indexed query.

**Cadence is not frequency.** The dispatcher ticks every 60 seconds; that is how often the
*question* is asked. An automation set to 15 minutes is checked fifteen times and run once,
and the fourteen extra checks are one query each.

**Refusing overlap rather than queueing it.** A pass that outruns its interval must not start
twice. Each automation holds an in-process lock and a second attempt is *refused*, not
queued: a queue lets a slow automation accumulate a backlog it can never work off, and for a
periodic measurement the next scheduled pass is a better answer than a stale queued one. The
refusal is recorded as a `skipped` run, so it is visible rather than silent.

**Fail-closed permissions.** The engine's route policy is a prefix table where the longest
match wins and anything unrecognised falls back to method defaults — where any mutation
demands `EDIT_TASK`. ARIES's routes were therefore already safe before this entry; they would
simply have been safe *by accident*, at the wrong permission. Registering them explicitly
states what each actually needs.

## Alternatives considered

**An external scheduler — cron, systemd timers, APScheduler.**
*Pros:* survives the process, standard, nothing to write.
*Cons:* a second source of truth about what should run. The state that decides — enabled,
interval, last run — lives in ARIES's database, so an external scheduler would either
duplicate it or ignore it. It also splits the audit trail in two and means a run that happens
outside the API process has no correlation id. The engine made this call already: "no external
scheduler process". Revisit only if ARIES must run with the API stopped.

**A worker per automation.** Rejected: twenty heartbeats and twenty restarts for what is one
question asked on a loop.

**A separate ARIES FastAPI app, proxying or beside the engine's.**
*Pros:* clean separation, ARIES could run without the engine's routes.
*Cons:* two middleware stacks, two ideas of who the caller is, two audit trails. The engine's
own comment on middleware order explains the cost: a correlation id must exist before anything
logs, and audit must sit inside auth so it can name the actor. Re-creating that correctly
twice is not worth the separation. ARIES imports the engine's `app` and adds a router to it.

**Exposing Edit, Duplicate and Rollback now**, since §27 lists them as controls. Rejected,
and this is the one worth defending. Those operate on a versioned genome, which is the
controlled-evolution engine of §18 — sandbox, benchmark, compare to a baseline, approve,
promote, roll back. A route that mutated a spec in place today would *look* like that feature
while providing none of its safety, and would have to be taken away again. They are absent
rather than stubbed; the genome already records `parent_version`, `evolution_history` and
`rollback_version`, so the data those controls will need is being collected from the start.

## Decision

| module | responsibility |
|---|---|
| `automations/runner.py` | the ONE path all three callers take; the overlap lock |
| `automations/worker.py` | the dispatcher, registered into the engine's worker roster |
| `api/routes.py` | the Control Centre, settings and notification surfaces |
| `api/permissions.py` | what each ARIES route demands |
| `api/app.py` | the engine's app plus the ARIES router |

**Everything runs through `run_automation`.** The worker, the API and the CLI differ only in
the `trigger` string they pass. An automation with a `task_kind` is not simply called — a Task
is created and handed to `run_task_now`, so every run inherits a durable record, an
evaluation, the retry/replan/escalate decision, an ActionProposal when a human is needed, a
correlation id and an audit trail. Bypassing the lifecycle would mean reimplementing all of
that, worse.

**Two switches, reported separately.** `automations.worker_enabled` (the user's setting,
`user_only`, default **false**) and the dispatcher task's actual state in this process. The
Control Centre shows both and says which is which, because "I turned it on but nothing
happens" and "it is on but the process died" are different problems.

**`force` runs a disabled automation without enabling it** — "Run now" on a paused
automation, so an operator can test one without changing its configuration. It does not skip
the overlap lock; two concurrent passes are always wrong.

## Implementation

### Files created

```
aries/automations/runner.py    152 lines   run_automation · run_due · the overlap lock
aries/automations/worker.py    108 lines   the dispatcher + its two settings
aries/api/routes.py            295 lines   13 routes: automations · settings · notifications · health
aries/api/permissions.py        45 lines   the route permission policy
aries/api/app.py                32 lines   the engine's app + the ARIES router
tests/test_api.py                          60 assertions, in-process over HTTP
scripts/start.sh                           rewritten (see Errors)
aries/cli.py                               `aries worker [--tick]`
```

### The genome gained two fields

`next_run_at()` derives the next run from the last recorded one plus the interval — the same
source `due()` uses, so the two cannot disagree. A disabled automation returns `None` rather
than a date that will not happen.

`learning_status` is an optional async callable on the spec. The Control Centre should not
have to know where an automation's learning lives, so the automation supplies it. Health's
reports how many metrics have a baseline, how many are **trusted**, and how many are of a kind
a baseline may soften — the distinction that matters, since an untrusted baseline suppresses
nothing:

> *0 of 18 metrics have at least 30 samples and are trusted; of those, 0 are the kind of
> metric a baseline is allowed to soften. Accumulating metrics such as disk usage are never
> softened.*

### The permission mapping

| route | GET | writes |
|---|---|---|
| `/api/aries/settings` | `view_data` | `manage_tools` |
| `/api/aries/automations` | `view_data` | `schedule` |
| `/api/aries/worker` | `view_data` | `execute` |

`POST /automations/{id}/run` resolves to **`execute`**, not `schedule`, because the engine
upgrades any path containing a `run` segment. Running work and scheduling it stay separate
permissions, which is the engine's intent and now ARIES's too.

The settings write route hard-codes its author as `"user"` rather than reading it from the
request. That is what makes the §30 write rules mean anything over HTTP: a caller cannot name
itself a human to reach a layer it should not. When per-person tokens are minted this becomes
the authenticated principal — the same place, still not the caller's choice of string.

## Data flow

```
worker tick (60s) ─┐
API POST /run     ─┼─→ run_automation(spec, trigger) ─→ overlap lock
CLI worker --tick ─┘                                      │
                                                           ↓
                                          Task ─→ run_task_now ─→ lifecycle
                                                           ↓
                                    evaluate → verdict → proposal if a human is needed
                                                           ↓
                                       AriesAutomationRun (status · summary · detail)
                                                           ↓
                          GET /api/aries/automations  ←  last run · next run · health · learning
```

## Security implications

Every new route is registered in the permission table rather than inheriting a default.
Reading the Control Centre needs only `view_data`; running an automation needs `execute`;
changing a setting needs `manage_tools`. The settings author is server-side. The dispatcher
ships **off**, and its switch is `user_only`, so no learning loop can ever turn on the thing
that runs other things.

`scripts/start.sh` binds to `127.0.0.1` and says why in a comment: `API_KEY` defaults to
empty, which means an open API — acceptable on loopback, never on a LAN.

## Performance implications

A tick with the switch off is one query (refresh the switch). A tick with it on is one query
per automation to check `due()`. A health pass remains ~40 ms. The dispatcher adds one asyncio
task to a process that already runs five engine workers.

## Risks

1. **The enabled-switch cache is one tick stale.** The engine calls a worker's `enabled`
   predicate synchronously, and the setting lives behind an async service, so the value is
   refreshed at the end of each pass and cached. Turning the worker on takes effect one tick
   later. The alternative — a blocking database read inside a synchronous predicate on the
   event loop — is worse, and a 60-second delay on a background dispatcher is not a real cost.
   Documented at the cache.
2. **The overlap lock is per-process.** Two API processes against one database could each run
   the same automation. Correct for a single-user desktop; a database-level lease is needed
   before ARIES ever runs more than one process.
3. **No per-automation error budget.** An automation that fails every tick will keep being
   retried forever. `health()` already records the failure rate; nothing acts on it yet.
   Worth a circuit breaker before automations that cost money exist.

## How the result was tested

60 new assertions driving the real ASGI app in-process with `httpx.ASGITransport`, plus a
live server on port 8077 exercised with `curl`. The in-process tests cover behaviour; the
live run proved the parts that only exist outside the test harness — that the dispatcher
actually starts under the engine's lifespan, and that `scripts/start.sh` works.

```bash
./scripts/test.sh
./scripts/start.sh 8077          # then curl /api/aries/automations
```

## Test results

```
=== engine ===                    passed 13 · failed 0
=== engine reference example ===  all passed
=== aries ===
test_api.py           passed  (60 checks)
test_automations.py   passed  (45 checks)
test_health.py        passed  (33 checks)
test_notify.py        passed  (22 checks)
test_settings.py      passed  (32 checks)
ALL SUITES PASSED
```

Live, against the running server — the dispatcher alongside the engine's own workers:

```
aries.automations      running   alive=True every=60s
autopilot              running   alive=True every=72000s
housekeeping           running   alive=True every=21600s
learning               running   alive=True every=86400s
scheduler              running   alive=True every=30s
triggers               running   alive=True every=600s

System Health Monitor v1.0.0  risk=low
  enabled=True  due_now=False  (ran 1 min ago (every 15 min))
  interval=15min  next_run=2026-09-12T17:44:37
  last_run=ok: healthy — 17 checks, nothing above threshold
  health=1.0 over 1 runs
```

It had already run itself once, on its own schedule, without being asked.

## Errors encountered

**1. The health automation shipped ENABLED BY DEFAULT — a specification violation.**
`POST /automations/aries.health/run` on a fresh database was expected to return 409
"disabled" and instead ran the automation.
*Cause:* `health.enabled` was defined with `default=True` in Entry 003. §11 says "do not
automatically activate every automation", and this project's own `AUTOMATIONS.md` states
"Nothing is enabled by default". I wrote both, and contradicted them in the same entry.
*Why Entry 003's tests missed it:* `test_disabled_until_asked_for` sets the value to `False`
before checking the disabled path, so it exercised the *behaviour* and never the **default**.
The API test caught it only because it starts from a fresh database and asserts nothing first.
*Fix:* default `False`, plus a structural guard — `test_no_automation_ships_enabled` reads
the schema default for **every** registered automation, so this cannot recur for one that
does not exist yet.
*Lesson:* a test that arranges state before asserting cannot test a default. When a rule is
about what ships, assert against the declaration, not against behaviour after setup. And a
rule written in prose in three places is still not enforced anywhere.

**2. `scripts/start.sh` exported the engine's own configuration into a syntax error.**
The server refused to start with
`line 35: status,journalctl,ps,ss,...: command not found`.
*Cause:* the script did `source <(grep -E '^[A-Z_]+=' .env)`, and `.env` contains
`SANDBOX_ALLOWED_COMMANDS=ls,cat,...,systemctl status,journalctl,...` — an **unquoted value
containing a space**. The shell split it and tried to run the remainder as a command. The
engine's own `start.sh` has the same defect in a different spelling (`export $(... | xargs)`).
*Fix:* the shell does not parse `.env` at all. pydantic-settings already reads it
(`env_file=".env"`), so exporting it was both redundant and fragile. ARIES's own defaults are
appended to `.env` once, on creation.
*Lesson:* when a library already reads a config file, having the shell read it too adds a
second, weaker parser — and shell is the worst available parser for anything containing
spaces.

**3. `pkill -f "uvicorn aries.api.app"` killed my own shell.**
The command exited 144 with no output. `pkill -f` matches against full command lines, and the
shell running the `pkill` had that exact string in its own command line — so it matched
itself.
*Fix:* `pkill -f "[u]vicorn aries"`. The bracket matches the same processes but the pattern
no longer matches its own literal text.
*Lesson:* an old trick, and still the right one. `pkill -f` with a literal pattern is
self-referential by construction.

## What was learned

* **Build the window before the machinery.** The Control Centre was written alongside the
  dispatcher rather than after it, and the dispatcher ships off. An unattended process should
  not exist before the means to watch it.
* **A test that sets up state cannot test a default.** This is the sharpest lesson of the
  entry: the Entry 003 suite looked thorough and had a hole precisely where the specification
  was most explicit. Rules about what *ships* must be asserted against the declaration.
* **Prose is not enforcement.** "No automation is enabled by default" appeared in the roadmap
  and in `AUTOMATIONS.md` and was still violated in code. It is now a test that covers
  automations nobody has written yet.
* **Two callers is where drift begins.** Making `run_automation` the only path — with the
  trigger string as the only difference — was cheap now and would have been expensive later.

## Rollback

```bash
rm -rf ~/aries/aries/api ~/aries/aries/automations/{runner,worker}.py
rm -f  ~/aries/tests/test_api.py
git checkout scripts/start.sh      # once git exists; otherwise it runs the engine app directly
# then remove the runner/worker exports from aries/automations/__init__.py
```
No engine file was modified. The permission entries are appended at import time, so removing
the ARIES package removes them.

## Git commit

Still pending — `git` is not installed. Entries 001–004 will be the first commits.

## What should happen next

1. **The Sources Registry (§24)** — a generic registry of user-configured sources (RSS, site,
   API, directory, repository) that agents query instead of hard-coding external addresses.
2. **The Interest Profile (§25)** and then the News Radar (§13/03), the first automation that
   reaches outside the machine — and therefore the first real exercise of the permission model
   on outbound work.
3. **A circuit breaker** for automations that fail repeatedly, before any automation can cost
   money (see Risks).

---

# Entry 005 — The Sources Registry: naming where ARIES may go

**Date:** 2026-09-12

## Objective

Build §24's generic Sources system: one registry of every place ARIES may get information
from — feeds, sites, APIs, folders, repositories, mailboxes — so that, in the specification's
words, "agents should query the Sources Registry instead of hard-coding external websites".

## Problem being solved

The visible problem is configuration: the user must be able to say "follow these five sites"
without editing YAML (§34), and agents must be able to ask what to consult without naming
anything themselves.

The real problem is that **this is the first component that names somewhere ARIES will later
GO**. Everything built so far was inward-facing: the Settings Service reads its own table,
the health automation reads `/proc` through a four-command allowlist. A source is different.
It is a stored instruction that some future component will act on — fetch this URL, read this
folder — and by the time that component runs, the user who typed the location is not there.

So the registry is not really a CRUD table with a validator attached. It is the place where
the question "may ARIES go here?" is answered, once, on the way in. Every consumer downstream
inherits that answer, and any consumer that has to re-ask it is a consumer that will
eventually forget.

## Why ARIES needs this

The News Radar (§13/03), Research Paper Watch (§13/04), Knowledge Ingestion (§13/11) and the
Morning Brief (§13/01) all need to know where to look, and §24 is explicit that they must not
each carry their own answer. It is also the prerequisite for §20's News settings screen and
§23's Connection Hub, both of which are views onto this registry.

## Concepts

**Validate on the way in, not on the way out.** A location that cannot be checked is
*refused*, not stored with a flag. The alternative — store it and let consumers check — puts
the security decision in every reader, and the value of a central registry is precisely that
the decision is made once. A rejection carries a sentence the user can act on.

**Resolve before judging.** `~/research` might be a symlink to `~/.ssh`. Any check made
against the string the user typed passes; only a check against the *resolved* path catches it.
So every path is expanded and `realpath`-ed first, and every rule is applied to where it
actually points. This is the single most important line of the module, and it is pinned by a
test that creates exactly that symlink.

**`outbound` as a declared property.** Whether a source reaches off this machine is the most
consequential fact about it: it decides whether privacy mode applies (§20), whether a
credential is involved (§32), and whether §21's "never send without permission" is in play. If
consumers had to infer it by pattern-matching locations, some would get it wrong. It is a
field on the type, so a consumer asks instead of guessing.

**Declaration, not inheritance.** The obvious design is a class per source type with a
`fetch()` method. That couples *describing* a source to *reading* one — but a user must be
able to add an RSS feed before anything that reads feeds exists. Types are declarations;
reading arrives later, per type, without the registry changing. A type that has no reader yet
says `needs_connector` and is excluded from what agents are offered, rather than appearing to
work.

**Robust ordering: layers, not a weighted blend.** §20 allows observed performance to inform
ranking and then states that "explicit user source preferences must override learned
preferences". A weighted score cannot honour that — enough mediocre results will always
eventually outweigh a HIGH the user set. So the sort is strictly layered: user priority, then
user trust, then observed usefulness, then reliability, then name. Observation decides ties
and nothing more.

**The cold-start trap.** A source never read has an *unknown* useful rate. Treating unknown as
zero sorts every new source to the bottom, where it is never consulted, never earns a record,
and stays there — a registry that quietly freezes its rankings on its first week of data. New
sources therefore sort at a neutral prior (`sources.unproven_prior`, default 0.5). The same
honesty rule as §13/20: null with a reason, never 0.

## Alternatives considered

**Sources as settings.** They are user-configured, and there is already a settings system.
*Rejected:* settings are *declared in code* and the user chooses values; a source is invented
by the user at runtime and has fifteen fields of its own, per-source health and per-source
counters. Settings would have become a generic key-value store, which is what a settings
system stops being useful as soon as it becomes.

**One table, no type registry** — a free-text `type` column.
*Rejected:* validation, default intervals, capabilities and the outbound flag all depend on
the type. Without a declaration, every one of those becomes a conditional somewhere else.

**Resolving hostnames at add time to block SSRF properly.**
*Rejected, with a caveat recorded below.* Resolving at validation proves nothing about what
the address will be at fetch time (DNS rebinding), it makes adding a source fail when the
network is down, and it makes the registry do I/O. The honest placement is at fetch time, in
whatever fetches, with the resolved address pinned. What this module does is block literal
private, loopback, link-local and reserved addresses — a guard against mistakes and casual
misuse, which is worth having and is not a complete defence.

**Letting a blocked source simply be deleted** instead of `Trust.BLOCKED`.
*Rejected:* "I never want this source" is information. A deleted source comes back the next
time something suggests it; a blocked one does not.

## Decision

| module | responsibility |
|---|---|
| `sources/types.py` | the nine source types, each declaring shape, reach and capabilities |
| `sources/safety.py` | may ARIES go here? — refuses, with a reason |
| `sources/models.py` | §24's field list, split into what the user said and what ARIES observed |
| `sources/service.py` | CRUD, the `for_agent()` query, health and performance recording |
| `sources/settings.py` | the four settings that apply to sources as a class |

**`for_agent()` is the interface §24 describes.** An agent says what kind of thing it needs
and what it is about; it gets an ordered list of places it is allowed to look. Disabled,
blocked, unpermitted, connector-less and — under privacy mode — outbound sources are *absent*,
not flagged. There is nothing for a consumer to check and forget.

**The user's half and ARIES's half never merge.** `priority` and `trust` are written only by
the user. `useful_rate`, `duplicate_rate` and `reliability` are counted by ARIES. They meet
only in `effective_rank()`, in that order, once.

## Implementation

### Files created

```
aries/sources/types.py       192 lines   9 types · Trust · Priority
aries/sources/safety.py      224 lines   path · URL · connector validation
aries/sources/models.py      181 lines   the table, health states, derived rates
aries/sources/service.py     337 lines   CRUD · for_agent · record_sync · record_feedback
aries/sources/settings.py     40 lines   4 settings
aries/api/routes.py                      +7 routes
aries/cli.py                             `aries sources [list|types|add|rm|resolve]`
tests/test_sources.py                    89 assertions
tests/test_api.py                        +14 assertions
```

### The safety rules, and what they caught

Run against real attack shapes before the tests were written:

```
ACCEPTED  legit feed               -> reuters-ai
ACCEPTED  legit folder             -> research
refused   symlink to ~/.ssh        -> is inside ~/.ssh, which privacy.excluded_paths forbids
refused   direct ~/.ssh            -> is inside ~/.ssh …
refused   /etc                     -> is inside the system directory /etc …
refused   traversal to .ssh        -> is inside ~/.ssh …
refused   localhost URL            -> 'localhost' is a loopback name
refused   127.0.0.1 URL            -> a loopback address
refused   private 192.168          -> a private address
refused   link-local 169.254       -> a link-local address (the cloud metadata range)
refused   file:// scheme           -> scheme 'file' is not allowed for this source type
refused   credentials in URL       -> credentials must not be embedded … stored in plain text
refused   nonexistent folder       -> does not exist
refused   bad type                 -> unknown source type 'telepathy' (known: api, calendar, …)
refused   duplicate location       -> already registered as 'reuters-ai'
```

The symlink case is the one that matters. It is caught only because resolution happens before
judgement — a check against the typed string would have let it through.

### `privacy.excluded_paths` gets its first enforcement

Defined in Entry 002 with a default of `["~/.ssh", "~/.gnupg"]` and marked `user_only`, it had
until now been a setting nothing read. The registry is the first component to enforce it, and
because enforcement is here rather than in each consumer, everything downstream inherits it.
That is the payoff of having built settings first: the denial existed before the component
that could violate it.

## How it works internally

```
add(name, type, location, …)
  ├─ types.require(type)                      → the declaration
  ├─ count < sources.max_sources
  ├─ safety.check(location, type,
  │      excluded  = privacy.excluded_paths   ← the user's own list
  │      allow_private = sources.allow_private_addresses)
  │     ├─ path: expanduser → realpath → excluded? → system dir? → exists & readable?
  │     ├─ url : scheme allowed? → host? → credentials? → private literal?
  │     └─ connector: "<connector>:<target>"
  ├─ location not already registered in this scope
  ├─ permissions ⊆ the type's capabilities
  └─ store + AuditEvent{outbound: …}

for_agent(type, topics, capability, scope)
  └─ enabled ∧ not blocked ∧ capability permitted ∧ connector exists
       ∧ (outbound → privacy mode off)
       ∧ (topics overlap ∨ source untagged)
     sorted by (priority, trust, usefulness, reliability, id)
```

## Data flow

```
user (UI · CLI · natural language) ──→ add/update ──→ safety.check ──→ aries_sources
                                                            │
                                                      refused, with a reason
                                                            │
agents ──→ for_agent(type, topics) ──→ ordered, permitted sources
                                              │
                                   (later) whoever reads them
                                              │
                            record_sync(ok, items_seen, useful, duplicate)
                            record_feedback(engaged, corrected)
                                              ↓
                       health · useful_rate · duplicate_rate · reliability
                                              ↓
                          ordering, but only among equally-ranked sources
```

## Dependencies

On the Settings Service (`privacy.excluded_paths`, `privacy.mode`, and its own four keys) and
on the engine's audit log. Nothing depends on it yet — the News Radar will be its first
consumer, which is the proper test of whether `for_agent()` is the right shape.

## Security implications

This is the security-heaviest component so far.

*Enforced:* symlinks resolved before judgement; `privacy.excluded_paths` honoured; system
directories refused; URL schemes allowlisted per type; credentials in URLs refused (they would
sit in the database in plaintext, and §32 puts secrets in the keyring); literal private,
loopback, link-local and reserved addresses refused unless explicitly allowed. Adding a source
requires `manage_tools`, not the `edit_task` a POST would otherwise default to — naming
somewhere ARIES will go is configuring the system's reach. Every add, update and removal is
audited with the location and whether it is outbound.

*Deliberately not claimed:* the address check reads the literal host and does not resolve it.
A public name that resolves to a private address passes, and so does one that resolves
differently at fetch time. Closing that means resolving at fetch time and pinning the address,
which belongs in the fetcher. This is written in the module docstring so no later reader
mistakes the guard for a defence, and it is the first item of the next entry's work.

## Performance implications

One indexed query per `for_agent()` call, then filtering and sorting in Python — correct at
the scale a personal registry has (the default ceiling is 200 sources). Validation of a path
does a handful of `stat` calls; URL validation does no I/O at all.

## Risks

1. **The SSRF guard is partial by construction.** Stated above and in the code. Must be
   completed by the fetcher, not here.
2. **`record_sync` is trusted.** Anything that reads a source reports its own item counts, so
   a buggy reader can distort a source's ranking. Acceptable while the only caller will be
   ARIES's own News Radar; worth revisiting if third-party readers ever exist.
3. **Topic matching is exact-string.** "ai" and "artificial intelligence" are different
   topics. The Interest Profile (§25) is where synonyms belong, not here.
4. **A folder registered while mounted becomes invalid when unmounted.** Health reports
   `stale`, but nothing re-validates the location. A revalidation pass belongs with whatever
   syncs.

## How the result was tested

89 assertions in `test_sources.py` plus 14 over HTTP, in isolated processes. The safety tests
construct the adversarial cases as real files — an actual symlink into an excluded directory,
an actual traversal path — rather than asserting against strings.

```bash
cd ~/aries && ./scripts/test.sh
```

## Test results

```
=== engine ===                    passed 13 · failed 0
=== engine reference example ===  all passed
=== aries ===
test_api.py           passed  (78 checks)
test_automations.py   passed  (45 checks)
test_health.py        passed  (33 checks)
test_notify.py        passed  (22 checks)
test_settings.py      passed  (32 checks)
test_sources.py       passed  (89 checks)
ALL SUITES PASSED
```

The assertions that pin decisions rather than code:

```
PASS  a symlink into an excluded path is refused
PASS  and a permitted symlink is stored resolved, not as the link
PASS  a source the user ranked HIGH comes first despite a terrible record
PASS  an unproven source outranks one with a proven bad record
PASS  its useful rate is reported as unknown, not as zero
PASS  a blocked source is absent, not flagged
PASS  a type whose connector does not exist yet is absent
PASS  privacy mode removes every outbound source
PASS  credentials embedded in a URL are refused — they would be stored in plain text
PASS  the cloud metadata address is named as such
PASS  a folder inside privacy.excluded_paths cannot be registered
PASS  the location is unchanged after a refused move
```

Live:

```
$ aries sources add --name "Evil" --type rss --location http://169.254.169.254/latest/meta-data
refused: '169.254.169.254' is a link-local address (the cloud metadata range). ARIES refuses
sources pointing at this machine or a private network by default — enable
sources.allow_private_addresses if that is really what you want

$ aries sources resolve --topics ai
  1. Reuters AI (reuters-ai)      priority=high trust=trusted useful=—
  2. Research papers (research-papers)  priority=normal trust=normal useful=—

$ aries settings-set privacy.mode true && aries sources resolve --topics ai
  1. Research papers (research-papers)
```

## Errors encountered

**1. `169.254.169.254` was reported as "a private address".**
Correct but unhelpfully vague. Python's `ipaddress` marks the link-local range as *both*
`is_private` and `is_link_local`, and my checks tested `is_private` first.
*Why it is worth fixing:* `169.254.169.254` is the cloud metadata endpoint — the single most
common SSRF target in existence. A user who typed it deserves to be told what they actually
aimed at, and a developer reading the rejection deserves the same.
*Fix:* check link-local before private, and name the metadata range explicitly.
*Lesson:* when several predicates are true at once, the order decides the message. Pick the
order by which word is most useful to the reader, not by which test is cheapest.

**2. A route-ordering hazard, caught before it bit.** `/sources/resolve` and `/sources/types`
would both be swallowed by `/sources/{source_id}` if declared after it — FastAPI matches in
declaration order, so `resolve` would have been read as a source id and returned 404. They are
declared first. Noted because the failure would have looked like a missing feature rather than
a routing bug.

**3. No test failures at all in this entry**, which is worth recording honestly rather than as
a boast: it means the adversarial cases were explored by *running* them (the fifteen-case probe
above) before the tests were written, so the tests were written against behaviour already
understood. The two previous entries found their bugs the same way — by running the thing
against reality first. That is now a deliberate habit rather than an accident.

## What was learned

* **The registry is a security boundary, not a table.** Framing it that way decided every
  question: refuse rather than warn, validate on the way in, make `outbound` a declared fact,
  and make the absence of a source the way a rule is enforced.
* **Resolve before you judge.** True of symlinks here; true of anything where the name a user
  gives and the thing it denotes can differ.
* **"Unknown" is not "zero", again.** The same rule that made a null success rate correct in
  Entry 003 makes a null useful rate correct here — and this time it also prevents a
  self-reinforcing failure, where burying new sources guarantees they stay unproven.
* **Layered ordering is how you honour an override.** Any weighted blend eventually lets
  learning outvote the user. Layers make it structurally impossible, which is the same
  technique as Entry 002's write rules.
* **Stating a limit is part of building the guard.** The address check is genuinely useful and
  genuinely incomplete. Writing that down in the module, rather than letting the next reader
  assume it is airtight, is the difference between a guard and a false sense of security.

## Rollback

```bash
rm -rf ~/aries/aries/sources ~/aries/tests/test_sources.py
# remove the sources routes from aries/api/routes.py and the entry from api/permissions.py,
# the `sources` import from aries/__init__.py, and the `sources` command from aries/cli.py
#   DROP TABLE aries_sources;
```
No engine file was modified.

## Git commit

Still pending — `git` is not installed. Entries 001–005 will be the first commits.

## What should happen next

1. **The Interest Profile (§25)** — topics with weights the user can inspect and override, and
   the place synonyms belong.
2. **The News Radar (§13/03)**, the first consumer of `for_agent()` and the first component to
   actually fetch. It must carry the fetch-time half of the SSRF guard: resolve, check the
   resolved address, and pin it for the request.
3. **A circuit breaker for automations** that fail repeatedly, still outstanding from Entry 004.

---

# Entry 006 — The Interest Profile: teaching ARIES what matters, and proving it cannot decide for you

**Date:** 2026-09-12

## Objective

Build §25's Personal Interest Profile: topics the user cares about with weights they control,
topics they never want to see, synonyms — and a deterministic, explainable answer to the
question everything downstream will ask: *is this item worth their attention, and why?*

## Problem being solved

Three problems, in increasing order of subtlety.

**The stated one.** The user must be able to say what matters, ARIES may learn weights from
behaviour, and §25 is explicit: "the user must always be able to inspect and override them",
"explicit user configuration has higher priority than inferred preferences."

**The one Entry 005 left behind.** The Sources Registry matches topics as exact strings, so a
source tagged `artificial intelligence` was invisible to a user who wrote `ai`. Synonyms had
to live somewhere, and the right somewhere is here: a synonym is a fact about what the USER
MEANS, not about where information comes from.

**The one that would have quietly ruined everything.** The obvious way to ask "is this text
about `ai`?" is `if "ai" in text`. That matches **s-ai-d**, **em-ai-l**, **camp-ai-gn**,
**Ukr-ai-ne**, **ag-ai-nst**, **cert-ai-nly**, **m-ai-ntain**. A profile built on substring
matching declares almost everything relevant. The user sees noise, blames the ranking, and the
actual defect — a broken matcher — never surfaces, because nothing ever errors.

## Why ARIES needs this

It is the precondition for every automation that filters rather than measures. The News Radar
(§13/03), Research Paper Watch (§13/04), Opportunity Radar (§13/18) and the Morning Brief
(§13/01) all reduce to "score this against what the user cares about, and keep the top of it".
§26's notification policy needs a relevance number to threshold on. And §20's news settings
screen is a view onto this profile.

## Concepts

**Word boundaries, not substrings.** Every term is compiled to a regex anchored with `\b` at
each end, and multi-word terms match as phrases with flexible whitespace (`llm\s+agents`), so
text from a feed with a newline in the wrong place still matches. A term that begins or ends
with a non-word character — `c++`, `.net` — cannot carry a boundary there, because `\b` would
never match; those ends are left unanchored.

**Noisy-OR, not a sum.** When several topics match, evidence combines as

```
score = 1 − ∏ (1 − weightᵢ)
```

A sum needs an arbitrary cap to stay in [0, 1], and then the cap decides the answer more than
the weights do. Noisy-OR saturates naturally — two strong matches are more convincing than one,
five are barely more convincing than four, which is how evidence actually behaves — and it
stays monotonic and explainable: every match can only raise the score, and each contribution
can be shown to the user as its own number. It reads as "the chance that at least one of these
topics is genuinely the subject", which is the question being asked.

**A stance, not a negative weight.** §25 lists "topics I do not care about" as its own
category. Modelled as `avoid`, such a topic **disqualifies outright** — no accumulation of
positive matches can outvote it. Weight 0 would only make it contribute nothing, which is a
weaker and different statement. The user means "not this", not "this, but less".

**Accent folding.** `normalise()` strips combining marks, so a user who types `cafe` matches
`café`. Small, but the alternative is a topic that silently fails on exactly the articles that
spell things properly.

## Alternatives considered

**Embeddings and cosine similarity for relevance.**
*Pros:* catches paraphrase; no synonym list to maintain.
*Cons:* needs a model on every item from every source, so it stops working with the network
down; it cannot explain itself beyond a number, which §25 and §29 both forbid; and it needs
tuning nobody can reason about. The engine's own rule applies — deterministic checks are the
backbone, a model is a second opinion. Worth revisiting as an *additional* signal once there
is a corpus to evaluate against, never as the only one.

**An LLM classifier per item.** Same objections, plus cost per item and non-determinism on
re-runs.

**Synonyms in the Sources Registry**, next to the topics that are already there.
*Rejected:* a synonym describes what the user means, and would have to be repeated on every
source tagged with the topic. Here it is stated once.

**A single `weight` column, overwritten by learning.**
*Rejected* for the third time in this project, for the third time correctly: provenance is
destroyed, and "what would ARIES think if I cleared this?" becomes unanswerable. The user's
weight and the learned weight are separate columns that meet only in `effective_weight()`.

## Decision

| module | responsibility |
|---|---|
| `interests/matching.py` | normalisation, word-boundary terms, noisy-OR scoring, the explanation |
| `interests/models.py` | the table; what the user said and what ARIES observed, kept apart |
| `interests/service.py` | CRUD, `score_text()`, `topics_for()`, `learn()`, engagement counting |
| `interests/settings.py` | three settings that apply to the profile as a whole |

**`learn()` writes `learned_weight` and physically cannot write `weight`.** The same technique
as Entry 002's settings and Entry 005's source ordering, for the same reason: the write path
enforces what the read path promises, so §25's precedence rule is not something a future
contributor has to remember. When an inference is shadowed by a user weight it is stored and
*reported* as shadowed, never silently dropped — because §25 requires the user be able to
inspect what ARIES concluded, and because clearing their own weight should fall back to the
inference rather than all the way to the default.

**Learning may weigh topics; it may not invent them.** `learn()` on an unknown topic is
refused. Deciding *what* the user follows is theirs; deciding *how much* is negotiable.

**`topics_for()` is the bridge to sources.** It returns the canonical topic *and* every
synonym, so asking the Sources Registry — which still matches exact strings — with that list
finds a source tagged either way. Entry 005's gap is closed without the registry changing.

## Implementation

### Files created

```
aries/interests/matching.py   186 lines   normalise · Term · Matchable · score
aries/interests/models.py     145 lines   the table, effective_weight, engagement rate
aries/interests/service.py    252 lines   CRUD · score_text · topics_for · learn
aries/interests/settings.py    26 lines   3 settings
aries/api/routes.py                       +5 routes
aries/cli.py                              `aries interests [list|add|rm|score]`
tests/test_interests.py                   73 assertions
tests/test_api.py                         +15 assertions
```

### Scoring, live

```
0.900  the model vendor ships new agentic tooling      matches 1 topic(s): llm agents (0.90)
0.600  5G rollout accelerates in the Balkans    matches 1 topic(s): telecom (0.60)
0.960  Agentic AI agents for telecom networks   matches 2 topic(s): llm agents (0.90), telecom (0.60)
0.000  Bitcoin ETF approved, agentic trading…   excluded: 'cryptocurrency' is on the list to ignore
0.000  A history of medieval pottery            no topic of interest appears in it
```

The fourth line is the stance rule doing its job: `agentic` matched at weight 0.9, and the
exclusion still won.

### The override rule, live

```
learned telecom=0.15                       -> effective 0.15   (no user weight set)
user sets 0.8, learner then says 0.05      -> effective 0.80
                                              shadowed: "the user's weight of 0.8 still decides"
user clears their weight                   -> falls back to the learned 0.05, not the default
```

## How it works internally

```
score_text(text, scope)
  ├─ profile(scope)                        ← global interests + this project's
  │    └─ per topic: Matchable(terms = canonical + synonyms,
  │                            weight = user ?? learned ?? default,
  │                            avoid, source)
  └─ score(normalise(text), matchables)
       ├─ any AVOID term present?  → 0.0, naming the topic and the term   [stop]
       ├─ collect WANT hits on word boundaries
       └─ 1 − ∏(1 − wᵢ), rounded, with every contribution attached
```

## Data flow

```
user (UI · CLI · natural language)  ──→ add/update ──→ aries_interests.weight
learning loop ──→ learn() ─────────────────────────→ aries_interests.learned_weight
                                                          │  (never the user's column)
                                                          ↓
                                                  effective_weight()
                                                          ↓
        item text ──→ score_text() ──→ {score, matched topics, terms, why}
                                                          ↓
                     notification policy · ranking · the briefing
                                                          ↓
                     record_engagement(shown | engaged | dismissed)
                                                          ↓
                     evidence for the next learn() — which still cannot overrule
```

## Dependencies

On the Settings Service (`interests.default_weight`, `interests.max_topics`) and the engine's
audit log. `topics_for()` is designed for the Sources Registry but does not import it —
sources and interests stay independent, and the News Radar is what will join them.

## Security implications

Modest, and worth stating precisely because it is not nothing. The profile is a description of
the user's attention, which is personal data: it says what they care about and what they avoid.
It stays in the local database, is never sent anywhere by this module, and nothing here
fetches. `privacy.excluded_memory_topics` (Entry 002) is the setting that should eventually
keep a topic out of memory entirely; wiring it is owed by whatever writes memory, not by this
module, and it is recorded as such. Editing the profile requires `edit_task` rather than the
`manage_tools` sources need — a topic shapes what reaches the user but names nowhere ARIES
will go.

## Performance implications

Regexes are compiled once per `Matchable` and the profile is built per call — one query, then
pure CPU. Scoring one headline against a 300-topic profile is well under a millisecond. If a
future caller scores thousands of items in a loop, the profile should be built once and passed
in; `score()` already takes the matchables, so that is a caller change and not a redesign.

## Risks

1. **Synonyms are manual.** "LLM" and "large language model" are only the same if the user
   says so. A suggestion pass (propose synonyms from what co-occurs) is a reasonable later
   addition; inventing them automatically is not, since a wrong synonym silently widens a topic.
2. **No stemming.** "agent" does not match "agents". Deliberate for now: stemming English is
   easy to do badly, and a wrong stem widens a topic invisibly. The user can add the plural as
   a synonym, which is explicit and inspectable.
3. **A very common word as a topic** ("data", "systems") will match almost everything at its
   full weight. Nothing prevents it. The engagement counters are the evidence that would let a
   later pass suggest narrowing it.
4. **Engagement is counted but not yet turned into a weight.** `learn()` exists and is tested;
   nothing calls it automatically. That is the medium loop of §16 and belongs with the News
   Radar, where there will be something to engage with.

## How the result was tested

73 assertions in `test_interests.py`, 15 more over HTTP. The substring trap has a test of its
own that asserts each of seven decoy strings scores zero.

```bash
cd ~/aries && ./scripts/test.sh
```

## Test results

```
test_api.py           passed  (93 checks)
test_automations.py   passed  (45 checks)
test_health.py        passed  (33 checks)
test_interests.py     passed  (73 checks)
test_notify.py        passed  (22 checks)
test_settings.py      passed  (32 checks)
test_sources.py       passed  (89 checks)
ALL SUITES PASSED
```

The ones that pin decisions:

```
PASS  'ai' does not match inside 'she said so'
PASS  'ai' does not match inside 'check your email'
PASS  'ai' does not match inside 'Ukraine'
PASS  a term ending in punctuation still matches          (c++)
PASS  an avoided topic disqualifies despite a perfect positive match
PASS  combining 0.9 and 0.6 gives 0.96
PASS  an explicit user weight outranks the learned one
PASS  clearing the user weight promotes the learned one, not the default
PASS  learning about an unknown topic is refused
PASS  the learned one is still visible … and marked as overridden
PASS  avoided topics are not offered as things to look for
```

## Errors encountered

**1. A floating-point artifact that would have looked like a flaky threshold.**
Two tests failed: a topic learned at weight `0.2` scored `0.19999999999999996`, and one at
`0.01` scored `0.010000000000000009`.
*Cause:* noisy-OR computes `1 − (1 − w)`, which is not an identity in binary floating point.
*Why it mattered more than the wrong digits:* the artifact bites `0.2` and `0.01` but **not**
`0.6` or `0.9`. A user setting a topic to 0.2 and a threshold to 0.2 would find that topic
silently excluded, while a colleague using 0.6 saw it work — a bug that presents as "the
threshold is flaky" and sends you looking in entirely the wrong place.
*Fix:* round the combined score to nine decimal places, far finer than any threshold a human
would set and coarse enough to absorb the error. This makes *"a single matching topic scores
exactly its weight"* a real invariant rather than an approximate one.
*Lesson:* when a formula is algebraically an identity, floating point may disagree — and it
will disagree for some inputs and not others, which is the hardest failure shape to diagnose.
Round at the boundary where a number becomes a decision.

**2. Caught while writing, not after: `clear_weight` as a flag.**
The natural REST spelling for "remove my weight" is `{"weight": null}`, but JSON cannot
distinguish *"set this to nothing"* from *"I did not mention this field"* — and the PATCH body
already omits unmentioned fields. Sending null would have been read as "no change", so
clearing would silently do nothing. An explicit `clear_weight: true` flag says the thing that
is actually meant.

## What was learned

* **The dangerous bugs are the ones that never raise.** Substring matching does not error, it
  just declares everything relevant; the floating-point artifact does not error, it just
  excludes some weights. Both would have surfaced as vague dissatisfaction with ranking, months
  later. Testing the *decoys* — asserting that "said" and "email" score zero — is what makes
  the first one visible.
* **The same separation has now paid off three times.** User value and learned value in
  separate columns, meeting in one function: settings (Entry 002), source ordering (Entry 005),
  topic weights (here). It is the project's most reused idea, and every instance of it makes a
  specification rule structural instead of procedural.
* **Deciding *what* versus deciding *how much*.** Refusing `learn()` on an unknown topic drew
  a line worth naming: ARIES may weigh what the user chose to follow, but may not choose what
  they follow. That distinction will matter again for automations and for memory.
* **Explanations are cheap if you build for them.** Returning the matched topic, the term that
  matched, and the weight's origin cost a few lines because the matcher already knew all three.
  Retrofitting it to an embedding score would have been impossible.

## Rollback

```bash
rm -rf ~/aries/aries/interests ~/aries/tests/test_interests.py
# remove the interests routes from aries/api/routes.py, the entry from api/permissions.py,
# the `interests` import from aries/__init__.py, and the `interests` command from aries/cli.py
#   DROP TABLE aries_interests;
```
No engine file was modified.

## Git commit

Committed with this entry — `git` is now installed and Entries 001–005 were committed as the
repository's first two commits.

## What should happen next

**The News Radar (§13/03)** — the first automation that fetches, and the piece that joins
everything built so far: sources to look at, interests to score against, the notification
policy to decide who hears about it, the dispatcher to run it. It owes two things recorded
earlier:

1. the **fetch-time half of the SSRF guard** — resolve the hostname, check the resolved
   address, and pin it for the request (Entry 005);
2. a **circuit breaker** for automations that fail repeatedly (Entry 004), which matters as
   soon as an automation talks to a network that can be down.

---

# Entry 007 — The News Radar: the first automation that reaches the internet

**Date:** 2026-09-12

## Objective

Build §13/03's Personal News Radar — `collect → cluster → verify → rank → deliver` — as a real
workflow through the Director, and pay the two debts recorded earlier: the fetch-time half of
the SSRF guard (Entry 005) and a circuit breaker for automations that fail repeatedly (Entry 004).

## Problem being solved

This is the first component that **reaches outside the machine**, and the first that joins every
piece built so far: sources to look at, interests to score against, the notification policy to
decide who hears, the dispatcher to run it, the circuit breaker to stop it when the world breaks.

The hard part is not fetching. It is that **a news feature is judged by what it does not show**.
A radar that delivers everything relevant is a radar nobody reads, and every design decision
below is about restraint — dedup, thresholds, caps, diversity, the repeat gate.

## Concepts

**A workflow, not a function.** The pipeline is a `WorkflowSpec` of five `NodeSpec`s with
dependencies and gates, executed by the engine's Director. Writing it as one `async def` would
have worked and thrown away everything §9 and §10 ask for: each node's decision is persisted,
each is traced, and §19's topology evolution has something to operate on later. `GET
/api/tasks/{id}` shows the whole pass, node by node, with the reason each ran or skipped.

**Jaccard similarity over stemmed word sets** for near-duplicate detection — two headlines about
one event share vocabulary but not order, so a set comparison has exactly the right invariance.

**Address pinning.** The fetcher resolves a name, validates *every* address it returns, then
connects to the validated IP with `Host` and TLS SNI set to the original name. There is no
second resolution for an attacker to win, and the certificate is still verified. Redirects are
followed manually so every hop is re-checked.

## Alternatives considered

**`feedparser`** — the obvious dependency, not taken. §3 asks that each dependency be justified
rather than adopted for popularity. RSS and Atom are small stable formats; ~150 lines of standard
library covers them, and it means one fewer package parsing hostile input in this process. The
moment ARIES needs the long tail of malformed real-world feeds, that is a reason to reconsider.

**A model for relevance** — rejected for the third time, consistently: it stops working offline,
costs a call per item, and cannot explain itself, which §25 and §29 both require.

**Automatic redirect following** — rejected. It is the single most common SSRF bypass: a
legitimate host answering `302 Location: http://169.254.169.254/…`.

## Implementation

```
aries/news/fetch.py        227 lines   resolve · validate every IP · pin · per-hop redirects · caps
aries/news/feed.py         213 lines   RSS/Atom/RDF, DTD-refusing, markup stripped
aries/news/dedupe.py       167 lines   identity keys · stemmed Jaccard clustering
aries/news/models.py       106 lines   every item stored, including what was not shown
aries/news/automation.py   330 lines   the workflow, the genome, the evaluators
aries/automations/breaker.py 140 lines the circuit breaker
tests/test_news.py                     38 assertions against a local feed server
```

**The circuit breaker** reads the durable run history rather than holding a counter, for the same
reason the dispatcher is paced by the last recorded run: a process restart would otherwise grant
a failing automation a fresh set of attempts, and during an incident restarts are exactly what
happens. Three states — closed, open, half-open — so it heals when the world does instead of
needing a human to re-enable it. `force` does not bypass it: "Run now" on a broken automation
should say it is broken, not queue another failure.

## Live result

```
8 delivered from 3 source(s), 0 held, 0 duplicates merged, 14 rejected, 4 sources

1.00  The Agent Incident Registry: Toward Preventing Repeated AI Agent Failures   arxiv · ai, agents, security
0.98  Finishing the Task Is Not Enough: Evaluating Agent Resilience               arxiv · ai, agents
0.90  the model vendor boss Dario Amodei calls for AI development to slow down           bbc   · ai
0.90  Nvidia is the central bank of AI                                            hn    · ai
```

## Errors encountered

Five, and four were only visible by running it against the real internet.

**1. The DOCTYPE guard refused a legitimate feed.**
`github.blog/feed/` was rejected as "document declares a DOCTYPE". It is valid RSS — but one of
its articles quotes `<!DOCTYPE html PUBLIC …>` inside escaped post content, and my check scanned
a flat 4 KB window.
*Fix:* a DOCTYPE is a declaration, and a declaration is only meaningful in the **prolog**. Search
only up to the first element start-tag; after `<rss>` opens, the same characters are content.
*Lesson worth keeping:* **a security check that rejects legitimate input gets turned off**, so
its precision is itself a security property. A guard with false positives is a guard with a
countdown on it.

**2. Relevance was mistaken for urgency.**
The first live pass delivered **26 items against a cap of 8**. Anything above
`news.breaking_threshold` bypassed the cap — and with two interests weighted 0.9 and 0.85,
noisy-OR puts almost any doubly-matching item at 0.98, so every arXiv paper was "breaking news".
*Fix:* the cap applies to everything. Relevance decides *how* an item is delivered — interrupt
now or wait for the briefing — never *how many* may be delivered.

**3. The News Radar recorded no automation runs at all.**
The Control Centre said "last run: never" after a successful pass, `health()` had no data, and —
worst — **the circuit breaker reads that table, so the one automation that talks to a network had
no breaker.** The health automation recorded its own row; the news workflow had no line that did.
*Fix:* the **runner** records for every automation on the lifecycle path, so a future one cannot
forget. A body that knows better still wins: health returns `status: degraded` when a probe
could not run, and the runner records that instead of guessing from the verdict.
*Lesson:* when a cross-cutting fact must be recorded for every member of a class, record it in
the one path they all take — not in each of them, where the newest member will be the one that
forgets.

**4. The step that reports was skippable by the conditions it reported on.**
When every source failed, `collect` returned no items, the cluster gate closed, and `verify`,
`rank` and `deliver` all skipped as dependents. `deliver` is what assembles the result — so a
pass in which **every single source was dead returned an empty dict and was recorded as a
success**, and the evaluator written specifically to catch that case never saw the data.
*Fix:* `deliver` depends on `collect`, not on `rank`. It runs whatever the gates decide, and its
position in the node list keeps it last.
*Lesson:* **a reporting step must not be downstream of the failures it exists to report.** This
is the most valuable bug of the entry, and it was found only because a test asserted on a
condition — "every source failed" — that the happy path never produces.

**5. One prolific source won the entire briefing.**
The first correct run delivered 9 of 10 items from arXiv, every one scoring higher than anything
the other three sources offered. By the user's own relevance numbers it was the optimal set, and
it was a worse briefing: they asked to be kept informed, not to be handed the highest scores.
*Fix:* `news.max_per_source_in_briefing`, default 3, applied before the overall cap. The result
went from 9-of-10 from one source to 8 items across three.
*Lesson:* optimising a metric is not the same as serving the goal. The metric was right and the
outcome was wrong, which is the ordinary way ranking systems fail.

**Also:** exporting `fetch` from `aries/news/__init__.py` shadowed the `aries.news.fetch` module,
so `from aries.news import fetch as F` silently bound the function and eight security tests failed
with `AttributeError`. Imports now name what they want from the module directly.

## What was learned

* **Run it against reality.** Four of five bugs were invisible against test fixtures: my sample
  feeds had no quoted DOCTYPE, my sample interests had one weight, my sample sources were equally
  prolific. The local test server is still where the *rules* are pinned — deterministically — but
  it cannot tell you your rules are wrong.
* **Test the unhappy path's data, not just its verdict.** The "every source failed" bug survived
  because nothing had ever asserted on what that case *returns*.
* **Restraint is the feature.** Dedup, thresholds, caps, per-source diversity and the repeat gate
  are most of this entry. Collecting is easy.

## Rollback

```bash
rm -rf ~/aries/aries/news ~/aries/tests/test_news.py ~/aries/aries/automations/breaker.py
#   DROP TABLE aries_news_items;
```

## Git commit

Committed with this entry.

## What should happen next

1. **The medium learning loop (§16).** Engagement is counted per item, per source and per topic;
   nothing yet turns it into a learned weight. `learn()` exists, is bounded, and cannot overrule
   the user — the loop that calls it is what is missing.
2. **The Morning Brief (§13/01)**, which is now mostly assembly: the news queue, the health
   summary and the held-notification queue already exist.
3. **`robots.txt`**, recorded in SECURITY.md as owed before any broader crawling.

---

# Entry 008 — Learning from behaviour, and choosing where news comes from

**Date:** 2026-09-12

## Objective

Two things the user asked for together, and they belong together: §16's medium learning loop —
adjust preferences from what is actually read — and a catalogue of feeds to pick from, because
§24 lets any feed be added only if you already know its URL.

## Problem being solved

**Learning.** Every component so far has been able to *record* a learned value and none has ever
produced one. `interests.learn()` and `SettingsService.learn()` were built, bounded and tested
across three entries with nothing calling them. This is the caller.

The difficulty is not the mechanism, it is the restraint. A loop that reacts to every click
produces a system whose opinions change for no visible reason, which is worse than one that never
learns — the user cannot predict it, so they stop trusting it, so the learning is worse than
useless.

**Choosing sources.** Nobody knows the URL of a feed. §34 asks that configuring ARIES feel like
configuring an operating system, and `https://feeds.bbci.co.uk/news/rss.xml` typed from memory is
the opposite of that.

## Concepts

**The Wilson score interval.** Given `k` successes in `n` trials it gives a *range* the true rate
plausibly occupies, and unlike the normal approximation it behaves near 0, near 1, and at small
`n` — which is the entire regime here. ARIES judges the interval, never the point estimate:

```
 1/3  → [0.06, 0.79]   too wide to mean anything → do nothing
 2/40 → [0.01, 0.17]   low even optimistically   → lower the weight
33/33 → [0.90, 1.00]   high even pessimistically → raise it
```

One click in three is not a 33% engagement rate. It is no evidence, and the interval is what says
so. This is the same instinct as the health baselines' robust statistics: prefer the estimator
that refuses to overreact.

**Two brakes on every change.** Confidence scales the step by how much evidence there is;
`learning.max_step` caps it regardless. A bug in the evidence should cost the user a nudge, not
their configuration.

**The circular-evidence trap.** Evidence is drawn only from items the user could actually act on
— `delivered` and `held`. Counting items *below* the threshold as "not engaged" would teach the
system that everything it withheld was uninteresting: a topic scored low, so it was never shown,
so it looked uninteresting, so it scored lower. That is how a recommender collapses onto its own
first guess, and excluding those rows is what prevents it.

**The bar only ever rises.** Heavy dismissal proposes a *higher* relevance threshold. Nothing
proposes lowering it, because the evidence for "you would have wanted more" can only come from
items the user never saw — the same circularity from the other direction. If the bar is too high
the user lowers it; the system only ever offers to be quieter.

## Decision

| module | responsibility |
|---|---|
| `learning/statistics.py` | Wilson intervals, bounded steps |
| `learning/loop.py` | gather evidence → propose → apply |
| `learning/automation.py` | the genome; off by default, no task kind |
| `news/catalogue.py` | 23 verified feeds, grouped by subject |

**Four rules the loop cannot break**, each enforced by a mechanism rather than a convention:

1. It writes the **learned layer** only — `learn()` physically cannot reach a user value.
2. It may **weigh** topics, not **invent** them — an unknown topic is refused.
3. It acts on **intervals**, not rates.
4. It moves **slowly**, and can propose without applying (`learning.apply_changes`), which is
   §18's observe → measure → propose in the small.

**The catalogue** is a suggestion list, not a privilege: an entry becomes an ordinary row subject
to the same validation as a hand-typed URL. Every entry was fetched and parsed on this machine
before being listed, and the three that failed are recorded in `UNAVAILABLE` rather than silently
dropped, so nobody re-checks them.

## Live result

```
$ aries news scan
44 delivered from 7 source(s), 0 held, 15 duplicates merged, 68 rejected, 9 sources

$ aries learning evidence
  ai            shown 33  opened 33  dismissed 0   rate 100%  [90%–100%]
  programming   shown 15  opened  6  dismissed 4   rate  40%  [20%–64%]
  agents        shown 10  opened 10  dismissed 0   rate 100%  [72%–100%]
  security      shown  8  opened  3  dismissed 5   rate  38%  [14%–69%]  (not enough yet)

$ aries learning propose
  ↑ ai      0.90 → 0.98   you opened 33 of 33 items about 'ai' — even at the pessimistic
                          end of the interval that is 90%, above the 40% mark
  ↑ agents  0.85 → 0.93   you opened 10 of 10 items about 'agents' — …72%…
```

`programming` at 40% is genuinely ambiguous and is left alone; `security` has 8 observations and
is below the minimum. Both are the loop declining to act, which is most of its job.

## Errors encountered

**1. The loop was reading five sixths less evidence than existed.**
`gather()` counted only `delivered` items. A live run delivered 6 and **held 23** — and held items
appear in the briefing, so the user sees them. The loop was blind to almost everything they would
actually read.
*Fix:* evidence is `delivered` + `held` — what the user had the opportunity to act on. Items
below the threshold stay excluded, for the circularity reason above.
*Lesson:* "shown to the user" and "delivered as an interrupt" are different sets, and I had
conflated them in the component where the distinction decides what gets learned.

**2. Cyrillic source names produced meaningless ids.**
Adding the Macedonian feeds gave `source` and `source-2`: `slugify` strips everything outside
`[a-z0-9]`, so "Мета.мк" and "МИА" both reduced to nothing. That id appears in URLs, in agent
prompts and in provenance.
*Fix:* transliteration (Macedonian, plus the Serbian and Russian letters that differ) and accent
folding, so "Мета.мк" → `meta-mk` and "Zeitung für Politik" → `zeitung-fur-politik`. A catalogue
entry also passes its own id as the slug base, since it is stable across renames.
*Lesson:* an ASCII-only slug is a latent bug in any system whose user does not write in ASCII.
It took a user writing in Macedonian to surface it, and it would have surfaced as "why are my
sources called source-2".

**3. Learned weights carried sixteen decimal places.**
A test comparing a stored weight with a score failed: `0.7885944107755797` against `0.788594411`,
because relevance scores are rounded (Entry 006) and learned weights were not.
*Fix:* round proposals to three places. Not a test convenience — that number appears in the
Settings UI and in the explanation of why an item was shown. Precision the system cannot justify
is noise, and noise that reaches the user is a bug.

**4. A catalogue entry went bad between writing it and shipping it.**
`mia.mk` answered on the first verification pass and, an hour later, timed out on three
consecutive attempts. I had claimed every entry was verified.
*Fix:* moved to `UNAVAILABLE` with exactly that note. The source-health machinery caught it
correctly in the meantime — it showed as `degraded` with the connection error, which is the system
working.
*Lesson:* "verified" has a timestamp on it. The honest form is a list of what was checked, when,
and what failed — not a claim that the list is good.

**Also:** the schema refused `news.max_items_per_briefing = 80` (maximum 50) during the demo.
Entry 002's validation catching me for the second time, which is the point of it.

## What was learned

* **Most of a learning loop is the part that declines to act.** Of four observed topics in the
  live run, two produced changes and two did not, and the two that did not are the harder
  engineering.
* **Circular evidence is the characteristic failure of anything that learns from what it chose to
  show.** Both guards here — excluding below-threshold items, and only ever raising the bar —
  exist for that one reason.
* **The separation has now paid off four times, and this was the payoff it was built for.**
  `learn()` was written in Entry 002 and could not reach a user value; four entries later the
  component that calls it inherited that guarantee for free.

## Rollback

```bash
rm -rf ~/aries/aries/learning ~/aries/tests/test_learning.py ~/aries/aries/news/catalogue.py
# remove the learning + catalogue routes, the learning import from aries/__init__.py,
# and the `learning` / catalogue commands from aries/cli.py
```
No new table: the loop reads what is already recorded and writes into existing learned layers.

## What should happen next

1. **The Morning Brief (§13/01)** — now mostly assembly: the news queue, the health summary, the
   held-notification queue and the learning status all exist.
2. **Reversal detection.** A topic lowered and then raised again is evidence the loop overreacted;
   `reversal_rate` is declared in the genome's metrics and nothing computes it yet.
3. **A visual Settings surface.** The CLI now covers sources, interests, learning and news, which
   is enough to know what the screens should contain.

---

# Entry 009 — The Morning Brief: one page, and the first parallel workflow

**Date:** 2026-09-12

## Objective

Build §13/01's Morning Intelligence Brief — parallel collection, then synthesis into one page —
and give the automation genome the time-of-day scheduling a morning brief obviously needs.

## Problem being solved

Most of this entry is assembly: the news queue, the health findings, the pending proposals and
the learning status all exist. The interesting problems are the three that only appear when
things are put together.

**Parallel collection is where a shared database session breaks.** §13/01 asks for it, and it is
the first place ARIES actually runs nodes concurrently.

**A brief is judged by what it leaves out.** Same lesson as the News Radar, one level up: a page
listing every section whether or not it has anything is a page nobody reads twice.

**Absence has two meanings.** A calendar section that is empty because there are no meetings and
one that is empty because no calendar is connected look identical on the page and mean opposite
things.

## Concepts

**One session per concurrent collector.** Verified before the design relied on it: five
coroutines sharing one `AsyncSession` inside `asyncio.gather` raise

```
IllegalStateChangeError: Method 'close()' can't be called here;
method '_connection_for_bind()' is already in progress
```

An `AsyncSession` is one logical connection with in-flight state, and two coroutines inside it
corrupt each other. The engine says the same thing from the other direction — "keep tool calls
that share a session sequential, or give each its own session" — and parallel collection is
exactly where it bites. Every collector therefore takes no session and opens its own.

**Length as a question, not a truncation.** Each length answers something different — *what needs
me?* / *what should I know?* / *everything, with reasoning* — so each keeps different things.
Truncating a standard brief would drop the decisions queue as readily as the news.

**Time-of-day pacing.** A brief at 07:30 is a statement about the user's morning, not about
elapsed minutes. The genome gained `time_setting`, and `due()` compares against today's local
target — still driven by the last *recorded* run, so a machine asleep at 07:30 produces the brief
when it wakes rather than skipping the day.

## Decision

| module | responsibility |
|---|---|
| `brief/sections.py` | eight collectors, each with its own session |
| `brief/render.py` | three lengths, each keeping different things |
| `brief/models.py` | briefs are kept, not just printed |
| `brief/automation.py` | the parallel workflow, the genome |

The graph is `prepare → 8 collectors in parallel → compose`.

**No section node is ever skipped**, and that is deliberate. The obvious design gates each
section on `briefing.sections` — which reproduces Entry 007's bug exactly, since `compose`
depends on all of them and a skipped dependency skips its dependents. So a switched-off section
returns itself marked unavailable, and `compose` cannot be skipped by the configuration it exists
to render.

**Order comes from settings, not from the graph.** The graph decides what is collected and with
what concurrency; `briefing.sections` decides what is shown and in what order. Reordering a brief
never touches the workflow.

**Decisions come first**, because they are the only section the user is *blocked* on. Everything
else is information; that is a queue.

## Live result

```
Morning brief  Sat 12 Sep, 20:55
1 decision(s) waiting for you

Waiting for you  1 decision(s) pending
!! system.critical: System Health Monitor
     Evaluation passed; consequential — needs a human.

System  2 thing(s) to look at
!! pch_cannonlake at 52 °C
     Check airflow and dust; sustained heat throttles the machine.

News  6 worth your time, of 80 seen
 · The Agent Incident Registry: Toward Preventing Repeated AI Agent Failures
 · Nvidia is the central bank of AI
  … and 1 more

ARIES itself  everything running

What I learned  nothing changed
```

## Errors encountered

**1. The shipped section list named a section that was never built.**
`briefing.sections` was defined in Entry 002, before any collector existed, as
`["priorities", "calendar", "news", "projects", "system"]`. "priorities" has no collector; the
three sections that turned out to matter most — decisions, automations, learning — were not in it.
The first live brief therefore led with *Calendar: not built yet* and omitted the decision queue.
*Fix:* a default of what exists and matters, `choices` on the setting so a typo is refused, and an
evaluator that warns when `briefing.sections` names something unknown.
*Lesson:* a default written before the thing it configures exists is a guess, and it does not
age into correctness. It needs revisiting the moment the thing is real.

**2. A section switched off announced that it was switched off.**
Every morning, five lines of *"— not in briefing.sections"*. Information for an operator, noise
for a reader — the noise §26 exists to prevent, arriving by a different route.
*Fix:* a section the user turned off is absent. A section that *cannot work yet* still appears
with its reason, because those are different facts and the user must be able to tell which they
are reading.

**3. An empty section took three lines to say nothing.**
A heading, a summary saying "everything healthy", and a line saying "— nothing". On a quiet
morning the whole page read as though something were wrong with the brief.
*Fix:* an empty section is one line — its summary already carries the message.

**4. The decision nobody could understand.**
The brief led with `!! System Health Monitor`, which is the automation's name, not the decision.
The proposal's title comes from the task, and the task's title is the automation's name.
*Fix:* the item text carries the *kind* (`system.critical: …`), and **urgent items carry their
explanation at every length**. Detail is a luxury for a news headline and a necessity for
something the user is being asked to act on — a warning they cannot interpret is a warning they
learn to ignore.

**5. A re-rendered brief claimed to be two hours old.**
`aries brief show --length headlines` printed `18:54` for a brief produced at `20:54`:
`created_at` is UTC and I formatted it directly as local. **The same two-clocks mistake as the
notification cooldown in Entry 003**, in a different module, made by me again three entries later.
*Fix:* convert to local at the point of display.
*Lesson:* knowing about a class of bug does not prevent it. The durable fix is a convention —
database timestamps are UTC, anything shown to a human is converted at the edge — not vigilance.

## What was learned

* **Assembly reveals what collection could not.** Nothing here was hard to build; almost every
  bug came from putting existing parts side by side and reading the result as a user would.
* **The same bug recurs across modules.** The UTC/local slip and Entry 007's skipped-dependency
  trap both reappeared here. Both are now guarded by structure rather than by memory.
* **"Off" and "impossible" must look different.** It is the same honesty rule as null-versus-zero,
  applied to a page instead of a number.

## Rollback

```bash
rm -rf ~/aries/aries/brief ~/aries/tests/test_brief.py
# remove the brief routes, the `brief` import from aries/__init__.py and the CLI command
#   DROP TABLE aries_briefs;
```

## What should happen next

1. **Reversal detection** for the learning loop — still outstanding from Entry 008.
2. **The fast loop (§16)**: a correction like "shorter" or "not this topic" turning into a
   scoped, structured feedback event.
3. **A visual surface.** The CLI now covers sources, interests, learning, news, health,
   automations and the brief; that is enough to know what the screens should contain.

---

# Entry 010 — Changing its mind, and being told

**Date:** 2026-09-12

## Objective

Two halves of §16 that were missing. **Reversal detection**: let a learned preference be taken
back when the evidence contradicts it, without letting every settled preference be one quiet
fortnight from being undone. **The fast loop**: turn something the user says into something
ARIES does, in seconds, scoped correctly — or into a question.

## Problem being solved

The medium loop of Entry 008 could raise a weight or lower one. It could not handle the case
where the evidence turns against a conclusion it has already drawn, and that gap has a shape:

* if reversing is as easy as forming, preferences never settle, and the user experiences a
  system whose beliefs drift for no visible reason;
* if reversing is impossible, the first confident conclusion is permanent, and a genuine change
  of interest can never be reflected.

The fast loop's problem is different and harder. Everything ARIES has learned so far came from
counting. A person *saying* something is a different kind of evidence — more authoritative, far
scarcer, and ambiguous in a way statistics are not. "Shorter" is unarguable about *what* and
silent about *how far*.

## Concepts

**Hysteresis.** From control systems, where the same problem has the same shape: a thermostat
switching at exactly one temperature chatters. Continuing in an established direction uses the
ordinary thresholds; reversing requires more.

**Wilson intervals at two confidence levels.** The key realisation of this entry, arrived at by
getting it wrong first. Hysteresis expressed as a *moved threshold* is unreachable; expressed as
a *confidence level* it is exactly right — reversing evaluates the same bar with a wider
interval, so it needs more evidence to clear the identical line.

**Diagnoses before strength.** A falling engagement rate has five causes. Contextual collapse
and fatigue must be tested *first*, because neither looks contradictory in aggregate.

**Scope as a layer.** The fast loop needed no new storage. §30's precedence, built in Entry 002,
already had `INSTRUCTION`, `PROJECT` and `USER` — unused for eight entries, and exactly the
vocabulary a scoped correction needs.

## Decision

| module | responsibility |
|---|---|
| `learning/evidence.py` | evidence sliced by time (window, recent third, four buckets) and by source |
| `learning/reversal.py` | the five-way classifier, hysteresis, the pending state machine |
| `learning/history.py` | every applied change; oscillation damping and freezing |
| `learning/feedback.py` | classify an utterance, infer scope, apply or ask |
| `learning/explain.py` | why ARIES believes anything — settings and topics alike |

**Four rules the reversal path cannot break:** it writes only the learned layer; it reverses
only what ARIES itself concluded (see Errors 1); it acts on intervals; and it requires
`learning.reversal_confirmations` consecutive passes agreeing.

**Two rules the fast loop cannot break:** ordinary conversation is `not_feedback` and changes
nothing; ambiguous persistence or scope produces a **question**, never a guess.

An explicit statement carries `USER` authority because the user made it. The medium loop can
never reach that layer; a person speaking can. That asymmetry is §30 working as intended.

## Live traces

**Reversal.** ARIES had concluded, months ago, that blockchain mattered (0.85, "you opened 18 of
20 items in October"). Sixty items since, none opened:

```
$ aries learning reversals
  blockchain  believes 0.85
     SUSTAINED  confidence 53%
     evidence: 0/60 engaged, interval [0.0, 0.06]
     the whole window clears 10% even at the higher confidence reversing requires,
     and the recent slice agrees
     PENDING 1/2 confirmations

$ aries learning run          # the confirming pass
1 REVERSAL(s) applied: blockchain 0.85→0.70

$ aries learning history
  ↓ blockchain  0.85 → 0.70
     2026-09-12 19:10 · sustained · reversal-v1
     REVERSAL after 2 consecutive passes: you engaged with 0 of 60 …
```

**Fast loop.**

```
$ aries learning feedback --text "shorter"
  heard: correction   scope current_result · confidence 50%
  the correction is clear; how far it reaches is not
  ? Should I make briefs shorter just this once, or from now on?

$ aries learning feedback --text "always keep briefs shorter"
  heard: persistent_rule   scope global · confidence 90%
  applied briefing.length = "standard"  at the user layer

$ aries learning explain briefing.length
  now      "standard"
  because  from your feedback: "always keep briefs shorter"
  from     user setting (explicit)
  Also held
    instruction    "standard"  from your feedback: "shorter"
  You said
    "always keep briefs shorter"  persistent_rule
    "shorter"  correction
```

## Errors encountered

**1. Hysteresis was implemented in the wrong currency, and was unreachable.**
I tightened the threshold itself: `strict = ignored_threshold × (1 − hysteresis)`, giving 0.06
at a hysteresis of 0.4. Because a Wilson upper bound sits well above the point estimate at
realistic sample sizes, clearing 0.06 required **literally zero engagement across sixty
observations** — and the recent slice, being a third of the data, could never clear it at all.
Every reversal test failed, and would have kept failing in production silently: the feature
would have existed and never once fired.
*Fix:* hysteresis as a **confidence level**. Reversing evaluates the same threshold with a
wider interval (95% → ~99%). `0/60` reverses; `1/60` does not, though the ordinary path would
act on it. The asymmetry is real and reachable.
*Lesson:* an unreachable rule is indistinguishable from an absent one, and far more expensive,
because it looks like a feature. "Be more certain" belongs in the confidence level; moving the
threshold changes *what* you are asking, not *how sure* you must be.

**2. I protected the wrong thing with hysteresis.**
The established position was read from the *effective* weight — which is the **user's** if they
set one. So ARIES applied the stricter reversal rules to a preference it had never formed:
protecting a value that was never its to change, and refusing to learn anything at all about
topics the user had configured.
*Fix:* `established` is `learned_weight` and nothing else. A reversal is ARIES changing **its
own** mind; the user's value is immutable to learning anyway, so there is nothing there to
reverse. A separate `base` still uses the user's value as a prior for a first opinion.
*Lesson:* "what is believed" and "what applies" are different questions wherever layers exist.

**3. Two of the five diagnoses were unreachable.**
Contextual collapse and fatigue sat *after* the "is this contradictory at all?" test. Neither
ever got there: a topic read avidly from one source and ignored from another averages to
something unremarkable, and a decline from 90% to 25% is still far above the ignored line.
*Fix:* the diagnoses are asked first. They are explanations of the evidence, not weaker
contradictions.
*Lesson:* when a classifier has a fall-through, the order encodes a claim about which questions
are independent. Mine claimed contextual collapse was a kind of contradiction. It is a kind of
*explanation*.

**4. A pending reversal was only withdrawn on a contradicting verdict.**
When the user started engaging again the verdict became `noise`, which routed down the ordinary
path and never touched the state machine — leaving a stale pending reversal to be confirmed by
the next genuine dip. **Alternating evidence would have reversed after all**, which is the exact
failure the confirmations exist to prevent.
*Fix:* the state machine is told about every pass for an established target, not only the
contradicting ones.
*Lesson:* a state machine must handle every input, including the ones that mean "never mind".

**5. Two `FeedbackRequest` classes in one module.**
The sources route defined one; I added another for the fast loop. Because `routes.py` uses
`from __future__ import annotations`, FastAPI resolves body models lazily **by name**, so the
second definition silently rebound the *first* route's model. The sources feedback endpoint
began demanding a `text` field, and its test failed several hundred lines from the cause.
*Fix:* renamed, plus a check that no two body models in the module share a name.
*Lesson:* lazy annotation resolution turns a name collision into action at a distance.

**6. A fully passing suite exited non-zero.**
The daemon `http.server` thread in two test files was killed mid-request at interpreter
shutdown, raising `BrokenPipeError` on stderr after every assertion had passed.
*Fix:* shut the server down explicitly before exiting.
*Lesson:* a green suite that reports failure is worse than a red one — it trains you to ignore
the exit code.

## What was learned

* **Getting hysteresis wrong twice taught more than getting it right would have.** Once in the
  wrong currency (unreachable), once against the wrong subject (protecting the user's value).
  Both produced code that ran, passed import, and did nothing useful.
* **Ordering in a classifier is a claim about the world.** Putting strength before diagnosis
  asserted that a contextual collapse is a weak contradiction. It is not.
* **The fast loop needed no new concepts, only the ones already built.** Scope maps onto §30's
  layers; authority is the difference between a person stating a rule and a machine inferring
  one. Both were designed in Entry 002 for a component that did not exist for eight entries.
* **The recurring bugs are now indexed.** `ERROR_LOG.md` shows two mistakes that have happened
  twice in different subsystems. Conventions, not vigilance.

## Rollback

```bash
rm -f ~/aries/aries/learning/{reversal,evidence,feedback,explain,history}.py
rm -f ~/aries/tests/test_{reversal,feedback}.py
# revert loop.py to its Entry 008 form; remove the learning routes added here
#   DROP TABLE aries_reversals; DROP TABLE aries_feedback; DROP TABLE aries_learning_changes;
```

## What should happen next

Stopping here for approval, as asked, before any UI work. The CLI now covers sources,
interests, news, health, automations, the brief, both learning loops, reversals and
explanations — which is a complete enough picture of the surface for the Settings and Control
Centre screens to be designed against something real rather than guessed at.

---

# Entry 011 — The Control Centre: a window onto everything built so far

**Date:** 2026-09-12

## Objective

The first graphical interface to ARIES — one a non-technical person can use to understand,
configure and control the ten entries of machinery underneath, without a terminal and without
ever editing a file.

## Problem being solved

Not "ARIES needs a frontend". The requirement is sharper than that, and two of its rules decided
the architecture before any screen was drawn:

* the UI must **consume the existing services**, not become a second implementation;
* it must never touch the database — `UI → typed boundary → core`.

Those are easy to state and easy to erode. A UI that can import the core will, eventually,
reach past the API for one convenient query, and then the boundary is a convention that holds
until someone is in a hurry.

## Concepts

**Two interpreters, turned into the architecture.** GTK's Python bindings belong to the system
interpreter (3.14); ARIES runs in a `uv` virtual environment (3.12). Rather than build PyGObject
from source to unify them, the split becomes the boundary: the Control Centre runs on system
Python, imports nothing from `aries`, and reaches it only over HTTP. The rule is now
**structural rather than disciplinary** — a future contributor cannot reach past the API,
because `aries` is not on that interpreter's path. ADR-0004.

**Threads, not asyncio.** GTK has one main loop and every widget touch must happen on it.
Requests run on worker threads and results return through `GLib.idle_add`, the one supported way
to touch GTK from elsewhere. Callbacks therefore always run on the main loop and no page needs a
lock.

**Generation counters.** Home → News → Home starts three requests that can land in any order,
and a late reply from the first repaints the screen with older data. Every request carries a
generation; superseded replies are discarded before reaching a widget.

**The screen is generated from the schema.** Settings declares type, control, choices, bounds,
unit and whether a setting is advanced — so the Settings screen is built from the API response.
Adding a setting to ARIES makes it appear, correctly rendered, with no UI change.

**Three states, not two.** `Loading`, `Empty`, and `Absent`. "No failed services" and "the
health automation has never run" are different facts; rendering both as blankness is lying by
omission — the same rule that makes ARIES report `null` with a reason instead of `0`.

## Alternatives considered

Recorded in full in ADR-0004. In short: **Qt/PySide6** would have kept one process and one
interpreter, at the cost of 150 MB of bundled Qt, a foreign look on GNOME, and a step away from
the GTK4/libadwaita direction the specification itself names. **Electron or a local web UI** was
rejected on the requirement's own terms and on the merits — a browser engine to render a
settings window on a machine ARIES is simultaneously monitoring is a poor trade. **A TUI** is not
the desktop application that was asked for.

The decisive facts were measured, not assumed: GTK4 4.22 and libadwaita 1.9 are **already
installed**, a window presents natively on `GdkWaylandDisplay`, and the bindings belong to the
system interpreter.

## Decision

```
aries_ui/
  client.py     the whole boundary: urllib, threads, GLib.idle_add, staleness
  contract.py   what the UI reads, as data — pure, importable from both sides
  design.py     tokens + CSS: severity, provenance, density, quiet
  widgets.py    shared components; Loading / Empty / Absent / Error
  page.py       the contract every screen implements
  app.py        NavigationSplitView, actions, accelerators
  command.py    16 intents over real capabilities
  explain.py    "why does ARIES believe this?"
  pages/        home · brief · news · interests · learning · automations ·
                system · connections · settings
```

Two API additions, both aggregates over existing services with no logic of their own:
`/api/aries/home` (one round trip, one paint) and `/api/aries/connections`.

And one new module in ARIES proper: `aries/integrations/` — §23's registry, whose status is
**derived** from whether a connector exists rather than declared, so the Connections screen
cannot claim a capability the system lacks.

## Errors encountered

**1. The Learning screen rendered an error page, and nothing had failed.**
`/learning/evidence` returns evidence sliced by time and source since Entry 010; the UI read the
old flat `engaged`/`shown` keys. The page's error contract caught it and showed a failure state
rather than crashing — but nothing in any test noticed, because the two processes share no
imports and nothing connected their expectations.
*Fix:* `aries_ui/contract.py` declares every endpoint and key the UI reads, and
`tests/test_ui_contract.py` asserts ARIES provides them. The contract now breaks in the test
suite rather than in front of the user.
*Lesson:* a process boundary that improves safety also removes the compiler. What it takes away
must be replaced deliberately.

**2. "scan for news" showed the News screen instead of scanning.**
Intent patterns overlap, matching is first-wins, and navigation intents were declared before
actions — so "scan for news" matched *show news*, and "make my morning brief shorter" matched
*show brief*. Both silently did the more generic, less useful thing.
*Fix:* actions before navigation, and a test naming ten phrases and the intent each must reach.
*Lesson:* in a router with overlapping patterns, order encodes precedence. A verb is more
specific than a noun and must be tried first.

**3. "Not built yet" rendered with a green tick.**
`info` was mapped to the success colour, so a neutral state and a verified-good one were
indistinguishable — the interface asserting that an unimplemented integration was fine.
*Fix:* `info` is its own muted treatment.
*Lesson:* if two meanings share a colour, the colour means neither. This is the same error as
reporting `0` for "unknown", in a different medium.

**4. The page action sat where a title belongs.** "Scan now" was packed at the header's start,
left of the window title, reading as a heading. Moved beside Refresh.

**5. GNOME refuses screenshots to unprivileged callers.** `org.gnome.Shell.Screenshot` answers
`AccessDenied`, and no screenshot CLI is installed.
*Fix:* render the window's widget tree to a `Gdk.Texture` offscreen and save that — deterministic,
needs no compositor permission, and can capture a specific screen rather than whatever is on top.

**6. The venv test loop tried to run the UI suite** and failed on `import gi`. The UI tests run
as their own step with the system interpreter; the loop skips them by name.

## What was learned

* **A constraint can be an architecture.** The interpreter split looked like an obstacle and is
  the reason the UI provably cannot bypass the audit log.
* **Removing the compiler means adding a contract.** Two processes cannot catch each other's
  drift, so the expectation has to be written down and tested — and the bug that proved it
  happened before the test existed.
* **The design system's job is to stop two meanings sharing a signal.** Both visual bugs here
  were that: neutral wearing success-green, and an action wearing a title's position.

## Testing

996 assertions, all passing. 290 are new: 76 for the UI/core contract, 214 for the Control
Centre's own logic. Nothing existing was weakened or skipped.

## Rollback

```bash
rm -rf ~/aries/aries_ui ~/aries/scripts/aries-ui ~/aries/tests/test_ui_{client,contract}.py
rm -rf ~/aries/aries/integrations ~/aries/docs/screenshots
# remove the /home and /connections routes from aries/api/routes.py
```
No existing ARIES module was changed except the API, which gained two read-only aggregates.

## What should happen next

Stopping for approval, as asked. Not started, and deliberately: no compositor, no shell
replacement, no changes to boot or login, no slow-loop evolution.

---

# Entry 012 — ARIES stops being an application

**Date:** 2026-09-12

## Objective

Make ARIES a persistent user-level layer that starts with the login session and runs whether or
not anything is watching — and make the Control Centre what it was always meant to be: an
optional window onto something already running.

## Problem being solved

Ten entries of machinery were being launched by hand. That is an application. An automation that
only runs while a terminal is open is not an automation, and a morning brief that requires
someone to start ARIES first has failed at the only thing it is for.

## The question that decided the architecture

The requirement sketches up to six services — core, api, dispatcher, learning, integrations,
background — and adds the qualification that mattered: *do not create unnecessary processes if a
smaller architecture is cleaner.*

Looking at what is actually there: **the API process already hosts every background component.**
Six workers run in its asyncio loop, started by the FastAPI lifespan — scheduler, triggers,
housekeeping, learning, autopilot, and ARIES's own automations dispatcher.

Splitting those would not separate things that are together by accident. It would separate
things that are together by design, and two of the splits would be **wrong**, not merely
wasteful:

* the **overlap lock is per-process** — an `asyncio.Lock` per automation, recorded as a known
  limit since Entry 004 and repeated in `SECURITY.md`. Two processes would each believe they were
  alone, and the News Radar would double-fetch every source and double-count the engagement
  evidence the learning loop reads;
* **SQLite has one writer at a time** — multi-process needs PostgreSQL *and* a database lease to
  replace the in-process lock.

So: one service, under a target. The target is not ceremony — it is the central lifecycle handle,
and a second service attaches later with `WantedBy=aries.target` without changing how ARIES is
started, stopped or reasoned about. ADR-0005 records what would have to change first.

## Concepts

**User units need no root.** `~/.config/systemd/user` belongs to the login session. ARIES installs
itself with no `sudo`, starts at login, and stops at logout — because `Linger` is off, which is
exactly what was asked for.

**Status is derived, not declared.** Four states, each assembled from evidence: systemd's view of
the unit, whether the API answers, and what the API says about its own workers, automations,
breakers and database. `DEGRADED` is the one that earns its place — a process that is alive
while its dispatcher has crashed is not "running" in any sense the user cares about, and saying
otherwise is the same dishonesty as reporting `0` for "unknown".

**The status command cannot need the thing it reports on.** It is asked most urgently when ARIES
is broken. Layers are optional: systemd always answers, the API adds detail when it can, and its
absence is itself an answer.

**Nothing schedules from a timer.** Automations are paced by their last *recorded* run, so a
reboot resumes rather than resets — a machine asleep at 07:30 produces the brief when it wakes.
That property was built in Entry 004 for a different reason and is what makes restart-safety
free here.

## Errors encountered

**1. The target started and would have pulled in nothing.**
`systemctl --user enable aries.target` makes the *target* start at login, but `aries-core.service`
is `WantedBy=aries.target` — and until the **service** is also enabled, no symlink exists in
`aries.target.wants/`. Enabling only the target gives a clean-looking install that starts an
empty target.
*Fix:* the installer enables both, with the reasoning written where it is done.
*Lesson:* in systemd, `WantedBy` describes a link that `enable` creates. Declaring the
relationship is not establishing it.

**2. Positional parsing of `systemctl show --value`.**
Status printed `inactive/dead since 0 · last result 0`. I asked for eight properties and read
the eight returned lines in the order I asked — but systemd emits them in **its own** order.
Checked directly: position 5 was empty and position 6 was `success`, so the timestamp and the
result were reading each other's values.
*Fix:* parse `KEY=VALUE` instead of `--value`; order-independent.
*Lesson:* a tool free to reorder its output has not promised not to.

**3. The safe restart policy became a trap.**
A stale manually-started ARIES held port 8000, so the service crash-looped, hit its start limit
and stopped — correct behaviour, well logged. But `aries start` then also failed, because a unit
in `start-limit-hit` refuses until `systemctl reset-failed`. The protection worked and left the
user needing an obscure incantation to escape it.
*Fix:* `start` and `restart` clear a hit start limit first. Clearing the failure is exactly what
a person means by "start it".
*Lesson:* a safety mechanism that cannot be recovered from through the normal interface is only
half built.

**4. Two tests depended on the wall clock — and it was 22:06.**
`test_notify.py` and `test_news.py` began failing with every individual check passing. The cause
was not the runtime work at all: it had gone past 22:00, quiet hours had begun, and notifications
that the tests expected to be *delivered* were correctly being *held until morning*. They had
passed at 20:5x that same evening.
*Fix:* the repeat-gate test pins an explicit hour; the news pipeline tests disable quiet hours,
since they are about the pipeline and delivery has its own suite.
*Lesson:* **a test that depends on the time of day passes until it does not** — and it fails in
the evening, which is when nobody is looking. This is the third clock-shaped bug in this project
(`ERROR_LOG.md`), and the first where the *test* rather than the code was wrong.

## Verified

```
aries status   → RUNNING · 6 workers alive, 4 automations enabled
aries stop     → STOPPED
aries start    → RUNNING
kill -9 <pid>  → restarted automatically → RUNNING within seconds
```

## What was learned

* **The smaller architecture was the more correct one**, and for a reason already written down.
  The locking limit recorded in Entry 004 turned out to be the argument against splitting into
  six services — a note kept for honesty became the deciding evidence two milestones later.
* **systemd's guarantees only apply to what you actually asked for.** The `WantedBy` and
  `--value` bugs are both this: a declaration that looked like a promise and was not.
* **A protection needs an escape hatch through the ordinary path**, or it converts a temporary
  fault into a permanent one for anyone who does not know the incantation.

## Rollback

```bash
./scripts/aries-service uninstall        # stops, disables, removes the units
rm -rf ~/aries/aries/runtime ~/aries/systemd ~/aries/scripts/aries-service
rm -f  ~/aries/tests/test_runtime.py
# remove the /runtime routes from aries/api/routes.py and the status commands from cli.py
```
Data in `var/` is untouched by uninstalling.

## What should happen next

Stopping for approval. Not started, deliberately: no compositor, no shell replacement, no
changes to boot or login beyond a user unit, no slow-loop evolution.

---

# Entry 013 — Staying awake without lying to the machine

**Date:** 2026-09-12

## Objective

Let ARIES keep working while the screen is dark: user logged in, display powers off as normal,
Linux does not suspend, automations and the scheduler and the learning loop carry on, network up,
Control Centre not required to be open.

## Problem being solved

Entry 012 made ARIES start with the session. That solved *launching*. It did not solve
*continuing* — a desktop left alone eventually suspends, and everything in the asyncio loop stops
mid-flight until someone moves the mouse. A morning brief that needs a human to wake the machine
first has the same defect as one that needs a human to start ARIES first.

## The choice that defines this entry

There are three ways to stop a Linux machine sleeping, and the difference between them is the
whole entry.

**Fake a user.** `xdotool`, `ydotool`, a pointer nudged one pixel every few minutes. It is what
most "keep awake" scripts on the internet do. It is also the worst of the three by a distance: it
defeats the screen lock, defeats the screensaver, makes the session permanently non-idle so
nothing that depends on idleness ever works again, needs input-injection permission Wayland does
not hand out casually, and — the real objection — it **lies to every other program on the machine
about whether a human is present**. The brief ruled it out explicitly, and it deserved to be.

**Change the GNOME setting.** Set `sleep-inactive-ac-type` to `nothing`. Honest, simple, and it
leaves a global, persistent change to the user's desktop behind. If ARIES dies, the machine never
suspends again and nothing on screen says why.

**Ask logind.** Take an inhibitor lock, the mechanism the platform provides for exactly this
question, and let logind arbitrate between ARIES and everything else that has an opinion. Chosen —
and the reason it is *safe* to choose is a detail of how the lock is held.

## Concepts

**An inhibitor is a file descriptor, not a record.** This is the part worth learning. `Inhibit()`
returns an fd over D-Bus, and the lock exists exactly as long as that fd stays open. There is no
release call to forget, no lease to renew, no timeout to tune, and — crucially — **no way for the
lock to outlive the process holding it**, because the kernel closes the fds of dead processes
however they die. Crash, OOM kill, `SIGKILL`, power cut: released by the same mechanism every time.

That single property is what makes a background program safe to trust with a lock on the whole
machine's power behaviour. Compare it with the GNOME-setting approach, where the cleanup is a
promise the program makes and a crash breaks.

ARIES holds its lock by running

```
systemd-inhibit --what=sleep --who=ARIES --mode=block --why=… /bin/sh -c 'read -r _ <&0'
```

with a pipe on stdin. The shell blocks forever on an empty read; closing the pipe ends it. I
verified all three paths before writing any of the feature: the lock appeared in
`systemd-inhibit --list`, disappeared when the pipe closed, and disappeared when the holder was
`kill -9`ed.

**`sleep`, never `idle`.** The two look interchangeable in the documentation and are opposites
here. An `idle` inhibitor says "a user is present", which stops the screen blanking — the exact
thing the brief wanted to keep. `sleep` holds back suspend and hibernate only. The Control Centre
asserts on screen that ARIES holds no `idle` lock, so if that ever changes, the person whose screen
stopped blanking can find out who did it.

**`block`, never `delay`.** `delay` buys a few seconds and then the suspend happens anyway; it is
for programs that need to save state first. `block` makes a non-interactive suspend fail. An
interactive `systemctl suspend` still works — the user is never shut out of their own machine.

**Reconcile, don't toggle.** Background Mode is a *setting*; the inhibitor is a *live process*.
Anything that tries to keep two such things in step by acting on transitions eventually drifts.
One idempotent `reconcile()` compares them and fixes the difference, called from three places for
three reasons: at startup (a reboot means no lock is held, whatever the setting says), on the
toggle (so the switch feels like a switch), and on every dispatcher tick (because the holder can
die without asking). Because it is idempotent, all three cost nothing.

The tick call sits **before** the automations-enabled check, deliberately. Background Mode must
hold its lock whether or not the dispatcher is switched on — and that is also where a lost lock is
noticed and retaken.

**Measured, not remembered.** "Is suspend inhibited?" is never answered from an ARIES flag.
`held()` checks the actual child process, and the status panel additionally reads
`systemd-inhibit --list`, because the honest answer is the one **logind** would act on.

**One thing is borrowed.** "Display off after" has no scoped equivalent — it is the global
`org.gnome.desktop.session idle-delay`. So it is treated as a loan: the existing value is recorded
in the database *before* anything is written, and written back exactly on switch-off. In the
database rather than in memory, so a crash does not lose it. It is the only GNOME key ARIES
touches, and setting the field to the value the desktop already has means nothing is written at
all.

**`user_only`.** Background Mode, "allow normal suspend" and "allow heavy GPU jobs" can never be
set by the learning loop (§30). Keeping a machine awake spends the user's electricity and their
battery. That is not a preference to infer from behaviour.

**A declared permission for an undelivered capability.** "Allow heavy GPU jobs while the display is
off" exists as a setting and nothing consumes it, because ARIES runs no GPU workload. The status
panel says so in those words — *declared, not implemented*. The alternative was to leave it out and
add it later, which would mean the capability arriving before the permission to use it.

## Errors encountered

**1. A timeout of "never" read as 320 seconds.**
`read_idle_delay()` stripped non-digits from the output of `gsettings get`, which prints the type
alongside the value: `uint32 0`. Stripping the non-digits leaves the `32` from the *type name*
followed by the value — `320`. So a display timeout of 0, meaning *never blank*, was recorded as
320 seconds, and that is the number that would have been written back on restore.
*Fix:* take the last whitespace-separated token, which is the value.
*Lesson:* a parser that throws away what it does not understand will quietly eat part of the
answer. Take the field; do not keep the leftovers.

**2. A test fixture that was a second opinion about the shape — and wrong.**
The UI panel test passed `"session": "session 1 · active"`, a string. The API returns an object.
The test passed while the real screen would have raised a `TypeError` on the first draw, because
GTK escapes subtitles and a dict is not text. This is the Entry 011 contract lesson arriving from
the other direction: there, the endpoint changed and the UI read stale keys; here, the *test's own
fixture* disagreed with the endpoint and vouched for the wrong thing.
*Fix:* the fixture now carries the shape the API actually returns, and the panel formats the
session rather than printing it.
*Lesson:* a hand-written fixture is an independent claim about the shape. When it is wrong, the
test using it cannot notice.

**3. An ampersand made a section title disappear.**
"Power & Background" rendered as an *untitled* group. `Adw.PreferencesGroup` parses its title as
Pango markup, the bare `&` starts an entity that never ends, and Pango rejects the whole string —
so the group drew with no heading at all and the reason went to stderr as a warning nobody reads.
`widgets.row()` has escaped its title since the first screen; `widgets.section()` never did, and
for eleven entries no section title happened to contain a character that mattered.
*Fix:* escape in `section()` too, with a test that a title containing `&` survives.
*Lesson:* escape at **every** door into a markup parser, not at most of them. And note the failure
mode: not a crash, not a wrong value — *nothing*, which is the hardest kind to notice.

**4. The assertion was edited to match a message I had already written honestly.**
`test_power.py` asserted the GPU note said "no GPU workload"; the note says "declared, not
implemented". I fixed the test rather than the message — worth recording only because the opposite
temptation is the usual one, and the note is the part a user reads.

## Verified

Real elapsed time, on this machine, with the service running under systemd:

```
$ ./scripts/test-background-mode.sh 16

=== Background Mode, 16 minute run ===

PASS  ARIES is running before the test begins   6 workers alive, 4 automation(s) enabled
      power supplies: none — this machine has no battery, so the AC policy is the
      only one that ever applies
      display timeout before: 0s · AC policy: nothing / 3600s · battery: suspend / 900s
      borrowed settings: health.interval_minutes=15, health.enabled=True,
                         automations.worker_enabled=False
PASS  Background Mode is on
PASS  ARIES holds a suspend inhibitor
PASS  and logind lists it as sleep/block   {'who': 'ARIES', 'pid': '57070',
                                            'what': 'sleep', 'mode': 'block'}
PASS  the display is allowed to power off   idle-delay now 60s
PASS  and the previous value was recorded for restoring   will restore to 0s
PASS  ARIES does NOT hold an idle inhibitor, which would stop blanking

      waiting 16 minutes…
      15.0 min left · inhibitor held · display off
      …
      -0.0 min left · inhibitor held · display off

PASS  the machine did not suspend (wall clock and monotonic agree)  drift 0.0s over 963s
PASS  and the journal records no sleep
PASS  the inhibitor was still held at the end
PASS  ARIES is still running   6 workers alive, 4 automation(s) enabled
PASS  an automation ran while the display was off   16 new health run(s)
      last run: ok · healthy — 17 checks, nothing above threshold
PASS  Background Mode is off
PASS  the inhibitor is released
PASS  and logind no longer lists one for ARIES
PASS  the display timeout is restored exactly   back to 0s
PASS  with nothing left to restore
PASS  and the machine is left exactly as it was found

ALL PASSED
```

And, while it ran, from outside the test:

```
$ systemd-inhibit --list --no-legend | grep ARIES
ARIES  1000  stamenovmartin  57070  systemd-inhibit  sleep
       ARIES Background Mode is on — automations keep running while the display is off  block

$ curl -s localhost:8000/api/aries/power | jq '{background_mode, display}'
{ "background_mode": true,
  "display": { "state": "off", "detail": "the screen is blanked",
               "off_after_seconds": 60, "will_restore_to": 0 } }
```

The screen was genuinely blanked, the lock was genuinely held, and logind — not ARIES — is the one
saying so.

## What this test cannot prove, and why it says so

This machine has `sleep-inactive-ac-type=nothing` and no battery at all: it was never going to
suspend. Waiting sixteen minutes and finding it awake therefore demonstrates **nothing** about the
inhibitor, and a test that claimed otherwise would be passing for the wrong reason — the most
expensive kind of green.

So the test asserts the mechanism instead of the outcome: that the `sleep`/`block` lock is held and
**logind lists it**, that the display really blanked, that automations really ran across the
interval, that wall-clock and monotonic time did not diverge (they would across a suspend) and the
journal records no sleep, and that every borrowed value came back. The suspend is deliberately
never triggered — suspending the user's machine to prove a point is not an acceptable test, and
`aries power status` says the same thing to the user's face rather than taking credit it has not
earned:

```
this machine is already set never to suspend on mains power, so the inhibitor
changes nothing while it is plugged in — it matters on battery
```

## What was learned

* **The safest design is often the one where the safety is a property of the mechanism rather than
  a promise of the code.** Nothing in ARIES cleans up the inhibitor on a crash, and nothing needs
  to, because the kernel does it. Every alternative would have needed a cleanup path — and a
  cleanup path is exactly what a crash skips.
* **Two names that sound alike can be opposites.** `idle` and `sleep` differ by the entire point of
  the feature.
* **Reporting what you did is not reporting what is true.** The panel reads logind rather than its
  own memory, and the difference only ever shows up on the day something has gone wrong — which is
  the only day anyone looks.
* **An honest negative result is a result.** The most useful sentence in this entry is the one
  saying the inhibitor changes nothing on this particular machine.

## Part two — what the machine may *do* while it is awake

Approved, with an addition that turned out to be the more interesting half: Background Mode must
distinguish lightweight from heavy work.

The addition is right, and the reason is worth stating. Keeping a machine awake is a promise about
*availability*, and on its own it is one-sided — an always-awake machine that will start anything
at any hour is a denial of service against its own owner. The inhibitor removes the thing that
used to stop runaway background work by accident: sleep. Something has to put a deliberate limit
where the accidental one was.

### Cost is declared, not inferred

ARIES could watch what an automation did last time and decide it is heavy. That is worse in three
ways at once: the first run is the one that would hurt, the inference is wrong for work whose cost
depends on its input, and the rule becomes unreadable. So it is a field in the genome —
`workload`, one of `light` · `inference_light` · `heavy_cpu` · `heavy_gpu` — versioned and
diffable with everything else, checkable before anything runs.

The temptation was to reuse `risk`, which already exists. They are different axes and it took
about a minute to see it: **risk is what happens if this goes wrong; workload is what it does to
the processor and the thermometer while it goes right.** The Morning Brief is low risk and
lightweight. A nightly local-model re-index would be low risk and very heavy indeed. One field
cannot say both, and a field that tried would have made "is this a big deal?" a question with two
incompatible answers.

`light` is the default, so adding the field reclassified nothing — every existing automation kept
exactly the behaviour it had.

### Two gates, and why they must not be one number

* **permission** — may this *class* run unattended at all? Static, from settings, default-closed
  for heavy work, nothing measured.
* **condition** — is the machine in a state to take it *now*? Live, from `/proc/stat`, the thermal
  zones and `nvidia-smi`.

It would have been less code to compute one "can it run" boolean. It would also have been worse to
use: *"heavy GPU work is not enabled while the display is off"* is fixed by a toggle and *"the
machine is at 84 °C"* is fixed by waiting, and a user told only "no" has to guess which. Refusals
are a user interface.

A person pressing **Run now** carries the permission gate — someone explicitly asking *is* the
explicit enabling the requirement asked for — but not the thermal one.

### The decision that looks like an oversight

**Lightweight work is never deferred, at any temperature.** Written down as a decision precisely
because it reads like a gap: surely at 95 °C everything should stop?

No — because the health check is *how ARIES finds out the machine is hot*. A policy that deferred
its own thermometer to save heat would be measuring nothing and protecting nothing, and would go
blind exactly when it mattered. News fetching and memory maintenance are the same shape: I/O-bound,
idle most of their duration, and cheaper than the measurement deciding about them would be.

### Hysteresis, in its second home

Temperature is a *condition*: it persists, and the thing that caused it is the thing that would
restart. So crossing the limit takes a **hold**, and releasing it needs the temperature back below
the limit *minus a margin*, and staying there for a number of consecutive checks.

This is Entry 010's lesson arriving in a completely different subsystem. There, hysteresis
implemented by moving a threshold produced a rule demanding literally zero engagement across sixty
observations — unreachable, and therefore the same as absent. Here the margin is measured downward
from a limit the user chose, so it is reachable by construction, and there is a test that asserts
the arithmetic: the coolest limit the settings allow minus the widest margin they allow is still a
temperature a machine reaches.

Utilisation gets no hold and no margin, and that asymmetry is the point. Utilisation is a *moment*.
It is re-asked next tick, and nothing about waiting makes the reading oscillate.

The hold lives as a row in an append-only table, and "is there a hold right now?" is read back from
that record rather than kept beside it — a state stored next to its own history is a state that can
disagree with it.

### "Never silently kill" decides the whole shape of stopping

The requirement says never silently kill critical stateful work. Taken seriously, that is not a
clause about one edge case — it settles what "stop" *is*.

So stopping is a flag a cooperating job reads between units of work. Nothing cancels a task,
nothing signals a process: a job killed at an arbitrary line is the definition of silently. Work
declaring `stateful=True` is not even asked — it is left to finish, recorded as over budget, and
its *next* run waits.

A job that ignores the flag keeps running, and that is accepted rather than solved. The record is
what a person acts on, and a supervisor empowered to kill work mid-write is a larger hazard than a
long job.

### Where it fails open, on purpose

An unreadable sensor is never a zero — it is `null` with a reason, as everything in ARIES is. But
the *gate* allows heavy work when temperature cannot be read, with the caveat recorded in the
verdict. Blocking heavy work forever on a machine with no thermal sensor would be the unreachable
rule a third time, and heavy work is already opt-in: the user asked for it explicitly. This is the
one place the policy fails open, so it is written down in ADR-0007 as a decision rather than left
to be discovered as an accident.

### What was rejected

**cgroups** (`systemd-run --slice`, `CPUQuota=`, `MemoryMax=`) genuinely enforce where this policy
only advises, and they are the right answer eventually. They constrain work ARIES spawns as
*processes*, and every automation today runs in-process in the asyncio loop — so adopting them now
would have enforced nothing while looking like it enforced everything. They belong with the first
automation that shells out to a long job, and they compose with this rather than replacing it: the
policy decides whether to start, cgroups bound what happens after.

**`nice`/`ionice`** sound gentler than refusing and solve nothing here: a de-prioritised GPU job
heats the machine exactly as much, and `nice` does nothing at all on an otherwise idle machine —
which is precisely the unattended case.

### Errors in part two

**5. The gate was never reached, because the test automation was never enabled.**
The first run of the runner test said `disabled`, not `resource_policy:not_enabled`, and recorded
no run at all. The synthetic spec had `enabled_setting=None`, so §11's switch refused it before the
resource policy was ever asked.
*Fix:* the test enables the automation, so the run reaches the gate under test.
*Lesson:* the four questions before a run — enabled, resource policy, breaker, overlap — are in a
deliberate order, and a test that does not satisfy the earlier ones is not testing the later one.
It failed loudly, which is the only reason it cost a minute rather than a milestone.

**6. `Reading.name` does not exist; the field is `metric`.**
Three list comprehensions, one wrong attribute, an `AttributeError` on the first live call.
Trivial, and recorded for what it says about reuse: the governor deliberately reads temperature
and GPU *through the health probes* rather than opening the sensors a second way, because two
readers of one sensor drift and a machine that is 51 °C on the health screen and 62 °C in the
power policy is a machine nobody can reason about. The cost of that reuse is exactly this — having
to know someone else's field names — and it is a good trade.

**7. A note that was honest in the morning was a lie by the evening.**
`gpu_jobs_note` said the GPU switch was "declared, not implemented". True when written; false the
moment the switch became the live gate for `heavy_gpu`. A stale honesty note is worse than none,
because it is believed.
*Fix:* the note now separates the two claims that were being blurred — *the gate is live* and *no
automation declares heavy GPU work yet* — and a test asserts both halves.
*Lesson:* a note explaining that something is not finished has to be revisited by the change that
finishes it. Being scrupulous once is not a property that lasts.

## Verified — part two

The thermal gate, against the machine's own sensors, by moving the limit under the live reading
rather than by heating the machine:

```
$ curl -s -X PUT localhost:8000/api/aries/power -d '{"temperature_limit_celsius":45}'
temp now 52.0 limit 45
  light             allowed   always runs, including while the display is off
  inference_light   allowed   always runs, including while the display is off
  heavy_cpu         deferred  pch_cannonlake is at 52.0 °C, at or above the 45 °C limit
  heavy_gpu         deferred  pch_cannonlake is at 52.0 °C, at or above the 45 °C limit
```

Light work stayed allowed while the machine was over its limit, which is the rule that looks like
a bug and is not. Limit restored to 80 °C afterwards.

```
$ aries power status
Resource policy

  CPU                6.8%   limit 70 %
  GPU                4%     limit 70 %
  Temperature        50 °C  limit 80 °C · pch_cannonlake
  Heavy job budget   20 min
```

145 assertions in `test_power.py`, 1281 across the suite, all green.

## Rollback

```bash
aries power off                  # releases the lock, restores the display timeout
rm -rf ~/aries/aries/power ~/aries/tests/test_power.py \
       ~/aries/tests/integration ~/aries/scripts/test-background-mode.sh
# remove the /power routes from aries/api/routes.py, cmd_power from cli.py,
# the reconcile and resource-policy calls from aries/automations/worker.py, the
# governor call from aries/automations/runner.py, the workload/stateful fields
# from aries/automations/genome.py, and power_status/resource_status from
# aries_ui/pages/settings.py
```

The `aries_resource_events` table can be dropped; it is history, and nothing else reads it.

Nothing here needed `sudo`, created a system file, or wrote outside `~/aries` except the one GNOME
key it borrows and returns.

## What should happen next

**The Background Runtime & Power milestone is complete.** ARIES starts with the session, survives
without a window, keeps the machine awake on request, lets the screen go dark, and now has a
defensible answer to what it may do in the dark.

Next is the part that makes ARIES *intelligent* rather than merely automated, in the order the
user set: **Integrations → Orchestrator → Dynamic agents → Context/Memory → Verifier → Model
router → Slow evolution.** The shell and the compositor are not the brain and come after all of
it.

Two things this entry leaves pointed at that work. The resource policy has no heavy work to
govern yet — a repository analyser or a local-model summariser will be the first to declare
`heavy_cpu` or `heavy_gpu`, and cgroups become worth adopting the moment one of them runs as a
process rather than in the loop. And the four questions a run must answer — enabled, affordable,
not broken, not already running — are the shape a goal-based orchestrator will need too, asked of
a plan rather than of one automation.

---

# Entry 014 — The desktop stops being Ubuntu with an AI application on it

**Date:** 2026-09-13

## Objective

An ARIES desktop shell on the session that already exists: top bar, dock,
universal command bar, launcher, notifications, quick settings, a design
language, backgrounds, identity. Without replacing GNOME, without a compositor,
without touching boot or login, and with an easy way back to plain Ubuntu.

## The measurement that decided the architecture

Before writing anything, the obvious plan was a GTK4 window — same toolkit as the
Control Centre, same language, same process model. It took one command to find
out that plan was impossible:

**Mutter does not implement `wlr-layer-shell`.** That protocol is how a Wayland
client anchors itself to a screen edge, reserves space, and sits above ordinary
windows — every single thing a panel or a dock has to do. Without it a "top bar"
is an ordinary window the user can drag, and lose behind Firefox.

So the options collapsed to one. Not a preference: a GNOME Shell extension is the
only place a panel can exist on a GNOME Wayland session, and the alternatives —
a wlroots compositor, an X11 session — were both excluded by the brief for good
reasons. ADR-0008 records what was measured (GNOME 50.1, wayland, no
gtk4-layer-shell) rather than what was assumed.

That this was checked *first* is the entire reason the milestone did not end with
a half-built GTK panel and a discovery.

## The consequence, which is not a detail

An extension runs inside `gnome-shell` — the process drawing the user's desktop —
and on Wayland **a shell that throws during startup cannot be restarted without
logging out.** There is no Alt+F2 `r` any more.

That single fact wrote most of the code:

* every entry point goes through `guard()`; a component that throws is logged,
  left out, and the rest of the shell runs. A broken ARIES must degrade ARIES,
  never the session;
* there is no synchronous HTTP path anywhere in the extension — not even a
  "quick" one, because a quick one is what gets reused later for a slow question,
  and the slow questions here are answered by running an automation;
* the dock does not reserve struts. A crash holding struts leaves every window's
  work area wrong until logout; an overlay a maximised window sits under is
  merely inconvenient. Recoverable beats tidy;
* `disable()` unwinds in reverse and tolerates parts that were never built.

## Testing without gambling the desktop

The obvious way to test an extension is to enable it and look. That is a test
whose failure mode is losing the user's session, which is not an acceptable
development loop.

GNOME Shell 50 can run **headless against a virtual monitor on its own D-Bus
session**. That is a complete, isolated GNOME — real Mutter, real St, real
extension loading — startable, drivable and killable without touching the session
the user is sitting in. `./scripts/test-shell.sh` was the second thing built,
before any component.

It earned that place immediately. Every bug in this milestone was found there,
by a machine, before a person saw one:

1. `affectsInputRegion` is no longer a parameter `addChrome` accepts in GNOME 50.
   It threw, and the command bar and launcher were silently left out.
2. `St.ScrollView` was given a bare `St.Widget` holding a `GridLayout`, which is
   not an `StScrollable`. The launcher never drew.
3. `AppSystem.get_installed()` returns `Gio.DesktopAppInfo`, **not** `Shell.App`.
   They share `get_name` and `get_id` and nothing else, so the tiles asked a
   GAppInfo for `create_icon_texture`.
4. Chrome actors are parented to `uiGroup`, which does not lay its children out —
   an actor must set its own position **and its own size**. Setting only the
   position left the containers allocated at zero height, and every row drew on
   top of the one before it.
5. `trackFullscreen: true` makes the LayoutManager set `visible` itself
   (`actor.visible = !inFullscreen`), overriding the `visible: false` the overlays
   were constructed with. The launcher sat on the desktop from the moment the
   shell started. Opting into a helper means opting out of controlling what it
   helps with.

Four of those five are the same shape: **an API that looked like the one I
remembered.** GNOME's extension API is not stable across major versions, and the
antidote was not care — it was extracting the actual shell JavaScript from
`libshell-18.so` and reading the version on this machine.

## The mid-milestone correction, and what it changed

Part-way through, a directive arrived that was more important than the feature:
*ARIES is the product; Linux is the foundation.* Never "Linux feature + ARIES
add-on", always "ARIES capability implemented using Linux". Every capability
needs five surfaces — core, orchestrator, automation, UI, audit — and the shell
is not a final decorative phase.

It changed code that was already written. The quick settings panel had been an
ARIES tile *beside* GNOME's Wi-Fi, audio and battery tiles, which is exactly the
"Linux feature plus add-on" the rule forbids: the user would have to know that
volume is GNOME's and autonomy is ARIES's. It became **ARIES Quick Settings** —
one panel, one language, covering Wi-Fi, audio, Bluetooth, brightness, Background
Mode, privacy and autonomy.

What the rule does *not* license is the more interesting half, and it is written
into `PRODUCT_IDENTITY.md` so it does not get lost: ARIES owns the **surface**,
not the **mechanism**. NetworkManager still does the networking, Gvc still does
the mixing, logind still arbitrates sleep. Rewriting a driver because "ARIES
should own it" would produce a worse system and contradicts §3. The test is
whether the *user* has to know, not who wrote the code underneath.

And where ARIES cannot own something honestly, it hands off visibly. Joining a
Wi-Fi network opens the system picker, because WPA-Enterprise, captive portals
and secret agents are a large surface and ARIES failing at them would be worse
than ARIES not claiming them.

## One router, two front ends

The command bar existed already — in `aries_ui/command.py`, bound to GTK widgets.
The shell needed the same thing in JavaScript in another process, and the obvious
move was to write the patterns again in JS.

That is precisely what the brief forbids, so the router **moved** into
`aries/shell/intents.py` behind `POST /api/aries/command`, and both surfaces call
it. The trick that makes one router serve two very different clients is that it
returns **actions rather than closures**: `{"kind": "navigate", "section": "news"}`
is data. The Control Centre switches page; the shell launches the Control Centre
on that page. The core decides what the user meant; each surface knows only how to
carry it out in its own medium.

The split of *who knows what* fell out of the same principle:

* **the shell contributes applications and windows**, because `Shell.AppSystem`
  already indexes every `.desktop` file and asking ARIES to keep a second index
  would be duplication pointing the other way;
* **files go through ARIES**, because `privacy.excluded_paths` is ARIES policy
  and a shell that walked the filesystem itself would be a second implementation
  of a privacy rule — one nobody would remember to update.

## Typing must never wait for a network

Applications are computed locally and drawn on the keystroke; the ARIES request
is debounced 90 ms and merges in when it lands, with a generation counter so a
late reply for an older query is dropped rather than repainting the list.

The consequence worth having: with ARIES stopped, `Super+Space` still opens, still
launches applications, and says the rest is unavailable. The desktop does not
depend on the thing it is a window onto.

## One design language, two toolkits

The Control Centre is GTK4/libadwaita; the shell is St inside `gnome-shell`. They
share nothing — different languages, processes and renderers — and the only thing
worse than two design systems is two that were supposed to be one.

So the tokens live in `aries/shell/tokens.py` and **both** stylesheets are
generated: theme-relative for GTK (`@accent_color`, so the Control Centre follows
the user's own accent and light/dark), fully resolved literals for St (which has
no variables, no `alpha()`, no `calc()`). A test asserts the file on disk is
exactly what the tokens produce, so a colour changed in one place cannot drift in
the other.

The constraint produced one genuine design rule. The first launcher capture had
the wallpaper showing through the gaps between application names — legible-ish,
and clearly wrong. The rule now written into the tokens: a panel may borrow colour
from what is behind it, but **a surface carrying text may not**.

## Errors worth the entry, beyond the five above

**6. Two test checkers that read their own documentation as violations.**
The scan for forbidden CSS matched the header comment listing which constructs St
cannot parse. The scan for synchronous calls matched the paragraph in `api.js`
explaining that `send_and_read()` would freeze the desktop. Both "failed" against
prose that exists to prevent the thing being scanned for.
*Fix:* strip comments before scanning.
*Lesson:* a checker that flags its own explanation is not checking anything — and
the tempting fix is to delete the explanation, which makes the codebase worse in
exactly the way the checker was meant to prevent.

**7. `make my morning brief shorter` rebuilt the briefing.**
A new `brief_now` intent (`make|build|generate|run … brief`) was declared before
the `shorter` correction, so a sentence asking for the brief to *change* triggered
the brief to be *rebuilt*. This is Entry 011's precedence bug exactly, in a table
that carries a comment warning about it.
*Fix:* corrections come before construction.
*Lesson:* a warning comment does not prevent the bug it warns about. The test that
enumerates phrase → action is what caught it, and it caught it in seconds.

**8. An exclusion test that would have passed with the exclusion removed.**
The file-search privacy test put its probe inside `~/.ssh`. The walk skips hidden
entries anyway, so the probe was never going to be found — the test proved nothing
about `privacy.excluded_paths`. It now uses a *visible* directory, and asserts
both that the file is refused and that it *would* have been found without the
exclusion.
*Lesson:* Entry 004's rule again in a new costume — a test that arranges the
outcome by accident is not testing the mechanism. The proof that an exclusion
works has to include the control case.

## Verified

```
$ ./scripts/test-shell.sh 30
PASS  the extension loaded and reached ENABLED
PASS  no ARIES component reported a build failure
PASS  no JavaScript exception mentions the extension
PASS  disable() ran and tore everything down cleanly — the fallback works
      GNOME also confirms it is INACTIVE
PASS  the extension's own log shows it starting

$ gdbus call --session --dest org.aries.Shell --object-path /org/aries/Shell \
    --method org.aries.Shell.Ping
('ARIES Shell 1 · 0 component failure(s)',)
```

Screenshots in `docs/screenshots/shell-*.png` are captures of the real shell
running in the nested session, driven over its own D-Bus interface — not mockups.
1387 assertions across the suite, all green.

## What was learned

* **Check the platform before designing for it.** One command about
  `wlr-layer-shell` turned a week's plan into a different architecture, at a cost
  of two minutes.
* **A test environment that cannot hurt the user changes what you are willing to
  try.** The nested GNOME made five crashes into five log lines.
* **A principle that arrives mid-build is worth applying backwards.** The quick
  settings panel was already written and already worked; rewriting it to own the
  surface cost an hour and is the difference between the goal and a near miss.
* **"Do not duplicate business logic" has a direction.** The core owns what ARIES
  knows; the shell contributes only what only the shell knows. Stated that way,
  every borderline case answered itself.

## Rollback

```bash
./scripts/aries-shell disable      # immediate, works from a TTY
./scripts/aries-shell uninstall    # extension, application entry, icon, wallpaper
rm -rf ~/aries/shell ~/aries/aries/shell ~/aries/tests/test_shell.py \
       ~/aries/scripts/{aries-shell,test-shell.sh} ~/aries/share
# remove the /shell and /command routes from aries/api/routes.py and the
# --section option from aries_ui/app.py
```

Nothing was installed system-wide, nothing needed `sudo`, and no part of GNOME,
the bootloader, the display manager or the login session was modified. Disabling
returns a plain Ubuntu GNOME session immediately.

## Part two — finishing the surfaces, and testing the parts that can be tested

Three things were outstanding against the brief: the workspace overview, the
wallpaper setting that nothing consumed, and test coverage for the failure states
the brief names by name — timeout, unavailable, malformed, cancelled.

### The overview: integration, not ownership

The instinct was to build an ARIES overview. GNOME's is already a mission-control
view — live thumbnails, a workspace strip, drag-between-workspaces, touchpad
gestures, and the accessibility that goes with all of it. Replacing that would
produce something worse and call it coherence.

What it was missing was ARIES. `Main.overview.searchController.addProvider()` is
a **public** API in GNOME 50, so ARIES registers as a search provider and typing
in the overview reaches automations, settings and every capability the router
knows. It calls `POST /api/aries/command` — the same endpoint as ARIES Search and
the Control Centre's palette. **One router, three front ends.**

The alternative was an "Ask ARIES" button pinned to the corner of someone else's
overview, which is exactly the "GNOME feature with an ARIES add-on" shape the
product identity principle rules out. A provider is the opposite: the user types
one thing, in one place, and ARIES answers among the rest.

Two details that matter more than they look. The provider asks for commands,
automations and settings but **not** applications or files, because GNOME already
provides both and asking again would show every result twice. And it honours the
cancellable — GNOME cancels a search on the next keystroke, and a provider that
keeps working afterwards is why overview search feels heavy on some systems.

### The wallpaper, borrowed rather than taken

`shell.wallpaper` had been declared and consumed by nothing — and worse, it
defaulted to `aries-dark`, so implementing it faithfully would have replaced the
user's wallpaper the moment the shell was switched on.

The default is now `system`, which changes nothing. When an ARIES background *is*
chosen, Entry 013's discipline applies: record what was there **before** writing,
in ARIES's settings service rather than in the extension's memory, so a crash
does not lose it and `system` puts back exactly what was there rather than a
guess at a default.

And `destroy()` deliberately does nothing. Disabling the extension does not
revert the background, because a teardown with an opinion about what the user's
desktop should look like is worse than one that leaves it alone.

### Testing the half of a shell that can be tested

`lib/api.js` imports Gio, GLib, Soup and its own logger — and nothing from
`gnome-shell`. That is not an accident of style; it means the HTTP layer loads in
plain `gjs`, outside a compositor, against a server that misbehaves on demand.
Which is the only way to produce the states the brief lists: a server that never
answers, a refused connection, a 200 carrying HTML, a truncated body, a reply
arriving after the widget that asked for it is gone.

28 assertions later, two bugs — **both in production code, neither in the test**:

**9. Two sources of truth for one address.**
`request()` built its URL from a module constant while the class also exposed
`get base()`. Overriding the address changed what the getter said and not where
the requests went, so a suite carefully pointed at a fake server silently tested
the real ARIES on :8000 — and "passed" the cases that happen to look the same.
*Fix:* one `_base`, set in the constructor, honouring `ARIES_API` exactly as the
Control Centre's client does.
*Lesson:* a getter that does not govern what it appears to govern is worse than
no getter, because it invites exactly this. And note how it surfaced: not as a
failing assertion about addresses, but as six unrelated tests failing with
"Not Found".

**10. A parse failure masking the status that mattered.**
A 500 whose body was `text/plain` came back as *"unreadable reply: JSON.parse:
unexpected character"*. Technically true and completely misleading: the news was
the 500, and the message sent the reader to look at the parser.
*Fix:* when the status is an error, the status is the reason — ARIES's own
`detail` when there is one, `ARIES answered 500` when there is not. The parse
result is only consulted for a reply that succeeded.
*Lesson:* when something fails for two reasons at once, report the one the reader
can act on.

**11. A fixture that serialised what it was meant to test.**
Three tests reported timeouts and looked like they were exercising the timeout
path. They were exercising `http.server.HTTPServer`, which handles one request at
a time, so everything queued behind `/slow`'s thirty-second sleep.
*Fix:* `ThreadingHTTPServer`.
*Lesson:* a fixture that cannot do two things at once cannot test what happens
when two things happen at once — and it fails in a way that looks like a pass of
the thing you wanted.

### "It loaded" was not a test

The nested-shell harness said `PASS the extension loaded and reached ENABLED`,
and that had been true all along — while telling us almost nothing. Every
component is wrapped in `guard()`, deliberately, so the extension reaches ENABLED
whether six surfaces were built or one. The containment that protects the user's
session also hides whether anything works.

So `org.aries.Shell.Ping` now returns data rather than a sentence: which parts
were built, which failed and why, and what ARIES last said. The harness asserts
every named surface is present, that ARIES Search and the launcher respond to
being driven over D-Bus, and — the one that actually matters — that the extension
**enables cleanly a second time** after being disabled.

That last check is the real teardown test. A leak (a keybinding still bound, a
panel role still taken, a D-Bus name still owned) does not fail on disable; it
fails on the *next* enable, which is the one nobody runs.

## Verified — part two

```
$ ./scripts/test-shell.sh 34
PASS  the extension loaded and reached ENABLED
PASS  no ARIES component reported a build failure
PASS  disable() ran and tore everything down cleanly — the fallback works
PASS  every surface was built, not merely the extension loaded
PASS  and none of them reported a failure
PASS  ARIES Search opens when asked over D-Bus
PASS  the launcher opens when asked
PASS  it enables cleanly a SECOND time — nothing leaked on teardown
PASS  with no failure on the second run either

$ ./scripts/test-shell-api.sh
ALL PASSED (28 checks)
```

Six screenshots in `docs/screenshots/`, captured from the nested session and
driven over D-Bus. Worth looking at the quick settings one: it says *"no
backlight"* and *"Bluetooth · no adapter"*, because this is a desktop with
neither — the honest-absence rule from Entry 003 showing through on a surface
built eleven entries later.

1442 assertions across the suite, all green.

## What should happen next

Stopping for approval before creating a dedicated ARIES login session, as asked.

That next step is a session entry the login screen offers — it changes what GDM
starts, not what GNOME is — and `PRODUCT_IDENTITY.md` now records as a standing
constraint that **Ubuntu remains a selectable fallback permanently**. It is the
recovery environment, not a transitional embarrassment.

---

# Entry 015 — ARIES on the login screen

**Date:** 2026-09-13

## Objective

`POWER → ARIES → ARIES Login → ARIES Desktop`. ARIES offered as a session at the
login screen, so logging into ARIES gives you the ARIES desktop — with Ubuntu
still offered beside it, permanently, as the recovery path.

## Reading the mechanism instead of inventing one

The temptation with a "custom session" is to write something that starts your own
things. Ubuntu already has a session, and the right first move was to find out
exactly how, which took four commands:

```
/usr/share/wayland-sessions/ubuntu.desktop          Exec=gnome-session --session=ubuntu
/usr/share/gnome-session/sessions/ubuntu.session    Name=Ubuntu
/usr/lib/systemd/user/gnome-session@ubuntu.target.d/ubuntu.session.conf
                                                    Requires=org.gnome.Shell@ubuntu.service
/usr/lib/systemd/user/org.gnome.Shell@.service      ExecStart=gnome-shell --mode=%i
/usr/share/gnome-shell/modes/ubuntu.json            enabledExtensions: [ubuntu-dock, …]
```

That last file is the whole answer. A **session mode** names the extensions the
session loads, which is how Ubuntu's dock appears in an Ubuntu session without
anybody enabling it. ARIES needs exactly the same thing with a different list.

So an ARIES session is five new files mirroring those five, and no modification
to any of them. Ubuntu's session keeps working and keeps being offered, which
`PRODUCT_IDENTITY.md` already made a standing constraint rather than a phase.

## Proving it before writing it

Everything else in this system fails safely. A broken automation is skipped, a
broken shell component is guarded out, a stopped runtime leaves a working
desktop. A malformed session definition is the one thing here that fails *before
the user has a desktop to fix it from* — a login screen offering a session that
does not start.

So nothing was installed until the arrangement was proved. `gnome-shell` finds
modes by walking `XDG_DATA_DIRS`, so pointing that at a staging directory loads
the **real** mode file in a **real** GNOME Shell, started exactly as the session
starts it (`gnome-shell --mode=aries`), in a nested headless session. No root, no
system files, no risk to the login screen.

Two findings came straight out of that, and both changed the design.

**12. GNOME refuses to load a per-user extension as part of a session mode.**
The mode loaded, the shell started, and the extension sat at `INITIALIZED` with
one line in the log explaining why:

```
Found user extension aries@aries.local, but not loading from
/home/…/.local/share/gnome-shell/extensions/… as part of session mode.
```

Which is **right**, and the reasoning is worth keeping: a session mode is system
configuration, and system configuration must not be able to auto-load code out of
somebody's home directory. The check is Ubuntu-specific (`Desktop.is('ubuntu')`),
and the ARIES session keeps `ubuntu` in its `DesktopNames` — so it applies. It
would have been one word's edit to escape it, and doing that to make an installer
easier is how you end up with a system nobody can reason about.

*Fix:* the session installs the extension into a system data directory. `--link`
is offered for development and says plainly that it means the code your login
session runs is writable by your user account; copying is the default.

**13. `disabled-extensions` silently overrides a session mode.**
With the extension staged system-wide, the mode still did not enable it. The
cause was in `_getEnabledExtensions()`: the mode's list is assembled first and
then *filtered* by the user's `disabled-extensions` key.

So a uuid sitting in that key — because you once ran `gnome-extensions disable` —
makes a correct, complete session install start **silently without ARIES**, which
looks exactly like an install that did not work. There is no error anywhere.

*Fix:* `install` removes it, `status` warns when it is set, and `verify` clears it
for its own run.
*Lesson:* a precedence rule you do not know about turns a working install into a
no-op with no diagnostic. This is the fourth precedence bug in this project
(ERROR_LOG) and the first where the precedence was somebody else's.

## The bug I caused, which is the one worth writing down

The reason `disabled-extensions` contained `aries@aries.local` at all is that
**my own test harness put it there.**

`dconf` is per-**user**, not per-session. `gnome-extensions enable` and `disable`
run inside a nested GNOME Shell write to the same keys the real desktop reads. The
nested harness had been switching extensions on and off for two milestones, and
the live session had quietly lost its dock and its desktop icons — with
`ubuntu-dock@ubuntu.com` and `ding@rastersoft.com` moved into
`disabled-extensions` on the user's actual machine.

I restored both keys by hand, and both harnesses now record them before anything
runs and restore them on every exit path including a failure or an interrupt.
`test_session.py` asserts that they still do.

*Lesson:* **a sandbox that shares the user's settings store is not a sandbox.**
The nested shell isolates the compositor, the D-Bus session and the display — and
isolates none of the configuration, which is the part that persists. Isolation is
a property you check per-resource, not a property a container grants.

It is also exactly the rule this project already had in a different costume —
Entry 013's *"a test that changes the machine puts it back"* — and it was written
for the display timeout, four entries before the thing that actually needed it.

## What the session loads

`ubuntu-dock` is out, because ARIES has its own dock and two docks is not one
environment. Everything else Ubuntu enables stays: the tray, the tiling
assistant, the search providers, the desktop icons, and — deliberately —
`snapd-prompting`, which is a security prompt. Dropping it would have made the
desktop tidier by making the system weaker, which is not a trade this project
gets to make quietly.

The mode sets `parentMode: user` and keeps the system's shell stylesheet, so
GNOME's own widgets look like the rest of the machine. ARIES restyles its own
surfaces and leaves everything else alone.

## Verified

```
$ ./scripts/aries-session verify

PASS  gnome-shell started with --mode=aries
PASS  the ARIES extension is ACTIVE because the SESSION says so — nobody ran
      'gnome-extensions enable'
PASS  it loaded the SYSTEM copy, which is the only kind a session mode accepts
      /tmp/aries-session-l5zkmY/gnome-shell/extensions/aries@aries.local
PASS  every ARIES surface was built inside the session
PASS  with nothing reporting a failure
PASS  Ubuntu's own session mode is present and unmodified
ALL PASSED
```

And afterwards the user's `enabled-extensions` and `disabled-extensions` are
exactly what they were before the run — which is now checked, not assumed.

51 new assertions in `test_session.py`, 1493 across the suite, all green.

## What was learned

* **Read the platform's own implementation before writing yours.** Five files and
  four commands turned "write a custom session" into "add one mode".
* **Prove anything that can break login before installing it.** The nested shell
  made a change with no safe rollback into a change with a rehearsal.
* **When a platform refuses you, the refusal is usually load-bearing.** The
  per-user extension rule looked like an obstacle and is a sound security
  boundary; the version of this that "worked" would have been the worse system.
* **Isolation is per-resource.** A nested compositor is not a nested
  configuration, and the difference cost the user their dock without either of us
  noticing for two milestones.

## Rollback

```bash
./scripts/aries-session uninstall     # removes exactly the five files
```

Then the login screen offers Ubuntu only. Nothing else on the system was
modified; there is no package file to restore, no boot entry to repair, and the
Ubuntu session was never altered in the first place. From a TTY it is the same
command.

## Installing it, and the thing that would not work

The install failed on the first attempt with `sudo: A terminal is required to
authenticate`. `sudo` wants a controlling terminal, and a script run from an
editor, an agent or a desktop launcher does not have one.

The workaround would have been to tell the user to open a terminal. The fix was
better: **everything privileged moved into one script**, and the caller picks an
escalation route this machine can actually authenticate through — passwordless
sudo if it exists, `pkexec` if there is a graphical session, plain `sudo` if
there is a terminal, and otherwise printing the exact command rather than dying
with a shell error. `pkexec` asks the desktop's own PolicyKit agent, which drew a
normal password dialog on screen.

The restructuring is worth more than the convenience. It was eight `sudo` calls
scattered through a script that also parses arguments, prompts and prints status
— eight authentications and a privileged surface nobody would read. It is now one
program of about fifty lines that refuses to run unless it is root, validates
every input, refuses a mode file that will not parse, and can be read in full
before you decide to run it.

**14. A parameter expansion that reads like a conditional.**
`"${link:+link}${link:-copy}"` expands to `linkyes` when `link=yes` — both halves
fire. `--link` would have silently installed a copy, and the only symptom would
have been edits not taking effect.
*Lesson:* shell expansions that look like ternaries are not ternaries. Two lines
and an `if` are free.

### Installed, and verified as installed

```
$ ./scripts/aries-session install --yes
wrote:
  /usr/share/wayland-sessions/aries.desktop
  /usr/local/share/gnome-session/sessions/aries.session
  /usr/local/share/gnome-shell/modes/aries.json
  /usr/local/share/gnome-shell/extensions/aries@aries.local
  /etc/systemd/user/gnome-session@aries.target.d/aries.session.conf

$ ./scripts/test-session.sh 20 --installed
      testing the INSTALLED files, not a staged copy
PASS  gnome-shell started with --mode=aries
PASS  the ARIES extension is ACTIVE because the SESSION says so
PASS  it loaded the INSTALLED system copy
      /usr/local/share/gnome-shell/extensions/aries@aries.local
PASS  every ARIES surface was built inside the session
PASS  Ubuntu's own session mode is present and unmodified
ALL PASSED
```

`--installed` was added because "this would work if installed" and "what got
installed works" are different claims, and only the second one is about the
machine somebody logs into. `/usr/share/wayland-sessions/` now holds two entries:
`aries.desktop` and Ubuntu's, byte-identical to what the package shipped.

## What should happen next

Stopping for approval. The session was installed after a rehearsal against the
real files, and verified again afterwards against the installed ones —
it needs `sudo`, and a change to the login screen should be made by the person
who has to log in. `./scripts/aries-session plan` prints exactly what it will
write; `verify` proves it first.

Not started, deliberately: an ARIES login *screen* (that means replacing or
theming GDM, a separate decision with a worse failure mode), any change to boot
or the bootloader, and the compositor.

---

# Entry 017 — A green suite over a broken product

**Date:** 2026-09-13

## What happened

M13 shipped with 1511 passing assertions and a Control Centre that could not
open. Not intermittently — at all, for days. Every navigate action in ARIES
Search, every notification click, every dock press: a silent no-op.

`scripts/aries-ui` contained one line:

```bash
exec "$HOME/aries/scripts/aries-ui" "$@"
```

That is the file's own path. It exec'd itself, forever, spawning bash processes
and never reaching python. I wrote it during M13 by putting the content intended
for the `~/.local/bin` shim into the file the shim points at — and since the shim
is a *symlink* to that file, the loop closed on itself.

## Why 1511 tests said nothing

This is the part worth keeping.

The suite tests components. The launcher is not a component — it is the **seam**
between two of them, and seams are what component tests skip by construction. The
router had tests. The Control Centre had tests. The shell had tests. The four
inches between them had none, and that is where the product lived.

Adding more component tests would not have found it, and did not: I added
thirty-odd during M13 while it was broken, and every one passed.

It was also invisible from the inside. Ping reported ten surfaces built and no
failures — correctly. `perform()` spawned the launcher and returned. The launcher
exited 0 eventually. Nothing in the system was in a position to notice that a
window never appeared, because nothing was looking for a window.

## The compounding failure: verifying against code that was not running

Three separate rounds of "it works now" were reported against a `gnome-shell`
holding code from hours earlier. GJS caches extension modules, so
`gnome-extensions disable` followed by `enable` runs `disable()`/`enable()` on the
object loaded at login and imports nothing new; on Wayland the shell cannot be
restarted at all. Only a new login loads new code.

Nothing in the system could have told me. There was no way to ask what revision
was running, so I did not ask, and I reported progress from a desktop that had
none of the changes in it.

## What was built in response

**`aries version`.** Source, installed and running, compared by *content hash*.
A commit is not an identity during development — the working tree is dirty more
often than not, and two dirty trees at one commit are different software. The
first time it ran it found a stale `/usr/local` copy, which is exactly its job.

The running shell reports its own build id, stamped into the extension at
generate time and read back over D-Bus. "What is installed" and "what is running"
can differ for hours; now they can be compared.

**`./scripts/aries-smoke`.** The handful of questions whose answer is "the product
is broken", in about five seconds, exiting non-zero. It checks the seams
explicitly: the launcher chain from PATH, whether the module imports on the
interpreter that will run it, whether the running build is the source build,
whether typing `news` resolves to something that can actually execute.

**`./scripts/aries-e2e`.** Real journeys on the installed system. Every assertion
is about observable state after crossing a process boundary. Nothing is mocked —
the launcher least of all.

## The root cause of the `--section` bug

Not a typo. A race dressed as a fallback:

```python
self._pending_section = options.get("section") or ""
self.activate()
if self._pending_section and self.window is not None:
    self.go(self._pending_section)          # "in case it already existed"
```

`activate()` reaches `do_activate`, which applies the section *and clears the
field*. So the second branch fires only when the first did not — and which one
that is depends on whether the window already existed, i.e. on whether this was a
cold start or a second invocation. It landed on Settings often enough to be
reported and not often enough to be obvious.

GTK has exactly one mechanism for "make the running instance go somewhere": an
action. Navigation is now a **stateful** `GAction`, which fixes the race and does
something better — the state is readable from another process, so a test can ask
the window where it actually is rather than trusting the caller. Nine sections,
cold and warm, deterministic.

## Errors while fixing the errors

**15. The e2e harness could not hear the answer.**
`Gio.DBusActionGroup` populates asynchronously and needs a running main loop. The
script has none, so `current_section()` returned `None` every time and eleven
journeys "failed" against a harness that was never going to receive a reply. A
synchronous `org.gtk.Actions.Describe` is both simpler and correct.
*Lesson:* a convenience wrapper that needs an event loop is not convenient in a
script, and a test that cannot observe is not a test.

**16. The launcher-chain check asserted an implementation, not an invariant.**
It assumed the PATH entry was a wrapper script and parsed its `exec` line — but
it is a symlink, so the check read the *real* launcher and reported
`/usr/bin/python3.14` as a fault. Rewritten to assert what actually matters:
following the chain terminates, reaches the launcher, and no step execs itself.
That holds for a symlink and for a wrapper.
*Lesson:* the invariant survives a refactor; the implementation check punishes one.

## Two levels of done

Adopted permanently, and written into `TESTING.md`:

**ENGINEERING GREEN** — the tests pass.
**PRODUCT GREEN** — real journeys work on the installed system.

A milestone needs both. And a third applies to anything making a claim: a feature
is *research-complete* only when it has been evaluated against a baseline
(`EXPERIMENTS.md`). **Never use implementation test count as evidence that a
research hypothesis is true** — a rule this entry exists to justify.

## What was learned

* **Coverage is not the axis.** The gap was in *kind*, not amount. Ask what the
  tested graph excludes, not how much of it is covered.
* **A no-op is the worst failure mode.** It has no error, no log line, no
  signature. Every layer reported success truthfully and the product did nothing.
* **Verification needs identity.** "It works now" is meaningless without knowing
  which revision "it" is.
* **I should have looked at the screen sooner.** Two of these bugs were visible in
  one glance and invisible to everything else.

## Rollback

```bash
rm -f scripts/aries-{smoke,e2e} && rm -rf tests/e2e experiments
git checkout scripts/aries-ui aries_ui/app.py
# and remove aries/runtime/version.py plus cmd_version from cli.py
```

## What should happen next

Stopping for approval, as asked. Not started: Integrations, the Orchestrator, or
any new UI feature.

The next milestone the user has named is **ARIES Operator v0.1** — natural
language producing real actions. Its evaluation is already designed in
`EXPERIMENTS.md`, before its implementation, and the design says something this
entry earned: the interesting measurement is not the success rate but the
**honesty gap** — the difference between what an operator reports and what an
environment verifier confirms actually happened. That gap is precisely what
1511 green assertions failed to measure here.

---

# Entry 018 — What ARIES forgets

**Date:** 2026-09-13

## Why this came before the Operator

The user's own framing, and it is the right one:

> "We need to also organise the junk data to be deleted etc its basically the
> same like opening chrome reading everything and closing chrome."

An Operator that can read mail, with nothing telling it what to forget, hoards.
Message bodies in a SQLite file, forever, because nothing ever said to remove
them. That is not a hypothetical about the future: before ARIES had read a single
personal thing, `automation_logs` was already the largest table in the database.

So the lifecycle is a **precondition** of the Operator, not a tidy-up after it.
Built first, on purpose.

## The rule

A browser opens a page, you read it, you close it, the page is gone. What
survives is a bookmark — not the HTML.

Five classes, declared once in `aries/lifecycle/policy.py`: **working**,
**operational**, **memory**, **provenance**, **audit**. The full design is in
`docs/DATA.md`; three things in it are worth the journal.

## 1. The interesting failure is not a crash

Deleting a row another subsystem reads.

The circuit breaker decides whether an automation is broken by reading its run
history. The learning loop measures engagement from news items. Health baselines
are computed from samples. Delete those too eagerly and **nothing fails** — the
subsystem quietly starts answering differently. A crash would be better, because
a crash is visible.

So every policy names its dependants and the shortest window that keeps them
correct, and a window below the minimum is **refused, not clamped**. Twice, in
two places, because one can be bypassed: the setting schema carries
`minimum=minimum_days` so the value is rejected at the door; and
`service._window_for` checks again, because a row written straight into
`aries_settings` never passes the schema at all. The test that proves the second
one does exactly that — writes the row directly — and it is the reason the check
exists in two places rather than one.

A retention window that starves a dependant is a correctness bug wearing a
preference's clothes.

## 2. A register with an exception is not a register

`test_no_table_is_left_undecided` reads `sqlite_master` and fails on any table
`POLICIES` does not name. It found **seventeen** of the engine's own tables with
no policy at all — `stored_credentials` and `memory_items` among them. They were
empty, which is exactly why it was easy to miss, and exactly why it mattered to
decide before something started filling them. Credentials and tokens are classed
**memory**: a credential that expired because a cleaner ran would break a
connection with no explanation.

Then I wrote the exception myself. `aries_working_set` was `discard()`ed from the
test with a comment saying it governs itself — while the register's own docstring
said *"everything ARIES writes appears here"*. Both cannot be true. The fix was
to put it in the register as its own class with no window in days, and change the
test to assert *that* rather than its absence. An invariant with a documented
exception is an invariant nobody can rely on.

## 3. The release nothing called

`working.release()` existed, the design said "released when the task ends", and
**nothing in the system ended a task**. It would have shipped as a comment.

It is now in `_run_through_lifecycle`, in a `finally` — because failure is when
releasing matters most: a pass that died halfway is precisely the one still
holding borrowed mail bodies. The test drives a real automation that grabs
context and then raises, and asserts nothing is held afterwards. Then I broke the
release on purpose and watched the test fail, because a cleanup test that passes
against a missing cleanup is worth nothing.

## What the screens had never been tested for

Nine Control Centre pages, and no test had ever called `render()`. The contract
suite proved the endpoints return the keys the UI reads; nothing proved a screen
could build a widget tree out of them. The same shape as Entry 017: each half
tested, the seam not.

`tests/test_ui_render.py` captures live payloads in the venv and runs
`tests/ui_render.py` on the system interpreter, which is the only one with `gi`.
Two processes, because that is genuinely how the product is built (ADR-0004). It
turns out GTK4 constructs and packs widgets with no display at all — only
presenting a window needs one — which is enough to catch missing keys, wrong
types and bad markup, all of which throw during construction.

It also asserts each page puts *something* on screen. A page that renders an
empty tree is a blank screen with no error, which is the failure that looks like
everything is fine.

## Errors on the way

* Assumed `created_at` on every table. Seven use something else
  (`recorded_at`, `first_seen_at`, `started_at`, `at`, `requested_at`), so the
  very first preview raised `no such column`. The test that catches it reads the
  real columns out of `sqlite_master` rather than trusting the register.
* String-surgery on `policy.py` inserted keyword arguments inside tuples. Rewrote
  the block wholesale instead.
* Two new tests called `check(label, ok, detail)`. The harness takes two
  arguments. Put the detail in the label.

## Two levels of done

**ENGINEERING GREEN** — 1,113 ARIES checks plus the engine's suite, all passing,
including 136 in `test_lifecycle.py`.

**PRODUCT GREEN** — `aries data` prints the register against the live database
(2.55 MB, 35 tables, nothing past its window); `GET /api/aries/data` answers on
the running service; **Data Lifecycle** appears in `aries automations`, disabled,
as it should be; and the Data screen renders real payloads.

Not research-complete, and does not claim to be: there is no experiment here
because there is no hypothesis to test yet. The question this subsystem will
eventually have to answer — *does ARIES discard what it should and keep what it
should?* — cannot be measured until something real is writing to the working set.
That is the Operator's first job.

## Rollback

```bash
rm -rf aries/lifecycle tests/test_lifecycle.py aries_ui/pages/data.py \
       tests/test_ui_render.py tests/ui_render.py docs/DATA.md
# then remove: the `data` import from aries/__init__.py, cmd_data from
# aries/cli.py, the /data routes from aries/api/routes.py, the data entries
# from aries_ui/contract.py, DataPage from aries_ui/pages/__init__.py, and
# _release_working_set from aries/automations/runner.py
```

## What should happen next

**ARIES Operator v0.1**, on the orchestrator that already exists in
`vendor/agentic-core` and is currently unused. Its evaluation is designed in
`EXPERIMENTS.md` before its implementation, and the working set is the seam it
plugs into: everything it reads to answer a question goes there, and is released
when the task ends. `qwen2.5:7b` is pulled and Ollama is running as a user
service on loopback, so private capabilities can be pinned to this machine.

---

# Entry 019 — ARIES Operator v0.1: knowing whether it worked

**Date:** 2026-09-13

## The claim

Not *"ARIES can open YouTube"* — that is a subprocess call. The claim is
**"ARIES knows whether it opened YouTube"**, and says so when it does not.

So every step carries two facts that are never merged: what the tool *reported*,
and what ARIES *verified* by looking at the machine afterwards. The difference is
the **honesty gap**, and it is precisely what 1,511 green assertions failed to
measure in M13.

The design is in `docs/OPERATOR.md`; four things belong in the journal.

## 1. The model picks goals, never commands

A model that emits shell produces something that cannot be checked before it
runs, cannot be checked after it runs, and cannot be refused by a permission
system that does not know what the command will do.

A model that emits `{"goal": "open_url", "url": "…"}` produces something with a
schema, a permission, an audit line, and a verifier that decides whether it
worked independently of anything the model claims. That constraint is the whole
design: it costs the Operator the ability to do arbitrary things and buys the
ability to be honest about what it does.

**And an enum the prompt states is an enum the validator enforces.** The prompt
listed the valid sections; the validator did not check them, and the model
answered "what is the weather tomorrow" with `open_section: weather` — a step
shaped exactly like a real one, naming a screen that does not exist. Asking
politely in a prompt is not a constraint.

## 2. The evidence ladder, and `unverifiable`

Four grades — **proof**, **strong**, **circumstantial**, **none** — and every
result says which it earned. A web goal can never beat circumstantial, because a
browser's active tab URL cannot be read from outside the browser; the title
comes from the page, and it is still a title.

`none` produces **unverifiable**, a third verdict beside met and unmet. It is
not a failure and it is certainly not a success. It is ARIES saying *"I did it
and I cannot confirm it"* — which is the truth, and which the metric must not
punish: an early version counted it as an honesty gap, which would have made the
number mostly about whether the user happened to be in the ARIES session.

This was tested by reality rather than by arrangement. The experiment ran in a
session whose shell predated the `Windows()` method, so seven of eight
window-dependent tasks came back unverifiable, each with the reason and with
what ARIES could still establish. No variant reported them as successes.

## 3. Only an exact match acts

The deterministic router was the dishonest component for an afternoon.
`intents.resolve` returns near matches ranked by keyword as *suggestions*, and
taking the top one turned **"send an email to my boss"** into **"open the
Connections screen"** — the plausible substitution this milestone exists to
stop, arriving from the layer that was supposed to be the exact one.

Now only `exact` counts. Everything else goes to the model, and a model plan is
**proposed, not performed** (`operator.confirm_model_plans`). The interesting
failure is not a model refusing; it is a model answering plausibly.

## 4. The verifier found four real bugs, none of them its own

* **`aries-ui` was broken for every invocation by name** — which is how the
  shell launches it. Every navigate action from the ARIES desktop had been dead.
  Own commit; the e2e now launches by name and both it and the smoke test run
  the launcher across the whole seam.
* **The News Radar was inserting duplicate `item_id`s**, poisoning its session
  and, after three passes, opening its own circuit breaker. It hid because the
  pass returned `success: True` from its body while the lifecycle recorded
  `failed` — two answers about one run that nothing compared until now. The
  first fix then broke the per-source counter by reusing `known` for two
  different meanings, which the existing test caught immediately.
* **`run_automation` reported `ran` as success.** `ran` means the automation was
  *reached*. A tool that lies to its own verifier makes the verifier do
  avoidable work and would be believed anywhere the verifier is not.
* **The at-most-once register replayed the second "open the news screen"** as a
  duplicate and returned success without doing anything. Correct for sending an
  email, exactly wrong for opening a window: `idempotent=False` is what "every
  call is new work" is called in the engine's vocabulary.

## The experiment

Designed before the implementation, as the rule requires, and run:
`experiments/operator/` — four variants, 26 tasks, one verifier for all of them.

| variant | verified | honesty gap | median s |
|---|---:|---:|---:|
| B0 direct launcher | 17/18 (94%) | +0% | 0.04 |
| B1 keyword router | 14/18 (78%) | +0% | 0.00 |
| B2 model, no verification | 16/18 (89%) | +6% | 0.45 |
| A ARIES Operator | 16/18 (89%) | +6% | 0.43 |

**The pre-registered failure criterion was not met.** A did not exceed B2's
verified rate — they plan with the same model and act with the same tools, so by
construction they achieve the same things. The difference is what each *tells
the user*: a B2 user is told 94%, an A user is told 89% with the contradiction
named. The 6% is what a B2 user would have been wrong about.

The criterion was badly posed, and it is recorded as such rather than rewritten
after seeing the data. Rewriting it would make every other number in the file
worth less.

Two harness bugs were caught before they produced a wrong result, and both are
worth more than the numbers:

* **Trials contaminated each other.** Four variants ran the same task in
  sequence, so a variant that refused and did nothing inherited the previous
  one's success — B1 "verified" three section tasks it had explicitly refused.
  Trials are now reset and the reset is confirmed before the trial begins.
* **The engine's hourly action cap fired mid-run** and was recorded as a
  planning failure. A rate limiter looked like a planner collapsing. Gated runs
  are now counted separately, and `held` is a distinct outcome from `failed`
  everywhere, not only in the experiment.

## Two levels of done

**ENGINEERING GREEN** — all suites pass, 85 checks in `test_operator.py`,
including mutation checks on the two tests that matter most: breaking the
verifier's independence and breaking the honesty-gap definition both fail.

**PRODUCT GREEN** — `aries do "run a system health check"` verifies at proof
grade in 0.17 s; `aries do "open youtube"` proposes, and with `--yes` opens the
page and reports `unconfirmed` with the reason; the **Operator** screen is live
in the Control Centre (`docs/screenshots/operator.png`) showing what ARIES can
act on, what it cannot verify and why, and its own history with the gap.

**RESEARCH** — run, with results and a falsified criterion recorded in
`experiments/operator/analysis.md`.

## What should happen next

**Log out and back in.** The system-wide shell copy is stale, so the running
shell has no `Windows()` and every window-grade verification is `unconfirmed`.
That single step converts seven unverifiable results into verifiable ones and
moves the experiment onto the tasks where its hypothesis has teeth. It needs
`./scripts/aries-session install` first, which asks for sudo.

Then the experiment is worth re-running, with more repeats and with tasks
designed for the honesty gap's natural habitat: a launcher that succeeds while
the goal does not.

## Rollback

```bash
rm -rf aries/operator aries/intelligence.py aries_ui/pages/operator.py \
       tests/test_operator.py experiments/operator docs/OPERATOR.md
git checkout aries/api/routes.py aries/cli.py aries_ui/contract.py \
             aries_ui/pages/__init__.py aries/__init__.py \
             shell/aries@aries.local/lib/dbus.js
```

---

# Entry 020 — Integrations: the boundary, and what crosses it

**Date:** 2026-09-13

## What this milestone is actually about

Not "ARIES can read your mail". Reading a mailbox is a hundred lines of
`imaplib`. The milestone is the **boundary** — what may cross it, in which
direction, and what happens to the things that do.

Two properties, and everything else in the package is arrangement around them.

## 1. A credential appears in exactly one place

The user's own rule: credentials must never enter prompts, general memory,
normal logs, audit payloads, Git or agent state, and agents never receive a raw
secret.

That is not a guideline in `secrets.py`, it is the shape of the module. Nothing
else in ARIES holds a password; everything holds a **reference** —
`aries:email:you@gmail.com` — which is meaningless without the keyring and is
therefore safe in the database, the audit log, a screenshot and a prompt.

The test is the part worth keeping: after connecting a mailbox it sweeps **every
text column of every table** for the password. Not the columns we expected it
to be in — all of them.

**Without a keyring, ARIES refuses to store the credential.** The fallback is
the interesting failure: a file would work, nobody would notice, and the
guarantee would be gone.

And a credential is never a command-line argument. `/proc/<pid>/cmdline` is
world-readable and shell history keeps it forever.

## 2. Content can never become an action

Three lines, in order of how much they can be relied on.

**Structural, and first.** A model that has read external content may produce a
summary, a category, an urgency and a topic list, and nothing else.
`untrusted.answerable()` is the schema its reply is validated against, and there
is no `goal`, `tool`, `recipient`, `url` or `setting` in it. Actions come from
the person, through the Operator's fixed goal vocabulary, with a confirmation.

**So the worst a successful injection achieves is a wrong summary.** There is no
path from content to action that does not pass through a human. That is the
whole design; the rest is defence in depth.

**Fencing, second.** Labelled, bounded, and marked with characters that are
stripped from the content on the way in — so the fence cannot be closed from
inside. It helps. It is a request made to a probabilistic system about text an
attacker chose, and it is not what the guarantee rests on.

**Telling the user, third.** Instruction-shaped text is reported next to the
summary and never filtered. Stripping it would corrupt what ARIES was asked to
read and would hide an attack rather than surface it.

Observed, on a file planted for the purpose — the model classified it
`suspicious` and *described* the instruction:

> "The content describes an overdue invoice and includes instructions to forward
> the most recent bank message…"

It reported the attack. It did not perform it.

## The first real orchestration

`aries.attention` is a workflow graph, not a function: **collect → understand →
weigh → report**, through the engine's Director and the task lifecycle. Every
node's decision is persisted, so a pass that produced nothing can be asked
*where* — the sources were unreachable, the model did not answer, or there was
genuinely nothing to say. Those need different fixes and one `run()` reports
them identically.

`report` depends on `collect`, not on `weigh` — the News Radar learned that
expensively, and the lesson generalises: **the step that reports must not be
skippable by the conditions it is reporting on.**

The judgement is not the model's. The model says what an item *is*; whether it
reaches the user is decided by the notification policy, the interest profile and
quiet hours. A model that could notify directly would be a model that could be
made to notify by anyone who can send mail.

## Errors on the way

* **The privacy guard failed OPEN.** `_blocked_roots()` answered `[]` when the
  settings read raised, so a database hiccup would have quietly removed every
  exclusion and ARIES would have walked into `~/.ssh` with nothing in any log to
  say why. A privacy guard that degrades to "allow everything" is worse than no
  guard, because it looks like one. It now falls back to the schema's declared
  default, which is known without a database.
* **A scan matched its own documentation. Again — the fourth time.** The test
  forbidding `\Seen` in the mail connector was matching the docstring that
  exists to explain why the connector must not set it. Comments and docstrings
  are now stripped before scanning, as they are in the other three scans.
* **A test asserted that email was "not implemented"** — true when it was
  written, and a lie the day the connector landed. The invariant is not *which*
  integrations are built; it is that the screen's answer tracks what is
  registered. `aries/integrations/registry.py` now asks the connector registry
  rather than reading a static `needs_connector` flag.
* **`understand()`'s remote-refusal branch turned out to be unreachable**,
  because `intelligence.location` offers only `local` and `none` — there is no
  remote provider to refuse. The test now drives the gate that *is* reachable
  and reads the code for the one that is not, and says so. An unreachable guard
  that was never written is the same as no guard when the day comes.
* Four API-name guesses in one sitting (`all_sources`, `Matchable.topic`,
  `resolve_all`, `genome.all`). The cost of writing against a large codebase
  from memory rather than reading it first.

## Two levels of done

**ENGINEERING GREEN** — all suites pass; 120 checks in `test_connect.py`, with
mutation checks on both security guards: removing the path exclusions and
dropping `BODY.PEEK` each make the suite fail.

**PRODUCT GREEN** — `aries connect add directory …` registers and reads; a
planted injection is detected, classified `suspicious` and described rather than
followed; `aries attention` reports *"1 need(s) you, 1 can wait, from 1
source(s), 4 instruction attempt(s) in the content"*; the Connections screen
shows Email as **available** rather than "not built yet", derived from the
connector actually existing.

**RESEARCH** — designed, **not run**, and recorded as not run in
`EXPERIMENTS.md`. The corpus that matters is the user's own mail and there is no
remote model configured to compare against. Both are solvable; neither is
solved.

## Rollback

```bash
rm -rf aries/connect tests/test_connect.py docs/INTEGRATIONS.md
git checkout aries/api/routes.py aries/cli.py aries_ui/contract.py \
             aries_ui/pages/connections.py aries/integrations/registry.py \
             aries/__init__.py requirements.txt
```

## What should happen next

The claim this package makes about privacy is untested, and it is the claim the
thesis rests on. **Run the experiment**: a committed corpus of injected content
for the security half, and the user's own labelled mail — kept out of the
repository — for the agreement half.

After that, the roadmap's next item is the orchestrator proper. The Attention
Pass is one workflow with fixed nodes; a goal-based orchestrator decomposes
*"prepare me for tomorrow"* into a plan over whatever sources and automations
exist. The pieces it needs now exist: connectors, a verifier, a working set, and
a local model.

---

# Entry 021 — The experiment run 1 could not make

**Date:** 2026-09-14

The shell build was installed and a fresh ARIES session logged in. Everything
Entry 019 said it was blocked on became available in one step: the source and
installed builds match at `1ad338cb5809`, `aries-smoke` reports *ARIES is
usable* across all thirteen checks, `org.aries.Shell.Windows()` answers, and
`open_section` verifies at grade **proof** with the Control Centre focused —
the Wayland raise works.

So the Operator experiment was re-run against a session that can actually be
observed: 31 tasks × 4 variants × 3 repeats, **372 trials, nothing
unverifiable**. Run 1 could not check 7 of its 26 tasks and said so; this is
the measurement it could not make.

## Ask whether the verifier works before asking anything else

Five **control** tasks were added, and they are the part of this entry worth
keeping. Each acts on one thing and is checked against another: open Wikipedia,
verify YouTube. Launch the calculator, verify GIMP. Navigate to News, verify
Interests. Run `aries.health`, verify `aries.news`. Launch a name that cannot
launch.

The correct verdict for every one of them is **UNMET**. A verifier that grades
the plan rather than the machine returns MET, and every other number in the file
is then worthless.

**52 of 52 correctly UNMET. 0 wrongly MET.**

Adding them required splitting `act` from `expect` in the task set, because B0 —
the variant handed the expected parameters directly — would otherwise have been
handed the *expectation* and satisfied it by construction. A control the harness
cannot fail is not a control.

Those same five tasks caught **27 claimed successes across the four variants
that the verifier contradicted**. On the controls, every variant would have told
the user it had done something it had not.

## The error in this entry is in the report, not the system

The integrity block first reported **8 verifier failures**. It had not applied
its own exclusion rule. A YouTube window left open by an earlier task — in a
*second* Firefox window, which the neutral-page reset could not reach — had
already been caught by the precondition check and marked `contaminated`. The
main rates excluded it. The integrity block did not.

The verifier had read the machine correctly. The summary had not read its own
rule.

Fixed by correcting the derivation and recomputing from the raw rows, never by
re-running the trials — **re-running to repair a report of a measurement changes
the measurement**. `--resummarise` exists now for exactly that, and says so.

## The criterion was not met, for the second time

> *"The hypothesis is not supported if A's verified success rate does not exceed
> B2's by a margin larger than the run-to-run variance."*

A − B2 = **0.0**. Not on verified rate, not on honesty gap, not on false
successes, not on unverifiable rate, not on tokens. They are identical on every
axis, which is what the hypothesis's own second sentence predicted: A and B2
plan with the same model and act with the same tools, so of course they achieve
the same things.

It is recorded as stated. Rewriting a criterion once the result is in is the one
move this file exists to prevent.

## What the run does establish

**Verification does not reduce the false claims a planner produces. It reduces
the false claims a user receives.** A and B2 each produce four. A reports none of
them as success; it reports them as contradicted, with what was checked and what
was found instead. A B2 user is told 96% and is wrong about four tasks. An A user
is told 90% and is shown which four.

And the strongest single number in the table belongs to the cheapest baseline.
**B0 — issue the command, trust the exit status — has the largest honesty gap of
any variant, +11.8%**, and reports success 0.05 s after issuing an action whose
effect takes seconds to appear. The most common way to build this is the most
dishonest one, and saying so needs no model at all.

## Four failure modes, and one of them is a design gap

**The model invents a plausible address rather than refusing.** *"What is the
weather tomorrow"* became `https://www.example.com/weather`, in all three
repeats, for both model variants. It opened a browser at a made-up address and
reported success. That one task is 3 of the 4 false successes in each.

B0 and B1 score 3/3 on it precisely because they *cannot* invent. This is the
same lesson as the Integrations boundary, arriving from the other side: **a model
that must produce an action will produce one**, and the defence is a vocabulary
it cannot leave. The Operator has that for tools. It does not have it for the
contents of a URL, which is free text the verifier must then chase.

**Reporting a launch as an arrival**, which is the thing the milestone exists to
measure — with a confound named rather than netted out: variant order is fixed,
B0 always runs first immediately after the reset, and it absorbs the cold
navigation that B2 and A inherit warm.

**`app` is effectively unmeasurable in a real session.** Every application in the
task set is single-instance, so a trial cannot be reset without closing a window
the user may own — for `app-terminal`, the one the experiment is running in. The
harness therefore measures the precondition instead of forcing it, and excludes
any trial that starts with its expectation already satisfied. 10–11 trials per
variant went that way. That class needs a different design, not more repeats.

**The keyword router refuses a quarter of what ARIES can do** — 27/36 — and has a
perfect +0.0% honesty gap. That is the trade B1 makes, and the reason it is a
baseline and not the product.

## What this entry did not touch

The Operator. Not one line. The instruction was a clean evaluation of the current
implementation, so every change is in `experiments/` — the controls, the
precondition rule, the per-trial recording, and a token probe that reads
`prompt_eval_count` and `eval_count` off the Ollama response rather than asking
the Operator to report something it does not report.

## The bug that is still open, and is not the Operator's

**ARIES Search still does nothing for "open youtube", and the Operator is not why.**
The Operator plans it correctly — `desktop.open_url` with
`https://www.youtube.com`. `Super+Space` never reaches that code. The search bar
posts to `/api/aries/command`, which is the intent table, and that file says in
its own docstring that launching applications and opening URLs are deliberately
not there. So it answers honestly and does nothing:

> *"ARIES cannot do 'open youtube' yet. This is a command bar over the
> capabilities that exist, not a chat."*

Two routers exist side by side — the intent table behind the search bar, and the
Operator's router-then-model behind its own service — and nothing connects them.
`news` works because it is in the first. `open youtube` fails because it is only
in the second. That is a surface wiring gap, and it is the next thing to fix.

# Entry 022 — A goal reaches the desktop and a dashboard

2026-09-14. User requested the missing end-to-end experience: research, dashboards,
opening applications and continuity. Inspection confirmed two command tables and
no Search-to-Operator connection. Implementation starts with a durable goal
workspace, bounded collectors and existing desktop verification. The public-search
query is the user's research clause, never retrieved private context. Interrupted
side effects are recorded and never automatically replayed. Evaluation protocol is
in docs/WORKSPACE.md; engineering tests are not a research result.

Completed implementation: twenty catalogue actions, durable jobs, exact approval
resume, explicit memory, native dashboards and scheduled research topics. Shared
command routing works with the already installed shell. Live trials found that an
old URL unit test opened example.com, then exposed hidden tabs and Firefox/Snap
launch failures under the core service sandbox. The unit test now stubs launchers;
GUI actions use separate desktop services and only visible evidence can satisfy a
browser goal. GVariant decoding now preserves Unicode.

Final validation: all suites pass; 66 workspace and 94 Operator checks; 31 real UI
checks; all 13 smoke checks. Live requests: 20/20 completion criteria, qualified by
an already-installed Firefox check rather than a fresh install. Earlier failures
are retained in experiments/workspace. WORKSPACE.md documents limits and examples.

Follow-up: the user requested separate Jarvis-style screens and visibility into
background agents/evaluation. Added command-deck styling, News Radar cards, live
system sensors, Files and Monitoring. The monitor exposes actual recent outcomes
and queue-inclusive elapsed time, preserves older pending work, and explicitly
states that research superiority and autonomous self-improvement are unmeasured.
Macedonian screen commands navigate correctly. All pages were captured from GTK
against the live API and visually inspected. Workspace suite now has 81 checks.

The user clarified that tabs inside one application still missed the goal. Final
presentation now uses independent desktop ResponseWindows for commands and goals;
the system control centre remains separate. Added source-grounded article reading,
a local AI title/summary/key points, bounded attributed publisher images, and AI
briefings that disclose whether coverage is full extracted text or feed excerpts.
A live MIT article rendered with its actual image. The reader excludes comments,
processes all extracted chunks, and does not execute source or model instructions.
Workspace checks increased to 89. WORKSPACE.md records the film-design references
and explicitly preserves the distinction between engineering and research evidence.


## 2026-09-17 — Executable demo and queue recovery

The live API rejected all submitted goals because twenty queued tasks had filled
the workspace. A future-dated scheduler checkpoint after clock correction held
the queue poll, while Topic Dashboards did not persist a run and repeatedly
queued the same topics. Workspace polling now uses the existing monotonic sleep
cadence without calendar checkpoints. Topic refresh records its run, reuses pending
topics and reserves three queue slots for interactive submissions. No historical
task was deleted to make the queue appear healthy.

Firefox was launching successfully but verification did not recognize the Snap
identity `firefox_firefox.desktop`. Verification now resolves the installed desktop
ID exactly; focus is still required and matching titles remain insufficient.
The temporary 30-second settle configuration used during diagnosis was restored
to 8 seconds after the identity defect was established. Browser body attachment
allows 45 seconds within the existing bounded transport and bridge deadlines.

Added `scripts/aries-demo`, timestamped acceptance evidence, `scripts/aries-research`,
paired descriptive statistics and a Macedonian presentation guide. The final live
run passed 11/11 including an expected missing-file failure. Research reproduced
15/20 versus 19/20, four improvements, no regressions and exact paired p=0.125;
it is a development fixture, not independent scientific validation.

The isolated shell harness passed, including focus/restore and wrong-identity
rejection. Native UI navigation passed 8/8. The live shell is still an older
module build and needs a fresh login; no forced logout was performed.

Rollback: revert only this batch's queue-poll override, dashboard bookkeeping,
Snap-ID verifier and browser allowance if needed, retaining evidence and earlier
user edits. Removing the demo/research entry scripts does not change stored tasks
or active retrieval selection. Reverting queue fixes can reproduce the stall;
restart aries-core.service after backend edits. Shell changes load at next login.

Final schedule audit: direct bookkeeping now records missing run history without doubling existing records; declared hour units convert to minutes. Automation dispatcher polling also ignores future wall-clock checkpoints. Automation, API, learning, lifecycle, power and runtime regressions passed after these changes; core demo passed 7/7. The scheduled Learning Loop now has an actual ok history row and a 1440-minute interval. Data cleanup remains disabled.


## 2026-09-17 — M14 capability execution and publication

Extended the existing durable workspace queue, resource locks and task JSON with
a strict registry, local structured planner, bounded loop, step transitions and
independent goal verification. Legacy rows retain their previous executor.
Model assertions never establish completion; unsupported completion semantics
remain partial. No arbitrary shell or new destructive capability is exposed.

Review caught and corrected search-consent false positives, nested desktop
planning, confirmation bypass, write-target mismatch, concurrent approval races
and parent-directory symlink traversal. Live model trials also exposed Ollama
grammar incompatibility and premature finish/refusal. All failed runs remain
recorded; constrained generation was adjusted and the successful runs are
engineering acceptance, not held-out planner evaluation.

Final live replication: experiments/agent/20260917T204843Z-1ae7a7, 4/4.
Full regression suites passed before the final small timing/call-budget fixes;
58 dedicated checks and live 4/4 passed afterwards. Isolated shell passed;
UI navigation passed 8/8. Existing full demo is 10/11 in the current old-shell
session; smoke correctly flags its build mismatch. Fresh login is still needed.
Validation logs are retained under experiments/agent/validation-20260917/.

Added a Macedonian research paper, 18-slide presentation, Mermaid sources and
rendered diagrams, PDFs and a hashed evidence manifest. Research reporting
separates raw claims from rendered verified verdicts, excludes contaminated
controls explicitly, and does not claim statistical superiority from p=0.125.

Rollback must retain workspace history/evidence. Do not revert the whole dirty
worktree: earlier user changes coexist with this batch. Restore changed M14
routing/backend files as a unit if needed, then restart the user core service.


## 2026-09-18 — Three-level intelligence

Converted the intelligence module to a compatible package and audited existing
model calls. Deterministic mappings remain authoritative; M14 and coding use
policy-controlled routing. A persistent loopback gateway abstracts the runtime
and preserves the engine's existing local transport. Background workers do not
gain a cloud path. Added native token/cost accounting, exact safe hint caching,
new API endpoints and routing/paired-execution development runners.

Installed the gateway user unit and core dependency, enabled user lingering,
and observed both inference listeners only on loopback. A real gateway outage
left core/code running and used direct-local fallback; the gateway was restored.
Cloud remained disabled/unconfigured. Simulated provider tests cover cloud
success/failure and price calculations; real cloud policy refusal is recorded.

The initial routing fixture scored 11/13 routing and 7/13 intent. Explicit intent
definitions improved the reused fixture to 13/13; failed artifacts remain and
this is not held-out evidence. Notification suggestions remain fallible, so a
deterministic low-priority veto supplements the existing delivery policy. The
full regression first found missing retention dependant declarations; fixed and
rerun. Final dedicated checks number 52, UI 8/8 and real agent demo 4/4.

Rollback: stop/disable the new gateway only after restoring core's previous
local transport and unit dependency. Preserve both telemetry tables and task
history. Do not revert the whole dirty workspace. User lingering can be reversed
with loginctl disable-linger stamenovmartin if background-after-logout is no longer
desired. No personal application windows were closed and no logout was forced.


## 2026-09-18 — Correct cloud transport to existing terminal login

The user clarified that cloud means installed `the reviewing agent` and `codex`, not a new
HTTP API credential. Added decision-only CLI adapters behind the same provider
interface and retained the existing engine process-group cleanup pattern.
Prompts use stdin, tools/MCP/custom hooks are disabled, output/time are bounded,
and native usage is parsed from JSON/JSONL. API price estimates never masquerade
as subscription charges. Enabled cloud with Codex after an actual successful
call; the reviewing agent initially returned a session-limit 429.

The real paired execution passed both arms 3/3. Full regression passed with
63 intelligence checks, including timeout cleanup, invalid/failed output,
unexpected tool attempts and native cached-token accounting. Evidence lives in
experiments/intelligence/cli-20260918 and 20260917T222712Z-ab-f2e66d.

## 2026-09-19 — Background operation and local news summaries

Enabled core/local user services, Background Mode and an evidence-only 24h timer.
Added bounded local-only summary generation with content-keyed cache and explicit
fallback; observed 2 accepted/4 fallback English summaries and 2 original Macedonian
excerpts. Fixed power tests to verify their own inhibitor PID rather than assume no
other ARIES process is running. Real service inhibitor stays intact during tests.
Desktop verification remains limited by the cached GNOME build; no forced logout.
See `docs/BACKGROUND_VALIDATION.md` and `docs/PERSONAL_NEWS.md`.

## 2026-09-19 — Production hardening batch

Added queue/automation maintenance drain with expiring owner token; live queued
task survived restart and completed. Window observations now fail closed on invalid
schemas, and focus requests require independently observed target focus. Added
read-only production readiness report, keeping desktop capability failure explicit.
Disabled automatic locking/lock-on-suspend at user's request. See
`experiments/hardening/maintenance-live.json` and `docs/PRODUCTION_READINESS.md`.
