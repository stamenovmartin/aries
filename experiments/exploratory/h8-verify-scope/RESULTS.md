# H8 rerun with ARIES_VERIFY_SCOPE: result (exploratory, designed after H8)

Run `runs/20261022T081008Z-exploratory-verify-scope/` (records.jsonl, run.json, exploratory.json), 2026-10-22,
frozen H8 harness (`run_mutants.py` SHA-256 `4f17771d…`) through `run.py`, with `ARIES_VERIFY_SCOPE=1` and
`ARIES_VERIFY_HARDENED=0` (so it is compared with H8 baseline-2, not with the hardened run). Offline: no GPU,
no model, no ARIES service. 41.7 s.

| | this run | H8 baseline-2 (`h8/RESULTS.md`) |
|---|---|---|
| side-effect-outside-scope mutants killed | **12 / 14** | 0 / 14 |
| all mutants killed | 167 / 218 | 155 / 218 |
| false alarms on clean replays | 0 / 174 | — |
| harness errors | 0 | — |

The prediction written in README.md before the run was 12 of 14, with `file.write` and `browser.download`
surviving because the harness's stray file lands in a sibling folder outside the one-level scope. That is
what happened. The rule was not widened afterwards.

**Status:** exploratory. The check was designed after seeing H8, on H8's own mutants, so this is evidence that
the mechanism works on the failure it was built for, not an independent test. The confirmatory H8 result is
unchanged. `ARIES_VERIFY_SCOPE` stays off by default.
