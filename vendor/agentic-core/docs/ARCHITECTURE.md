# ARCHITECTURE

This document describes two things, in this order:

1. **How the existing Insomnia Marketing OS backend works** (`examples/marketing/backend`), preserved exactly, with file references.
2. **What was isolated into `agentic_core`** and how each original module maps to a generic one.

The Mermaid diagram of the reusable engine is in [DIAGRAM.md](DIAGRAM.md).

---

## 1. The original system (as it runs today)

The marketing backend is a FastAPI application (`backend/app/main.py`) with four layers around one database:

| Layer | Original location | What it does |
|---|---|---|
| API | `app/api/*.py` (44 route modules) | Thin routes; every state change goes through the same service the workers and the chat use |
| Orchestration | `app/orchestration/{graph,campaign,pipeline,router}.py` | A **Director** that routes a graph of agents by evaluating gates against the live context |
| Execution | `app/execution/{errors,operations,dag,audit,plans}.py` | Failure taxonomy, idempotent side effects, resumable multi-step plans, immutable audit |
| Domain/Policy | `app/domain/states.py`, `app/policy/{engine,states}.py` | State machines with import-time invariants; deterministic policy gate |
| Agents | `app/services/agent/*` + `app/services/ai/*` | research → strategy → copy → review → repair, all through one provider layer with a deterministic template fallback |
| Evaluation | `app/services/agent/review.py`, `app/evals/{scorers,judge,runner,seed}.py` | Deterministic QA gate (blocking), LLM lector (advisory), eval harness with weighted scorers + LLM judge |
| Memory | `app/services/context_layer`, `app/services/memory`, `app/services/agent/learning.py`, `ChatMessage` | Shared context files (short-term), vector RAG (long-term), feedback → StyleGuide distillation, chat history |
| Scheduling | `app/services/{scheduler_worker,scheduling,learning_scheduler,data_worker,telegram_worker,metrics_worker,triggers}.py`, `app/services/autopilot/*` | In-process asyncio workers paced by the last recorded run; a due-queue with quiet hours/caps/backoff; event triggers; autopilot |
| Approval | `app/services/proposals`, `app/services/channels.py`, `app/services/{telegram,whatsapp}`, `app/services/agent/dispatch.py` | Typed ActionProposals; approval over Telegram/WhatsApp; channel-agnostic inbound dispatcher |
| Tools/Connectors | `app/connectors/*`, `app/compilers/*`, `app/services/posting/*`, `app/services/agent/workspace.py` | Capability-declaring connectors, intent→native compilers, the cross-poster with every gate, the chat's action registry |
| Security | `app/core/{permissions,principal,crypto,tenancy,environments,dbguard}.py`, `app/services/connections/store.py` | RBAC route table, principals, credentials-at-rest, tenant isolation in the ORM, environment gate, drop-guard, secret store |
| Observability | `app/core/{logging_setup,correlation,metrics_registry}.py`, `app/execution/audit.py`, `app/services/agent/trace.py`, `app/services/ai/telemetry.py`, `app/api/health.py` | JSON logs with 3-layer redaction, request ids, honest metrics (null ≠ 0), immutable audit, per-agent trace, provider telemetry, component health |

### 1.1 The request that defines the system

```
POST /api/agent/run {brief, product_id?, platform_ids?}
  └─ services/agent/__init__.py::assemble_campaign
       ├─ orchestration/pipeline.py::run_agent_phase      (Director.execute over
       │     research → competitor → strategy → memory)     gated nodes; every
       │                                                     decision recorded)
       ├─ platform selection (strategy decides; explicit caller choice wins)
       ├─ learned style (StyleGuide) + measured findings + account voice → prompt
       ├─ Director.execute over copy → review → repair
       │     copy   : one generation per platform, concurrent (asyncio.gather)
       │     review : review.py deterministic checks (+ AI lector, advisory)
       │     repair : gate=review found HARD errors → gate_and_repair regenerates
       │              with a corrective note; adopts only strictly better drafts
       ├─ persist Campaign + CampaignTarget rows; trace.record per agent
       └─ request_campaign_approval → Telegram/WhatsApp buttons
                └─ dispatch.py: approve / reject(+reason→Feedback) / edit / schedule
                      └─ posting/__init__.py::publish_campaign
                           test-mode → live gate → policy → atomic claim →
                           compile → classifieds quota → idempotent op (begin/
                           mark_sent) → gather(connectors) → record → rollup
```

### 1.2 The properties the original code insists on (kept verbatim in the core)

* **The AI proposes; it does not act.** Anything consequential is an `ActionProposal` a human approves; approval records consent, a separate executor acts (`proposals/__init__.py`).
* **Credentials are not consent.** `posting_test_mode` (dry-run) and `live_platforms` (an explicit allowlist) both have to open before anything reaches the world (`posting/__init__.py::is_live`, `api/environment.py`).
* **Not all failures are the same.** `execution/errors.py`: only TRANSIENT retries blindly; UNCERTAIN reconciles first; VALIDATION is fixed; POLICY/AUTH go to a human.
* **At-most-once side effects, by construction.** `execution/operations.py` persists `sent` BEFORE the call, and `begin()` answers `done`/`reconcile`/`execute` on the idempotency key.
* **Plans resume, never restart.** `execution/dag.py` skips succeeded steps and blocks on an uncertain one.
* **State machines with invariants checked at import.** `domain/states.py`: cancelled never publishes; a failure never becomes success; partial is resumable but never silently complete; an edit to approved content revokes the approval.
* **Deterministic checks are the backbone; the model is a second opinion.** `review.py` hard errors block; the AI lector only suggests. `evals/scorers.py` caps the overall score when the factual scorer fails.
* **Every agent degrades to a deterministic template** so the pipeline never hard-fails; strict mode (`require_ai`) raises instead.
* **Workers are paced by the last recorded run, not a timer**, so a missed cycle is caught up, not skipped (`data_worker.py`, `learning_scheduler.py`, `autopilot/loop.py`).
* **Honest observability**: a metric with no observation is `null` with a reason, never 0; tokens/cost are `null` when the provider does not return them; health says which probe depth produced each answer.
* **Nothing may break its caller**: audit lines, trace notes, telemetry and log formatting never raise.

---

## 2. What was isolated into `agentic_core`

The engine keeps the code shape and, where possible, the code itself. Every module docstring names the file it came from. The vocabulary changed from marketing to work:

| Marketing word | Core word |
|---|---|
| Campaign | Task |
| CampaignTarget (per platform) | a step / tool call of the task |
| product facts (price, stock) | `ctx["facts"]` given to evaluators |
| platform (Facebook, Reklama5…) | tool / connector target |
| publish | execute a side-effecting tool |
| copywriter / strategist / researcher / reviewer | executor / planner / researcher / reviewer (+ repairer, judge, distiller, assistant, router) |
| StyleGuide | LearnedRule (per scope) |
| pending_approval → approved → publishing → published/partial | awaiting_approval → approved → executing → done/partially_done |

### 2.1 Package map

```
agentic_core/
  config/        settings.py (env)            runtime.py (file-backed switches)
  database/      base.py, models.py, migrate.py, guard.py (drop_all refusal)
  orchestrator/  graph.py     Director + AgentNode (+ optional parallel levels)
                 dag.py       resumable ExecutionPlan/Step executor + reconcile_step
                 operations.py idempotent ExecutionOperation begin/mark_sent/record
                 errors.py    ErrorClass + classify + ACTION table
                 states.py    TaskState/ExecutionState + 4 invariants
                 retry.py     with_retry(policy) — classified retries
                 lifecycle.py run_cycle: TASK→EXECUTION→RESULT→EVALUATION→PASS/FAIL→RETRY/REPLAN/ESCALATE
                 service.py   create/delegate/edit/approve/reject/cancel tasks
  router/        rules.py (keyword rules + HUMAN_WORDS) · llm.py · router.py (rules→LLM→fallback, confidence)
  agents/        base.py (AgentSpec) · registry.py · runtime.py (prompt→provider→validate→tool loop) · builtin.py (roster)
  llm/           providers.py (cli/ollama/openai/template) · structured.py · cache.py · telemetry.py
  tools/         base.py (ToolSpec: schema, permission, risk, side_effect) · registry.py · calling.py (9 gates) · connectors.py · builtin.py
  evaluators/    base.py (Evaluator, Verdict, evaluate_all) · deterministic.py · scorers.py · judge.py · gate.py · runner.py
  workflows/     spec.py (NodeSpec/WorkflowSpec/gates) · engine.py (→ Director) · examples.py
  memory/        context_layer.py · vector.py · feedback.py · chat_history.py · checkpoints.py · recovery.py
  scheduler/     worker.py · registry.py · scheduled.py (due-queue) · queue.py (run_task_now, register_kind) · triggers.py · builtin.py
  security/      permissions.py · principal.py · crypto.py · secrets_store.py · environments.py · sandbox.py · approvals.py · policy.py
  observability/ logging_setup.py · correlation.py · metrics.py · audit.py · trace.py
  api/           main.py (middleware order) · middleware.py · routes.py · health.py
```

### 2.2 Data flow of one task in the core

```
POST /api/tasks {kind, title, brief, run_now}
  ├─ orchestrator/service.create_task → router.route (rules → LLM → fallback) → Task(draft)
  └─ scheduler/queue.run_task_now
       ├─ handler_for(kind)  (register_kind: workflow | executor, evaluators, judge, replanner, policy)
       ├─ dependencies_met (depends_on)
       └─ orchestrator/lifecycle.run_cycle
            ├─ EXECUTION: workflows/engine (Director over NodeSpecs → agents/tools) or a custom executor
            ├─ EVALUATION: evaluators.evaluate_all (deterministic + optional judge) → Verdict
            ├─ VERDICT: pass | retry(corrective note) | replan(planner re-run) | reconcile | escalate
            └─ records: TaskRun(decisions, evaluation, verdict), AgentStep per phase,
                        AutomationLog line, AuditEvent on escalation, ActionProposal for a human
```

A side-effecting tool inside any of that goes through `tools/calling.call_tool`: permission → schema → dry-run → live gate → policy → approval → idempotency → call → record.

### 2.3 What is deliberately NOT in the core

* Anything that knows a product, a platform, a price, or Macedonian copy — see `examples/marketing`.
* Multi-tenancy (`app/core/tenancy.py`). The engine is single-tenant; the original's ORM-level isolation is documented in SECURITY.md as the pattern to re-add.
* Alembic history. The engine ships `create_all`; `database/migrate.py` says where `alembic upgrade head` goes.
* The Next.js dashboard. The API is the contract.
