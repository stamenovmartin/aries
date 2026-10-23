# IIS on public data: news ranking (MIND) and memory retrieval (LoCoMo)

This folder tests two parts of the ARIES information layer on public datasets that ARIES was never developed on.
Both evaluations are **exploratory**: they were not preregistered as hypothesis tests. All design choices were
fixed before the runs and are written in each folder's `NOTES.md`. No parameter was tuned on the evaluation data.

The datasets are not in the repository (their licences, and the rule that external data is never committed).
`download.sh` in each folder fetches them and checks their SHA-256. The result files hold aggregate numbers only.

## 1. News ranking on MIND-small

**The question.** ARIES keeps an interest profile (topics with weights) and scores each news item against it.
Does that profile rank the news a person actually clicked above the news they skipped, compared with standard
baselines? And does ARIES's online learning (adjusting weights from clicks) help?

**The data.** MIND-small dev (Microsoft News, Wu et al., ACL 2020): 73,152 impressions from 50,000 users. In
each impression a user saw several news items and clicked some of them. A user's interest profile is built
from the news in their click history.

**The result** (`mind/results/mind-dev-20261022T142633Z.json`; 95% intervals by bootstrap over users):

| System | AUC | MRR | nDCG@10 |
|---|---|---|---|
| **ARIES interests (static profile)** | **0.6134** [0.6112, 0.6154] | 0.2956 | 0.3802 |
| ARIES interests + online learning | 0.6135 [0.6113, 0.6155] | 0.2957 | 0.3803 |
| Embedding (e5, history vs candidate) | 0.6000 [0.5978, 0.6022] | 0.2835 | 0.3633 |
| ARIES interests + diversity re-ranking | 0.5782 | 0.2805 | 0.3527 |
| Popularity | 0.5780 | 0.2694 | 0.3521 |
| BM25 | 0.5779 | 0.2652 | 0.3456 |
| TF-IDF | 0.5729 | 0.2649 | 0.3436 |
| Most recent | 0.5141 | 0.2142 | 0.2915 |
| Random | 0.4991 | 0.2177 | 0.2852 |

- The ARIES profile beats every baseline. Against the strongest, the embedding baseline, the paired AUC
  difference is +0.0134 [0.0109, 0.0160]; against popularity it is +0.0354.
- **The online learning changes almost nothing:** +0.0001 AUC [0.00003, 0.00018]. On this data the learning
  rule moves the weights too little to change the ranking.
- The diversity re-ranking costs 0.035 AUC.
- For scale only: on the full MIND test split, the original paper reports AUC 0.599 (LibFM) to 0.678 (NRMS)
  for models trained on MIND (`mind/reference-published.json`). That is a different split and dataset size,
  and ARIES is not trained on MIND, so it is context, not a comparison under the same conditions.

## 2. Memory retrieval on LoCoMo

**The question.** ARIES stores parts of a conversation in its semantic memory and later retrieves them to answer
a question. When a question is asked, are the dialogue turns that the dataset annotators marked as the
evidence among the top 5 rows retrieved?

**The data.** LoCoMo (Maharana et al., ACL 2024): 10 long conversations, 5,882 turns, 1,982 questions with
annotated evidence turns. Each conversation is fed to ARIES turn by turn; answers are not generated or scored.

**The result** (`locomo/results/locomo-20261022T142603Z.json`; intervals by conversation-cluster bootstrap):

| Memory variant | hit@5 | MRR |
|---|---|---|
| **BM25 over every turn (baseline)** | **0.500** [0.478, 0.521] | 0.359 |
| ARIES store, e5 embedder | 0.377 [0.359, 0.396] | 0.258 |
| ARIES store + write cascade, e5 | 0.375 [0.357, 0.395] | 0.257 |
| ARIES store, bge-m3 embedder | 0.349 [0.320, 0.378] | 0.232 |
| ARIES store + write cascade, bge-m3 | 0.349 [0.320, 0.378] | 0.232 |
| ARIES verbatim-focused retrieval (earlier run) | 0.196 | — |

- **A plain keyword baseline beats ARIES memory** by 0.12 hit@5 (ARIES e5 minus BM25: −0.123, conversation
  interval [−0.140, −0.104]; McNemar on hit@5: 277 items better, 521 worse, p = 4 × 10⁻¹⁸).
- By question type it is not uniform: ARIES e5 is **better** on multi-hop questions (+0.106 [0.054, 0.172]),
  similar on open-domain (+0.087 [−0.019, 0.190]), and worse on temporal (−0.128), single-hop (−0.152) and
  adversarial (−0.253) questions.
- The write cascade (a local model decides per turn whether to store, merge or skip) made 5,657 model calls
  and did not change retrieval.
- The store gate is not the cause: 99.6% of the questions still have an evidence turn stored.

## 3. After the first results: remedies (M1, registered exploratory)

Registered in `docs/preregistration/M1-information-layer-remedies.md` before the runs. Both datasets had
already been used, so these are **exploratory** numbers; a confirmatory test needs unseen data (for memory,
LongMemEval).

**LoCoMo** (`locomo/results/locomo-20261022T193500Z.json`, same 1,982 questions, same rows as
`embedding-only-e5`, only the ranking differs; intervals are conversation-cluster bootstrap):

| Ranking | hit@5 | vs BM25 | vs ARIES e5 (semantic-v3) |
|---|---|---|---|
| BM25 | 0.500 | — | |
| ARIES e5, semantic-v3 (as shipped) | 0.377 | −0.123 [−0.140, −0.104] | — |
| hybrid RRF + recency/importance (`ARIES_MEMORY_HYBRID_RRF`) | 0.492 | −0.008 [−0.029, 0.017] | +0.116 |
| cosine only, no recency/importance (ablation) | 0.603 | +0.103 [0.077, 0.133] | +0.226 |
| RRF only, no recency/importance (ablation) | 0.621 | +0.121 [0.098, 0.147] | +0.244 |
| `ARIES_MEMORY_HYBRID_RRF` + `ARIES_MEMORY_SIMILARITY_RANK` (designed after the run above) | 0.620 | +0.120 [0.098, 0.147] | +0.243 |

- **The cause was not the embedder but the ranking formula.** semantic-v3 adds recency (half-life 72 hours
  for an utterance) and importance to the similarity. In conversations that span months this pushes every
  early session down. Without those terms the same e5 rows beat BM25 by 0.10–0.12.
- `ARIES_MEMORY_SIMILARITY_RANK` (default off) makes similarity decide and leaves recency, importance and
  layer as tie-breaks. It was designed after this result; its LoCoMo number (last row, run
  `locomo-20261022T200243Z.json`) is therefore exploratory, not a confirmation.

**MIND-small dev** (`mind/results/mind-dev-20261022T193501Z.json`, 73,152 impressions):

| System | AUC |
|---|---|
| ARIES interests | 0.613 |
| + round-robin diversity (as shipped) | 0.578 |
| + MMR diversity (`ARIES_NEWS_DIVERSE_TOPK`) | 0.611 |
| learning, absolute bars (as shipped) | 0.6135 |
| learning, relative bars (`ARIES_LEARNING_RELATIVE_CTR`) | 0.6134 |

- **MMR recovers almost all of the diversity cost:** +0.033 [0.031, 0.034] over round-robin, −0.003 against
  no diversity at all.
- **Relative learning does not help, and the expectation behind it was wrong.** The absolute rule was not
  idle: it changed 4,031 topic weights (mostly down, because almost every topic is below a 10% click rate);
  the relative rule changed 453. Neither moves AUC. Learning from clicks does not improve ranking on MIND.

## What this means

On news ranking, the hand-built ARIES interest profile is a real improvement over simple baselines, and
MMR keeps diversity almost free; the learning on top of it does not add anything measurable, with either
rule. On conversational memory, the first run made ARIES look weaker than keyword search; M1 shows that the
recency and importance terms of the ranking were the cause. With similarity deciding the order (and BM25
fused in), ARIES retrieves the evidence in the top 5 for 62% of the questions, against 50% for BM25. Both
remedies are behind flags, default off, and exploratory until measured on unseen data.

## Reproduce

```
bash experiments/iis/real-data/mind/download.sh
OPENBLAS_NUM_THREADS=1 nice -n 19 .venv/bin/python experiments/iis/real-data/mind/mind_eval.py --data ~/data-ext/mind --embedding
bash experiments/iis/real-data/locomo/download.sh
OPENBLAS_NUM_THREADS=1 nice -n 19 .venv/bin/python experiments/iis/real-data/locomo/locomo_eval.py \
    --variants bm25,embedding-only-e5,cascade-e5,embedding-only-bge-m3,cascade-bge-m3
```

The embedding and cascade variants need the local models (`var/models`, Ollama with bge-m3 and qwen2.5:7b).
