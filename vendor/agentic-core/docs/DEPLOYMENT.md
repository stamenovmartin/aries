# DEPLOYMENT

## 1. Run locally (no Docker)

```bash
cd agentic-orchestration-export
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # defaults: sqlite, template provider, dry-run
scripts/start.sh                # → http://localhost:8000/docs
```
Optional: `AGENTIC_APP=examples.linux_agent` in `.env` loads the Linux starter (its agents, tools, task kinds, triggers and autopilot).

Smoke:
```bash
curl -s localhost:8000/api/health | python -m json.tool
curl -s -X POST localhost:8000/api/tasks -H 'content-type: application/json' \
  -d '{"kind":"generic","title":"hello","brief":"write a note","run_now":true}'
curl -s localhost:8000/api/tasks/1
```
Note: the `generic` kind needs a handler — the test suite registers one; in your app call `register_kind("generic", workflow="plan_execute_verify", evaluators=[...])` (see `examples/linux_agent/workflow.py`).

## 2. Docker

```bash
cp .env.example .env && echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
docker compose up -d --build
docker compose logs -f api
```
* `postgres` (loopback-only port), `api` (8000). The API creates the schema on boot (`scripts/init_db.py`), recovers stuck work, then starts the workers (`scheduler, learning, triggers, housekeeping, autopilot`).
* CLI-agent auth is **mounted**, not configured: `~/.the reviewing agent` and `~/.codex` are bind-mounted read-only (the original's pattern: run `codex login` on the host; an expired login silently disables the "brain" — check `/api/health` → `ai_provider`).
* The image installs Node + `@the model vendor-ai/claude-code` + `@openai/codex` so `AI_PROVIDER=cli` works; drop those lines from the Dockerfile if you only use HTTP providers.

## 3. Configuration

All keys are in `.env.example`, grouped: storage, app/auth, credentials key, LLM provider (`template | cli | ollama | openai`), approval channel, execution safety (`DRY_RUN`, `LIVE_TOOLS`, sandbox allowlist, hourly cap), scheduler, memory. Runtime-mutable switches (provider, strict mode, dry-run, live tools, autopilot, operator prompt) live in `data/runtime.json` and are changed with `POST /api/environment/go-live` without a restart.

Going live, in the order the original does it:
1. `DRY_RUN=true` — everything simulated (default).
2. Rehearse: run the task; read `/api/tasks/{id}` and `/api/execution/recent`.
3. `POST /api/environment/go-live {"dry_run": false, "live_tools": "linux.service_restart"}` — one tool at a time.
4. High-risk tools still require an approved proposal (`/api/proposals`).

## 4. Database initialisation

* SQLite: created on first boot.
* Postgres: `scripts/init-db.sql` runs once in the container; tables are created by `run_migrations()` (`create_all`). To adopt Alembic, copy the original's `backend/alembic/` layout and `app/core/migrate.py` (upgrade/stamp/fail-in-production).

## 5. Startup sequence (`agentic_core/api/main.py::lifespan`)

1. JSON logging installed (`setup_logging`), 2. built-in agents/tools/workflows/workers imported, 3. `AGENTIC_APP` imported, 4. audit immutability guard, 5. `CREDENTIALS_KEY` copied into the process env, 6. `data_dir` created, 7. schema, 8. `recover_stuck()`, 9. production sanity (`API_KEY`, `SECRET_KEY`), 10. workers started (never in `APP_ENV=test`). Shutdown stops workers and disposes the engine.

## 6. Operations

| need | endpoint |
|---|---|
| liveness/components | `GET /api/health` (cheap, unauthenticated) |
| metrics (JSON, honest nulls) | `GET /api/observability/metrics` |
| workers alive? run one now | `GET /api/observability/workers`, `POST /api/observability/workers/{name}/run` |
| journal / audit | `GET /api/logs`, `GET /api/audit` (needs `manage_users`) |
| what would run | `GET /api/orchestration/plan?workflow=…` |
| queues | `GET /api/scheduler`, `GET /api/proposals`, `GET /api/execution/recent` |
| unblock an uncertain step | `POST /api/execution/plans/{key}/steps/{step}/reconcile {"found": true|false}` |

Logs are one JSON object per line with `correlation_id` (also returned as `X-Request-Id`), `task_id`, `agent`, `tool`, `error{class,action}`; grep by id, not by time.

## 7. Tests

```bash
scripts/run_tests.sh              # 13 core test files + the Linux example, each in its own process/sqlite
python agentic-core/tests/run_tests.py lifecycle tools   # filter
```
Or with pytest: `pip install pytest && cd agentic-core && pytest tests`.

## 8. The original stack (for reference)

`examples/marketing/docker-compose.yml`: postgres (pgvector), redis, ollama (profile), Postiz + Temporal + Elasticsearch (profile `full`), the FastAPI backend (mounts `.env`, `~/.the reviewing agent`, `~/.codex`; `BACKEND_RELOAD` opt-in), the Next.js frontend (production build; restart to rebuild). See `examples/marketing/README.md`.
