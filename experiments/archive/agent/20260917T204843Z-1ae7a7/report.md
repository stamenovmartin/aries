# M14 live agent execution

Run: 20260917T204843Z-1ae7a7

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | done | True | 2 | 3 | 14.785 |
| system-inspection | done | True | 1 | 2 | 4.673 |
| negative-control | failed | True | 1 | 2 | 4.13 |
| browser | done | True | 2 | 3 | 11.35 |

4/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.
