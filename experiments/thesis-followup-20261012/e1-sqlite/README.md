# E1: SQLite "database is locked": what exists, what was measured, what is not done

Date 2026-10-13. Code: `thesis-followup` at d865447, plus the uncommitted H4b resolver. The resolver is
off here, and the stress test does not touch it. Engineering work, not a hypothesis.

## What the master plan asked for, and what already exists in the frozen code (4b3fd50)

| Asked for | Status | Where |
|---|---|---|
| WAL on every connection | already present, on every SQLite engine | `vendor/agentic-core/agentic_core/database/base.py`, `apply_sqlite_pragmas` |
| `synchronous=NORMAL` | already present | same |
| `busy_timeout` | already present, **15000 ms**, read back and logged if it did not take (the plan's 5000 ms would be shorter, so it is not changed) | same, `BUSY_TIMEOUT_MS` |
| one serialised writer | already present, per process and per event loop, with a bounded 30 s acquire | `agentic_core/database/writer.py`, `write_session` |
| `BEGIN IMMEDIATE` for writes | already present, inside `write_session` | same |
| bounded retry with backoff and logging | already present, as a last resort | `writer.retry_busy` |
| the agent's own writes through the writer | already present | `aries/workspace/service.py:283` (save), `:292` (progress) |
| no transaction across an LLM call or a capability | **partly**: before capability I/O, the session is rolled back (`agent.py`, "no read snapshot held across budget admission or capability I/O"). A **read** session stays open during planner calls (`agent.py`, `agent_planner.plan(db, …)`), and the new resolver call follows the same pattern | `aries/workspace/agent.py` |

This work was done before the freeze, after the incidents of 2026-09-29 to 2026-10-03
(`docs/ERROR_LOG.md`, `experiments/locking/`).

## Stress test (`stress.py`): 4 processes × 5 goals × 32 steps, plus a background writer

ARIES never runs two agent goals at once in one process. Each goal reserves the files, desktop,
local-model and browser lanes (`service.resources_for`), and `MAX_CONCURRENT` is 3. Contention
therefore comes from several processes writing the same file. Two parts of the plan's shape were
changed:
- **Steps:** a goal can have at most 32 steps (`workspace.agent_max_steps`), so the plan's 50 is
  impossible.
- **Concurrency:** the "concurrent goals" are separate processes.

Result (`results/stress-before-4x5.json`), on a scratch database with a scripted planner and no
model:

| | value |
|---|---|
| goals | 20 (19 `partial`, 1 read back as `running`; see below) |
| steps per goal | 32 of 32 in every goal |
| lock errors (records, logs, stderr) | **0** |
| writer lock per worker | 980 acquisitions, 0 contended, 0 timed out, maximum wait 0.7 ms |
| background writer (separate process, plain sessions) | 996 writes, 0 errors |
| wall time | 20.2 s |

The goal read back as `running` already has all 32 steps. The likely cause is that the worker
read it before its final save. All processes share one queue, so another worker's `dispatch` can
claim that goal. This would be an artefact of the test harness, not a lock fault, but it has not
been verified.

## The 20-process run took the machine down (2026-10-13, 21:01)

A second shape, 20 processes × 1 goal × 32 steps, ran while the live ARIES (core and voice) was
running. Every process imports the whole of ARIES. The kernel log of that boot ends with
`python invoked oom-killer` at 21:01:14. The desktop froze and the author had to power off. The
same run most likely ended the previous session too. **It must not be run again in this form.**
If it is ever needed, it must run with memory limits (for example `systemd-run --user -p MemoryMax=`),
with the live ARIES stopped, and only after the author's approval.

## Conclusion and what is not done

- **No lock error was reproduced.** None was found in the 2026-10-06 held-out records either. The
  6 goals that never reached the planner remain "cause unknown".
- **No code was changed for E1.** The flag-guarded change the plan proposes would duplicate code
  that already exists.
- **One candidate change remains:** close the read session before each planner or resolver model
  call. In WAL a read snapshot does not block writers, so this matters only if a lock error is
  traced to it. It would go behind a flag.
