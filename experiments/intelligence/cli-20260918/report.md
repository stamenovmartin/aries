# Terminal cloud integration validation

Cloud uses installed `the reviewing agent` / `codex` authentication. This installation has
cloud enabled with `codex-cli` selected. No new API key was required.

- Codex direct constrained decision: passed, native usage recorded.
- the reviewing agent initial request: session quota 429, explicitly failed.
- Real Codex execution A/B: A 3/3, B 3/3, including an expected failed missing-file task.
- A: 6 cloud calls, 77,151 native total tokens including cached input.
- B: 0 cloud calls, 4 local calls plus deterministic system probe.
- Complete regression: ALL SUITES PASSED; 63 intelligence checks.
- CLI cost is account/subscription usage; no USD invoice is inferred from tokens.

Paired artifact: ../20260917T222712Z-ab-f2e66d/result.json.
This is a three-case engineering comparison, not a held-out general task benchmark.
No model shell execution is authorized: CLI tools are disabled, and returned
JSON still passes the existing ARIES policy/executor/verifier boundaries.
