# M14 live agent execution

Run: 20260917T203544Z-497bea

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | partial | False | 8 | 9 | 21.281 |
| system-inspection | done | True | 1 | 2 | 4.155 |
| negative-control | failed | False | 0 | 20 | 11.677 |
| browser | done | True | 2 | 3 | 9.666 |

2/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.

file-workflow: Action budget exhausted without verified goal completion

negative-control: Finish requires existing verified evidence IDs; unknown/failed references rejected
