# Handoff to the main thread / the reviewing agent

Update: run_loop.py now connects the four-condition adapter to production agent.run,
Decision parsing, file execution/verification/completion and a real local LLM in a scratch
process. See README.md and runs/ for actual evidence. This supersedes the earlier statement
that this directory has only an offline building block; it does not deploy the adapter into
the live API planner or complete the broader benchmark. Static findings below describe the
earlier inspected source; the reviewing agent subsequently reported production fixes in COORDINATION.md.

This side conversation owns only this new directory. No production file was edited,
no deployment or measurement was started, no shared git index was touched.

## Static inspection on 2026-10-03

The platform already has a bounded agent loop, separate execution_result/verification,
evidence records, a planner context builder and an English 90-goal harness. That is enough
infrastructure for the proposed study, but NOT enough to claim the experiment is implemented.

1. agent_planner.context now uses ARIES_VERIFY_FEEDBACK, but its off branch removes
   verification_status/evidence_refs while retaining observation. agent.run overwrites
   observation with verification.data and evidence_id after verification. Check this leak
   using canary evidence in a prompt test; changing only the flag is not a clean ablation.
2. agent.completion requires real verified evidence IDs. Removing all planner-visible IDs
   creates a mechanically disadvantaged control. Keep opaque handles in ALL conditions;
   evaluate them internally. Adjust shared planner instructions consistently in all arms.
3. Audit other routes for leakage: goal_progress, state_snapshot, completion_feedback,
   execution_status, nested tool output, memories and retrieved successful traces. Some
   state information is intentionally shared: document it, don't call that arm blind.
4. run.py in the current suite sets recovered=detected for component faults. That is safe
   detection, not completed recovery. Keep historical data and its definition; introduce
   separate fields for the new study rather than relabeling historical runs.
5. Fault injection is in-process capability evaluation, not a full agent execution. Add
   isolated full-loop fixtures (scratch DB/owned resources) and explicit reached/exposed
   markers. Never patch production or bypass approvals for a fault experiment.
6. Confirm actual LLM planner calls: deterministic file/system paths cannot establish an
   improvement in LLM planning. Report them separately, even if the task has several steps.

## Suggested integration ownership

Main planner owner: integrate a condition selector in the context builder using separate
execution_result and verifier payload; propagate the EFFECTIVE condition to traces. Reuse
feedback.py or an equivalent production adapter after review. Do not import eval modules
into production without a deliberate packaging decision. Add prompt canary/content tests.

Main executor owner: make opaque references available without revealing verdicts, preserve
completion/approval checks, and capture model finish claims separately from guarded replies.
Add isolated full-loop failure cases, without weakening VERIFICATION_FAILED stop policy.

Main evaluation owner: implement matched decision replay and full-loop runners with reset,
paired fault schedules, actual runtime configuration, independently authored oracles and
separate stop/recovery outcomes. Adapt existing suite; preserve its historical results.

Research package: run `python3 eval/research_feedback/smoke.py` for pure adapter checks.
The package is a prepared protocol and offline building block, not a live implementation.

## Completion criteria

- Four prompt variants demonstrably differ only in declared content/representation.
- No verdict canary reaches A via another prompt field; C/D contain identical facts.
- All arms can submit valid completion references with the same safeguards.
- At least one replay and one closed-loop fault smoke exercise an actual LLM decision.
- Independent oracle disagrees with a deliberately false tool-success report in a control.
- Saved run provenance and denominators validate; held-out fixtures are frozen before use.
- Only then start confirmatory runs and update thesis result tables from their artifacts.


## Controlled screen adapter (2026-10-04 Europe/Skopje)

`run_loop.py --case vf-09 --controlled-screen --fixture-smoke-only` exercises
an owned synthetic PNG scene, real GdkPixbuf decoding, English Tesseract OCR,
executor return, verifier, and an independent authored-file predicate. The
five screen case IDs are supported, with two distinct frame IDs for vf-11.
Neither portal access, session-lock override, physical desktop capture nor
personal window inspection occurs. Omitting `--controlled-screen` preserves
native preflight behaviour. Removing `--fixture-smoke-only` selects the existing
real-agent/local-LLM path; this batch has NOT run that path for screen cases.

This is explicitly a returned-artifact intervention after capture defences,
NOT the original native portal injection. Native capture/OCR full-path validity
cannot be inferred from these checks. Capture uses the production PNG verifier;
OCR uses a fixture-specific fresh-OCR check instead of querying live window titles.
`controlled_screen_checks.json` records the component smoke denominators and
source-stable run artifacts. Its scores are not goal-success measurements.

A correct artifact alone cannot establish a correct final visual description.
The oracle returns false for a missing/corrupt required observation and unknown
for a valid observation whose final semantics are not adjudicated. Consequently
`comparison_admission=false` and `valid_for_comparison=false` are enforced for
this adapter until that methodological gap is resolved. Do not replace the
native 10/15 historical preflight result with a misleading 15/15 study-ready claim.

Live B1/B2 was active during construction. No concurrent LLM smoke, 600-run
study, production deployment, or completion of the main build is claimed.
