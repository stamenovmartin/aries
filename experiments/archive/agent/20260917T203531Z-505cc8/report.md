# M14 live agent execution

Run: 20260917T203531Z-505cc8

Engineering acceptance, not a held-out model benchmark; every attempt retained.

| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |
|---|---|---|---:|---:|---:|
| file-workflow | error | False | — | — | 0.002 |
| system-inspection | error | False | — | — | 0.0 |
| negative-control | error | False | — | — | 0.0 |
| browser | error | False | — | — | 0.0 |

0/4 required checks passed.
Excluded: none

Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.

file-workflow: URLError: <urlopen error [Errno 111] Connection refused>

system-inspection: URLError: <urlopen error [Errno 111] Connection refused>

negative-control: URLError: <urlopen error [Errno 111] Connection refused>

browser: URLError: <urlopen error [Errno 111] Connection refused>
