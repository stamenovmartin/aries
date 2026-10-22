# R1: tool selection and out-of-scope detection on public datasets (NL2Bash, CLINC150)

**Registered:** 2026-10-22, before any label, sample-derived file or model output exists. Committed and pushed
before labelling starts. Any later change goes into a dated Amendment section in a new commit.

**Family:** R1 is its own family, separate from the Holm family H4b/H5/H6/H8. Holm's correction is applied
inside R1 only (six tests, below).

**Why:** a reviewer asked for an evaluation on real, public data of (a) choosing which tool or agent is called
and (b) each component's performance. Every earlier router and planner evaluation used author-written or
LLM-written fixtures. R1 uses two public datasets that ARIES was never developed or tuned on.

## Datasets (never committed; download scripts with SHA-256 are committed)

| dataset | source | license | SHA-256 of the files used |
|---|---|---|---|
| NL2Bash (Lin et al., LREC 2018) | `github.com/TellinaTool/nl2bash`, `data/bash/all.nl`, `all.cm` | GPL-3.0 | `all.nl` `1db0c529c350b463919624550b8f5882a97c42ad5051c7d49fbc496bc4e8b770`; `all.cm` `3a72eaced7fa14a0938354cefc42b2dcafb2d47297102f1279086e18c3abe57e` |
| CLINC150 (Larson et al., EMNLP 2019) | `github.com/clinc/oos-eval`, `data/data_full.json` | CC BY 3.0 | `36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0` |

## The system under test (frozen)

- Source: the frozen ARIES-FINAL-20261006 source archive `experiments/thesis-final-20261006/frozen/`
  (verified against its `source-manifest.json` before every run), the same as H6.
- **Label space:** the 15 planner capabilities of the frozen registry (`aries/workspace/registry.py`, SHA-256
  `96f32e4984a9416caa43c227cde2cc9c30e74bd6e6566f4e879db28ac51cfc29`) plus `OUT_OF_SCOPE` = 16 labels. Each
  capability is shown with its one-line registry description, verbatim: `file.read`, `file.write`,
  `file.list`, `file.search`, `file.exists`, `browser.open`, `browser.read`, `browser.search`,
  `desktop.launch`, `desktop.focus`, `system.status`, `system.storage`, `system.processes`, `task.inspect`,
  `notification.send`.
- **ARIES router:** the frozen router (`router.route`, `allow_contract=True`) with the frozen **A1** prompt
  (SHA-256 in `experiments/thesis-final-20261006/protocol.json`, `hashes.A1`), qwen2.5:7b (digest
  `845dbda0…`), the frozen settings of H6 (temperature 0.1, top_p 0.9, 450 output tokens). A0 is used only in
  CLINC150 (H-R1d). The router *abstains* when the intent is `ASK`, `OUT_OF_SCOPE` or `UNKNOWN`, or on an
  error or fallback; otherwise it *acts*.
- **ARIES planner:** the frozen offline next-action planner of `experiments/thesis-final-20261006/planner/`
  (same configuration, empty history, no completion-contract hints, no execution). Its decision supplies the
  capability.
- **ARIES capability prediction** for one request: `OUT_OF_SCOPE` if the router abstains; otherwise the
  planner's capability if its action is `execute` with a capability of the label space; otherwise
  `OUT_OF_SCOPE`. Nothing is executed.
- One repetition per request and system (the H6 runs showed three repetitions change few majority outcomes;
  one is a stated limitation).

## Labels (two independent LLM labelers, adjudication, frozen before any ARIES run)

- **Labeler A:** Claude Code CLI (`claude -p`), a fresh session per batch, an empty working directory, all
  tools disabled, no session persistence. **Labeler B:** Codex CLI (`codex exec`), a fresh ephemeral session
  per batch, an empty working directory, read-only sandbox. Neither gets the repository, ARIES's prompts or the
  other labeler's output. Each gets only the instruction below, the 16 labels with their descriptions, and
  the request texts (batches of at most 50, in a seeded random order). The JSON event logs are kept and checked
  for tool calls; a batch with a tool call is discarded and relabelled in a new session, and that is reported.
- **Instruction (NL2Bash):** "An assistant can act only through the capabilities listed. For each request,
  give the one capability the assistant would use as the first step to fulfil the request completely, using
  only listed capabilities. If the listed capabilities cannot fulfil the request completely (for example it
  needs to delete, modify, compress or transform files, run arbitrary commands, or change system settings),
  answer OUT_OF_SCOPE."
- **Instruction (CLINC150, per intent):** the same, applied to an intent, shown as its name and its first three
  training utterances in file order: "SUPPORTED with capability X" (one of the 15) or "OUT_OF_SCOPE".
  CLINC's own `oos` class is `OUT_OF_SCOPE` by definition and is not labelled.
- **Agreement:** Cohen's kappa over the 16 labels and over the binary in-scope/out-of-scope reduction, both
  datasets, with the raw agreement counts.
- **Adjudication:** every disagreement goes to a third fresh `claude -p` session (same isolation), shown the
  request, the label list and the two labels in random order without their source; it picks one of the two
  or a third label. Its choice is final.
- **Freeze:** the label files are frozen with SHA-256 and committed (labels only, with request IDs and line
  numbers, never the request text) before any ARIES or baseline run. No label is changed after any system
  output exists.

## Samples (fixed seeds)

- **NL2Bash:** exact-duplicate NL lines removed (first occurrence kept). Stratum = the first utility of the
  command (first token of `all.cm`, after a leading `sudo`). 600 requests drawn with seed `20261022`, allocation
  proportional to stratum size (largest remainder), then split into **test 500** and **dev 100** with seed
  `20261023`, stratified the same way. Dev is used only to set the two baseline thresholds below; no ARIES
  parameter is set on any R1 data.
- **CLINC150:** after the intent labels are frozen: from the `test` split, 200 utterances from SUPPORTED
  intents, 200 from in-scope intents labelled OUT_OF_SCOPE, 200 from `oos_test`, each stratified evenly over
  intents with seed `20261024` (if a pool is smaller than 200, all of it is used and that is reported).
  The `val`/`oos_val` splits are used only for the embedding threshold.

## Baselines

1. **Embedding nearest capability:** the ARIES embedder (`e5-base-int8`); query = request, passages =
   "`<capability id>`: `<description>`"; cosine; `OUT_OF_SCOPE` if the maximum is below a threshold τ.
   NL2Bash: τ maximizes top-1 accuracy on the 100 dev requests. CLINC150: τ maximizes out-of-scope F1 on
   `val` + `oos_val` under the frozen intent mapping. τ is a grid of 0.001 steps; ties go to the lowest τ.
2. **BM25 over capability descriptions** (NL2Bash only): k1 = 1.5, b = 0.75, lowercase word tokens; same
   threshold rule on dev.
3. **Zero-shot qwen2.5:7b** with the 16 labels and descriptions, no ARIES prompt or structure: one system
   message (committed before any run), output constrained to a JSON enum of the 16 labels, temperature 0.1.
4. **Secondary, exploratory, outside Holm:** llama3.1:8b in the ARIES router and planner (same pipeline).

## Metrics

- NL2Bash (test 500): top-1 accuracy over 16 labels; macro-F1 over the labels present in the gold set;
  out-of-scope precision and recall (positive class = `OUT_OF_SCOPE`); router-only in-scope vs out-of-scope
  accuracy (acts vs abstains). Proportions with exact Clopper-Pearson 95% intervals; F1 with a 2,000-replicate
  percentile bootstrap (seed `61022`).
- CLINC150 (600): out-of-scope precision, recall and F1 (positive class = unsupported, i.e. intents labelled
  OUT_OF_SCOPE plus `oos`); in-scope accuracy = share of SUPPORTED utterances on which the system acts.
  Same intervals.
- Paired: exact McNemar on per-request correctness.

## Tests (family R1, two-sided exact McNemar, Holm at α = 0.05 over the six)

| id | dataset | correctness per request | comparison |
|---|---|---|---|
| H-R1a | NL2Bash test | top-1 label correct | ARIES vs embedding |
| H-R1b | NL2Bash test | top-1 label correct | ARIES vs BM25 |
| H-R1c | NL2Bash test | top-1 label correct | ARIES vs zero-shot qwen2.5:7b |
| H-R1d | CLINC150 | act/abstain correct | router A1 vs router A0 |
| H-R1e | CLINC150 | act/abstain correct | router A1 vs embedding |
| H-R1f | CLINC150 | act/abstain correct | router A1 vs zero-shot qwen2.5:7b |

No direction is assumed; each result is reported with its direction, b, c, raw and Holm-adjusted p. A
baseline that beats ARIES is reported as such.

## Per-component table

A per-component table for the thesis is generated from `thesis-tables/` by `check.py` (router: frozen, H6,
CLINC150; planner: frozen test, NL2Bash; executor and verifiers: H8; completion contract: H5;
clarification: H4b; end to end: held-out and agent suite), every cell from a committed file.

## Procedure and order

1. This file is committed and pushed. 2. Sampling script and labeling scripts are committed. 3. Labels are
produced, kappa computed, disagreements adjudicated, labels frozen and committed. 4. Runs start only after the
running H5 and H4b measurements end (the local GPU is shared). 5. Analysis script committed before the runs.

## Limitations stated in advance

- The gold labels come from LLMs, not people; kappa and adjudication are reported, not a human review.
- NL2Bash requests are shell tasks; most are expected to be out of scope for a 15-capability planner, so
  accuracy is dominated by the out-of-scope class. Macro-F1 and per-label counts are reported for that reason.
- CLINC150 is a virtual-assistant intent dataset (banking, travel, small talk), not desktop tasks.
- One repetition; temperature 0.1; local Ollama shared with no other load during the runs.
