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
