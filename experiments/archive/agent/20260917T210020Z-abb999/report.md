# M14 live agent execution

Run: 20260917T210020Z-abb999

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | done | True | 2 | 3 | 13.26 |
| system-inspection | done | True | 1 | 2 | 4.649 |
| negative-control | failed | True | 1 | 2 | 4.07 |
| browser | done | True | 2 | 3 | 10.244 |

4/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.
