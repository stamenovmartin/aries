# ARIES thesis protocol: state-verification feedback

Status: proposed protocol, not a registered study or an experimental result.
Date: 2026-10-03. Language of experimental tasks: English. Macedonian remains frozen.

## Positioning

Title: **The Impact of Structured State Verification on LLM Agent Planning and Reliability**.

ARIES is the experimental platform. The research object is the information supplied to an
LLM after an action, and its effect on subsequent decisions. The contribution is an implemented
mechanism and controlled empirical analysis, not a claim to have invented agent loops,
external verification, reinforcement learning, or a new foundation model.

Research question: Does structured feedback from independent state verification improve
next-action selection and task completion under silent tool failures, and at what inference cost?

H1: Adding independent verification reduces unsupported model completion claims.
H2: Detailed verification improves recovery/next-action decisions versus a binary verdict.
H3: Structured versus textual presentations of IDENTICAL facts differ in performance; this
is a two-sided comparison, with no improvement assumed in advance.

## Related work and limits on novelty

- ReAct: interleaved reasoning, action and observation: https://arxiv.org/abs/2210.03629
- CRITIC: external tool feedback for correction: https://arxiv.org/abs/2305.11738
- Reflexion: linguistic feedback and episodic memory without weight updates:
  https://arxiv.org/abs/2303.11366
- OSWorld: real-computer tasks with execution-based evaluation:
  https://arxiv.org/abs/2404.07972
- tau-bench: final-state evaluation and repeated-trial reliability:
  https://arxiv.org/abs/2406.12045
- ReliabilityBench also studies controlled tool failures; fault injection alone is not a
  novelty claim: https://arxiv.org/abs/2601.06112

Potentially distinctive angle to investigate: discrepancies between a tool's success report
and independently observed effects, including explicitly UNVERIFIABLE outcomes, with feedback
content separated from representation. This is a candidate contribution, not established novelty.

## Conditions (same model, tools, permissions, budgets and completion guard)

| ID | Planner receives after an action | Primary contrast |
|---|---|---|
| A tool_only | Raw tool output; opaque evidence handles, no verdict | Reference |
| B binary | A plus VERIFIED / FAILED / UNVERIFIABLE | B vs A: verification information |
| C structured | A plus verdict, expected/observed state and error code | C vs B: detailed information |
| D text | Exactly C's facts rendered as labeled text | C vs D: representation |

Use feedback.py as an OFFLINE projection building block. It is NOT wired into production.
Both C and D retain identical raw tool output and evidence handles. The detailed packet is
rendered reversibly; content-equivalence is asserted by the focused smoke test. Record actual
token counts: equal content does not imply equal tokens. Do not truncate one condition's facts
to match tokens; use a sufficient common context budget and report overhead.

Keep safety and approval gates enabled in every condition. Never turn off USER-memory
preservation or permissions to create an all-off baseline. Use disposable synthetic state.
All-off/all-on product evaluations answer a DIFFERENT question and are supplemental only.

The completion API must accept equally available opaque reference handles in all arms and
resolve them against the internal verifier. The planner must not be told it must name hidden
IDs. Internal safety checks remain unchanged. Their binary completion rejection is shared
feedback in every arm and must be recorded; A means no PER-STEP verifier feedback, not no
verification signal of any kind. This limits interpretation and belongs in the paper.

## Two complementary experiments

1. Matched decision replay: freeze real action traces and deliver A/B/C/D at the same decision
   boundary. Ask the same model for its next structured action. Judge against independently
   authored sets of acceptable actions, not one exact reference plan. Useful for isolating
   decision effects; cannot establish executed-goal success.
2. Closed-loop execution: run the real agent loop with state reset for each trial, including
   injected faults reached inside the executor. An independent final-state oracle evaluates
   the result. This establishes task-level effects; include fault-reached and planner-exposed
   markers to distinguish cases where a hard guard stops before the LLM can act again.

If VERIFICATION_FAILED always forces a hard stop, do not claim LLM recovery on that branch.
Measure detection/safe stopping separately. Study replanning with permitted alternative-route
errors and in replay; never weaken production policy to manufacture recovery opportunities.

## Fixtures, repetitions and leakage prevention

Audit the existing 90 English goals rather than assuming all exercise the LLM. Tag each path:
deterministic, LLM-planned, component-only. Thesis primary results require LLM exposure.
Use existing exposed cases for development; author held-out task families/compositions for
confirmatory evaluation, freeze their hashes and acceptable outcomes before measuring.
Do not call a random split of already inspected cases unseen generalization.

Plan a minimum three independent repetitions per eligible held-out goal per condition, with
paired initial states and fault schedules. Counterbalance condition order. Freeze prompt,
model identifier/settings, tool catalogue, routing, memory snapshot, retrieval examples and
step/token limits. Do not learn from test runs between arms. If too costly, reduce declared
scope BEFORE the scored run and document it; do not silently reduce repetitions after results.

No faults that require unshipped production surfaces: wrong gamma ramp is currently a gap,
not covered by a different display mechanism. App/browser tests need controlled owned state.

## Outcomes and denominators

| Outcome | Numerator / denominator |
|---|---|
| End-state completion | Independent oracle met / valid executed task trials |
| Unsupported model claim | Model finish claims with unmet oracle / valid task trials |
| Conditional unsupported claim | Unsupported model claims / all model finish claims |
| User-visible false success | User-visible success with unmet oracle / valid task trials |
| Completed recovery | Goal completed after reached fault / reached-fault trials |
| Safe stop | Policy-appropriate stop without false success / reached-fault trials |
| Appropriate next action | Decision in acceptable set / valid replay decisions |
| Verification coverage | Actually checked eligible steps / verifier-eligible executed steps |

Also report all assigned trials, skips with causes, oracle failures, verifier false positives
and false negatives, latency p50/p95, model calls, tokens, step counts and cost where available.
Unknown denominators or zero denominators yield null, not 0% or 100%. Do not count a refusal as
completed recovery. Runtime guard suppression and model reasoning are separate outcomes.

Report paired differences and 95% confidence intervals, resampling by goal/family rather than
treating repeated trials of one goal as independent tasks. Declare primary contrasts B-A and
C-B; C-D is the representation study. Retain every run, failed API call and exclusion reason.
For a small single-repeat paired binary sample, an exact McNemar analysis is an option; do not
apply it naively to dependent repetitions. Interpret uncertainty rather than chasing p-values.

## Required result provenance

Store protocol/fixture/oracle/code hashes; UTC start/end; task and trial IDs; actual runtime
condition (not just harness environment); model/settings; initial-state/fault identifiers;
planner exposure; raw and presented observation digests; decisions; end-state oracle; model
claim vs user-visible claim; stop reason; tokens and latency. Include raw counts beside rates.
Freeze protocol version before confirmatory measurement; amendments create a new version.

## Admission abstract

This thesis investigates the effect of structured state-verification feedback on the planning
and reliability of large language model agents. ARIES serves as an experimental platform
integrating planning, tool execution, independent verification and bounded replanning. The
study compares tool outputs, binary verification, structured observations and textual
observations containing equivalent facts. Evaluation uses multi-step tasks and controlled
silent tool failures, with an independent assessment of final system state. The analysis
examines task completion, unsupported success claims, recovery, next-action selection and
inference cost to identify the benefits and limitations of verification-informed orchestration.

## Results

No thesis results collected by this package. Historical product measurements are not results
for these four conditions. Do not copy them into a thesis comparison table.
