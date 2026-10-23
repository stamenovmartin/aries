# M1: information-layer remedies on LoCoMo and MIND-small (registered exploratory)

**Registered:** 2026-10-22, after the first LoCoMo and MIND-small results
(`experiments/iis/real-data/locomo/results/locomo-20261022T142603Z.json`,
`experiments/iis/real-data/mind/results/mind-dev-20261022T142633Z.json`) and before any run of the variants
below. Committed before those runs. Any later change goes into a dated Amendment section in a new commit.

**Label: exploratory.** Both datasets have already been used, and the remedies were designed after their
results. This file fixes the variants, the comparisons and the expected directions before the runs, so that
the runs cannot be chosen after the fact. It does **not** make them confirmatory, and no result here enters a
Holm family. A confirmatory test needs data not yet seen (for memory, for example LongMemEval,
arXiv:2410.10813).

## The remedies (each behind its own flag, default off)

| flag | what it changes | why (from the first results) |
|---|---|---|
| `ARIES_MEMORY_HYBRID_RRF` | semantic-v3's similarity term becomes the Reciprocal Rank Fusion (k = 60; Cormack, Clarke and Buettcher, SIGIR 2009) of the cosine ranking and a BM25 ranking (k1 = 1.2, b = 0.75) of the same rows; recency, importance and layer are added as before | BM25 hit@5 0.500 vs ARIES e5 0.377 on 1,982 LoCoMo questions, and the two miss different questions (e5 better on multi-hop by +0.106) |
| `ARIES_LEARNING_RELATIVE_CTR` | the ordinary learning path's bars become min(setting, 2 × the user's pooled engagement rate) for "engaged" and min(setting, 0.5 × rate) for "ignored" | MIND's click-through rate is about 4%, so the absolute bars 0.4 and 0.1 are never crossed and learning added +0.0001 AUC |
| `ARIES_NEWS_DIVERSE_TOPK` | the briefing picks by Maximal Marginal Relevance (λ = 0.7, redundancy = the primary topic is already picked) instead of round-robin over topics | round-robin cost 0.035 AUC on MIND |

The constants (k = 60, ratios 2.0 and 0.5, λ = 0.7) are the literature default (RRF) or fixed by hand before
any run; none is fitted on LoCoMo or MIND.

## LoCoMo (`experiments/iis/real-data/locomo/locomo_eval.py`)

Same data (SHA-256 `79fa87e9…`), same hit rule, same metrics, bootstrap and seed as the first run. All three
new variants store the same rows as `embedding-only-e5` (stage-1 gate, every permitted turn), so only the
ranking differs:

- `hybrid-rrf-e5`: semantic-v3 with `ARIES_MEMORY_HYBRID_RRF=1` (the shipped change).
- `cosine-only-e5`: ablation, cosine alone, no recency, importance or layer term.
- `rrf-only-e5`: ablation, the fused rank alone, no recency, importance or layer term.

One run: `--variants embedding-only-e5,hybrid-rrf-e5,cosine-only-e5,rrf-only-e5` (bm25 is always added).
Comparisons (paired, item bootstrap within conversations and conversation-cluster bootstrap, as before):
each new variant minus `bm25`, and each new variant minus `embedding-only-e5`. Expected directions, stated
now: `hybrid-rrf-e5` > `embedding-only-e5` on hit@5; `hybrid-rrf-e5` ≥ `bm25` is uncertain and is the
question of interest; `cosine-only-e5` > `embedding-only-e5` would show that the recency term costs
retrieval on LoCoMo's months-long conversations.

## MIND-small dev (`experiments/iis/real-data/mind/mind_eval.py`)

Same data, same prequential order, same metrics and user bootstrap (1,000 replicates, seed 20261022) as the
first run, with `--embedding` so the embedding baseline is in the same file. Two systems are added:

- `aries-interests+mmr`: the static ARIES ranking re-ordered by MMR (`ARIES_NEWS_DIVERSE_TOPK`).
- `aries-learning-relative`: the learning layer with `ARIES_LEARNING_RELATIVE_CTR`.

Comparisons: `aries-interests+mmr` − `aries-interests` and − `aries-interests+diverse`;
`aries-learning-relative` − `aries-interests` and − `aries-learning`. Expected directions: MMR costs less AUC
than round-robin; relative learning changes more topic weights than the absolute rule (counted in
`diagnostics`), with its AUC effect of unknown sign. Warming the learner on MIND train is not part of M1.

## Limitations stated in advance

- Both datasets are already seen; these are exploratory numbers.
- LoCoMo evidence labels were not audited; MIND labels are logged clicks.
- One run each; the LoCoMo retrieval and MIND scoring are deterministic given the data and code.
