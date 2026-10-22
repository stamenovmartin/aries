# MIND-small dev evaluation: notes

Working notes, not the README. They cover every design decision, the data, and the
exact commands run.

## Data

- MIND-small, train and dev (`MINDsmall_train.zip`, `MINDsmall_dev.zip`), fetched by
  `download.sh` from `https://huggingface.co/datasets/Recommenders/MIND/resolve/main/<file>`.
  The official Azure blob is no longer public.
- SHA-256 (checked by `download.sh` and recorded again in every result file):
  - train `6ef97a271580b98ccfc4301ada55cc639423cb0576a78b8dcfcf74a4dbcc3194`
  - dev `d6ce515dcaa6b6d47ddf0a326eebc8a31b84735ae410285c9882ca2a06eec669`
- License: Microsoft Research License Terms (research use). Citation: Wu et al., "MIND: A
  Large-scale Dataset for News Recommendation", ACL 2020.
- The data lives in `~/data-ext/mind/{train,dev}/` and is never committed. `.gitignore`
  here blocks `*.tsv`, `*.zip`, `*.vec`, `*.npy` and `*.ids.json`. Only code, this note,
  `reference-published.json` and aggregate result JSON are committed.
- Dev: 73,152 impressions, 50,000 users and 2,740,998 candidates. Every impression has at
  least one click and at least one non-click, so no impression is excluded from any
  metric. In dev each user's history is the same in every impression (checked:
  `history_variants = 0`). 35,174 users have exactly one dev impression and 14,826 have
  two or more. All dev timestamps fall on 2019-11-15.

## Fixed before running (nothing tuned on dev)

The values come from ARIES defaults or were chosen a priori. All of them are also in
`parameters` of each result file.

### Evaluation

- **Metrics** follow the MIND `evaluate.py` definitions:
  - AUC is the Mann-Whitney statistic with average ranks for ties, so a tie counts 1/2.
  - MRR is the MIND variant: the sum of 1/rank over all clicked items, divided by the
    number of clicks.
  - nDCG@k uses gain 2^y−1 and discount log2(rank+1).
  - AUC is undefined for an impression with no positive or no negative, and MRR/nDCG are
    undefined with no positive. Both kinds are counted; there are 0 of each in dev.
- **Tie-break for MRR/nDCG:** `crc32("<seed>:<impression id>:<news id>")` ascending, the
  same for every system. It is fixed, pseudo-random and independent of system and
  position. AUC does not use it.
- **Aggregation:** the mean over impressions.
- **Intervals:** percentile 95% bootstrap with 1000 replicates. Users are resampled with
  replacement, and the statistic is the impression mean over the resampled users. Seed
  20261022.
- **Paired intervals:** each paired difference reuses the same replicate draws for both
  systems. The pairs are:
  - each ARIES system minus each baseline
  - learning minus static
  - diverse minus static
- **Subsets:** everything is reported for all impressions and again for impressions whose
  user has a non-empty history. 2,214 impressions (1,407 users) have an empty history.
  ARIES scores those all 0, so they tie (AUC exactly 0.5, MRR/nDCG decided by the
  tie-break). They are included in "all".

### `aries-interests`

- **Topics** are the `aries.interests.matching.normalise`d category, subcategory and every
  `TitleEntities[].Label` of each history item (train+dev `news.tsv`). Each topic is one
  `Matchable.build(key, [], weight)`; there are no synonyms and no avoid topics.
- **Static weight** = the share of the user's history items (those found in `news.tsv`)
  that carry the topic. An item counts at most once per topic.
- **Candidate text** = `category | subcategory | title | entity labels`. The `" | "`
  separator is a non-word, non-space character, so ARIES's phrase patterns (words joined
  by `\s+`) cannot match across fields.
- **Scoring:** `matching.score(text, matchables)` is the real ARIES function (noisy-OR,
  word boundaries, rounding to 9 places).
- **Exact pre-filter** (for speed only): the run passes `score` only the Matchables whose
  term `\w+` tokens are all present in the candidate text. A word-boundary match needs
  every `\w+` run of the term to be a whole token of the text, so the omitted Matchables
  could not have matched. Profile order is kept, so `matched` is identical too.
  - The run validates this on the first 20,000 candidate pairs against the full profile:
    0 mismatches.
  - A unit test checks it as well.
- **Profile order** is weight descending, then key. `score` sorts matched topics by weight
  with a stable sort, so this order decides the "primary" topic when weights are equal.
- **Side effect of word-boundary matching**, kept on purpose because it is ARIES's
  behaviour: a category topic such as `news` or `video` also matches that word in a
  candidate's title.

### `aries-interests+diverse`

- The static ranking is passed to `aries.news.selection.diverse` with:
  - `topics` = the primary matched topic. Unmatched items go to `'other'`, as in
    `diverse`.
  - `per_source = 0` (disabled) and `limit` = all candidates.
- This mirrors `aries/news/automation.py`, which passes
  `[m["topic"] for m in relevance.matched]`.
- AUC uses −position, so it has no ties.

### `aries-learning`

This mirrors the ordinary path of `aries.learning.loop.propose()`.

- **Order:** dev impressions are processed in time order (timestamp, then impression id).
  Each impression is scored first and only then used for an update (prequential).
- **Evidence:** every candidate counts as "shown" for each profile topic it matches, and
  label 1 counts as "clicked". In ARIES only delivered/held items count; in MIND every
  candidate was shown.
- **When a pass runs:** after every impression, and only over topics whose evidence
  changed. This mirrors the source-digest guard in `loop.apply`, which refuses to
  re-apply unchanged evidence.
- **Rule** (`aries.learning.statistics.wilson` / `step_toward` are imported):
  - Skip if shown < `min_observations` (10).
  - If Wilson lower ≥ `engaged_threshold` (0.4), move toward 1 with confidence
    (lower−0.4)/(1−0.4).
  - Else if upper ≤ `ignored_threshold` (0.1), move toward 0 with confidence
    (0.1−upper)/0.1.
  - The step is capped at `max_step` (0.15) × `damping` (0.5)^reversals, and moves under
    0.005 are dropped.
- **Reversals and freezing:** a reversal is a change whose direction differs from the
  previous change. Reversals are counted over the last `LOOKBACK` = 8 changes (imported
  from `aries.learning.history`), and a topic freezes at `max_reversals` (3). All of these
  are default values read from `aries.settings.schema` after importing
  `aries.learning.settings`.
- **Base and scope:** the base is the learned weight if one exists, otherwise the static
  weight. Learning only touches topics already in the profile (ARIES rule 2: it does not
  invent topics).
- The `window_days` (30) evidence window covers all of dev, which spans a single day.

### Baselines

- **random:** `numpy.default_rng([20261022, impression id]).random`.
- **popular:** the number of clicks on the item in train+dev impressions with a timestamp
  strictly before this impression. Same-time and later clicks never count. History clicks
  carry no time and are not counted. A unit test checks that there is no leakage.
- **recent:** the earliest timestamp of any train+dev impression that lists the item. It
  is a proxy, because MIND has no publish time. The minimum is never later than the
  current impression, which lists the item itself, so it uses no future information.
- **Text tokens** (for tfidf and bm25): `\w+` over `normalise(title)`, with no stop words
  and no stemming.
- **tfidf:**
  - The user document is the concatenated history titles; tf is the raw count.
  - idf = ln((1+N)/(1+df))+1 over all 65,238 train+dev news titles. This is unsupervised
    corpus statistics only, with no labels.
  - Vectors are L2-normalised and compared by cosine.
- **bm25** (own implementation; no BM25 library is in `.venv` and nothing was
  installed):
  - The query is the candidate title's unique terms, and the document is the
    concatenated history titles.
  - k1 = 1.2 and b = 0.75 (textbook defaults).
  - idf = ln(1+(N−df+0.5)/(df+0.5)), over the same corpus as tfidf.
  - avgdl is the mean over dev users with a non-empty history (309.2 tokens).
- **embedding** (code and synthetic test only, NOT run):
  - Score: the mean of the history-title embeddings against the candidate title, by
    cosine. It uses `aries.workspace.memory.embedding.get('e5-base-int8')` with
    `kind="query"` for both sides; e5's symmetric-task prefix choice was made before
    running.
  - Embeddings are cached on disk by news id, outside the repo. The default is
    `~/data-ext/mind/embedding-cache`, and a cache inside the repo is refused.
  - Enable it with `--embedding`.

## ARIES code: what was imported and what was not

- **Imported unchanged:**
  - `aries.interests.matching` (`Matchable.build`, `score`, `normalise`)
  - `aries.news.selection.diverse`
  - `aries.learning.statistics` (`wilson`, `step_toward`)
  - `aries.learning.history.LOOKBACK`
  - the setting defaults via `aries.settings.schema.require(...).default`
- **`aries.news.selection` side effect:** the module imports `sqlalchemy` and
  `aries.news.models`, which registers ORM classes on `agentic_core`'s `Base`. That only
  defines classes; no engine connection or session is opened. `diverse()` itself is pure.
- **`loop.propose()` is not callable offline.** It reads `SettingsService`, interests,
  history and `EvidenceUse` from the database, so its ordinary-path decision rule is
  mirrored in `learning_step` (about 25 lines). The thresholds, statistics and step
  function stay ARIES's own.
- **Not mirrored:**
  - The hysteretic reversal path (`aries.learning.reversal.classify` / `observe`), which
    needs per-pass DB state and confirmations across passes. Here, reversals of an
    established learned value go through the ordinary rule with damping/freeze, which is
    less strict than ARIES.
  - The relevance-threshold proposal, which does not affect ranking.
  - The "fatigue" decay.
  - The control epoch floor.
- **Inconsistency found in ARIES:** the `learning.max_reversals` description says
  "0 disables freezing", but `history.stability` computes `frozen = reversals >=
  max_reversals`. With 0, any target that has a change history is therefore always
  frozen. This does not matter at the default (3); the simulation follows the code.
- **Cadence:** ARIES runs a learning pass every `interval_hours` (24). Here a pass runs
  after every impression, as the task specified, so the simulation is more aggressive
  than ARIES's cadence would be.

## Commands run (in `/home/stamenovmartin/aries-iis`)

```
export PYTHONPATH=$PWD/vendor/agentic-core:$PWD/vendor:$PWD OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1

nice -n 19 experiments/iis/real-data/mind/download.sh ~/data-ext/mind
#   zips already present: SHA-256 verified, no download, no unzip; 0.6 s

nice -n 19 .venv/bin/python experiments/iis/real-data/mind/mind_eval.py --limit 2000 --replicates 100 --out <scratchpad>/smoke1.json
#   smoke run, not kept; 18 s

nice -n 19 .venv/bin/python tests/test_iis_mind_eval.py
#   63 checks pass; about 1 s

/usr/bin/time -v nice -n 19 .venv/bin/python experiments/iis/real-data/mind/mind_eval.py --data ~/data-ext/mind
#   started 2026-10-22T07:22:49Z; wall 4:12 (252 s), 99% of one CPU, max RSS 4.7 GB
#   -> results/mind-dev-20261022T072250Z.json
```

**Commit and dirty flag.** The full run used code at commit `82f77ae`. The result file
shows `code_dirty: true` only because `reference-published.json` and `results/` were
untracked in this directory when it ran. `git diff 82f77ae -- experiments tests` was empty
afterwards.

## Observations to carry into the README (not interpretation yet)

- **`aries-learning` ≈ `aries-interests`:** the difference is +0.0001 AUC, CI [0.0000,
  0.0002]. Most dev users have only one impression (35,174 of 50,000), and a topic needs
  10 shown items before anything can change. Only 2,582 users got any change (4,031
  changes in total). MIND-small dev is one day and is too short to measure the 24-hour
  learning loop.
- **`diverse` lowers every accuracy metric against static:** AUC −0.035, nDCG@10 −0.028.
  This is expected, because diversity trades accuracy. Beyond-accuracy metrics were not
  measured.

## Reference numbers

`reference-published.json` holds published numbers, labelled "reference, not directly
comparable":

- **MIND paper, Table 3:** MIND-large test, not small, read from the PDF.
- **Recommenders NRMS quick-start notebook:** MIND-demo validation.
- **MIND-small dev numbers for the neural models:** "not verified".
