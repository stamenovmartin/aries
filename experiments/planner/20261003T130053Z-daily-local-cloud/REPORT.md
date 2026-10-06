# Live planner comparison

Measured: 2026-10-03T13:00:54.537833+00:00

| Backend | Plausible next decision (n) | Valid JSON (n) | Valid schema (n) | Median seconds |
|---|---:|---:|---:|---:|
| local | 22/23 | 23/23 | 23/23 | 5.838 |
| cloud | 23/23 | 23/23 | 23/23 | 5.987 |

Identical frozen23 payloads; fallback disabled; actual local/cloud backends called. No actions executed. This scores plausible next capability/action and schema, not end-to-end goal completion or fully correct arguments. Continuation fixtures contain seeded observations.

Local failure: windows.mk chose browser.tabs

Routing policy remains unchanged; the user decides after reviewing evidence. One daily sample, not a longitudinal accuracy estimate.
