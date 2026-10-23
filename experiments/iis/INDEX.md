# IIS project evidence

The information layer: interests and news, learning from feedback, semantic memory. Plain-language summary of
the public-data results: [`real-data/README.md`](real-data/README.md).

## Public datasets (2026-10-22/23)

| path | what | status |
|---|---|---|
| [`real-data/mind/`](real-data/mind/) | news ranking and online learning on MIND-small dev (73,152 impressions, 50,000 users) | exploratory, measured: AUC 0.613, above all 7 baselines (best 0.600) |
| [`real-data/locomo/`](real-data/locomo/) | memory retrieval against annotated evidence turns on LoCoMo (1,982 questions) | exploratory, measured: BM25 0.500 beat the original memory 0.377 |
| M1 remedies on both (`docs/preregistration/M1-information-layer-remedies.md`) | LoCoMo hit@5 0.620 with `ARIES_MEMORY_HYBRID_RRF` + `ARIES_MEMORY_SIMILARITY_RANK`; MIND MMR AUC 0.611 vs round-robin 0.578; relative learning +0.000 | registered exploratory, measured; flags default off |

## Earlier series, in this folder

| path | what | status |
|---|---|---|
| [`memory/`](memory/) | semantic memory v0.1: extract-then-store vs store-everything, e5-base; bge-m3 swap (`scripts/aries-memory-eval` writes here) | preregistered hypothesis; swap exploratory |
| [`memory-preservation/`](memory-preservation/) | memory before and after an update, 2026-10-03 | descriptive |
| [`interests/`](interests/) | news preference relevance checks | descriptive |
| [`news/`](news/) | news runs and live-news JSON, 2026-09-18/19 | descriptive |
| `experiments/learning/` (top level) | learning provenance, recovery and comparison JSONs (`docs/LEARNING_COMPARISON.md`) | descriptive |

## Code

[`aries/interests/`](../../aries/interests/), [`aries/news/`](../../aries/news/),
[`aries/learning/`](../../aries/learning/), [`aries/workspace/memory/`](../../aries/workspace/memory/),
[`aries/workspace/retrieval.py`](../../aries/workspace/retrieval.py).
