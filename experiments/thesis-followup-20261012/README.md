# ARIES thesis follow-up, 2026-10-12

These are follow-up results added on top of the frozen evaluation **ARIES-FINAL-20261006**. Nothing in this folder
changes or replaces a reported result. Every number here comes from a file in this folder or from a frozen
artifact named next to it.

| | |
|---|---|
| Date | 2026-10-12 |
| Branch | `thesis-followup` |
| Snapshot base | `479e746` (tag `thesis-final-20261006-snapshot`). Its `aries/` is byte-identical to `experiments/thesis-final-20261006/frozen/aries` (0 differing files). |
| Code under test | `1ac3e55`: snapshot + `planner-clarification.patch` (`736e22c` code, `1ac3e55` H4 preregistration). Later code is named per item below; the H4 freeze is `a2d1609` (tag `h4-frozen-20261012`). |
| Outputs committed in | the commit that adds this README (see `git log -- experiments/thesis-followup-20261012`) |
| Model | `qwen2.5:7b`, digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`. This equals the digest in `experiments/thesis-final-20261006/protocol.json`. Inference was run only where the table below says so; every such run records its digest. Task 6 uses `llama3.1:8b` (digest in `task6-model/protocol.json`). |
| Effective flags | Default values at `a2d1609`, resolved with `aries.flags.describe()` (`var/flags.env` sets none). Measurement runs pin their own values and record them. On: ARIES_CAP_TOPK, ARIES_COMPLETION_PROGRESS_GUARD, **ARIES_COMPLETION_READ_PARAPHRASE (new)**, ARIES_CONTEXT_ENGINE, ARIES_CONTRACT_FINISH, ARIES_MK_FROZEN, **ARIES_PLANNER_CLARIFY (new)**, ARIES_PLAN_MEMORY, ARIES_ROUTER_ABSTAIN, ARIES_STATE_SNAPSHOT, ARIES_TERMINAL_READ_FAILURE, ARIES_TILE_HIDPI, ARIES_TRACE_FEWSHOT, ARIES_TYPE_STRICT, ARIES_VERIFY_FEEDBACK. Off: ARIES_GOAL_TEAMS, **ARIES_PLANNER_CLARIFY_GUARD (new)**. |

## Contents

| Path | Task | What it is |
|---|---|---|
| `task1-tests/` | 1 | logs and `summary.txt` of the 11 test suites after applying the patch |
| `terminal-diagnosis/` | 2 | `extract.py` (read-only extraction) and `goals.json` (per-goal terminal paths of the held-out run). The write-up is `docs/analysis/terminal-state-diagnosis.md`. |
| `h4-scenarios/` | 4 | instructions for the external author, empty `set_a.jsonl`/`set_c.jsonl`, `example_pair.jsonl` (excluded from scoring), `validate_oracles.py` and `validation/` |
| `stats.json`, `stats.md` | 5 | exact McNemar and Cochran's Q on the frozen router decisions; produced by `scripts/thesis_stats.py` |
| `inputs/final-evaluation.json` | 5 | unchanged copy of `dokazi/final-evaluation.json` from `thesis/ARIES_Diplomska_Paket_20261006.zip` |
| `verifier-count.md` | 7 | the 57-vs-56 verifier count and the list of affected files |

| `task2-tests/` | 2 | tests of `ARIES_COMPLETION_READ_PARAPHRASE`, including flag-off equality with the frozen contracts |
| `task3-planner/`, `task3-demo/`, `task3-summary.json` | 3.2 | planner 72 and demo 3 on `79d1f23`. Planner strict 60/72 against frozen 68/72, all in p20–p22. Demo 3/3. |
| `task3-planner-guard/` | 3.2 | planner 72 with the H4 treatment flags on `a2d1609`: 69/72, **confirmation after the fix, not independent evidence** |
| `h4-dev/` | H4 dev | development set (7, never scored), `DEVLOG.md` with the baseline and the 3 allowed rounds, failures included |
| `h4-runs/` | H4 | `run_h4.py` (isolated instance per run) and its smoke and dev runs. No H4 measurement yet. |
| `guard-tests/`, `revert-tests/` | — | guard tests; the revert of the export's word substitution |
| `task6-model/` | 6 | router protocol with `llama3.1:8b`; an aborted run (live service was on) is kept unscored. The full run is scheduled for 2026-10-13 01:00 CEST with the live ARIES stopped. |

**H4 is not measured yet.** It waits for the external sets A and C. They are validated only by
`h4-scenarios/validate_oracles.py` and are not opened. Protocol: `docs/preregistration/H4-planner-clarification.md`
with Amendments 1 and 2.
