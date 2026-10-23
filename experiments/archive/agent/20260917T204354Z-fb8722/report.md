# M14 live agent execution

Run: 20260917T204354Z-fb8722

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | done | True | 2 | 3 | 10.734 |
| system-inspection | done | True | 1 | 2 | 4.166 |
| negative-control | failed | True | 1 | 2 | 4.154 |
| browser | done | True | 2 | 3 | 10.853 |

4/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.
