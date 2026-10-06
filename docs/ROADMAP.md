# ARIES — Roadmap

The specification describes twenty automations and seven levels of evolution. The
architecture must be *capable* of all of it (§13); only a fraction gets built at a time, in
an order where each step has a working predecessor.

## Done

* **M0 — Foundation.** Reproducible runtime (Python 3.12 via `uv`, no `sudo`), the
  `agentic_core` engine vendored and verified on this machine: 13 engine test files and the
  Linux reference example all green. *Build Journal Entry 001.*
* **M1 — Settings Service.** §20/§30/§31: typed schema registry, layered store with
  provenance, precedence enforced on both the read and the write path, 33 shipped settings
  across 7 sections, 32 assertions. *Entry 002.*

* **M2 — System Health automation.** §13/08 end to end on real hardware, with the two
  components it needed: the Automation Genome (§12) and the notification policy (§26).
  Seven probes, baselines using robust statistics, three notification gates, a CLI.
  98 assertions. *Entry 003.*

* **M3 — Dispatcher + Control Centre.** One background dispatcher paced by each automation's
  own last run; the §27 Control Centre, settings and notification surfaces over HTTP; route
  permissions registered explicitly. The dispatcher ships switched off. 60 assertions.
  *Entry 004.*

* **M4 — Sources Registry (§24).** Nine source types; validation that refuses rather than
  warns (symlinks resolved before judging, `privacy.excluded_paths` enforced, private and
  metadata addresses blocked); layered ordering so learning never outvotes the user; health
  and per-source performance. 103 assertions. *Entry 005.*

* **M5 — Interest Profile (§25).** Topics with inspectable, overridable weights; synonyms;
  noisy-OR scoring with word boundaries; `avoid` disqualifies rather than subtracts.
  73 assertions. *Entry 006.*

* **M6 — News Radar (§13/03).** The first automation that reaches the network: the Director
  workflow graph, deduplication, delivery caps, a circuit breaker over durable run history, and
  the fetch-time half of the SSRF guard (resolve, validate every address, pin, `sni_hostname`).
  38 assertions, plus 53 security assertions. *Entry 007.*

* **M7 — Medium learning loop + source catalogue (§16, §24).** Engagement becomes a learned
  weight only where a Wilson interval says so; the catalogue gives the user somewhere to choose
  where news comes from. *Entry 008.*

* **M8 — Morning Brief (§13/01).** Parallel collection, honest absence, time-of-day awareness.
  44 assertions. *Entry 009.*

* **M9 — Reversal detection + fast learning loop (§15, §16).** ARIES changing its own mind, with
  hysteresis expressed as a confidence level; feedback classified and scoped, asking rather than
  overgeneralising. 136 assertions. *Entry 010.*

* **M10 — Control Centre v0.1 (§27–29).** GTK4/libadwaita in its own process, HTTP only, no
  database access, no second implementation of ARIES logic. 214 assertions across two suites.
  *Entry 011.*

* **M11 — ARIES as a system layer.** `aries.target` + one `aries-core.service` under
  systemd `--user`; four derived states; crash recovery verified with `kill -9`. 49 assertions.
  *Entry 012.*

* **M12 — Background Runtime & Power — complete.** A `sleep`/`block` logind inhibitor held as an
  open file descriptor, so it cannot outlive the process; the display still blanks; the one
  borrowed GNOME key is recorded and restored. Plus the resource policy: workload classes in the
  genome, permission and condition gates kept apart, configurable CPU/GPU/temperature/duration
  limits, thermal holds with a reachable resume margin, a budget that never kills stateful work,
  and every decision in the audit log. 220 assertions. *Entry 013.* ADR-0006, ADR-0007.

* **M13 — ARIES Shell v0.1.** Top bar, dock, ARIES Search on Super+Space,
  application grid, ARIES Quick Settings, ARIES notifications, one design
  language across two toolkits, and a nested-GNOME test harness so the user's
  session is never the thing under test. 106 assertions. *Entry 014.* ADR-0008.

## Next

**Standing constraint from M13 on:** every capability below ships with its ARIES
surface, not "UI later" — see [PRODUCT_IDENTITY.md](PRODUCT_IDENTITY.md). Five
surfaces each: core capability, orchestrator access, automation access, ARIES UI,
and audit/security/learning.

The order the user set after M12, heaviest first in value: **Integrations → Orchestrator →
Dynamic agents → Context/Memory → Verifier → Model router → Slow evolution.** The UI, a custom
shell and a compositor are explicitly *not* the brain and come after.

* **Capability / Integrations layer.** GitHub, email, calendar, local project folders, the web,
  Docker and SSH — each under the permission model. This is what gives the reasoning real hands;
  Connections already lists them honestly as not built.
* **Goal-based orchestrator v1.** A goal rather than an agent: "prepare me for tomorrow". It
  decomposes, picks agents and tools, plans parallel and sequential steps, and verifies.
* **Dynamic sub-agent teams.** Not ten fixed agents — a planner assembling a temporary team
  (researcher, analyst, verifier, synthesiser) per goal.
* **Personal memory / knowledge graph (§14).** Projects, people, deadlines, decisions, research
  topics, past failures, useful workflows, and the relations between them — always answerable
  with *why do you think that?* and *where do you know it from?*
* **Context engine.** What to retrieve before each task: which memories, settings, project
  context, how much history, which external sources. A poor context engine is a good model with
  bad results.
* **Verifier / critic layer.** For high-risk work: execute → critique → verify → confidence →
  result, rather than straight to the user.
* **Model router.** A local model for classification, a strong one for synthesis, a coding model
  for repositories, a cheap one for background filtering — and learning which suits which class
  of task.
* **Slow evolution loop (§18/§19).** Agent versions, workflow versions, routing policy, prompts,
  tools, retrieval strategy — only ever propose → sandbox → benchmark → compare → approve →
  promote → rollback.
* **Automation discovery.** "You do this every Sunday" → a proposed workflow.
* **Proactive agent mode.** Controlled: "you have a deadline in two days, the repository has
  failing tests, and you have 90 free minutes today — shall I draft a plan?"

## Later

* **The rest of the twenty automations (§13).** The architecture carries all of them; four exist.
  Several of the ones left — a repository analyser, a local-model summariser — are the first work
  that will declare a heavy workload class and meet the resource policy.
* **A dedicated ARIES session.** `POWER → ARIES → ARIES Login → ARIES Desktop`,
  as a session entry the login screen offers — which changes what GDM starts
  without changing what GNOME is. **Ubuntu stays a selectable fallback
  permanently**; no milestone may remove it.
* **An ARIES compositor (§5, §34).** Becomes the right answer when ARIES needs
  window management or input routing GNOME will not give it — not before, and
  behind everything above.

## Standing constraints

* No automation is enabled by default (§11).
* No dependency is adopted for popularity; each is evaluated on purpose, maturity,
  maintenance, architecture fit, licence, performance, lock-in, security and alternatives (§3).
* The self-improvement review (§13/20) never modifies production behaviour directly.
* Every step gets a Build Journal entry written *while* it happens (§35).

## Known debt

* Screenshots in `docs/screenshots/` predate the Power & Background panel; the offscreen renderer
  used in Entry 011 returned an empty node this time and was not chased.
* No rename map for settings keys yet; needed the first time a key is renamed.
* The dispatcher's enabled-switch cache is one tick (60s) stale by design; documented at the cache.
* The overlap lock is per-process — a database lease is needed before ARIES runs more than one.
* `robots.txt` is not consulted by the fetcher (recorded in SECURITY.md).
* Interest synonyms are manual, and there is no stemming (`agent` ≠ `agents`) — both deliberate,
  since a wrong synonym or stem widens a topic invisibly.
* Memory exclusions now cover stored utterances, derived conclusions, ranking and automatic
  inference neighbours (2026-10-01). Common non-imperative information questions, including
  "што има денас од вести", are rejected by the automatic gate. General semantic judgement of
  what deserves retention remains a model-quality limitation; see MEMORY.md.
* No automation declares a heavy workload class yet, so the resource policy refuses nothing
  today. The gate and its budget are implemented and tested; what is absent is heavy work to meet
  them.
* Background Mode's inhibitor is absent for the `RestartSec=5` window after a crash. Accepted: the
  alternative is a lock that can outlive the process holding it.
* The docs listed in §37 are created as their subsystems land, not stubbed in advance.
