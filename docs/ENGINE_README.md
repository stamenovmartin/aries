# agentic-orchestration-export

A complete, reusable export of the orchestration architecture of the **Insomnia Marketing OS** — an agentic system that researches, plans, writes, reviews, repairs, asks a human for approval over Telegram/WhatsApp, and executes side effects idempotently — isolated into a domain-neutral engine (`agentic_core`) with the original marketing implementation kept beside it for reference.

```
agentic-orchestration-export/
├── README.md                     ← this file
├── MIGRATION_GUIDE.md            ← how to reuse the engine for an Agentic Linux Operating Environment
├── .env.example                  ← every configuration key, no secrets
├── Dockerfile · docker-compose.yml · requirements.txt · pyproject.toml
├── scripts/                      start.sh · run_tests.sh · init_db.py · init-db.sql
├── agentic-core/                 ← THE REUSABLE ENGINE (Python package `agentic_core`)
│   ├── agentic_core/
│   │   ├── orchestrator/  Director graph · resumable DAG · idempotent operations · error taxonomy
│   │   │                  state machines · retry · lifecycle (TASK→…→RETRY/REPLAN/ESCALATE) · task service
│   │   ├── router/        rule-based → LLM-based → fallback routing, confidence, needs_human
│   │   ├── agents/        AgentSpec (prompt, schemas, tools, permissions, model, termination), registry, run loop, roster
│   │   ├── llm/           providers (cli the reviewing agent/codex · ollama · openai-compatible · template), structured output, cache, telemetry
│   │   ├── tools/         ToolSpec registry · the 9-gate guarded call · capability connectors · built-ins
│   │   ├── evaluators/    deterministic checks · weighted scorers · LLM judge · gate_and_repair · eval runner
│   │   ├── workflows/     declarative NodeSpec/WorkflowSpec run through the Director
│   │   ├── memory/        context layer · vector memory (RAG) · feedback→rules · chat history · checkpoints · recovery
│   │   ├── scheduler/     in-process workers · due-queue (quiet hours, backoff, dead-letter) · triggers · run-now path
│   │   ├── security/      RBAC · principals/tokens · credentials-at-rest · secret store · environments · sandbox · approvals · policy
│   │   ├── observability/ JSON logs + 3-layer redaction · correlation ids · metrics (null≠0) · immutable audit · agent trace
│   │   ├── database/      SQLAlchemy models · engine · schema bootstrap · drop_all guard
│   │   ├── config/        settings (env) · runtime switches (file)
│   │   └── api/           FastAPI: correlation → auth → audit middleware; tasks, proposals, execution, scheduler, memory, evals, health
│   ├── tests/             13 test files (unit + integration + agent + evaluator + API) — `python tests/run_tests.py`
│   └── docs/              ARCHITECTURE · DIAGRAM (Mermaid) · AGENTS · ORCHESTRATION · EVALUATION · MEMORY · TOOLS · SECURITY · DEPLOYMENT · TESTING
└── examples/
    ├── marketing/         the ORIGINAL backend (secrets/data stripped) + README mapping every module to the core
    └── linux_agent/       a starter Agentic Linux OE on the engine: inspector/planner/verifier agents, Linux tools,
                           inspect→plan→execute(DAG)→verify→repair workflow, disk/service triggers, autopilot, test
```

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env                                 # sqlite · template provider · DRY_RUN=true
scripts/run_tests.sh                                 # 13 core test files + the Linux example
AGENTIC_APP=examples.linux_agent scripts/start.sh    # http://localhost:8000/docs
```
Docker: `docker compose up -d --build` (needs `POSTGRES_PASSWORD` in `.env`).

## What the engine guarantees (all pinned by tests)

* **The AI proposes; a human approves; an executor acts** — `ActionProposal`/`ApprovalRequest`, consent ≠ execution.
* **Credentials are not consent** — `DRY_RUN` and `LIVE_TOOLS` both have to open; high-risk tools also need an approved proposal.
* **Not all failures are equal** — transient → retry, validation → replan, uncertain → reconcile (never re-run), policy/unknown → escalate.
* **At-most-once side effects** — `sent` is persisted before a call; a repeated payload returns the recorded result.
* **Plans resume, never restart** — a multi-step plan skips succeeded steps and blocks on an uncertain one.
* **State machines with import-time invariants** — a cancelled task cannot execute; a failure never becomes success; partial is resumable, never silently done; an edit revokes an approval.
* **Deterministic evaluation is the backbone; the LLM judge is a second opinion** that can lower but never override a hard error.
* **Every agent degrades to a deterministic fallback** so the pipeline never hard-fails (strict mode raises instead).
* **Workers are paced by the last recorded run**, so a missed cycle is caught up, not skipped.
* **Honest observability** — `null` with a reason instead of 0; tokens/cost only when the provider returns them; health labels its probe depth.

## Read next

* `agentic-core/docs/ARCHITECTURE.md` — the original system as it runs, and the mapping to the core.
* `MIGRATION_GUIDE.md` — reusing it for Linux tasks (agents execute, inspect, evaluate, repair/retry).
* `examples/marketing/README.md` — how to run the original and where each mechanism lives in it.

## Secrets

None. Every credential in `.env.example` is empty; the marketing copy had its `.env`, data directory, service-account key, uploads, screenshots and context files removed, and its baked-in default database password replaced. A scan for token shapes (`EAA…`, `sk-…`, `gsk_…`, Telegram bot tokens, PEM keys) over the export is clean.
