# Documentation index

This page is a map. It adds nothing that is not already in the files it links to.

## Start here

| document | what it is |
|---|---|
| [`REVIEWER_GUIDE.md`](REVIEWER_GUIDE.md) | **for reviewers**: every research question with its result and evidence, the code by component, how to recompute the tables |
| [`../README.md`](../README.md) | what ARIES is, and the **evaluation map** (thesis and IIS), with a status label for each result |
| [`STATE_OF_ARIES.md`](STATE_OF_ARIES.md) | the current state of the system, area by area |
| [`AUDIT.md`](AUDIT.md) | the 2026-10-22 static audit: layout, code health, flags, test failures, known bugs, integration and runtime health, plus the **Fixed / remaining** section. Raw tool outputs are in [`audit/`](audit/) |
| [`ENVIRONMENT.md`](ENVIRONMENT.md) | the machine, Python, the pinned packages (`../requirements.lock`), the Ollama version and the model IDs |
| [`CONFIG_REFERENCE.md`](CONFIG_REFERENCE.md) | every flag and every setting, with its default, **generated from the code** by `../scripts/gen_config_reference.py` |
| [`../Makefile`](../Makefile) | one entry point: `setup`, `test`, `lint`, `check`, `smoke`, `eval-thesis`, `eval-iis` |

## Architecture

| document | what it is |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | the architecture |
| [`JARVIS_ARCHITECTURE.md`](JARVIS_ARCHITECTURE.md), [`architecture/`](architecture/) | the target architecture and its diagram |
| [`decisions/`](decisions/) | ADR-0001 to ADR-0008: engine, runtime, settings precedence, UI, runtime model, inhibitor, resource policy, shell |
| [`AGENT_EXECUTION.md`](AGENT_EXECUTION.md), [`CAPABILITIES.md`](CAPABILITIES.md), [`verification_table.md`](verification_table.md) | the planner loop, the capability registry, and what each verifier proves |
| [`RUNTIME.md`](RUNTIME.md), [`SESSION.md`](SESSION.md), [`SHELL.md`](SHELL.md), [`UI.md`](UI.md), [`SPEECH.md`](SPEECH.md), [`POWER.md`](POWER.md) | the runtime, login session, GNOME Shell extension, Control Centre, speech, power and background mode |
| [`MEMORY.md`](MEMORY.md), [`LEARNING.md`](LEARNING.md), [`INTERESTS.md`](INTERESTS.md), [`PERSONAL_NEWS.md`](PERSONAL_NEWS.md), [`INTELLIGENCE.md`](INTELLIGENCE.md) | the information layer (IIS project) |
| [`DATA.md`](DATA.md), [`SECURITY.md`](SECURITY.md), [`SETTINGS.md`](SETTINGS.md), [`API.md`](API.md) | data lifecycle, security, settings, API |
| [`ENGINE_README.md`](ENGINE_README.md), [`ENGINE_MIGRATION_GUIDE.md`](ENGINE_MIGRATION_GUIDE.md) | the vendored `agentic-core` engine |

## Preregistrations and amendments

All of these are in [`preregistration/`](preregistration/). They are frozen: an amendment is a new
section in the same file, dated, and written before the measurement it changes.

| hypothesis | file | amendments | status (README evaluation map) |
|---|---|---|---|
| H4 planner clarification | [`H4-planner-clarification.md`](preregistration/H4-planner-clarification.md) | 1, 2 (2026-10-12) | registered, not run |
| H4b clarification resolver | [`H4b-clarify-resolver.md`](preregistration/H4b-clarify-resolver.md) | 1 (10-18), 2 (10-19), 3 (10-22) | confirmatory, measured (not met) |
| H5 completion paraphrase / typed contract | [`H5-completion-paraphrase.md`](preregistration/H5-completion-paraphrase.md) | 1, 2, 3 (10-18), 4 (10-22) | confirmatory, measured (not met) |
| H6 abstention replication | [`H6-abstention-replication.md`](preregistration/H6-abstention-replication.md) | 1, 2, 3 (10-18) | confirmatory, measured |
| H8 verifier fault injection | [`H8-verifier-fault-injection.md`](preregistration/H8-verifier-fault-injection.md) | 1, 2, 3 (10-18) | confirmatory, measured |
| R1 public data (NL2Bash, CLINC150) | [`R1-real-data-benchmarks.md`](preregistration/R1-real-data-benchmarks.md) | 1, 2 (10-22) | confirmatory (own family), measured |
| H7 hybrid scope gate | [`H7-hybrid-scope-gate.md`](preregistration/H7-hybrid-scope-gate.md) | — | postponed (future work) |
| H9 progress ledger | [`H9-progress-ledger.md`](preregistration/H9-progress-ledger.md) | — | dropped (design record) |

See also [`preregistration/README.md`](preregistration/README.md) and
[`preregistration/CITATIONS.md`](preregistration/CITATIONS.md).

## Evaluation map (where the evidence is)

The status of each result is in the README evaluation map. The experiment folders are indexed by
their current path:

| index | what |
|---|---|
| [`../experiments/thesis/INDEX.md`](../experiments/thesis/INDEX.md) | thesis evidence: frozen trees, precursors, preregistrations, exploratory follow-ups |
| [`../experiments/iis/INDEX.md`](../experiments/iis/INDEX.md) | IIS project evidence |
| [`../experiments/archive/INDEX.md`](../experiments/archive/INDEX.md) | archived folders, and the deleted placeholders with their owed evaluations |
| [`EXPERIMENTS.md`](EXPERIMENTS.md), [`../experiments/README.md`](../experiments/README.md) | how experiments are laid out and run |
| [`../experiments/thesis-followup-20261012/RESULTS.md`](../experiments/thesis-followup-20261012/RESULTS.md) | the full follow-up results |
| [`analysis/terminal-state-diagnosis.md`](analysis/terminal-state-diagnosis.md) | why no held-out goal reached `done` |
| [`BUILD_RESULTS.md`](BUILD_RESULTS.md), [`LEARNING_COMPARISON.md`](LEARNING_COMPARISON.md), [`publication/`](publication/) | build results, the learning comparison, the M14 paper |

## Status, history and process

| document | what it is |
|---|---|
| [`ROADMAP.md`](ROADMAP.md), [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md), [`JARVIS_PROGRESS.md`](JARVIS_PROGRESS.md) | plans and readiness |
| [`CHANGELOG.md`](CHANGELOG.md), [`BUILD_JOURNAL.md`](BUILD_JOURNAL.md), [`ERROR_LOG.md`](ERROR_LOG.md) | history and incidents |
| [`TESTING.md`](TESTING.md), [`../CONTRIBUTING.md`](../CONTRIBUTING.md), [`HISTORY_ATTRIBUTION_AUDIT.md`](HISTORY_ATTRIBUTION_AUDIT.md) | how to test and contribute, and the history attribution audit |
