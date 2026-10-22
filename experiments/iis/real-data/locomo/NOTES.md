# LoCoMo: retrieval against annotated evidence turns

This is the real-data evaluation of ARIES's semantic memory for the IIS project. Each LoCoMo
conversation is passed through an ARIES memory variant one turn at a time. For every QA item
the question is used as the retrieval request, and we score whether the top 5 rows include a
turn that the dataset annotators marked as evidence for that item.

## Data and licence

- File: `locomo10.json`, from
  `https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json`, with
  SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
  `download.sh [DEST]` fetches the file and its LICENSE, and refuses both if the hash does not
  match. The default destination is `~/data-ext/locomo`. `locomo_eval.py` checks the hash again
  every time it runs.
- Licence: CC BY-NC 4.0. The LICENSE file sits beside the data.
- Citation: Maharana, Lee, Tulyakov, Bansal, Barbieri, Fang. "Evaluating Very Long-Term
  Conversational Memory of LLM Agents", ACL 2024.
- **Nothing from the dataset is committed**: no dataset, no turn text, no questions, no per-item
  outcomes. `results/*.json` hold only aggregates: counts, means, intervals and
  per-conversation hit@5.
- Contents: 10 conversations, 5,882 turns across 272 sessions, 1,986 QA items, and 1,226 turns
  that share a photo.

## Why evidence and not answers

`aries/workspace/memory_eval.py` states why ARIES originally avoided LoCoMo: **6.4% of its
answer key is wrong**, and tuning against wrong gold labels teaches the system those errors.
This evaluation never reads an answer string. It scores **retrieval**, the part that ARIES's
semantic memory is responsible for, against a different label: the evidence dialogue ids
(`D<session>:<turn>`) attached to each item. Answer generation is not evaluated. Evidence
labels can also be wrong. We did not audit them, so this measures agreement with LoCoMo's
annotation and does not establish ground truth.

## What is measured

- **Hit rule.** A stored row carries `sources`, the dialogue ids it was built from. A row is a
  hit for an item when any of its sources is one of the item's evidence ids. A row the cascade
  merged (see below) carries every id that was merged into it.
- **Metrics over the top 5:** hit@1, hit@3, hit@5, MRR (rank of the first hit; 0 if none in the
  top 5), and evidence recall@5 (the share of an item's evidence ids that the top 5 cover; this
  is mainly useful for multi-hop). `gold_storable` is the share of items with at least one
  evidence turn present in the store. It is the ceiling that the gate and the cascade impose.
- **Groups:** `all` (categories 1–5), `non-adversarial (1-4)`, and each category separately.
- **Category names.** LoCoMo stores the category as a number only. The names come from the
  comments in the official scorer, `snap-research/locomo/task_eval/evaluation.py`, which
  labels the category-1 branch "multi-hop", the category-5 branch "adversarial", and the joint
  2/3/4 branch "single-hop, temporal, open-domain". The data were used to work out which of
  2/3/4 is which:

  | n | category | evidence per item | items whose evidence spans >1 session | name |
  |---|---|---|---|---|
  | 1 | 282 | 3.14 | 96% | multi-hop |
  | 2 | 321 | 1.17 | 9% (77% of questions begin "When") | temporal |
  | 3 | 96 | 2.17 | 35% (inference: "would … be likely to") | open-domain |
  | 4 | 841 | 1.06 | 0.1% | single-hop |
  | 5 | 446 | 1.03 | 0% | adversarial |

  So the mapping is 1 multi-hop, 2 temporal, 3 open-domain, 4 single-hop, 5 adversarial. The
  order of the numbers does not match the order in which the paper lists the categories. The
  mapping rests on the scorer's comments and on the statistics in the table, not on an explicit
  table in the paper.
- **Adversarial (category 5).** 444 of 446 items have `adversarial_answer` and no `answer`. The
  question carries a false premise, usually by attributing one speaker's event to the other.
  These items still have evidence ids, namely the turn the premise was borrowed from. We score
  them exactly like the other categories: the question is whether retrieval finds the turn
  that would expose the false premise. They are reported separately, and the
  `non-adversarial (1-4)` group is reported alongside `all`.
- **Exclusion.** Evidence strings are normalised: every `D<s>:<t>` found in an entry is kept,
  which fixes the 6 malformed entries upstream, such as `D8:6; D9:17`, `D:11:26` and a bare
  `D`. An item is **excluded** in two cases: it has no parseable evidence (4 items, reason
  `no-evidence`), or none of its evidence ids exists in its conversation (0 items, reason
  `evidence-not-in-conversation`). 2 individual evidence ids point at turns that do not exist;
  they are dropped, and their items keep the evidence that remains. **1,982 items are scored.**
- **Intervals.** The 95% percentile bootstrap uses 10,000 replicates, seed 20261022, and is
  reported **two ways**. With only 10 conversations, the difference between the two matters:
  - *item-level*: items are resampled with replacement **within each conversation**
    (stratified). This treats the conversations as fixed and the items as the sample.
  - *conversation-cluster*: whole conversations are resampled with replacement, and the
    statistic is the ratio of sums. This treats conversations as the sampling unit and is
    the honest interval for generalising to new conversations. With 10 clusters it is coarse,
    and for a category concentrated in a few conversations it can be degenerate.
- **Paired differences.** Each variant is compared with `bm25`, and `cascade-X` with
  `embedding-only-X`, item by item. Both bootstraps are applied to the per-item differences. An
  exact McNemar test on hit@5 is added through ARIES's own `learning_eval.paired_statistics`.
  McNemar assumes independent items, and items within a conversation are not independent, so the
  cluster interval should be read first. `bm25` is recomputed in every run, which takes about
  2 s. That is why no per-item outcome ever needs to be written to disk for later pairing.

## Variants and how they reuse ARIES

| variant | what is stored | ranking |
|---|---|---|
| `bm25` | every turn, verbatim, with no gate | Okapi BM25, k1 = 1.2, b = 0.75, Lucene idf, casefolded `\w+` tokens, no stemming or stop words; ties keep storage order |
| `verbatim-focused` | every turn, verbatim | `retrieval.score_memories(..., "focused-v2")`, ARIES's own lexical fallback (extra, CPU only) |
| `embedding-only-e5` | stage 1 (`extraction.gate`) only; every permitted turn is stored | `retrieval.score_memories(..., "semantic-v3")` with e5-base-int8. This is `memory_eval`'s `verbatim-gated-semantic` |
| `embedding-only-bge-m3` | same as above | same, with bge-m3 through ollama |
| `cascade-e5` | the full cascade: `extraction.gate`, then `extraction.Cascade.run` (stage 2 novelty, stage 3 model) | `semantic-v3` with e5. This is `memory_eval`'s `extracted-semantic` |
| `cascade-bge-m3` | same as above | same, with bge-m3 |

The loop follows `memory_eval.build`. It does not call that function, for the reasons listed
under *What blocked faithful reuse* below:

1. `extraction.normalise` is applied to the turn. The stored text is `"<speaker>: <text>"`,
   plus ` [shares <blip_caption>]` when the turn shares a photo. The caption is LoCoMo's own
   text stand-in for the image. The speaker is kept because the questions use names, while
   ARIES's store models a single user.
2. Stage 1, `extraction.gate`, judges the **content without the speaker label**, because its
   command and question patterns are anchored at the start of the string.
3. The text is embedded once as a passage. The 5 nearest stored rows from a
   `vectors.VectorCache` become the neighbours for `Cascade.run`, as in `store.observe`.
4. The verdict is applied:
   - **NOOP** merges the turn into the neighbour it duplicated. Its dialogue id is appended to
     that row's `sources`, and the row's `last_retrieved_at` is set to the turn's time.
     `store.observe` refreshes recency the same way.
   - **ABORT** drops the turn.
   - **APPEND, COEXIST and SUPERSEDE** store a row. On SUPERSEDE **both** rows are kept, which
     is what the current store does: `arbitrate` never expires a USER statement, and
     `withdrawn_sources` returns an empty set.
5. Rows carry layer 60 (USER), `importance = IMPORTANCE[kind]` with `kind` from
   `classify_kind` or from the verdict, and `created_at = valid_at = the session's date and
   time`. Turns within a session are spaced one second apart so their order is kept.
6. Retrieval calls `retrieval.score_memories` with `now` set to the time of the conversation's
   last turn, since the questions are asked after the last session. `touch` is not applied:
   evaluation is read-only, as in `memory_eval`. If a row has no vector, the ranker refuses to
   run, so `semantic-v3` cannot silently fall back to `focused-v2`.

**The model stage is injectable.** `InjectableCascade` subclasses `extraction.Cascade` and runs
the shipped `decide`, which builds the prompt and few-shot examples and constructs the
`Verdict`. Only the function `decide` calls is replaced: `extraction.calibration` is rebound
for the duration of the call and then restored. With `classify=None` the real
`calibration.classify` runs against local ollama. The tests and `--dry-run-calls` pass a
constant function instead. If the model is unavailable, the shipped `Cascade.run` falls back to
APPEND. The runner counts these fallbacks and marks the variant `INVALID`, so a cascade run
against a dead model cannot be reported as a result for the cascade.

## Parameters: all ARIES defaults, nothing tuned on LoCoMo

Every value below is also written into each result file under `parameters`.

- Retrieval: `semantic-v3`, the `workspace.memory_retrieval` default. Weights are
  W_SIM = 1.0, W_RECENCY = 0.5, W_IMPORTANCE = 0.3, W_LAYER = 0.4, with MAX_LAYER = 80 and
  row layer = 60. Similarity is min-max rescaled across the candidates (`_rescale`).
- Half-lives in hours (`models.HALF_LIFE_HOURS`): identity 87,600; preference 4,320; fact
  8,760; plan 336; episodic 720; utterance 72. The fallback for `fact` is 8,760.
- Importance (`models.IMPORTANCE`): identity 0.9, preference 0.7, fact 0.6, plan 0.5,
  episodic 0.35, utterance 0.2. The default is 0.5.
- Cascade: `REDUNDANT_ABOVE` = 0.97, `NOVEL_BELOW` = 0.85, model `qwen2.5:7b`, context 4
  neighbours, timeout 30 s, 5 neighbours searched. These thresholds were calibrated on e5 (see
  `experiments/memory/analysis.md`). They are applied **unchanged** to bge-m3, where they made
  zero model calls on the 25-probe fixture.
- Gate: `MIN_CHARS` = 8, `MAX_CHARS` = 2000. `privacy.excluded_memory_topics` = [] and
  `privacy.remember_conversations` = true, both defaults.
- Embedders: `e5-base-int8` (max_tokens 256, 4 ORT threads, one sequence per graph call) and
  `bge-m3` through ollama (`OllamaEmbedder` defaults).
- k = 5.
- BM25: k1 = 1.2, b = 0.75. These are the textbook defaults and were not tuned.

## Results so far: `bm25` and `verbatim-focused` (CPU only)

The result file is `results/locomo-20261022T072458Z.json`. Over 1,982 scored items it reports
the mean, then the 95% CI from the item-level bootstrap, then the 95% CI from the
conversation-cluster bootstrap:

| bm25 | hit@1 | hit@3 | hit@5 | MRR@5 |
|---|---|---|---|---|
| all (n = 1982) | 0.274 [0.254, 0.294] [0.255, 0.293] | 0.429 [0.408, 0.452] [0.404, 0.456] | 0.500 [0.478, 0.522] [0.478, 0.521] | 0.359 [0.340, 0.378] [0.338, 0.381] |
| 1–4 (n = 1536) | 0.270 [0.249, 0.292] [0.246, 0.296] | | 0.489 [0.464, 0.514] [0.464, 0.512] | 0.353 [0.332, 0.374] [0.328, 0.378] |
| 1 multi-hop (282) | 0.124 | | 0.305 [0.252, 0.355] [0.228, 0.388] | 0.186 |
| 2 temporal (321) | 0.315 | | 0.567 [0.514, 0.617] [0.492, 0.634] | 0.411 |
| 3 open-domain (92) | 0.109 | | 0.261 [0.185, 0.348] [0.133, 0.386] | 0.168 |
| 4 single-hop (841) | 0.320 | | 0.546 [0.513, 0.579] [0.518, 0.574] | 0.407 |
| 5 adversarial (446) | 0.287 | | 0.538 [0.491, 0.583] [0.510, 0.573] | 0.382 |

`verbatim-focused`, ARIES's lexical `focused-v2` scoring over the same rows, reaches hit@5 =
0.196 [0.179, 0.214] [0.177, 0.219]. Its paired difference from bm25 is −0.304, with an
item-level CI of [−0.326, −0.281] and a cluster CI of [−0.332, −0.277]. 39 items improved and
641 regressed. It is worse in every category.

This was not investigated further, because diagnosing it would mean tuning. A plausible
explanation that has not been tested: `focused-v2` rescales a Jaccard over stems to [0, 1],
and then recency (0.5) and importance (0.3) are added. Over 400–700 long conversational turns,
those two terms can outweigh weak lexical overlap. `semantic-v3` uses the same additive terms,
so the embedding variants should be read with this in mind.

## Stage 1 on LoCoMo (no model needed: `census` in every result file)

- 5,882 turns are offered. Stage 1 refuses **74**: 63 as questions, 6 as too short, 3 as
  credentials and 2 as commands. **5,808 turns pass.**
- **8 evidence turns** (of 1,430 distinct ones) are refused by the gate, so the gated variants
  cannot retrieve them.
- Two false positives from the gate are visible in LoCoMo's ordinary English and are reported,
  not fixed:
  - The `SECRETS` pattern `token\w*\s*\S+` fires on "...visualize goals and **tokenize**
    successes".
  - `QUESTION` refuses exclamations that begin with "What", such as "What a photo! ... Last
    weekend I volunteered at a career fair...". That turn is a declarative statement of fact.

## Estimated cascade calls and wall time

The local model is reached only from stage 2's uncertain band, which needs real cosine
similarities and therefore the real embedder. Neither could be loaded now, so the estimate has
two parts:

- **Hard upper bound: 5,798 calls.** This is the turns that pass the gate (5,808) minus one per
  conversation, since the first permitted turn has no neighbour and is always APPENDed. The
  synthetic full-data run with `--fake-embedder` confirms that the pipeline runs end to end. Its
  call count reflects hash-vector cosines and **is not** an estimate.
- **Point estimate from the fixture rate: about 4,770 calls.** On the 25-probe fixture, e5
  escalated 27 of the 33 utterances that passed the gate (82%); see
  `experiments/memory/analysis.md` §7. Applying 82% to 5,808 gives about 4,770. LoCoMo turns
  are longer, and within one conversation they stay on related topics, so cosines are likely to
  fall in e5's compressed 0.83–0.99 band. The real count is therefore likely close to the upper
  bound and unlikely to be far below it.
- **bge-m3:** with the same e5-calibrated band, the fixture escalated nothing. Expect very few
  calls, and the arm then measures retrieval, not extraction (see `analysis.md`).

| calls | at 0.5 s | at 1.0 s | at 1.5 s | at 68 ms (measured in `calibration.py`) |
|---|---|---|---|---|
| 5,798 (upper bound) | 48 min | 1 h 37 min | 2 h 25 min | 6.6 min |
| 4,770 (82% estimate) | 40 min | 1 h 20 min | 2 h 0 min | 5.4 min |

The embedding and ranking cost comes on top of the model calls. Embedding is roughly 5,900
passages plus 1,986 queries per embedder, about 1–4 min with e5 on CPU at 7.5 ms or more per
text; LoCoMo turns are longer than the fixture's. Ranking is cheap by comparison: in the synthetic run, `semantic-v3`
scoring of all 1,982 questions over 400–700 rows took about 3 s per variant. `focused-v2`'s
129 s is spent re-stemming every row for every question. To get the **exact** call
count before spending any model time, run the dry run below. It loads e5 but no LLM.

## Commands and durations

Run everything from the repository root, at low priority and with a single BLAS thread:

```bash
# data (once)
experiments/iis/real-data/locomo/download.sh            # -> ~/data-ext/locomo

# tests (synthetic conversation, no models): 43 checks, ~2 s
.venv/bin/python tests/test_iis_locomo_eval.py

# CPU baselines, run 2026-10-22: 136 s total (bm25 2.2 s, verbatim-focused 129 s)
OPENBLAS_NUM_THREADS=1 nice -n 19 .venv/bin/python \
    experiments/iis/real-data/locomo/locomo_eval.py --variants bm25,verbatim-focused

# exact stage-3 call count, real e5, constant-APPEND model, no LLM -> results/locomo-dryrun-<UTC>.json
OPENBLAS_NUM_THREADS=1 nice -n 19 .venv/bin/python \
    experiments/iis/real-data/locomo/locomo_eval.py --variants cascade-e5 --dry-run-calls

# LATER, the GPU/model variants: needs e5 in var/models, and ollama with qwen2.5:7b and bge-m3
OPENBLAS_NUM_THREADS=1 nice -n 19 .venv/bin/python \
    experiments/iis/real-data/locomo/locomo_eval.py \
    --variants embedding-only-e5,cascade-e5,embedding-only-bge-m3,cascade-bge-m3
```

Every run writes `results/locomo-<UTC>.json` and opens it with `open(path, "x")`, so a
collision gets a `-1`, `-2`, … suffix and nothing is overwritten. Dry runs and runs with the
fake embedder write `locomo-dryrun-*` and `locomo-synthetic-*` files, which are marked
`"synthetic"` inside. `--conversations 0,3` restricts a run to some conversations.
`--bootstrap N` sets the number of replicates. `bm25` is always added so that the paired
differences can be computed.

Synthetic smoke run on the full data (hash embedder, constant APPEND model, all four model
variants; kept in the scratchpad and not committed): 18.4 s in total, about 3.3–3.8 s
per variant. 12 stage-3 calls were made and 5 NOOP merges occurred, both artefacts of the hash
vectors. This shows the pipeline runs end to end. It measures nothing about ARIES.

## What blocked faithful reuse (divergences, all deliberate and stated)

1. **`memory_eval.build` could not be called directly.**
   - It fixes `created_at = origin + index × 1 h`, while LoCoMo has real session dates.
   - It drops NOOP turns without recording which row they merged into, which the hit rule
     needs.
   - It removes the contradicted row on SUPERSEDE. That was the older arbitration. The current
     `store.arbitrate` and `withdrawn_sources` keep USER statements retrievable.

   The loop here makes the same ARIES calls in the same order, with those three differences.
2. **`Cascade.decide` has no injection point.** It calls the module-level
   `calibration.classify`. The workaround rebinds `extraction.calibration` for the duration of
   one call. A `classify=` constructor argument in ARIES would remove this.
3. **`store.observe` has no `valid_at`.** It calls `record(...)` without one, so the live write
   path stamps every observed utterance with `datetime.utcnow()`, and NOOP bumps use the wall
   clock as well. Replaying a dated conversation through the live store would make every
   recency term equal. Like `memory_eval`, this evaluation therefore drives
   `extraction`/`vectors`/`retrieval` directly rather than going through SQLAlchemy, and it
   uses each turn's session time as the clock.
4. **One row stands for the utterance/conclusion pair.** `store.relevant` returns both the
   USER utterance and the LEARNED conclusion, which have the same text and vector, so a live
   top 5 would hold about 3 distinct turns. `memory_eval` collapses the pair, and so does this
   evaluation. The same applies to stage-2 neighbours, which in the live cache would contain
   each text twice.
5. **The single-user store meets a two-speaker corpus.** The speaker name is part of the stored
   text, and the gate judges the content without it.
6. **The e5-calibrated stage-2 band is applied to bge-m3 unchanged**, per the no-tuning rule.
