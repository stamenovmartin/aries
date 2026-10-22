# R1b development log

Development uses only R1's 100 NL2Bash **dev** items (`nl2bash-dev`, never scored in R1) and 150 CLINC150
**val** utterances (`clinc-dev`, seed 20261101; R1 used val only for the embedding threshold). Runs are
`run_r1b.py aries --allow-dirty`, which refuses any other set. Scores come from `dev_score.py` against R1's
final labels. None of these numbers is a result; the confirmatory runs are on the new R1b samples
(`sample_r1b.py`), which no system has seen.

Sampling at temperature 0.1 makes a single dev run noisy: on the same 73 items the gate and the zero-shot
baseline (the same question) disagreed on 19, which bounds how much a one-point dev difference means.

## Round 1 (2026-10-22): the five remedies, together and apart

| config | flags | top-1 /100 | in scope /42 | false actions | planner invalid |
|---|---|---|---|---|---|
| C0 | none (current source) | 53 | 25 | 30 | 18 |
| C1 | surface + gate + hint + per-cap grammar + OOS message | 72 | 22 | 8 | 0 |
| G | gate + hint | 67 | 25 | 16 | 15 |
| P | per-cap grammar + OOS message | 58 | 0 | 0 | 0 |
| S | surface | 66 | 23 | 15 | 13 |
| zero-shot | R1 baseline | 72 | 25 | — | — |

P refused all 81 items it planned (`fail` with OUT_OF_SCOPE), claiming that capabilities such as
`file.search` were not allowed: the OOS message alone is far too strong.

## Round 2: C2 = gate + hint + per-cap grammar (no surface change, no OOS message)

63/100, in scope 28/42, false actions 23. The gate's label differed from the zero-shot label on 19 of the
73 items it saw although the question is the same; the gate prompt carried one extra sentence. From here the
gate instruction is R1's zero-shot instruction word for word (tests/test_r1_remedies.py checks it).

## Round 3: C1 again (gate prompt now identical to zero-shot), C3 = C1 without the OOS message

C1: 74/100, in scope 19/42, false actions 3, planner `fail` 14 of 39 planned.
C3: 70/100, in scope 23/42, false actions 11, planner `fail` 0, invalid 3.

## CLINC150 development (150 val utterances, act/abstain correct; always abstain = 94)

| config | act/abstain /150 | acts | planner invalid |
|---|---|---|---|
| C0 | 89 | 83 | 15 |
| C1 | 106 | 28 | 0 |
| C2 | 105 | 33 | 0 |
| zero-shot | 98 | — | — |
| C3 | 107 | 27 | 0 |

## Decision (frozen before any R1b run)

Rule: the configuration with the highest sum of nl2bash-dev top-1 and clinc-dev act/abstain correct.
C1 = 74 + 106 = 180, C3 = 70 + 107 = 177, C2 = 63 + 105 = 168, C0 = 53 + 89 = 142 (zero-shot 72 + 98 = 170).
**Treatment = C1** (`configs.json` → `treatment`). Exploratory on the R1b samples: C0, G, S, C3.

What development shows about C1, stated before R1b: it refuses much more than C0 and gets fewer in-scope
requests right (NL2Bash dev 19/42 against 25/42 for C0 and zero-shot); its planner refused 14 of the 39 dev
requests it planned. Its gain comes from abstaining correctly, which is also where the always-OUT_OF_SCOPE
reference scores (58/100, 94/150).
