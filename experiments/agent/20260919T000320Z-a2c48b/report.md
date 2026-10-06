# M14 live agent execution

Run: 20260919T000320Z-a2c48b

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | done | True | 2 | 3 | 23.018 |
| system-inspection | done | True | 1 | 2 | 8.127 |
| negative-control | failed | True | 1 | 2 | 5.088 |
| browser | done | True | 2 | 3 | 12.284 |

4/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.
