# M14 live agent execution

Run: 20260917T205349Z-bb1a48

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | done | True | 2 | 3 | 10.243 |
| system-inspection | done | True | 1 | 2 | 4.67 |
| negative-control | failed | True | 1 | 2 | 4.108 |

3/3 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.
