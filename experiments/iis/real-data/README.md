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

## What this means

On news ranking, the hand-built ARIES interest profile is a real improvement over simple baselines, but the
learning on top of it does not add anything measurable here. On conversational memory, ARIES's embedding
retrieval is clearly weaker than keyword search over the raw turns overall, though it helps on multi-hop
questions. A hybrid (keyword plus embedding) is the
obvious next step and has not been tested.

## Reproduce

```
bash experiments/iis/real-data/mind/download.sh
OPENBLAS_NUM_THREADS=1 nice -n 19 .venv/bin/python experiments/iis/real-data/mind/mind_eval.py --data ~/data-ext/mind --embedding
bash experiments/iis/real-data/locomo/download.sh
OPENBLAS_NUM_THREADS=1 nice -n 19 .venv/bin/python experiments/iis/real-data/locomo/locomo_eval.py \
    --variants bm25,embedding-only-e5,cascade-e5,embedding-only-bge-m3,cascade-bge-m3
```

The embedding and cascade variants need the local models (`var/models`, Ollama with bge-m3 and qwen2.5:7b).
