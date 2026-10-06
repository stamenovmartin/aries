# M14 live agent execution

Run: 20260917T205446Z-0a6b2a

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | done | True | 2 | 3 | 10.269 |
| system-inspection | done | True | 1 | 2 | 4.098 |
| negative-control | failed | True | 1 | 2 | 4.09 |
| browser | done | True | 2 | 3 | 9.255 |

4/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.
