# Connected research pathway

Native-case integration update (2026-10-03): `--case vf-01` through `vf-15` dispatch
the original focused fixture. Ten service/network cases have native read-only adapters;
the five screen cases are explicit precondition skips until an owned known scene is
provided. `case_coverage.json` records the observed preflight, not task success.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python eval/research_feedback/run_loop.py --case vf-01 --condition structured
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python eval/research_feedback/run_loop.py --case vf-05 --condition tool_only
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python eval/research_feedback/audit_cases.py
```

For native cases, fault shims are installed inside the executor only and restored
before the production verifier and external oracle run. The oracle compares actual
returned observation data with an uninjected re-read; it never accepts a verifier's
boolean as ground truth. A verifier can itself collect the requested observation,
so its data is considered but independently checked. CPU/storage probes use metric
identity/presence because exact instantaneous readings vary: this is a weaker
secondary oracle and must not support a numerical-accuracy claim.

Fault-reached, planner-exposed, post-action-feedback-exposed, capability refusal,
contradiction, model stop and runtime stop are separate fields. A task succeeding
despite an injected command response is NOT automatically completed recovery.
No valid alternate-capability repair has yet been independently adjudicated.
The preflight does not prove that a later fault is reached or changes the state;
the native pilot demonstrates why those distinctions matter.

Run from the repository root with the existing local inference service available:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python eval/research_feedback/run_loop.py --condition structured --fault none
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python eval/research_feedback/run_loop.py --condition structured --fault stale_read
```

`--condition tool_only|binary|structured|text` selects the four feedback presentations.
`--max-steps` (default 3) and `--timeout` (default 120 seconds) bound a run.
The normal goal reads two owned files. The fault substitutes a stale tool result once;
the real verifier re-reads the actual file. Artifacts go to `runs/<timestamp>-<id>/result.json`.

Connected, rather than simulated:

1. The real local LLM produces each decision via ARIES local_structured and its generation schema.
2. The real Decision parser validates it.
3. The production agent.run executes its bounded loop and persists a real WorkspaceGoal row.
4. The real file.read capability and verifier run on owned files with existing policy checks.
5. The selected feedback adapter builds the next prompt from separately stored results/evidence.
6. The unchanged production completion guard rechecks proposed success.
7. An external byte/content oracle scores the trace independently of verifier status.

Isolation: fresh scratch database and two synthetic files, removed after the run; only
read capabilities exposed; no production source patch, service restart, cloud call or
production database modification by this runner. The existing inference gateway may record
its normal usage accounting. Global replacements exist only in this separate Python process
and are restored in finally. The prompt adapter is experimental, not the deployed API planner.

No scored thesis result is implied. This connects all four presentations to one real loop;
the current integration scenario is two file reads, not the 90-task suite or all desktop fault
types. A single run proves a path executes, not that any condition improves performance.
Artifacts distinguish model finish claims, user-visible success, completed recovery,
model-chosen stop and exhaustion. Source hashes before/after expose concurrent code drift.

Next main-thread integration: adopt this bounded adapter or its logic for the focused fixture
the reviewing agent handed over in experiments/verification-feedback; preserve the protocol's equal handles,
no verifier leakage, independent oracles and fixed policies. Finish the broader fault coverage
and freeze held-out tasks before comparative runs. See PROTOCOL.md and INTEGRATION.md.
