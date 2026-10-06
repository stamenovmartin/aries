# Live planner comparison

Measured: 2026-10-03T13:18:49.226779+00:00

| Backend | Plausible next decision (n) | Valid JSON (n) | Valid schema (n) | Median seconds |
|---|---:|---:|---:|---:|
| local | 21/23 | 23/23 | 21/23 | 7.571 |
| cloud | 23/23 | 23/23 | 23/23 | 6.46 |

Identical frozen23 payloads; fallback disabled; actual local/cloud backends called. No actions executed. This scores plausible next capability/action and schema, not end-to-end goal completion or fully correct arguments. Continuation fixtures contain seeded observations.

Unusable decisions: local:app.en chose desktop.launch; local:music.mk chose desktop.launch

Routing policy remains unchanged; the user decides after reviewing evidence. One daily sample, not a longitudinal accuracy estimate.

## Same-day instruction change

Before artifact: experiments/planner/20261003T130053Z-daily-local-cloud

| Backend | Before plausible (n) | After plausible (n) | Before median s | After median s |
|---|---:|---:|---:|---:|
| local | 22/23 | 21/23 | 5.838 | 7.571 |
| cloud | 23/23 | 23/23 | 5.987 | 6.46 |

One sample per case/backend before and after. Prompt wording separates desktop windows from browser tabs. Model nondeterminism and shared load remain; no causal latency or held-out generalization claim.

Candidate accepted: False
Local usable decisions regressed22/23 to21/23; cloud unchanged23/23. Corrected windows.mk but lost valid arguments in app.en and music.mk.
Candidate never deployed to core; own instruction change reverted to measured baseline hash.
