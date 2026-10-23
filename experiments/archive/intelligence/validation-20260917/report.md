# Intelligence validation — 17 September 2026 UTC / 18 September local

- Complete regression set: ALL SUITES PASSED.
- Dedicated intelligence unit/integration checks: 52 passed.
- Native GTK navigation: 8/8.
- Final routing/intent fixture: 13/13; local intent 4/4; false/missed escalation 0 in this reused development fixture.
- Final agent execution demo: 4/4, including a real failed missing-file control.
- Paired execution B: 3/3; A unavailable because cloud is not configured/enabled. No measured savings or equivalence claim.
- Services: core, local gateway and Ollama active. Loopback listeners 11434/11435. User lingering enabled.
- Actual gateway outage: core/code stayed available; direct local inference fallback worked; service restored.
- Background health probes: zero cloud requests.
- Cloud response/accounting/failure tests use simulated providers. The real API correctly refuses unavailable cloud; no actual paid response measured.

Final complete regression output is in `full-regression.log`. Earlier failing retention-metadata and service-readiness runs are retained. These failures were corrected, not removed from the evidence.

Routing artifacts: `../20260917T220113Z-49e29a/`; paired attempt: `../20260917T220125Z-ab-8a2e51/`; execution artifact: `../../agent/20260917T220135Z-27c955/`.
