# M14 live agent execution

Run: 20260917T203400Z-51901a

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | failed | False | 0 | 2 | 3.578 |
| system-inspection | failed | False | 0 | 2 | 1.036 |
| negative-control | failed | False | 0 | 2 | 2.047 |
| browser | failed | False | 0 | 2 | 2.041 |

0/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.

file-workflow: Planner output remained invalid after two recorded attempts

system-inspection: Planner output remained invalid after two recorded attempts

negative-control: Planner output remained invalid after two recorded attempts

browser: Planner output remained invalid after two recorded attempts
