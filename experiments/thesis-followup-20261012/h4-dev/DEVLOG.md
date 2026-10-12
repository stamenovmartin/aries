# H4 development log: ARIES_PLANNER_CLARIFY_GUARD

Development set: `dev.jsonl`, 4 ambiguous (`dev-a-*`) and 3 matched controls (`dev-c-*`), written by Claude on
2026-10-12. **Never part of H4 sets A/C or of any H4 score.** The validator rejects dev rows in a scored set, and
the runner refuses to mix them. Sets A and C have not been opened; they are still empty.

**Why the guard exists.**
- In the follow-up planner test (`../task3-summary.json`), with `ARIES_PLANNER_CLARIFY` on, the model chose
  `ask_clarification` on 3 unambiguous browser goals and attached arguments, 9 of 9 attempts. Strict matches fell
  from 68/72 to 60/72.
- In the smoke test, the planner never listed the folder, so it had nothing to ask about.

**Rules (author, 2026-10-12).**
- At most **3 development rounds**. Every round is logged here, including failures.
- Confirming an action is `ask_approval`; choosing between observed candidates is `ask_clarification`.
- After the rounds, a dated amendment to the H4 preregistration is pushed before any measurement on A/C.

**Procedure.** Each round is one run of the 7 dev scenarios through `../h4-runs/run_h4.py --sets dev`. The baseline
(`on`, guard off) is not a round: nothing is changed for it.

## Attempts

| When (UTC) | Run | Condition | Result |
|---|---|---|---|
| 2026-10-12T17:27:58Z | baseline (not a round) | `on`, guard off | **refused by preflight**: GNOME session locked or blanked (idle-delay 60 s); nothing submitted |
| 2026-10-12T17:28:18Z | baseline (not a round) | `on`, guard off; screen woken (not locked; lock disabled), idle inhibited for the run | **0/7.** All 4 A cases failed without asking; all 3 C cases failed to read their target. Pattern: `file.read` on the folder itself → guessed file name (`report.txt`, `invoice`, `notes.txt`) → `TARGET_NOT_FOUND` → the same read repeated until the step budget ran out. Only `dev-c-02` ever listed its folder, too late to finish. `dev-a-04` (Macedonian) never reached the planner: `service.plan` routed it to the legacy `read_file` with path `dev-a-04.`, keeping the sentence period (`INVALID_ARGUMENT`). This is a separate routing defect that the guard cannot affect. Run: `../h4-runs/20261012T172818Z-dev-baseline-on/` |
| 2026-10-12T17:31:15Z | **round 1** | `on-guard`, guard exactly as committed in `5590f41` | **2/7** (A 0/4, C 2/3). The list-first hint worked: every case listed its folder first (baseline: 1/7). No invalid decisions and no confirmation questions. Controls `dev-c-01` and `dev-c-02` passed by reading their single target. **In A, the model listed and then read a candidate (silent choice) instead of asking**, although the clarification instruction was present. In `dev-a-03` and `dev-c-03` the candidates sit in subfolders; after the top-level listing the model read `readme.txt` and stopped at `proposed`. `dev-a-04`: same routing defect as the baseline. Run: `../h4-runs/20261012T173115Z-dev-round1-on-guard/` |
