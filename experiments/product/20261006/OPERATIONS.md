# Product foundations — 2026-10-06

This release adds a final inference egress gate, task/root attribution, durable shared budgets, scoped read-only runtime specialists, structured context selection, compound read contracts and a strict paired artifact evaluation gate. It does not implement autonomous policy evolution.

## Evidence

- `checks.json` and suite logs: 397 assertions across 11 focused suites, all passing. No full repository suite was run while the reviewing agent held a concurrent documentation claim.
- `component-trials.jsonl` / `component-evaluation.json`: five paired single-agent/team trials, 10/10 independently verified file reads, stable source hashes. Deterministic planners: no real token or cost savings can be inferred.
- `native-decomposition.json`: actual local model generated two valid specialist nodes.
- `native-team.json`: actual qwen2.5:7b, one compound system inspection, two completed runtime agents and independently verified root; 5 model calls, 5,199 native tokens, 8 executor/verifier invocations, about 8.18 seconds. This is a smoke test, not a general success rate.
- `release-manifest.json`: exact source hashes; source checkpoint in `var/product-releases/20261006-foundations/`. This captures the current dirty source, including prior work, not a pre-upgrade source backup.
- `deployment.json`: live restart/health evidence. Initial update script timed out receiving its maintenance lease; a fresh status confirmed its lease active and every queue drained before restart.

## Rollout and rollback

`ARIES_GOAL_TEAMS` and `ARIES_CONTEXT_ENGINE` default to false. Both can be enabled for a controlled run through existing environment or `var/flags.env` overrides. Environment takes precedence. Disable either by setting its override to `0`; preserve other entries. New roots then use the existing serial planner/context path. Existing team children retain grants, budgets and normal cancellation; disabling a flag does not unsafely replay or discard in-flight work. Drain with `scripts/aries-update` for source deployments. Do not drop budget tables or reset usage when resuming a root.

The provider egress gate and root budgets are security/accounting invariants, not unsafe ablation switches. Unclassified/private content stays local. Unknown consumption retains its reservation and holds the root. A positive financial cap refuses unpriced providers; a zero cap means no financial limit, not free inference. Token reservation is conservative; unexpected measured overrun is recorded and stops subsequent calls, not a guarantee against provider overrun.

There is no automatic production promotion, policy execution, source rewrite or persistent versioned policy rollback engine. `policy_evaluation.compare` evaluates complete paired artifacts only; unit fixtures are not admission evidence for a live candidate. Before slow evolution: bind candidates/results to source and fixture hashes, define held-out repeated trials, implement atomic versioned promotion/rollback, and evaluate failure injection and recovery.

## Remaining limitations

Teams currently support a bounded read-only surface, exact user-named file paths, up to four agents, and independently checkable contracts. Semantic goals without a root oracle remain partial. Calendar/project/message integration and general autonomous project repair are not completed by this release. Context currently retrieves memory, preserves source metadata, and discloses missing domains. Labels are trusted-assembler provenance, not comprehensive semantic PII detection. Conservative privacy gating can route a public goal locally when its assembled context includes personal state. The root budget covers generation and typed agent executor/verifier calls, not every legacy subsystem. Adaptive model optimization, long-duration validation and autonomous slow evolution remain outstanding. Product maturity is not 100%.

Final compatibility correction: the explicit cloud classification assembler binds its current request provenance; private requests still fail the final gate. A new test fixture initially used an invalid schema field (`complexity` instead of `estimated_complexity`); corrected and rerun, original failure log retained. New test entry points now propagate harness failure exit codes. Live single-agent API smoke: `live-smoke.json`, done with one independent proof, 2 calls and 4,493 native tokens.
