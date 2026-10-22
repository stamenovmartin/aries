# R1b: the remedies for R1, on new public samples (NL2Bash, CLINC150)

**Registered:** 2026-10-22, after R1 and after development on R1's dev items only, before any system output on
the R1b samples exists. Committed before the R1b labels are frozen and before any R1b run. Any later change goes
into a dated Amendment section in a new commit.

**Family:** R1b is its own family of four tests (below), with Holm's correction inside R1b. It is separate from
R1 and from the Holm family H4b/H5/H6/H8. R1's results are not changed or re-tested.

**Why:** R1 (`docs/preregistration/R1-real-data-benchmarks.md`, results in
`experiments/thesis-r1-real-data/summary.json`) found ARIES worse than simple baselines on both datasets:
NL2Bash 229/500 against zero-shot 321/500, CLINC150 277/600 against zero-shot 336/600. The exploratory analysis
named two causes: the router acts on 449 of 500 NL2Bash requests although 307 are out of scope, and 126 of 449
planner outputs failed the argument schema. Remedies were designed for both and tried on R1's 100 dev items
(and on 150 CLINC val utterances), never on R1's test items. R1b asks whether they work on items no part of
the system has seen.

## Datasets

The R1 files, same SHA-256 (`experiments/thesis-r1-real-data/common.py`, `SHA`).

## Samples (new, disjoint from R1; `experiments/thesis-r1b/sample_r1b.py`, fixed seeds)

- **NL2Bash r1b, 500:** R1's pool (exact-duplicate NL lines removed) minus R1's 600 lines and minus any line
  whose text equals one of them: 10,748 lines, 576 strata. 500 drawn with seed `20261101`, R1's allocation rule
  (proportional to the first-utility stratum, largest remainder). Manifest:
  `experiments/thesis-r1b/nl2bash-sample-manifest.json`.
- **CLINC150 r1b, 600:** from `test`, minus R1's items: 200 utterances of supported intents and 200 of in-scope
  intents labelled OUT_OF_SCOPE (R1's frozen intent labels), spread evenly over intents, and 200 from
  `oos_test`, seed `20261102`. Manifest: `experiments/thesis-r1b/clinc-sample-manifest.json`.

## Labels

- **NL2Bash r1b:** R1's procedure unchanged (`experiments/thesis-r1b/label_r1b.py` runs R1's `label.py` and
  `adjudicate.py`): labeler A Claude Code CLI, labeler B Codex CLI, isolated sessions, no tools, batches of 50;
  every disagreement adjudicated by a third fresh Claude Code session; kappa reported. Frozen and committed
  before any R1b system run.
- **CLINC150 r1b:** R1's frozen per-intent labels (`thesis-r1-real-data/labels/clinc-final.json`); no new labels.

## The systems

- **Treatment (`T`):** the current ARIES source at the commit that adds this file's last amendment, with the
  flag configuration named `treatment` in `experiments/thesis-r1b/configs.json`. Router: the A1 abstention
  setting, qwen2.5:7b, R1's router settings (temperature 0.1, top_p 0.9, 450 tokens). When the router acts, the
  planner is asked for one next action with the frozen planner protocol's settings and context flags, as in R1.
  Nothing is executed. Runner: `experiments/thesis-r1b/run_r1b.py aries`, which refuses uncommitted changes
  under `aries/` or `vendor/`.
- **Frozen ARIES (`F`):** R1's system exactly (frozen ARIES-FINAL-20261006 source, frozen A1 prompt, frozen
  planner), run by R1's own stage functions on the new samples (`run_r1b.py frozen`, `frozen-planner`).
- **Zero-shot qwen2.5:7b:** R1's zero-shot stage on the new samples.
- **Embedding and BM25:** R1's stages on the new samples, with R1's thresholds (read from R1's
  `summary.json`; nothing is set on R1b data). Descriptive in R1b.
- **References:** always OUT_OF_SCOPE (NL2Bash), always abstain (CLINC150). Descriptive.

Prediction rules are R1's: OUT_OF_SCOPE unless the router acts and the planner executes one of the 58
capabilities (NL2Bash); on CLINC150, correct when the system acts on a supported utterance or abstains on an
unsupported one, where "acts" is the router's decision (for `T`, after its capability gate).

## Tests (family R1b, two-sided exact McNemar on per-item correctness, Holm at α = 0.05 over the four)

| id | dataset | comparison |
|---|---|---|
| H-R1b-a | NL2Bash r1b | `T` vs `F` |
| H-R1b-b | NL2Bash r1b | `T` vs zero-shot |
| H-R1b-c | CLINC150 r1b | `T` vs `F` (router A1) |
| H-R1b-d | CLINC150 r1b | `T` vs zero-shot |

No direction is assumed in the tests; each result is reported with its direction, b, c, raw and Holm p. The
expectation stated now, from development: `T` beats `F` on both datasets; `T` against zero-shot is open.

## Metrics (R1's, from R1's functions)

Top-1 over 58 capabilities + OUT_OF_SCOPE with Clopper-Pearson 95% intervals; macro-F1 with bootstrap;
OUT_OF_SCOPE precision and recall; in-scope top-1 (descriptive); CLINC150 correct act/abstain, unsupported F1,
acts on supported. Stage counts for `T` (router acts, gate OUT_OF_SCOPE, planner invalid, planner fail) and the
mean time per request.

## Exploratory, on the R1b samples, outside Holm

`C0` (current source, all new flags off) and the development configurations named in
`configs.json` → `exploratory_on_r1b`, each paired against `T`. They are run after `T`, `F` and the baselines.

## Procedure and order

1. This file, `configs.json` with `treatment` set, `analyze_r1b.py` and the development log are committed.
2. NL2Bash r1b labels are completed, adjudicated, frozen and committed. 3. With the live ARIES stopped (as in
R1): `F` router and planner, `T`, zero-shot, embedding and BM25 on both samples; then the exploratory
configurations. 4. `analyze_r1b.py` writes `summary.json`.

## Limitations stated in advance

- Gold labels from LLMs, not people; the labeler A model is whatever `claude -p` serves on the day (recorded).
- The remedies were designed after R1's results; R1b's samples are new, but they come from the same datasets
  and the same label procedure.
- One repetition at temperature 0.1. In development the same question asked twice (gate and zero-shot)
  disagreed on 19 of 73 items, so small differences are within sampling noise.
- The treatment adds a model call (the capability gate) before the planner; its time cost is reported.
