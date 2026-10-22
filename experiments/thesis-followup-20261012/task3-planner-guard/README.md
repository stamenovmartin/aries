# Planner protocol with the guard: confirmation after the fix

**Label: "confirmation after the fix", not independent evidence.** `ARIES_PLANNER_CLARIFY_GUARD` was designed after
the Task 3.2 run showed `ask_clarification` misused on p20–p22, with this protocol's failure in view
(preregistration H4, Amendment 2). This run shows that the specific failure is gone. It does not show that the guard
generalises.

| | |
|---|---|
| Code | `a2d1609` (tag `h4-frozen-20261012`), archived to `var/followup-source/a2d1609`. Only `aries/flags.py` and `aries/workspace/agent_planner.py` differ from the Task 3.2 source `79d1f23` (`source-manifest.json`). |
| Flags | the H4 treatment, pinned in the environment by `run_guard.py`: `ARIES_PLANNER_CLARIFY=1`, `ARIES_PLANNER_CLARIFY_GUARD=1`, `ARIES_COMPLETION_READ_PARAPHRASE=0`. All three report `source: environment` in `run-manifest.json`. All other flags are the frozen protocol's. |
| Model | `qwen2.5:7b`, digest `845dbda0…` (equal to the router protocol), stable over the run |
| Protocol | byte copies of `../task3-planner/{run_planner.py,protocol.json,fixture.json}`. `validate_run.py` differs only in the path of the pre-inference dry run it compares prompts with (`runs/20261012T193014.755446Z`). |
| Run | `runs/20261012T193022.180980Z`, 2026-10-12, live ARIES running (as in ARIES-FINAL-20261006 and Task 3.2) |

## Result (`confirmation.json`)

| Run | Schema valid | Strict (capability + arguments) |
|---|---|---|
| frozen ARIES-FINAL-20261006 | 72/72 | 68/72 |
| Task 3.2, `ARIES_PLANNER_CLARIFY` alone | 63/72 | **60/72** |
| this run, with the guard | 72/72 | 69/72 |

- p20, p21 and p22 went from 0/3 to 3/3 each. All 9 attempts chose `execute`. The guard changed the prompts of
  p05–p07 and p20–p22; the other 18 prompts are byte-identical to the Task 3.2 dry run.
- The only remaining failure is p12, at 0/3 in both follow-up runs.
- Independent recalculation: 22/22 checks.
- The 60/72 regression stays a reported result. 69/72 versus 68/72 is one attempt in one run and is not claimed as
  an improvement over the frozen system.
