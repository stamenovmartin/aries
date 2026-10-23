# M14 live agent execution

Run: 20260917T220135Z-27c955

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | done | True | 2 | 3 | 9.215 |
| system-inspection | done | True | 1 | 2 | 4.091 |
| negative-control | failed | True | 1 | 2 | 4.612 |
| browser | done | True | 2 | 3 | 9.738 |

4/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.
