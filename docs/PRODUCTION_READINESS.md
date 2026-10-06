# Production readiness

## Current verification — 1 October 2026 (Europe/Skopje)

The existing feature set passes the full regression suite and the isolated desktop
harnesses. Final installed desktop acceptance is still pending while the user's
session is locked. This is not a declaration that every future roadmap feature or
arbitrary agent task is complete.

Evidence and exact changed-source hashes:
[system completion manifest](../experiments/coordination/system-completion-20260930/manifest.json).
The subsequent [the reviewing agent review follow-up](../experiments/coordination/claude-review-20261001/result.json)
adds SQLite result-code logging and visible interruption of worker checkpoint
recording; 15 execution-boundary checks and 13 scheduler checks passed. Core was
updated through the maintenance drain. The earlier manifest retains its original
batch hashes; the follow-up records the two newer source hashes.

The latest [recovery and memory privacy batch](../experiments/coordination/recovery-memory-20261001/manifest.json)
records 69 counted application/UI/HTTP suites and 3,630 checks passing, plus
engine/reference suites. The final question-prefix change was checked separately
after the relevant full-run suite: 26 privacy/question checks and 126 existing
memory checks passed. Recovery has 26 passing checks and existing agent tests 65.
The [installed real-planner recovery](../experiments/coordination/read-recovery-20260930T235336Z-6615e5/result.json)
passed 7/7 checks: a failed file read resumed in a linked child, independently
verified fresh content, preserved the parent's failure, and reused the child on
duplicate recovery. Core was updated through the maintenance drain.

Recovery now rejects invalid/exhausted histories, clears stale child evidence,
and honours current policy before re-observation. Memory exclusions cover stored
rows and source-linked conclusions before ranking, recency updates and neighbour
inference; unavailable privacy rules fail closed. Ordinary information questions
are filtered by bounded MK/Latin/English prefixes, not a complete semantic
classifier. Exclusions hide context reversibly without deleting historical rows.
Implementation learning record: 49.

The [latest readiness check](../experiments/readiness/20260930T235615Z/result.json)
passes every check except the desktop protocol, with `session_locked=true`.
Live desktop focus and a fresh real microphone-to-speaker interaction remain
pending. The table below retains the preceding batch's measurements.

| Check | Measured result |
|---|---|
| Full regression | ALL SUITES PASSED: 67 counted application/UI/HTTP suites, 3,573 checks, plus engine and Linux reference suites |
| Engine after lifecycle changes | All 13 suites passed; 11 additional execution-boundary checks passed |
| Final voice flow | 46 checks passed, including restart during initial result wait |
| Isolated GNOME Shell and ARIES session | Both ALL PASSED; real window focus, teardown, re-enable and fallback checked |
| Installed core workflows | [7/7 passed](../experiments/demo/20260930T223728Z-c1067f/README.md) |
| Installed full workflow run | [9/11 initial](../experiments/demo/20260930T223417Z-212d04/README.md): one stale comparison assertion corrected and rechecked; app launch refused while locked |
| Model parameters | Live parameter tests passed, including context-window changes; no Ollama restart required for this run |
| Historical endurance | Existing 290 samples over 24.01 hours still pass corrected coverage accounting; not a new 24-hour run |

This batch fixed SQLite writer retention across lifecycle evaluator, retry,
replanner and notification waits; cancelled workers being recorded as successful;
pending voice-result IDs being lost on daemon restart; missing trailing intervals
in endurance coverage; and hard-coded two-version comparison reporting.
Updates drained active work before restarting core. The desktop session was retained.

An initially unlocked smoke/readiness run passed all checks. The session later
locked, and application launch correctly refused. No forced unlock or logout was
used. News, morning brief and an agent's independently verified web-page title
completed during the installed full run.

Remaining acceptance limits:

- Repeat application launch/focus on the unlocked live desktop.
- A real microphone-to-speaker interaction and human assessment of the selected
  Kiko voice remain unverified in this batch; the user's earlier choice of Kiko by
  ear remains valid. Synthetic RHVoice-to-Whisper evidence
  is saved in [speech results](../experiments/speech/results-system-completion.json);
  raw mean word error rate is 0.387, including number-format and proper-name errors.
  This combines synthesis and recognition errors and isolates neither component.
- Pending reply IDs are bounded to 16 tasks and 30 minutes. Removing an ID before
  playback avoids repeated speech, but a crash during playback can lose that spoken
  reply; the task result remains in the dashboard.
- The reproduced lifecycle lock is one confirmed contention source, not proof that
  every historical SQLite error is resolved. A comparable field observation window
  and workload are still needed to assess recurrence; no 48-hour follow-up has been
  completed or scheduled by this batch.
- Parallel orchestration remains limited to read-only work; sequential mutations
  retain approval and verification. External account setup, broader semantic task
  quality and independent research benchmarks are not established by these tests.

## Historical release assessment — 19 September 2026

ARIES is not declared production-complete. The current release candidate has a
working local-first core and explicit desktop/semantic limitations.

## Implemented hardening

- Update leases pause new workspace/automation execution, let active work drain,
  retain queued tasks through restart and expire after abandoned updates.
- Live verification proved a queued system-status goal survived a core restart
  and completed, while a forced automation was held by the maintenance gate.
- Malformed/missing window arrays cannot be interpreted as an empty desktop.
- Focus request acceptance is insufficient: the exact window ID and application
  must be reread as focused and not minimized before focus succeeds.
- Automatic GNOME lock and lock-on-suspend disabled at the user's request.
- A read-only readiness command reports core/model/power/desktop health and latest
  enabled automation failures. It does not infer success from a model response.

```bash
./scripts/aries-production-check
./scripts/aries-update
# Also restart gateway only when its code/config changed:
./scripts/aries-update --local-model
```

Current readiness: core API, local-model health, enabled services, background
inhibitor and latest automation status pass. Desktop protocol fails; the active
legacy bridge lacks FocusWindow when unlocked, and is suspended while locked.
The command returns nonzero rather than labelling the system fully ready.

## Remaining acceptance gates

1. Live desktop focus and extension update lifecycle without session loss.
2. Completed, reviewed endurance evidence; current service sampling alone does
   not demonstrate task correctness or zero downtime between samples.
3. Quality-evaluated Macedonian summaries; current model output has explicit
   fallback and unverified labels.
4. Safe reconciliation/continuation of interrupted dynamic M14 tasks, beyond
   existing conservative refusal and bounded legacy recovery.
5. Broader independent completion contracts and consistent cross-path metrics.
6. Frozen release and independent benchmark with negative controls, followed by
   updated publication artifacts. Existing demos are development evidence.

The maintenance gate covers the existing single-core queue and automation
runner. Direct nonqueued API interactions and distributed/multi-core deployment
are not protected by this process-local lease. A failed drain cancels the update,
not user tasks. Neither screen locking nor desktop capability gaps are bypassed
by lowering verification requirements.
