# M14 live agent execution

Run: 20260917T203732Z-b2ba9e

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | done | True | 2 | 3 | 9.141 |
| system-inspection | done | True | 1 | 2 | 4.117 |
| negative-control | partial | False | 1 | 20 | 19.811 |
| browser | done | True | 2 | 3 | 9.694 |

3/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.

negative-control: No current verified evidence satisfies {"capability": "file.read", "path": "/this/path/does/not/exist/aries.txt"}
