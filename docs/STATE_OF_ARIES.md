# ARIES — State of the System

> **18 September — terminal cloud correction:** `claude-cli` and `codex-cli`
> adapters use existing terminal login. Cloud routing is enabled with Codex selected;
> no separate API key is required. The HTTP-only “unconfigured cloud” limitation
> below is historical. the reviewing agent initially returned a session-limit 429; this is
> recorded as a provider failure, never successful completion.

> **18 September 2026 — Local-first intelligence:** code/local/cloud routing is
> integrated into the existing workspace. The persistent localhost model gateway
> is active, with native usage tracking, confidence policy and safe decision cache.
> Development routing/intent fixture: 13/13; real agent demo: 4/4. Cloud is
> unconfigured/disabled, so all-cloud task comparisons and cost savings remain
> unmeasured. Services survive logout through user lingering; suspend/power loss
> still stops work. See [INTELLIGENCE.md](INTELLIGENCE.md) for limits and evidence.

> **17 September 2026 — M14:** central registry (15 capabilities), strict local-model
> decisions, bounded execution, independent completion checks, durable step/evidence
> history and API/Monitor integration are implemented. Final live run
> `experiments/agent/20260917T204843Z-1ae7a7/` passed 4/4, including a genuinely
> failed missing-file task. Full regression suites passed; 58 dedicated checks and
> native UI 8/8 passed. The latest legacy demo is 10/11 because the loaded older
> GNOME extension cannot focus an existing background Firefox window; smoke also
> detects that build mismatch. Fresh login remains necessary, not performed automatically.
> General execution is supported; independent semantic completion contracts remain
> deliberately limited. See [AGENT_EXECUTION.md](AGENT_EXECUTION.md) and
> [publication artifacts](publication/README.md).

> **17 September 2026 demo update:** the integrated installed-system runner
> passed 11/11 checks (`experiments/demo/20260917T185011Z-72477e/`). Fixed a
> clock-correction queue stall, unrecorded dashboard schedules/duplicate pending
> work, and Snap Firefox identity verification. Browser navigation has a bounded
> longer DOM allowance. The research runner records 15/20 vs 19/20 relevance
> cases, exact paired p=0.125; this is exploratory, not a significant held-out
> improvement. See [DEMO.md](DEMO.md) and [RESEARCH_DEMO.md](RESEARCH_DEMO.md).
> The current GNOME session still has the older extension loaded: a new login
> is required for the tested new window-focus method. This supersedes earlier
> smoke-green claims for the current session.

> **14 September 2026 update (working tree):** Search now reaches the Operator through
> a durable goal workspace with twenty base capabilities, an additional article
> reader, independent response windows and AI summaries with attributed images. The full
> suite passes; 31 installed UI checks and 13 smoke checks pass. The live acceptance
> run completed 20/20 requests, including an already-installed package check, **not
> a fresh installation**. See [WORKSPACE.md](WORKSPACE.md) for current behavior,
> evidence and limits. The historical counts and missing-feature statements below
> describe the earlier snapshot and are superseded where this update applies.

**One document, everything built so far.** The Build Journal has the reasoning, the
Changelog has the order, this has the whole picture on one page: what ARIES is, what
exists today, what it was measured against, what does not exist yet, and what is next.

> **Read this first, then the rest.** Every section links to the document that owns
> the detail. Nothing here is a summary of intent — every number below was read out
> of the running system at the commit named in *Provenance*.

---

## 1. What ARIES is

**ARIES** — *Artificial Responsive Intelligent Execution System* — is a personal,
AI-native, adaptive, **agentic computing environment** built on Linux.

Not an assistant application that happens to run on a desktop. A computing
environment whose behaviour is the product: it watches the machine, holds a model of
what its user cares about, takes goals in natural language, acts, **verifies that it
actually acted**, and changes its own mind when it was wrong.

Three principles govern every line of it, and they are older than any milestone:

| | |
|---|---|
| **Product identity** | The product is ARIES. Linux, GNOME and systemd are *implementation foundations*. Nothing ships as "a GNOME feature with an ARIES add-on". Every capability gets five surfaces: core capability · orchestrator access · automation access · ARIES UI · audit/security/learning. |
| **Research evaluation** | A capability is *engineering-complete* when it works and passes tests, and *research-complete* only when it has been measured against an honest baseline. **Implementation test count is never evidence that a research hypothesis is true.** |
| **Two levels of done** | **Engineering green** = the suite passes. **Product green** = the real journey works on the *installed* system. A milestone needs both, and the second has failed while the first was green more than once. |

[VISION.md](VISION.md) · [PRODUCT_IDENTITY.md](PRODUCT_IDENTITY.md) · [EXPERIMENTS.md](EXPERIMENTS.md) · [TESTING.md](TESTING.md)

---

## 2. Where it stands today

**Engineering green.** Every suite passes: the vendored engine (13 files), the
engine's Linux reference example, ARIES's own 22 suites, the shell's HTTP layer run
under `gjs` against a deliberately broken ARIES, and the Control Centre on the system
interpreter — **2,047 assertions, 0 failures**.

**Product green.** The current shell build is installed and a fresh ARIES session
is logged in. Source and installed builds match at `1ad338cb5809`, and
`scripts/aries-smoke` reports **ARIES is usable** across all thirteen checks —
including *"the running shell is the source revision"*.

Verified on the installed system, not in a test:

| | |
|---|---|
| `org.aries.Shell.Windows()` | answers, with `wm_class` / `app_id` / `pid` / `focused` / `minimised` per window |
| Control Centre navigation | `open_section` verifies **met**, grade **proof** — the Control Centre answers for itself |
| Control Centre focus | `Windows()` confirms it `focused=true` — the Wayland raise works |
| ARIES Search | `news` resolves and executes end to end |

**One thing is still broken, and it is not what it looks like.** ARIES Search does
nothing for *"open youtube"*. The Operator plans it correctly — `desktop.open_url`
with `https://www.youtube.com`. `Super+Space` never reaches that code: the search
bar posts to `/api/aries/command`, which is the intent table, and that file
deliberately holds no `open_url` or `open_app`. So it answers honestly and does
nothing:

> *"ARIES cannot do 'open youtube' yet. This is a command bar over the capabilities
> that exist, not a chat."*

Two routers exist side by side — the intent table behind the search bar, and the
Operator's router-then-model behind its own service — and nothing connects them.
`news` works because it is in the first; `open youtube` fails because it is only in
the second. **A surface wiring gap, and the next thing to fix.**

---

## 3. The system, layer by layer

```
            ┌──────────────────────────────────────────────────────┐
   surface  │ ARIES Shell (GNOME Shell extension, GJS)             │  Super+Space search, dock,
            │ ARIES Control Centre (GTK4/libadwaita, own process)  │  top bar, quick settings,
            └───────────────┬──────────────────────────────────────┘  application grid
                            │  HTTP only — the UI never touches the database
            ┌───────────────▼──────────────────────────────────────┐
   reason   │ Operator  ·  Automations  ·  Learning  ·  Interests   │
            │ Intelligence (local model)  ·  Lifecycle  ·  Power    │
            └───────────────┬──────────────────────────────────────┘
            ┌───────────────▼──────────────────────────────────────┐
   boundary │ Connect — connectors · secrets · untrusted content    │
            └───────────────┬──────────────────────────────────────┘
            ┌───────────────▼──────────────────────────────────────┐
   engine   │ agentic_core — tasks, workflows, evaluators, gates,   │
            │ audit, at-most-once tool calls                        │
            └──────────────────────────────────────────────────────┘
```

### The engine — `vendor/agentic-core`

Every unit of work is a **task** with a lifecycle: `EXECUTE → EVALUATE → VERDICT →`
retry · replan · escalate · reconcile. Multi-step work is a `WorkflowSpec` graph of
nodes, gates and dependencies executed by the Director. Quality is not a boolean — an
`Evaluator(name, fn, weight)` raises `issue(severity, code, message)`, and a
`LifecyclePolicy` decides what a verdict means.

Every tool call passes **eight gates** in order: permission → schema → dry run →
live-tool allowlist → policy → approval → at-most-once → journal.

[ENGINE_README.md](ENGINE_README.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

### Runtime — ARIES is not an application

`aries.target` plus one `aries-core.service` under systemd `--user`. It starts with
the login session and keeps running whether or not a window is open. Four derived
states, crash recovery verified with `kill -9`.
[RUNTIME.md](RUNTIME.md)

### Settings — the user always wins

**145 settings across 18 sections** (`ai`, `automations`, `autonomy`, `briefing`,
`connect`, `data`, `general`, `health`, `intelligence`, `interests`, `learning`,
`news`, `notifications`, `operator`, `power`, `privacy`, `shell`, `sources`). A typed
schema registry with a layered store, provenance on every value, and precedence
enforced on **both** the read and the write path — so learning can never quietly
outvote an explicit choice. No YAML.
[SETTINGS.md](SETTINGS.md)

### Automations — declarations, not scheduled functions

Six shipped, none enabled by default:

| automation | what it does |
|---|---|
| **System Health Monitor** | seven probes, baselines from robust statistics, three notification gates |
| **News Radar** | the first automation to reach the network: workflow graph, dedup, delivery caps, a circuit breaker over durable run history, full SSRF guard |
| **Morning Brief** | parallel collection, honest absence, time-of-day awareness |
| **Learning Loop** | engagement becomes a learned weight only where a Wilson interval says so |
| **Data Lifecycle** | the forgetting pass — see §3 Data |
| **Attention Pass** | the first real orchestration over external content: collect → understand → weigh → report |

Each is an `AutomationSpec` (the Automation Genome) plus an append-only run history.
[AUTOMATIONS.md](AUTOMATIONS.md)

### Sources and interests — where ARIES may look, and what matters

Nine source types with validation that **refuses rather than warns**: symlinks
resolved before judging, `privacy.excluded_paths` enforced, private and metadata
addresses blocked. Interests are topics with inspectable, overridable weights and
noisy-OR scoring; `avoid` disqualifies rather than subtracts.
[SOURCES.md](SOURCES.md) · [INTERESTS.md](INTERESTS.md)

### Learning — and changing its mind

The medium loop (behaviour → weights, gated by a Wilson interval), the fast loop
(explicit feedback, classified and scoped, asking rather than overgeneralising), and
**reversal detection** — ARIES noticing it was wrong, with hysteresis expressed as a
confidence level.
[LEARNING.md](LEARNING.md)

### Power — staying awake without lying to the machine

A `sleep`/`block` logind inhibitor held as an **open file descriptor**, so it cannot
outlive the process that took it. The display still blanks. The one borrowed GNOME
key is recorded and restored. Plus the resource policy: workload classes in the
genome, permission and condition gates kept apart, CPU/GPU/temperature/duration
limits, thermal holds with a reachable resume margin, a budget that never kills
stateful work, every decision in the audit log.
[POWER.md](POWER.md)

### Data lifecycle — what ARIES forgets

**35 retention declarations over 5 classes**, so that no table in the database is
undecided:

| class | meaning |
|---|---|
| **Working** | what ARIES is reading right now to do one task. Released when the task ends, *whatever the outcome*. |
| **Operational** | logs, samples, runs. Useful for a window, then noise. |
| **Memory** | what ARIES concluded and what you told it. Kept until you remove it — a preference that expired is not a preference. |
| **Provenance** | where a memory came from. Lives exactly as long as the memory it supports. |
| **Audit** | the record of what ARIES did, including its own deletions. Never removed automatically. |

Stored credentials are *never* on a timer: a credential that expired because a
cleaner ran would break a connection with no explanation.
[DATA.md](DATA.md)

### The boundary — Integrations

**Four connectors**: `directory`, `documents`, `email`, `repository`.

Two guarantees, and everything else is arrangement around them.

**A credential appears in exactly one place.** The freedesktop Secret Service holds
it; everything else in ARIES holds a *reference* — `aries:email:you@example.com` —
which is meaningless without the keyring and therefore safe in the database, the
audit log, a screenshot and a prompt. **Without a keyring, ARIES refuses to store the
credential** rather than falling back to a file. A credential is never a command-line
argument (`/proc/<pid>/cmdline` is world-readable). The test sweeps *every text
column of every table* for the password — not the columns we expected it to be in.

**Content can never become an action.** Three layers, in order of how much each can
be relied on:

1. **Structural, and first.** A model that has read external content may return only
   a summary, a category, an urgency, a topic list. `untrusted.answerable()` has no
   `goal`, `tool`, `recipient`, `url` or `setting` in it. **The worst a successful
   injection achieves is a wrong summary.**
2. **Fencing, second.** Labelled, bounded, marked with characters stripped from the
   content on the way in — so the fence cannot be closed from inside.
3. **Telling the user, third.** Instruction-shaped text is reported next to the
   summary and **never filtered**. Stripping it would hide an attack rather than
   surface it.

Verified live, on a file planted for the purpose: the model classified it
`suspicious` and *described* the instruction — *"the content … includes instructions
to forward the most recent bank message"*. It reported the attack. It did not perform
it.

Mail is read with `BODY.PEEK[]` and `readonly=True`, so ARIES reading your inbox
never marks anything as seen.
[INTEGRATIONS.md](INTEGRATIONS.md) · [SECURITY.md](SECURITY.md)

### The Operator — natural language that produces *verified* action

> **"Open YouTube" is not done when a command exits 0. It is done when a browser is
> on YouTube.**

Router → local model → refusal, over a fixed goal vocabulary and **four tools**
(`open_app`, `open_section`, `open_url`, `run_automation`). Then the part that
matters: an **evidence ladder**. `Verification(verdict, grade, checked, found,
evidence)` with verdicts `MET` / `UNMET` / `UNVERIFIABLE` and grades from
`CIRCUMSTANTIAL` to `PROOF`.

The verifier **never reads the action's own report** — that is enforced structurally
and tested. `UNVERIFIABLE` is a first-class verdict, so a missing observation is never
reported as either success or failure. The **honesty gap** measures how often ARIES
reported a success that verification contradicted.
[OPERATOR.md](OPERATOR.md)

### Intelligence — local only

`intelligence.location` offers `local` or `none`. Private data is processed on the
user's own RTX 3060 through Ollama on `127.0.0.1:11434`, `qwen2.5:7b` at **≈69 tok/s
warm**. There is deliberately no remote provider configured.

### The surfaces

**ARIES Shell v0.1** — a GNOME Shell extension: top bar status, dock, ARIES Search on
`Super+Space`, application grid, ARIES Quick Settings, ARIES notifications, and
`org.aries.Shell.Windows()` — which exists because **Wayland gives no client a way to
enumerate another client's windows**; only the compositor knows.
[SHELL.md](SHELL.md)

**ARIES Login Session** — `POWER → ARIES → ARIES Login → ARIES Desktop` as an entry
the login screen offers, installed as five files. Ubuntu stays a selectable fallback
permanently; no milestone may remove it.
[SESSION.md](SESSION.md)

**ARIES Control Centre** — GTK4/libadwaita in its own process, over HTTP only, with
no database access and no second implementation of ARIES logic.
[UI.md](UI.md) · [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) · [COMMAND_HISTORY.md](COMMAND_HISTORY.md)

---

## 4. The record — every milestone, in order

| # | milestone | what it established | journal |
|---|---|---|---|
| **M0** | Foundation | reproducible runtime (Python 3.12 via `uv`, no `sudo`); the `agentic_core` engine vendored and verified | 001 |
| **M1** | Settings Service | typed schema, layered store, provenance, precedence on read *and* write | 002 |
| **M2** | System Health | the first automation end-to-end on real hardware; the Automation Genome; notification policy | 003 |
| **M3** | Dispatcher + Control Centre | automation made *visible* before making it autonomous; ships switched off | 004 |
| **M4** | Sources Registry | validation that refuses; symlinks resolved before judging; SSRF address rules | 005 |
| **M5** | Interest Profile | inspectable, overridable weights; `avoid` disqualifies | 006 |
| **M6** | News Radar | the first network automation; circuit breaker; fetch-time SSRF guard | 007 |
| **M7** | Medium learning loop | engagement → weight only where a Wilson interval says so | 008 |
| **M8** | Morning Brief | parallel collection; honest absence | 009 |
| **M9** | Reversal detection | ARIES changing its own mind, with hysteresis | 010 |
| **M10** | Control Centre v0.1 | GTK4 in its own process, HTTP only | 011 |
| **M11** | ARIES as a system layer | systemd `--user`; crash recovery verified with `kill -9` | 012 |
| **M12** | Background Runtime & Power | the inhibitor as a file descriptor; the resource policy | 013 |
| **M13** | ARIES Shell v0.1 | the desktop stops being Ubuntu with an app on it | 014 |
| — | **M13 stabilisation** | *a green suite over a broken product* — the entry that produced the two-levels-of-done rule | 017 |
| **M14** | ARIES login session | ARIES on the login screen | 015 |
| — | **Data lifecycle** | what ARIES forgets, and what it must never forget on a timer | 018 |
| — | **Operator v0.1** | knowing whether it worked | 019 |
| — | **Integrations v0.1** | the boundary, and what crosses it | 020 |

[CHANGELOG.md](CHANGELOG.md) · [BUILD_JOURNAL.md](BUILD_JOURNAL.md) — 4,869 lines of reasoning written *while* the work happened.

---

## 5. The system in numbers

| | |
|---|---:|
| ARIES Python | 19,887 lines |
| Tests | 8,579 lines |
| Control Centre (GTK4) | 4,178 lines |
| ARIES Shell (GJS + CSS) | 3,726 lines |
| Documentation | 10,604 lines across 30 files |
| Settings | **145** across 18 sections |
| Automations | **6** (none enabled by default) |
| Connectors | **4** |
| Operator tools | **4** |
| Retention rules | **35** across 5 data classes |
| Test suites | engine 13 · engine reference example · ARIES 22 · shell HTTP (gjs) · Control Centre |
| Assertions, ARIES suites | **2,047** — all passing |

---

## 6. Research status — what has actually been measured

The thesis claim is not *"I built fifteen features"*. It is *"I built a system and
showed experimentally which adaptive agentic mechanisms actually help"*. A capability
that works but was never compared to anything contributes nothing to that claim.

### `operator/` — **RUN TWICE** · latest 2026-09-13, 372 trials

31 tasks × 4 variants × 3 repeats, in a fresh ARIES session on the current shell
build. **Nothing was unverifiable** — run 1 could not check 7 of its 26 tasks
because that session's shell predated `Windows()`.

**The verifier was tested first.** Five *control* tasks act on one thing and are
checked against another, so the correct verdict for each is UNMET:
**52 of 52 correct, 0 wrongly MET.**

| variant | verified | honesty gap | false successes | median s |
|---|---:|---:|---:|---:|
| B0 direct launcher | 57/68 · 84% | **+11.8%** | **8** | 0.05 |
| B1 keyword router | 45/67 · 67% | +0.0% | 0 | 0.00 |
| B2 model, no verification | 60/67 · 90% | **+6.0%** | 4 | 0.48 |
| **A** ARIES Operator | 60/67 · 90% | **+6.0%** | 4 | 0.43 |

**The pre-registered failure criterion was not met, for the second time.**
A − B2 = 0.0 on every axis. Recorded as stated rather than rewritten: A and B2
plan with the same model and act with the same tools, so by construction they
achieve the same things. The difference is what each *tells the user* — a B2 user
is told 96% and is wrong about four tasks; an A user is told 90% with those four
named.

The strongest number belongs to the cheapest baseline. **B0 — issue the command,
trust the exit status — has the largest honesty gap of any variant**, and reports
success 0.05 s after an action whose effect takes seconds to appear. That is the
case for verification made without reference to any model.

**Dominant failure mode:** the model invents a plausible address rather than
refusing. *"What is the weather tomorrow"* became `https://www.example.com/weather`
in all three repeats, for both model variants — 3 of the 4 false successes in
each.

### `connect/` — **designed, not run**

Blocked on two honest obstacles, both recorded rather than worked around: the corpus
that matters is the user's own mail (**never committed, ever**), and
`intelligence.location` offers only `local`/`none`, so there is no remote model to
compare against.

### `learning/` — implemented, **not evaluated**

M7–M9 are engineering-complete and research-incomplete. Recorded here rather than
quietly counted as done.

### `orchestrator/` · `memory/` · `dynamic_agents/` · `model_router/` · `evolution/`

Designs to be written when each milestone starts — *before* its implementation, which
is the order the rule requires.

[EXPERIMENTS.md](EXPERIMENTS.md) · `experiments/`

---

## 7. What the errors taught

[ERROR_LOG.md](ERROR_LOG.md) exists because the same mistakes keep arriving in new
modules. The recurring shapes, each now a convention:

| shape | convention |
|---|---|
| **Two clocks** (×3) | database timestamps are UTC; conversion happens at the point of display; where both clocks appear in one function, name them |
| **A reporting step downstream of what it reports** (×2) | the node that reports depends only on the node that *starts* the work, never on the nodes whose outcomes it describes |
| **Unknown is not zero** (×4) | report `null` with a reason; a new thing reported as `0.0` sorts last, looks broken, and is never consulted again |
| **A default written before the thing it configures** | a setting defined ahead of its consumer is a guess; revisit it when the consumer lands |
| **Two meanings sharing one signal** | a colour, a position or a number carries one meaning — if two states share it, it means neither |
| **A boundary removes the compiler** | four API names guessed wrong in one sitting, all across a module boundary |
| **A scan matching its own documentation** (×4) | structural tests tokenize and strip comments and docstrings before searching |

The four bugs the Operator's **verifier** found — a launcher broken for every
invocation by name, the News Radar's circuit breaker silently open, a tool reporting
`ran` as success, an at-most-once register replaying window opens — are the strongest
argument in the project for verification as a mechanism, and none of them came from
the test suite.

---

## 8. What does not exist yet

Stated plainly, because a status document that only lists achievements is not a
status document.

* **Zero agents registered.** The engine supports agent definitions; ARIES defines none.
* **No goal-based orchestrator.** The Attention Pass is one workflow with *fixed* nodes. Decomposing "prepare me for tomorrow" over whatever sources and automations happen to exist is not built.
* **No personal memory / knowledge graph (§14).** Projects, people, deadlines, decisions, past failures and their relations — always answerable with *why do you think that?* — does not exist.
* **No context engine.** Nothing decides what to retrieve before a task.
* **No model router.** One local model does everything.
* **No slow evolution loop (§18/§19).** No agent versions, no sandboxed benchmark, no promote/rollback.
* **16 of 20 specified automations** are unbuilt. The architecture carries them; four exist.

Plus the standing debt: screenshots predate the Power panel · no rename map for
settings keys · the dispatcher's enabled-switch cache is one tick stale by design ·
the overlap lock is per-process · `robots.txt` is not consulted ·
no automation
declares a heavy workload class, so the resource policy refuses nothing today · the
inhibitor is absent for the `RestartSec=5` window after a crash.

---

## 9. What is next

The order the user set after M12, heaviest first in value:

**Integrations ✅ → Orchestrator → Dynamic agents → Context/Memory → Verifier → Model router → Slow evolution**

Integrations is delivered. Two candidates sit at the front, and they are not in
competition — one is measurement, one is capability:

1. **Re-run the Operator experiment after the install step**, with the window list
   available, more repeats, and tasks in the honesty gap's natural habitat. The
   hypothesis has never been tested where it is strongest.
2. **The goal-based orchestrator.** The pieces it needs now all exist: connectors, a
   verifier, a working set, and a local model.

[ROADMAP.md](ROADMAP.md)

---

## 10. Where everything is written

| document | what it owns |
|---|---|
| [VISION.md](VISION.md) | what ARIES is for |
| [PRODUCT_IDENTITY.md](PRODUCT_IDENTITY.md) | the product is ARIES; Linux is the foundation |
| [ARCHITECTURE.md](ARCHITECTURE.md) | the layering |
| [ROADMAP.md](ROADMAP.md) | done · next · later · standing constraints · known debt |
| [BUILD_JOURNAL.md](BUILD_JOURNAL.md) | how it was built, in order, with the reasoning intact |
| [CHANGELOG.md](CHANGELOG.md) | milestones, newest first |
| [ERROR_LOG.md](ERROR_LOG.md) | bugs found while building, indexed so recurring shapes are visible |
| [EXPERIMENTS.md](EXPERIMENTS.md) | the evaluation rule, and every experiment's status |
| [TESTING.md](TESTING.md) | two levels of done |
| [SECURITY.md](SECURITY.md) | the threat model |
| [DATA.md](DATA.md) | what is kept, for how long, and what is discarded |
| [INTEGRATIONS.md](INTEGRATIONS.md) | the boundary and what may cross it |
| [OPERATOR.md](OPERATOR.md) | natural language → verified action |
| [AUTOMATIONS.md](AUTOMATIONS.md) · [SOURCES.md](SOURCES.md) · [INTERESTS.md](INTERESTS.md) · [LEARNING.md](LEARNING.md) · [MEMORY.md](MEMORY.md) | the reasoning layer |
| [RUNTIME.md](RUNTIME.md) · [POWER.md](POWER.md) · [SESSION.md](SESSION.md) · [SHELL.md](SHELL.md) | the system layer |
| [UI.md](UI.md) · [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) · [SETTINGS.md](SETTINGS.md) · [COMMAND_HISTORY.md](COMMAND_HISTORY.md) · [API.md](API.md) | the surfaces |
| [INSTALLATION.md](INSTALLATION.md) | getting it running |
| [ENGINE_README.md](ENGINE_README.md) · [ENGINE_MIGRATION_GUIDE.md](ENGINE_MIGRATION_GUIDE.md) | the inherited engine |

---

## Provenance

Read out of the running system at commit `47aec24`, working tree clean, on
2026-09-14. Shell source and installed builds both `1ad338cb5809`; smoke green.
Every count in §5 was measured, not estimated.
