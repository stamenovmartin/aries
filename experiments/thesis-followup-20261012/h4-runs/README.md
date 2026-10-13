# H4 measurement runs

Runner: `run_h4.py`. Protocol: `docs/preregistration/H4-planner-clarification.md` with **Amendments 1 and 2**.
No H4 measurement has been run yet; it waits for the external scenario sets.

## Conditions

| Condition | `ARIES_PLANNER_CLARIFY` | `ARIES_PLANNER_CLARIFY_GUARD` | `ARIES_COMPLETION_READ_PARAPHRASE` | Part of H4 |
|---|---|---|---|---|
| `on-guard` (treatment, Amendment 2) | 1 | 1 | 0 | yes |
| `off` (control) | 0 | 0 | 0 | yes |
| `completion-fix` | 1 | 1 | 1 | **no**: a separate, labelled condition (Amendments 1 and 2) |
| `on` (clarify without guard) | 1 | 0 | 0 | **no**: refused for `--sets h4`; used only for the dev baseline |

- **Order:** on-guard, off, on-guard, off, on-guard, off (labels `r1`…`r6`), then `completion-fix` ×3 (`x1`…`x3`).
- **Materials:** each run covers set A (10), set C (10) and the 49 runnable held-out cases. These are the
  DISCRIMINATING cases of the original `oracle_validation.json`, without `requires`, which is the same selection
  as the 2026-10-06 run.

## Two procedural decisions (approved 2026-10-12)

1. **Fresh isolated database per run**, as the preregistration requires. Each run gets a new folder containing a
   new SQLite file (`aries.sqlite3`), data dir, runtime store, context dir and flags file. The server is the same
   command as `aries-core.service` (`uvicorn aries.api.app:app`) on port 8100, with the running aries-core's own
   environment and only these keys replaced. The live `var/aries.db` is opened read-only, once per run, to copy
   the owner's settings. No goals, memories or history are copied.
2. **`needs_clarification` is a terminal state.** It is the agent's end state when it asks. Without it, every
   question would wait until the 180 s budget ran out (`run_fixtures.py` does not list it). It changes only when
   polling stops, not the stored record.

## Isolation measures (identical in every condition)

- Telegram token and polling removed; `connect.*`, `news.*`, `briefing.morning_enabled` and
  `workspace.ai_briefings` forced off. This prevents a second instance from competing with the live one or
  contacting the owner.
- `shell.*` and `power.*` settings are not copied, so the instance cannot change the desktop or power state.
- The instance also starts the shell watchdog. Like the live one, it acts only if the ARIES extension is
  enabled but inactive on an unlocked screen.
- The live ARIES keeps running, as it did during the 2026-10-06 run, so the local model is shared.

## Validity checks per run (refuse or flag, never rerun silently)

- **Refuses to start if:** the session is locked or blanked; tracked code differs from the commit; the effective
  flags (resolved with `aries.flags.describe()` in the instance's exact environment) differ from the declared
  condition; or `set_a`/`set_c` lack a PASS validation for their current sha256.
- **Recorded:** commit and model digest before and after (`code_stable`, `model_stable`); sha256 of every input
  file and of both scorers; the copied and forced settings.
- **Scoring:** the checks and the verdict rule of `run_fixtures.py`. Per case, `h4.grounded_question` follows
  the preregistered definition: `needs_clarification`, `clarification.source == "planner"`, ≥ 2 choices, sandbox
  unchanged, and no forbidden state violated.

## Smoke test (excluded from everything)

`20261012T164122Z-smoke-on/`: condition `on`, example pair only.
- The instance came up, flags verified, 9 real local planner calls per goal, `model_stable` and `code_stable` true.
- Both example goals FAIL. The planner first called `file.read` on the folder, then guessed a nonexistent
  `meeting_notes.txt`, then repeated itself. It never listed the folder, so there was no verified observation
  to ask about.

This checks the instrument only and is not a result.

## What is committed from each run folder (author rule, 2026-10-13)

Committed: `records/*.json` (one per case), `results.redacted.json` and `run.redacted.json`.
Kept local and never committed: `aries.sqlite3` (and `-shm`/`-wal`), `flags.env`, `instance.log`, `var/`, and
the original `results.json` and `run.json`. Their SHA-256 and size are in `../local-only-manifest.json`.

**Redaction.** The runner copies the owner's live settings into the isolated instance and records them in
`run.settings.copied` as `{key, set_by, value}`. The values are private configuration, so `redact.py` replaces
each `value` with `"[redacted]"` and keeps `key` and `set_by`; nothing else in the file changes. No scoring field
depends on these values. `thesis-tables/check.py` reads the redacted copies and, wherever the local original
exists, checks that redacting it gives exactly the committed copy.

The smoke run's database, flag file, log and unredacted results were committed and pushed in e122d3f, before
this rule. From the next commit on they are no longer tracked, and the committed copy is redacted. They remain in
the pushed history: the history is not rewritten, because rewriting it would change the hashes of the H4
preregistration and amendment commits.
