# IIS project evidence: path map

This folder is an index. **Nothing has been moved into it.** Each folder below has references
outside itself (counts from `git grep`, `docs/AUDIT.md` §1.2), so it stays at its current path
until those references are rewritten or a symlink is left behind.

| path | what | status (README evaluation map) | refs outside |
|---|---|---|---:|
| `experiments/memory/` | semantic memory v0.1, extract-then-store vs store-everything, e5-base; bge-m3 swap | preregistered hypothesis; swap exploratory | 12 |
| `experiments/memory-preservation/` | memory before and after an update, 2026-10-03 | descriptive | 1 |
| `experiments/learning/` | learning provenance, recovery and comparison JSONs | descriptive (`docs/LEARNING_COMPARISON.md`) | 12 |
| `experiments/interests/` | news preference relevance checks | descriptive | 1 |
| `experiments/news/` | news runs and live-news JSON, 2026-09-18/19 | descriptive | 2 |

## Public datasets (2026-10-22)

| path | what | status |
|---|---|---|
| `experiments/iis/real-data/mind/` | news ranking and online learning on MIND-small dev (73,152 impressions) | exploratory, measured |
| `experiments/iis/real-data/locomo/` | memory retrieval against annotated evidence turns on LoCoMo (1,982 questions) | exploratory, measured |

Plain-language summary of both: [`real-data/README.md`](real-data/README.md).
