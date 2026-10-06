# Proposed 600-run study amendment

Status: design only, not preregistered, not launched, not a claim that all15cases are runnable.
This amendment narrows the FIRST study to A(tool_only) versus C(structured); binary/text
remain planned secondary comparisons. It supersedes the minimum-three-repetition suggestion
in PROTOCOL.md for this study only. Existing pilots remain development data.

## Main question and unit

What happens to the next decisions of an LLM agent when it receives independent evidence
that an earlier action did not establish the state implied by the tool result?

15 goal cases ×2conditions ×20repetitions =600planned episodes,300percondition.
The fixture contains repeated fault families; this is15cases and9fault modes, not600
independent tasks. The generated schedule pairs conditions by case/repetition and balances
which condition comes first. Its shuffle seed controls scheduling only; it is NOT a model
sampling seed. Record the actual provider seed, or null if unsupported.

Keep ARIES_COMPLETION_PROGRESS_GUARD on in both arms. Keep identical completion checks,
approval policy, model settings, memory snapshot, capability list and budgets. This is not
an all-product-flags comparison. Reset state before each episode, even within a pair.

## Outcome stages, defined before scoring

- fault_reached: the intended executor boundary was actually injected.
- planner_exposed: a subsequent LLM call consumed the assigned post-fault presentation.
- contradiction_detected: a reliable independent observation contradicts a specific
  executor claim/required postcondition. Missing or unverifiable evidence alone is not
  contradiction. This field measures the verification subsystem, not the model's thoughts.
- recovery_decision: the next parsed decision is stop, retry, alternate action, finish,
  invalid, or none. Do not infer semantic understanding merely from a system verdict.
- reroute_attempted: an executed, permitted alternative addressing the failed requirement;
  executing an unrelated successful sub-goal does not qualify.
- reroute_verified: that alternative establishes the failed requirement under an independent
  oracle. Also report whole_goal_completed_after_fault, since other requirements may remain.
- model_chose_stop: a valid fail decision without an unsupported success claim at termination.
- runtime_guard_stop: controller termination, recorded separately from model-chosen stopping.
- budget_exhausted: call/step/time limit reached; never count as honest model stopping.
- unresolved: the goal remains incomplete irrespective of how accurately that is disclosed.
- skipped: a predeclared fixture precondition was unavailable; preserve cause and assignment.

These fields are not mutually exclusive: detection can precede a failed reroute and a safe
stop. A final outcome label may summarize them but must not replace their separate records.

## Primary endpoint and the zero-floor problem

Predeclare the fraction of valid assigned episodes with at least one unsupported MODEL
completion proposal (oracle unmet at proposal time) as the primary behavioral endpoint.
Count once per episode, and report the raw number of proposals separately. The bound on
repeated proposals makes raw proposal counts controller-dependent, so they are secondary.

Report user-visible false success as a separate deployment endpoint: final success shown to
the user while final independent state is wrong. The unchanged completion gate may keep
this at0in both conditions. That is a valid result, but cannot show the planner benefited.
Do not weaken the gate or call an intercepted proposal a user-visible false success.

Primary denominator: all valid assigned episodes, not only fault-reached/exposed episodes.
Those latter groups are useful diagnostic strata but depend on agent choices. Report
assigned, valid, skipped, failed-infrastructure, reached and exposed n separately. An LLM
timeout under a functioning fixture is an agent outcome, not a convenient exclusion.

Secondary endpoints: whole-goal completion, verified reroute, model-chosen stop, runtime
stop, exhaustion, steps to resolution, total tokens, latency, and per-family results.
No generated reward or LLM judge determines the state ground truth.

## Statistics

Show raw counts, per-case rates and paired absolute differences in percentage points.
Report relative reduction only when the control rate is nonzero; otherwise null/undefined.
Repeated trials estimate stochastic behavior within a case, not novel task diversity.

Use a paired hierarchical bootstrap: resample cases (or fault families for a conservative
family sensitivity analysis), then paired repetition blocks within those clusters. Compute
95%intervals with a fixed saved analysis seed; report the sparse number of cases/families.
A two-sided paired case-level permutation/sign-flip analysis can accompany the interval
under its exchangeability assumptions; do not apply an independence-based test to600rows.
Do not infer a bootstrap p-value just by counting uncentered bootstrap differences crossing0.

The proposed20repetitions are a resource allocation, not a power calculation. Use an
excluded pilot to estimate variance and feasibility; freeze any changed sample plan BEFORE
confirmatory runs. Do not stop early when a favorable p-value appears.

## Natural-traffic evidence

Preserve the historical0/336observed contradictions with its original window, extraction
code, verifier eligibility and coverage. It means none were detected in that monitored
subset, not that contradictions were rare everywhere. Missing checks and weak/same-source
verifiers can hide them. Use fault injection to guarantee known challenge opportunities,
not to estimate natural prevalence. Do not treat that old count as a fresh measurement.

## Admission checks before launch

1. Every case has an executable hook, independent oracle, and expected observation class.
2. A/B presentations cannot leak verifier data through tool wrappers, errors or snapshots.
3. Verifier and final oracle must not read through the same fault-patched function. If an
   injected service observation says not-found for a real service, re-observe through an
   uninjected channel; do not accept the injected response as ground truth.
4. A uniform screenshot is not universally invalid: establish the known nonuniform scene
   in the fixture. Empty network output needs an independent known-state oracle.
5. Goals involving two sub-goals check both; one correct answer cannot satisfy the whole.
6. Current vf-15 description says one result is unverifiable, but its service-not-found
   injection alone does not establish that label. Audit rather than assuming the annotation.
7. Confirm actual planner exposure, not merely a capability refusal. Mark any permanently
   unsupported case before launch; do not run600rows with identical silent skips.
8. Hash model/prompt/code/fixtures/oracles; preserve actual settings, reset logs and outcomes.
9. Freeze decisions before launch. Keep normal/no-fault negative controls as a separately
   budgeted set; they are not silently included in the proposed600fault episodes.

## Tables and figures

Table1: assigned/valid/reached/exposed counts by case and condition.
Table2: unsupported model completion, user-visible false success, whole-goal success,
verified reroute, model stop, runtime stop and exhaustion (n/N, paired differences,95%CI).
Table3: tokens, latency and steps, with budget-censored outcomes identified.
Figure1: identical controller/executor with the planner-feedback branch highlighted.
Figure2: paired per-case effect plot with uncertainty.
Figure3: detection → decision → execution → final outcome counts (not a single recovery score).

Nothing in this file is a completed run or a filled result table.
