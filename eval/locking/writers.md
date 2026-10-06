# A2 — every SQLite file ARIES opens, and every writer of each

Built by reading the code on 2026-10-03: `grep` for `create_async_engine`,
`create_engine`, `sqlite3.connect`, `aiosqlite.connect`, `async_session`,
`.commit()`, `DATABASE_URL` and `*.db` / `*.sqlite*` across `aries/`, `aries_ui/`,
`vendor/`, `scripts/`, `systemd/`, `tests/` and `experiments/`, plus
`systemctl --user show -p Environment` for every running unit. Not from memory.

## 1. The files

| File | What it is | Engines that open it | Opened by |
|---|---|---|---|
| `var/aries.db` (240 MB, 61 443 pages) | **The** ARIES database. Every engine table and every ARIES table. | exactly one in production: the module-level singleton in `vendor/agentic-core/agentic_core/database/base.py` | 3 OS processes + every CLI run + read-only probes — see §3 |
| `<firefox profile>/permissions.sqlite` | Firefox's own permissions store, not ARIES's | none — a bare `sqlite3.connect` | `aries/workspace/media.py:242` only |
| `./data/agentic_core.db`, `./agentic_core.db` | dead configuration, never created on this machine | — | the first (overridden) `DATABASE_URL` line in `.env` and the `settings.database_url` default |
| temporary `*_test.db` per test/eval process | one scratch file per process, `tempfile.mkdtemp` | the same singleton engine, pointed at the scratch file by `tests/_harness_shim.py` → `_harness.bootstrap()` | tests, `eval/`, `experiments/*/run.py` |

`find` confirms there is no other `*.db` / `*.sqlite*` in the tree, and no vector
index file (`*.npy`, `*.faiss`): `agentic_core.memory.vector` stores embeddings as
rows in `memory_items` in `var/aries.db` and does cosine similarity in Python, so
semantic memory is **not** a second database — it is more writers of the first one.

## 2. Writers of `var/aries.db`

Everything in this section goes through **the shared engine** in
`agentic_core/database/base.py`. There is no second engine and no direct
`sqlite3.connect` to this file anywhere in production code. "Own session" means
the module calls `async_session()` itself; "caller's session" means it writes into
an `AsyncSession` handed to it (a FastAPI dependency, a worker context, a
lifecycle `ctx["db"]`) — same engine either way, so the same pragmas, but the
transaction boundary belongs to someone else.

### 2a. Opens its own session from the shared engine

| Module | Writes | Note |
|---|---|---|
| `aries/workspace/service.py` (21 commits) | `aries_workspace_goals`, audits | `save()`, `progress()`, `dispatch()`. **The sub-goal write path.** Contended file — see `PROPOSAL.md` |
| `aries/workspace/orchestration.py` (7) | child/parent goals, evidence | `_persist` → `service.save`; `claim()` CAS; `_drive` interrupt path |
| `aries/workspace/memory/store.py` (10) | `aries_workspace_memory`, conclusions | claimed by codex today |
| `aries/automations/runner.py` (8), `automations/worker.py` (1) | `automation_logs`, tasks | the hourly automations pass |
| `vendor/.../scheduler/worker.py` (1) | `automation_logs` checkpoint, at **`worker.py:83` — `await db.commit()`** | the site the earlier investigation named. **Verified**: that line is the commit, and the `except Exception` below it is the handler that logs `sqlite_errorcode`/`sqlite_errorname` |
| `vendor/.../memory/recovery.py` (1) | `task_runs`, `tasks`, `execution_operations`, `execution_plans`, `scheduled_tasks` | `recover_stuck()`. **This is the writer still failing live** — see §5 |
| `vendor/.../scheduler/queue.py`, `scheduler/builtin.py` | queue rows, built-in jobs | |
| `vendor/.../api/middleware.py` (2) | request/audit rows | one per HTTP request |
| `aries/intelligence/server.py` (1) | `generation_usage` | **runs in a different OS process** (`aries-local-model`) |
| `aries/cli.py` (3) | whatever the subcommand does | **a new OS process per invocation** |
| `aries/shell/watchdog.py` (1) | repair audit | |
| `aries/workspace/agent.py`, `workspace/automation.py`, `workspace/capabilities.py`, `brief/sections.py`, `connect/automation.py`, `connect/files.py`, `news/summaries.py`, `operator/goals.py`, `api/app.py` | various | |

### 2b. Writes into a session the caller owns

`aries/api/routes.py` (5) · `aries/settings/service.py` (2) · `aries/sources/service.py` (5) ·
`aries/interests/service.py` (5) · `aries/connect/service.py` (4) · `aries/operator/service.py` (3) ·
`aries/news/automation.py` (3) · `aries/learning/{reversal,loop,history,feedback}.py` (3+2+2+2) ·
`aries/intelligence/{router,generation}.py` (2+1) · `aries/lifecycle/service.py` (2) ·
`aries/power/service.py` (1) · `aries/health/automation.py` (1) · `aries/brief/automation.py` (1) ·
`aries/workspace/{reviews,registry,recovery}.py` (1 each) ·
`vendor/.../orchestrator/{dag,service,lifecycle}.py` (10+6+5) ·
`vendor/.../api/routes.py` (6) · `vendor/.../tools/calling.py` (5) ·
`vendor/.../scheduler/{scheduled,triggers}.py` (4+1) ·
`vendor/.../security/{secrets_store,approvals}.py` (4+1) ·
`vendor/.../memory/{vector,feedback,chat_history}.py` (2+1+1) ·
`vendor/.../evaluators/runner.py` (1)

`vendor/.../orchestrator/lifecycle.py:121` is the second fix the earlier
investigation claimed. **Verified**: the `await db.commit()` before each attempt
is there, with the comment explaining that otherwise a settings read autoflushes
pending trace rows and holds the writer lock across the executor's external I/O.

### 2c. Not a writer, despite having `DATABASE_URL`

`aries-voice.service` loads `EnvironmentFile=-%h/aries/.env`, which sets
`DATABASE_URL` to `var/aries.db`, and `experiments/voice/voice.py` imports
`aries.speech`. It nevertheless has **no** write path: it reaches ARIES over
`http://127.0.0.1:8000/api/aries`, and `grep` finds no `async_session` or
`.commit()` under `aries/speech/` or in `voice.py`. Same for `aries_ui/`: the GTK
dashboard is an HTTP client (`aries_ui/client.py:45`), not a database client.
Both are one import away from becoming writers, which is why they are listed.

## 3. Processes that hold the file at the same time

The in-process picture is not the whole picture. Three live units and one
on-demand process point `DATABASE_URL` at the same file:

| Process | How it gets the URL | Writes? |
|---|---|---|
| `aries-core.service` | `Environment=DATABASE_URL=...var/aries.db` | yes, almost all of §2 |
| `aries-local-model.service` | same, in its own unit | yes — `generation_usage`, `aries/intelligence/server.py:119` |
| `aries-voice.service` | `.env`, via `EnvironmentFile=-` | no today (§2c) |
| `scripts/aries <cmd>` | `export DATABASE_URL="${DATABASE_URL:-...var/aries.db}"` | yes, one new process each time |
| `aries-lock-observer-20261003-final.service` | — | no: it reads `journalctl`, not the database |
| `experiments/**` probes | `?mode=ro&uri=true` | no, SQLite refuses the write |
| `experiments/memory-preservation/measure.py` | sets `DATABASE_URL` to the **live** file | writes, then rolls back (codex's fixture) |

**This bounds what "one writer" can mean.** A process-local lock cannot serialise
`aries-core` against `aries-local-model` or against a CLI run. For those, SQLite's
own file locking plus `busy_timeout` is the only mechanism, and that is why §4
matters as much as the lock does.

## 4. WAL and `busy_timeout` — state after this item

One constant, `BUSY_TIMEOUT_MS = 15000`, in `agentic_core/database/base.py`, used
in three places that previously each carried their own literal: the pysqlite
`connect_args["timeout"]`, the `PRAGMA busy_timeout`, and the read-back check.

`apply_sqlite_pragmas(engine, url=...)` is now exported, so an engine built
anywhere else gets the identical set instead of a hand-copied listener; it skips
`journal_mode` on `?mode=ro` and `:memory:` URLs (WAL is a header write and would
raise on a read-only probe), and it **reads the pragmas back** and logs a warning
if they did not take, because a pragma that silently failed is indistinguishable
from no configuration until a lock error hours later.

| Opener | WAL | `busy_timeout` | In my write scope? |
|---|---|---|---|
| the shared engine, `database/base.py` | yes | 15 000 ms | yes — done |
| `aries/workspace/media.py:242`, Firefox `permissions.sqlite` | **no, deliberately** | **200 ms, deliberately** | no — reported, not edited |
| `experiments/{locking,remediation,verification}/*.py` | n/a, `mode=ro` | 0–10 s, varies | no — read-only, cannot deadlock a writer |
| `tests/test_media_autoplay.py`, `tests/test_memory.py` | no | default | no — scratch files |

`media.py` is correct as it stands and should **not** be changed: that file is
Firefox's, Firefox sets its own journal mode, and the 200 ms timeout is the point
— `ensure_youtube_autoplay` must give up immediately when the browser is open and
retry on the next play request, which is what the docstring says and what
`tests/test_media_autoplay.py` asserts. Forcing WAL on another program's database
from outside would be the bug, not the fix.

## 5. What the evidence actually says about the lock errors

Three claims were handed to me. Two check out, one does not.

1. **`worker.py:83` and the lifecycle autoflush** — both verified in the code, §2.
2. **"199 in 30 days, last at 2026-10-01 00:00 UTC, zero since"** — **not true any
   more.** `metrics.locking_failures` now reports **n = 200**, and the newest row
   is **`2026-10-03 14:09:11`**, about two hours before this item was built:
   `scheduler.failed`, `UPDATE task_runs SET status=?, verdict=?, finished_at=? WHERE
   task_runs.status = ? AND task_runs.started_at < ?` — i.e.
   `agentic_core/memory/recovery.py:32`, `recover_stuck()`. The symptom is not
   quiet. It is rare and it is now down to one writer.
3. **`SQLITE_BUSY_SNAPSHOT`** — measured, twice, and it is **not** what these are:
   - `experiments/locking/waited.py`, re-run today: all 16 recoverable failures
     waited **15.2–19.6 s** before failing (`task_runs` 15.2/16.7/19.6;
     `aries_workspace_goals` n=13, min 15.8, median 16.3, max 17.2). A
     `BUSY_SNAPSHOT` returns in ~0 s because it never retries. So `busy_timeout`
     was in force and was **exhausted** — some writer held the write lock for
     over fifteen seconds.
   - A direct probe on this driver (`A` selects, `B` commits underneath it, `A`
     then updates) **succeeds**: pysqlite only begins a transaction before DML, so
     a SELECT holds no read snapshot and there is nothing to invalidate.
     `SQLITE_BUSY_SNAPSHOT` is therefore unreachable here *today* — and only by
     accident of the driver's legacy isolation. `eval/locking/smoke.py` pins that
     with a check, so turning on `isolation_level=None` or PEP 249 autocommit
     fails loudly in the eval instead of quietly at 3 a.m.; and
     `write_session()`'s `BEGIN IMMEDIATE` keeps it unreachable even then, because
     a transaction that already holds the write lock has no upgrade to lose.

**So raising `busy_timeout` further would not fix anything.** The remaining
failure is a writer holding the lock past the timeout, and
`experiments/locking/overlap.py` says 0 of 13 blocked windows overlap any logged
automation run of ≥1 s — the holder is not a job that records itself. Finding it
is a Part B measurement, not a claim this item may make. What this item does is
remove the queueing that makes it reachable from inside `aries-core`, and name the
one writer that is still losing.
