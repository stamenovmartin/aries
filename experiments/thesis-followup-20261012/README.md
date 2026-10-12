# ARIES thesis follow-up, 2026-10-12

These are follow-up results added on top of the frozen evaluation **ARIES-FINAL-20261006**. Nothing in this folder
changes or replaces a reported result. Every number here comes from a file in this folder or from a frozen
artifact named next to it.

| | |
|---|---|
| Date | 2026-10-12 |
| Branch | `thesis-followup` |
| Snapshot base | `479e746` (tag `thesis-final-20261006-snapshot`). Its `aries/` is byte-identical to `experiments/thesis-final-20261006/frozen/aries` (0 differing files). |
| Code under test | `1ac3e55`: snapshot + `planner-clarification.patch` (`736e22c` code, `1ac3e55` H4 preregistration) |
| Outputs committed in | the commit that adds this README (see `git log -- experiments/thesis-followup-20261012`) |
| Model | `qwen2.5:7b`, digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`. This equals the digest in `experiments/thesis-final-20261006/protocol.json`. **No model inference was run for anything in this folder.** |
| Effective flags (running `aries-core`, resolved with `aries.flags.describe()` in the service's own environment) | all at their defaults; `var/flags.env` sets none. On: ARIES_CAP_TOPK, ARIES_COMPLETION_PROGRESS_GUARD, ARIES_CONTEXT_ENGINE, ARIES_CONTRACT_FINISH, ARIES_MK_FROZEN, **ARIES_PLANNER_CLARIFY (new)**, ARIES_PLAN_MEMORY, ARIES_ROUTER_ABSTAIN, ARIES_STATE_SNAPSHOT, ARIES_TERMINAL_READ_FAILURE, ARIES_TILE_HIDPI, ARIES_TRACE_FEWSHOT, ARIES_TYPE_STRICT, ARIES_VERIFY_FEEDBACK. Off: ARIES_GOAL_TEAMS. |

## Contents

| Path | Task | What it is |
|---|---|---|
| `task1-tests/` | 1 | logs and `summary.txt` of the 11 test suites after applying the patch |
| `terminal-diagnosis/` | 2 | `extract.py` (read-only extraction) and `goals.json` (per-goal terminal paths of the held-out run). The write-up is `docs/analysis/terminal-state-diagnosis.md`. |
| `h4-scenarios/` | 4 | instructions for the external author, empty `set_a.jsonl`/`set_c.jsonl`, `example_pair.jsonl` (excluded from scoring), `validate_oracles.py` and `validation/` |
| `stats.json`, `stats.md` | 5 | exact McNemar and Cochran's Q on the frozen router decisions; produced by `scripts/thesis_stats.py` |
| `inputs/final-evaluation.json` | 5 | unchanged copy of `dokazi/final-evaluation.json` from `thesis/ARIES_Diplomska_Paket_20261006.zip` |
| `verifier-count.md` | 7 | the 57-vs-56 verifier count and the list of affected files |

**Measurements (Task 3) and the second model (Task 6) have not been run.** They need explicit approval and,
for H4, the external scenario sets.
