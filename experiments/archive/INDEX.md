# Archive

Superseded or one-off series, kept as evidence. No frozen measurement reads them. A few older entry points
still run from here and were pointed at the new paths: `scripts/aries-demo` and `scripts/aries-agent-demo`
(`workspace/`, `agent/`), `scripts/aries-intelligence-ab` and `scripts/aries-intelligence-eval`
(`intelligence/`), `scripts/aries-computer-benchmark` (`aries100/`) and `scripts/aries-production-check`
(writes to `readiness/`). Scripts that compute the repository root from their own location were updated for the new depth
(`parents[k]` → `parents[k+1]`); their results are unchanged files.

| path | what |
|---|---|
| [`agent/`](agent/) | agent run evidence, 2026-09-17; superseded by `eval/agent_suite` and the held-out run |
| [`architecture/`](architecture/) | 2026-10-06 architecture review (findings, focused-check logs) |
| [`aries100/`](aries100/) | ARIES-100 benchmark, self-declared superseded on 2026-10-03 |
| [`background/`](background/) | 2026-09-19 background-mode validation logs |
| [`hardening/`](hardening/) | maintenance and screen-lock policy logs |
| [`intelligence/`](intelligence/) | router A/B runs, 2026-09-17..24, precursor of the thesis router runs |
| [`readiness/`](readiness/) | readiness reports, 2026-09-19..10-01 |
| [`remediation/`](remediation/) | 2026-10-01/03 remediation logs |
| [`ui/`](ui/) | Settings-page latency measurement |
| [`workspace/`](workspace/) | workspace acceptance protocol, 2026-09-14, superseded |
| [`router-rejected-handoff/`](router-rejected-handoff/) | a rejected router candidate (`decision.json` and two `.py` files) |
| [`runtime/`](runtime/) | `no-login-update/` logs |
| [`stability-watch/`](stability-watch/) | `watch.py` and two 2026-10-03 smoke samples |
| [`intent-confidence/`](intent-confidence/) | calibrated intent classification probe and its fixture; cited in `aries/workspace/memory/calibration.py` |

Historical records (`thesis-followup-20261012/revert-tests/revert-plan.json`, the raw inventories under
`product/independent-acceptance/raw/`) name the old paths; they describe the tree at their own commit and are
not edited.

## Deleted, recorded here

| was | what it was | note |
|---|---|---|
| `mmsasr.tsv` (repository root) | a saved S3 `AccessDenied` XML error body, 1 line | a failed download, not data |
| `experiments/orchestrator/` | an empty `.gitkeep` | **evaluation owed:** the orchestrator milestone design and evaluation (`docs/EXPERIMENTS.md`, "orchestrator/, dynamic_agents/, model_router/, evolution/") |
| `experiments/dynamic_agents/` | an empty `.gitkeep` | **evaluation owed:** single agent vs fixed multi-agent vs dynamic team, measuring whether a dynamic team helps or only spends more tokens (same section of `docs/EXPERIMENTS.md`) |
| `experiments/model_router/` | an empty `.gitkeep` | **evaluation owed:** the model router milestone (same section) |
| `experiments/evolution/` | an empty `.gitkeep` | **evaluation owed:** the evolution milestone (same section) |

When one of these evaluations starts, make its folder under `experiments/thesis/`.
