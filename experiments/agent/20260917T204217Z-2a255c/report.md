# M14 live agent execution

Run: 20260917T204217Z-2a255c

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | done | True | 2 | 3 | 10.792 |
| system-inspection | done | True | 1 | 2 | 4.654 |
| negative-control | failed | False | 0 | 1 | 3.078 |
| browser | done | True | 2 | 3 | 13.412 |

3/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.

negative-control: The file does not exist at the specified path.
