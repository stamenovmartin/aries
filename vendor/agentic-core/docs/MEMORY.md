# MEMORY AND STATE

## 1. Short-term memory

**Original — the shared context layer** (`app/services/context_layer/__init__.py`): a folder per module (`intelligence, analytics, strategy, production, distribution, director`) under `backend/context/`; each document has front matter (title, author, updated, one-sentence summary) and a body; `digest()` (summaries only, ≤1600 chars) is appended to EVERY system prompt (`services/ai/__init__.py::_system_prompt`), so agents never start from zero. Journal mode (`append_line`) keeps the last 400 lines (the director's task-log). Files on purpose: the owner can read them without a screen. Also: `services/signals.py::team_signals` folds the meeting focus, freshest trend, offer angle and season into a ~700-char block every generator appends.

**Core**: `memory/context_layer.py` — same API (`write, append_line, read, read_data, listing, digest, read_log`), modules `intelligence, analytics, strategy, production, execution, director` (+`register_module`). `llm/providers.system_prompt()` appends the digest. `GET /api/context`, `GET /api/context/{module}/{name}`.

Per-run working memory is the Director's **ctx dict** (threaded node to node) and the tool-loop message list inside `agents/runtime`.

## 2. Long-term memory

**Original — vector memory** (`app/services/memory/__init__.py`): `MemoryItem(kind, title, content, embedding JSON, dim, backend)`; embeddings are a deterministic lexical hash (char trigrams + words, 512 dims, L2-normalised) by default, Ollama optional; cosine recall in SQL through pgvector's HNSW index when available, Python fallback otherwise; `consolidate()` rebuilds seeded items from BrandMemory, competitor reports, StyleGuide and strategies; `ask()` is RAG (answer grounded ONLY in recalled items). Also `BrandMemory` (per-brand notes updated by research), `StyleGuide` (learned rules), and `insights/learned.py` (measured findings, cached a week).

**Core**: `memory/vector.py` — `remember, recall, recall_context, ask, forget_seeded, stats`; `POST /api/memory`, `GET /api/memory/recall`, `POST /api/memory/ask`. pgvector is the documented scale-up (see the original's startup SQL in `main.py`).

## 3. Learning from feedback

**Original**: `Feedback(kind=edit|reject, op, instruction, before, after, sender, distilled_at)` captured from every channel (phone edits, dashboard rewrites, rejection reasons — a bare ❌ makes the bot ask "why?", `conversation.py::capture_reject_reason`) → nightly `learning.py::distill_feedback` (AI shown the standing rules so it can retire a contradicted one; deterministic heuristics otherwise; newest rules first in the union; rows watermarked only when their platform learned) → `StyleGuide(platform, rules, banned_phrases)` → `load_style_context` into the copy prompt.

**Core**: `memory/feedback.py` — `capture_edit, capture_reject, distill, load_rules_context, rules_snapshot`; `LearnedRule(scope)`; `POST /api/feedback`, `POST /api/learning/distill`, `GET /api/learning/rules`; the `learning` worker runs it daily (`scheduler/builtin.py`); `AgentSpec.learn_scope` selects which rules an agent receives.

## 4. Database schemas

Core tables (`database/models.py`) and their originals (`app/models/*.py`):

| core table | original | purpose |
|---|---|---|
| `tasks` | `campaigns` | the unit of work; status governed by `orchestrator/states.py`; `depends_on`, `parent_id`, routing, result, attempts, approval fields |
| `task_runs` | `agent_runs` | one execution of the chain: trigger, workflow, decisions (JSON), evaluation (JSON), verdict, correlation_id |
| `agent_steps` | `agent_steps` + `automation_logs(action=agent_step)` | per-agent contribution with confidence, evidence, duration |
| `artifacts` | `campaign_targets.media_url`, `/uploads`, `/screenshots` | produced files/outputs per task (`data_dir`) |
| `action_proposals`, `approval_requests` | same | typed proposals; decisions per channel |
| `audit_events` | same | append-only; flush guard |
| `execution_operations`, `execution_plans`, `execution_steps` | same | idempotency + resumable DAG |
| `scheduled_tasks` | `scheduled_posts` | due-queue with attempts/backoff |
| `automation_logs` | same | the journal (events, worker runs, lifecycle verdicts) |
| `feedback`, `learned_rules` | `feedback`, `style_guide` | learning loop |
| `memory_items` | same | vector memory |
| `chat_messages` | same | conversation history |
| `eval_cases`, `eval_runs`, `eval_results` | same | the harness |
| `users`, `api_tokens`, `stored_credentials` | `users`, `api_tokens`, `tenant_credentials` | identity, token digests, ciphertext-only credentials |

Not carried over (marketing-specific): products, platforms, campaign_targets, campaign_research/strategy, brand_memory, generated_posts/posting_queue/posted_history, post_metrics, competitor_*, product_changes, events (measurement), tracking, billing, tenants/memberships.

Schema bootstrap: `database/migrate.run_migrations` (`create_all`, idempotent). The original uses Alembic (`backend/alembic/`) with `upgrade head` / `stamp head` and a production rule that a failed migration stops the boot.

## 5. Task history and conversation history

* Task history: `GET /api/tasks/{id}` returns every `TaskRun` with decisions, evaluation, verdict and its `AgentStep`s (`observability/trace.for_task`). `GET /api/logs` is the journal; `GET /api/audit` the immutable record.
* Conversation: `memory/chat_history.py` (`record`, `history`, `as_transcript`) — the assistant is given the last N turns.

## 6. Artifact storage

`Artifact(task_id, kind, name, path|content, content_hash)`; files live under `settings.data_dir` (mounted as `./data` in compose). The original stored uploads under `/app/uploads` and rehearsal screenshots under `/app/screenshots`, served as static routes.

## 7. State persistence and checkpoints

| checkpoint | original | core |
|---|---|---|
| `sent` persisted BEFORE the external call | `execution/operations.mark_sent` | `orchestrator/operations.mark_sent` |
| plan progress committed after every step | `execution/dag.run_plan` | `orchestrator/dag.run_plan` |
| runtime switches | `data/runtime.json` (atomic tmp+rename) | `data/runtime.json` (`config/runtime.py`) |
| worker cursors | `data/telegram_offset` | `data/cursors/<name>.cursor` (`memory/checkpoints`) |
| worker pacing | `MAX(AutomationLog.created_at)` per worker | `checkpoints.last_run_at` / `mark_run` |
| context layer | `backend/context/*` | `data/context/*` |

## 8. Recovery after restart

Original: `posting.recover_stuck_publishing` (startup AND every scheduler tick — a crash-loop never grants a 10-minute-old restart), `scheduling.recover_stuck_scheduled`, `_recover_crashed_run` (in-flight targets → terminal `skipped`, never `failed`). Core: `memory/recovery.recover_stuck(older_than_minutes=10)` — tasks `executing`→`approved`, `running`→`failed(uncertain)`; runs → `interrupted`; operations `sent`→`uncertain`; plans `running`→`blocked`; scheduled `processing/executing`→`failed`. Called in the API lifespan and by the `scheduler` worker every pass.
