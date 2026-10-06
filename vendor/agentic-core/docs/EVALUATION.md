# EVALUATION

The most important loop in the system. First how the original does it, then the generic version, then the exact sequence.

## 1. Original evaluators (`examples/marketing/backend`)

### Deterministic QA gate — `app/services/agent/review.py`
`review_content(platform, text, expected_price, old_price) -> [ {severity, code, message} ]`:
* `error` (BLOCKING): `empty`, `too_long` over a hard limit (X 280), `price_mismatch` (a stated price that is neither current nor former), `price_invented` (a price when the catalogue has none), `unsupported_discount` (discount words with no `old_price`), `free_delivery_forbidden` (the owner's hard rule), `unsupported_warranty`.
* `warn` (advisory): `too_short`, soft length, banned chars (Reklama5 `*`/`+`), superlatives, scarcity claims, `price_missing`.
* `suggest`: the AI lector's tips (`ai_review`, `run_review_pass(use_ai=True)`), never flip `ok`.
* `review_facts(product)`: campaign-level preconditions copy cannot fix (out of stock, no price) — reported to the human, kept out of the repair loop (`attach_product_facts`).

### Repair — `review.py::gate_and_repair(items, regenerate, rounds=1)`
Regenerate every item with a hard error using the same context plus a corrective note (`_corrective_note`), adopt only when the new draft has STRICTLY fewer hard errors. Never blocks assembly.

### Policy gate — `app/policy/engine.py`
`evaluate_publish`: out-of-stock product blocks, missing price warns, >8 publishes in the last hour blocks, empty content blocks. `evaluate_ad_activation`: budget over cap, >50% increase, no conversion tracking block; <5 conversions warns.

### Eval harness — `app/evals/`
* `scorers.py`: `factual` (reuses `review_content` — "an eval that disagreed with the gate would be worse than none"; an error caps at <0.5), `human_voice`, `specificity`, `length_fit`, `cta`, weights .35/.25/.20/.10/.10; `score_all` caps the overall at 0.4 when `factual` < 0.5; pass = overall ≥ 0.7 AND factual ≥ 0.5.
* `judge.py`: LLM rubric (persuasive, on_brand, human) 0..1, validated schema, cached; a failed judge returns `{}`.
* `runner.py`: `score_output` blends judge at weight 0.3 (deterministic leads); `run_suite(generate_fn)` persists `EvalRun`/`EvalResult` with per-dimension averages and the `COPY_PROMPT_VERSION` so a regression is attributable.
* `seed.py`: cases include temptations (real discount, out of stock, no discount) — "a suite that only tests easy inputs measures nothing".

### Acceptance criteria in the original
A campaign may be sent for approval when `review["ok"]` (no hard error) after repair. It may be published when: not test mode, platform in `live_platforms`, `evaluate_publish.allowed`, claim won, quota not exceeded, operation not already done. Scheduled rows retire only after an ATTEMPT (`deferred` keeps them queued).

## 2. Generic evaluation (`agentic_core/evaluators`)

### Contract — `evaluators/base.py`
`Evaluator(name, fn(result, task, ctx) -> [Issue], weight, replan_codes)`; `evaluate_all(evaluators, result, task, ctx, judge, pass_threshold) -> Verdict`.

Scoring per evaluator: no issues 1.0; warnings `max(0.5, 1 - 0.15·warns)`; errors `max(0, 0.4 - 0.2·(errors-1) - 0.1·warns)`. Overall = weighted mean, **capped at 0.4 when any hard error exists**. Judge (weight 0.3) adjusts the overall but the cap is re-applied — a perfect judge cannot rescue a hard error. `passed = overall ≥ threshold AND no hard error`. `needs_replan` when an error carries a code in the evaluator's `replan_codes`.

### Deterministic checks — `evaluators/deterministic.py`
`not_empty`, `schema`, `length(soft, hard)`, `banned_patterns`, `required_patterns`, `grounded_facts(extract, facts_key)` (the generic "no invented price"), `exit_code`, `expected_state(name, predicate, replan=True)` (the Linux verifier: "service active", "df < 90%").

### LLM-as-a-judge — `evaluators/judge.py`
`make_judge(rubric)` → async `judge(result, task, ctx) -> {scores, note, suggestions} | {}`; structured with one corrective retry; cached by prompt hash (idempotent); suggestions become `suggest` issues.

### Scorer suites — `evaluators/scorers.py`
`ScorerSuite(scorers=[(name, fn, weight)], cap_on="grounded", cap_below=0.5, cap_to=0.4, pass_threshold=0.7)`; generic scorers: `score_grounded(extract)`, `score_prose`, `score_mentions(key)`, `score_length_fit`, `score_forbidden`, `default_suite()`.

### Runner — `evaluators/runner.py`
`run_suite(db, label, generate_fn, suite, judge, prompt_version, agent)` → `EvalRun` with per-dimension averages; `POST /api/evals/run?agent=executor&judge=true`.

### Gate + repair — `evaluators/gate.py`
`gate_and_repair(items, hard_errors, regenerate, rounds)` — the original algorithm, generic keys.

## 3. The exact sequence

```
TASK        Task(kind, brief, input)            orchestrator/service.create_task
  ↓
EXECUTION   executor(task, ctx{attempt})        workflows/engine (Director) | custom executor
            → agents (prompt→provider→validate) | tools (9 gates) | DAG plan
  ↓
RESULT      {success, content|stdout|exit_code|state…, uncertain?, requires_approval?}
  ↓
EVALUATION  evaluate_all(deterministic…, judge?) → Verdict{passed, score, issues, needs_replan}
  ↓
PASS        → require_approval / high risk ? awaiting_approval + ActionProposal : done
FAIL        → classify (result.details / uncertain flag / issue codes)
  ├─ RETRY     transient | hard error, attempts ≤ max_retries
  │            ctx["corrective_note"] = Verdict.corrective_note()  (gate_and_repair pattern)
  ├─ REPLAN    validation | expectation_failed, replans < max_replans
  │            ctx["issues"] → replanner(task, ctx) → ctx["plan"] → EXECUTION again
  ├─ RECONCILE uncertain — never re-run; ActionProposal(escalation:reconcile)
  └─ ESCALATE  policy | auth | capability | unknown | exhausted
               → ActionProposal(escalation:<verdict>), AuditEvent, notify, task.status failed/validation_failed
```
Every step lands in `TaskRun.decisions / evaluation / verdict` and one `AgentStep` per phase (`GET /api/tasks/{id}`).

## 4. Feedback loops and self-correction

| loop | original | core |
|---|---|---|
| in-run repair | `gate_and_repair` with a corrective note | lifecycle RETRY with `corrective_note`; `evaluators/gate.py` |
| replanning | (strategy re-run was manual) | lifecycle REPLAN → `replanner` |
| human corrections → prompts | `Feedback` → nightly `distill_feedback` → `StyleGuide` → `load_style_context` | `memory/feedback.py` → `LearnedRule` → `load_rules_context` injected by `agents/runtime` |
| measured results → prompts | `insights/learned.py` (what the audience rewarded) | application-specific: write a `LearnedRule` or a context-layer doc from your metrics |
| eval trend | `EvalRun.prompt_version` | same |

## 5. Retry conditions, in one table

| condition | who decides | what happens |
|---|---|---|
| provider timeout / 429 / 5xx | `llm/providers.chat` via `classify` | up to 3 attempts, then raise → fallback |
| hard error in the evaluation | `lifecycle` | retry with corrective note, ≤ `max_retries` |
| `expected_state` failed / `replan_codes` | `lifecycle` | replan ≤ `max_replans` |
| tool result `uncertain` | `operations.record`, `dag`, `lifecycle` | block/reconcile, never retry |
| scheduled run failed | `scheduler/scheduled.process_due` | requeue with backoff × attempts, dead-letter after `max_attempts` |
| scheduled run not attempted (dry-run/held/policy/deps) | same | row stays queued (deferral is not an outcome) |
| worker pass crashed | `scheduler/worker` | recorded as `<worker>.failed`; next check re-evaluates "due" |
