# Thesis data tables

One CSV per thesis table. The first line of each names its source files, with each file's SHA-256 and last
commit, and the table's label (confirmatory, regression check or exploratory). An optional `# note:` line follows.

| CSV | Content |
|---|---|
| `router_arms.csv` | router metrics per arm, qwen2.5:7b and llama3.1:8b |
| `router_by_class.csv` | binary correctness per true class and arm |
| `router_tests.csv` | per-request tests (McNemar, Cochran's Q, GEE, GLMM), exploratory |
| `verifiers_ledger.csv` | verifier classes and ledger outcomes |
| `heldout_by_class.csv` | held-out fixture per class, with terminal states |
| `terminal_end_paths.csv` | terminal end paths |
| `contract_coverage.csv` | static contract counts, paraphrase flag off and on |
| `planner_runs.csv` | the three planner runs (frozen, clarify alone, clarify + guard) |
| `h4_dev_cases.csv`, `h4_dev_rounds.csv` | H4 development rounds, per case and totals |
| `h8_fault_injection.csv` | H8 kill rates, criteria and McNemar per run (confirmatory, sealed check, exploratory 23+2, superseded run 1) |

    .venv/bin/python experiments/thesis-followup-20261012/thesis-tables/check.py           # check
    .venv/bin/python experiments/thesis-followup-20261012/thesis-tables/check.py --write   # rewrite

Check mode rebuilds every table, recomputes it a second way where the raw data allows, and exits 1 on any
difference. It needs only files tracked in this repository; folder hashes leave out git-ignored files.
