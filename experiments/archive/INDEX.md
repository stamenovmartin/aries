# Archive

These are superseded or one-off experiment folders. Each one was moved here only when both of
these held:
- `docs/AUDIT.md` §1.2 marked it "move → archive";
- `git grep` found no path reference to it outside itself.

The only mentions left were bare names in the historical inventory
`experiments/product/independent-acceptance/raw/repo_facts.json`, and those still resolve. Each
moved item has a relative symlink at its old path, so `experiments/<name>` keeps working.

## Moved here (symlink at the old path)

| now | old path (symlink) | what |
|---|---|---|
| `experiments/archive/router-rejected-handoff/` | `experiments/router-rejected-handoff` | a rejected router candidate (`decision.json` and two `.py` files) |
| `experiments/archive/runtime/` | `experiments/runtime` | `no-login-update/` logs |
| `experiments/archive/stability-watch/` | `experiments/stability-watch` | `watch.py` and two 2026-10-03 smoke samples. Its `ROOT` was changed from `parents[2]` to `parents[3]` for the new depth; it resolves the same root through the symlink |
| `experiments/archive/intent_fixture.json` | `experiments/intent_fixture.json` | a fixture that nothing reads; `intent_confidence.py` stays in place because `aries/workspace/memory/calibration.py:12` cites it |

## Marked "archive" by the audit, still in place (referenced)

| path | refs outside | why it stays |
|---|---:|---|
| `experiments/agent/` | 14 | superseded by `eval/agent_suite`; the refs need rewriting or a symlink |
| `experiments/architecture/` | 3 | one-off review |
| `experiments/aries100/` | 3 | self-declared superseded on 2026-10-03; `scripts/aries-computer-benchmark` goes with it |
| `experiments/background/` | 1 | one-off |
| `experiments/hardening/` | 1 | one-off |
| `experiments/intelligence/` | 7 | router A/B runs, precursor of the thesis runs |
| `experiments/readiness/` | 3 | one-off |
| `experiments/remediation/` | 3 | one-off |
| `experiments/ui/` | 1 | one-off |
| `experiments/workspace/` | 12 | superseded acceptance protocol |

## Deleted, recorded here

| was | what it was | note |
|---|---|---|
| `mmsasr.tsv` (repository root) | a saved S3 `AccessDenied` XML error body, 1 line | a failed download, not data |
| `experiments/orchestrator/` | an empty `.gitkeep` | **evaluation owed:** the orchestrator milestone design and evaluation (`docs/EXPERIMENTS.md`, "orchestrator/, dynamic_agents/, model_router/, evolution/") |
| `experiments/dynamic_agents/` | an empty `.gitkeep` | **evaluation owed:** single agent vs fixed multi-agent vs dynamic team, measuring whether a dynamic team helps or only spends more tokens (same section of `docs/EXPERIMENTS.md`) |
| `experiments/model_router/` | an empty `.gitkeep` | **evaluation owed:** the model router milestone (same section) |
| `experiments/evolution/` | an empty `.gitkeep` | **evaluation owed:** the evolution milestone (same section) |

When one of these evaluations starts, make its folder again at the old path.
