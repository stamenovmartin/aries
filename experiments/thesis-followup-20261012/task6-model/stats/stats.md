# Router statistics, second model llama3.1:8b (re-analysis of the Task 6 run, no new inference)

- **Script:** `scripts/thesis_stats.py --second-model ../summary.json`. **Output:** `stats.json` in this folder.
  Every number below is copied from `stats.json`.
- **Same as the qwen2.5:7b analysis (`../../stats.md`):** the same tests, the same frozen scorer
  (`analyze_router.py::correct`) and the same reproduction gate. The only differences: the raw files are
  `../raw/r{1,2,3}-A{0..3}.jsonl`, and the expected hashes and totals come from `../summary.json`.
- **Status: exploratory.** The model is not the one the arms and the criterion were declared for, and the prompts
  were not re-tuned for it. qwen2.5:7b remains the primary result.

## Reproduction gate (passed)

- All 12 raw files match `summary.json`'s `raw_sha256`: 2,700 decisions.
- Binary correctness: **A0 376/675, A1 390/675, A2 405/675, A3 419/675**, equal to `summary.json`.
- A3 vs A1 per-case means: **23 improved, 12 worse, 190 equal**, equal to `summary.json`.

## Per-request majority (correct in ≥ 2 of 3 repetitions), n = 225

| Arm | llama3.1:8b | qwen2.5:7b (`../../stats.json`) |
|---|---|---|
| A0 | 125 | 129 |
| A1 | 130 | 154 |
| A2 | 136 | 146 |
| A3 | 141 | 155 |

## Exact McNemar tests (two-sided)

| Comparison | First right, second wrong | First wrong, second right | Both right | Both wrong | p | qwen p |
|---|---|---|---|---|---|---|
| A3 vs A1 | 19 | 8 | 122 | 76 | 0.052 | 1.000 |
| A2 vs A1 | 14 | 8 | 122 | 81 | 0.286 | 0.268 |
| A1 vs A0 | 15 | 10 | 115 | 85 | 0.424 | 0.00035 |

## Cochran's Q across A0–A3

Q = 11.53, df = 3, p = 0.0092 (n = 225). For qwen: Q = 23.89, p = 2.6 × 10⁻⁵.

## Mixed-effects logistic model (all 2,700 decisions, reference arm A1)

The setup is the same as for qwen: variational-Bayes `BinomialBayesMixedGLM` with a random intercept per request,
and a GEE logistic cross-check clustered by request (exchangeable working correlation 0.80). statsmodels 0.15.0 was
run from `var/venv-stats`.

| vs A1 | GLMM log-odds (≈95%) | GLMM odds ratio | GEE log-odds ± robust SE | GEE p |
|---|---|---|---|---|
| A0 | −0.454 (−0.813, −0.096) | 0.64 | −0.085 ± 0.079 | 0.29 |
| A2 | +0.487 (+0.137, +0.837) | 1.63 | +0.092 ± 0.081 | 0.26 |
| A3 | +0.937 (+0.586, +1.289) | 2.55 | +0.179 ± 0.091 | 0.0495 |

The random-effect log-SD is 1.99 (posterior SD 0.05).

## Reading

- **The arms differ overall** (Cochran's Q, p = 0.009). The pattern is not qwen's.
- **A3 vs A1 points towards A3**, but the evidence is borderline and not robust:
  - McNemar p = 0.052 (19 vs 8);
  - GEE p = 0.0495;
  - only the variational GLMM interval clearly excludes 0.
  
  With Bonferroni over the three McNemar tests (α = 0.0167), nothing is significant. Report the direction, not an
  effect.
- **A1 vs A0, robust for qwen, does not replicate for llama**: McNemar p = 0.42 and GEE p = 0.29. Only the GLMM
  interval excludes 0.
- **A2 vs A1** is not significant (McNemar p = 0.29, GEE p = 0.26).
- The GLMM's per-request effects are larger than GEE's population-averaged ones, as for qwen. Where the two
  disagree, the more conservative GEE and McNemar results decide what is reported.

## Limits

- The p-values are not corrected for multiple comparisons.
- The fixture is the author's own. Both models were tested on the same 225 requests.
- The prompts were written for qwen2.5:7b. Most of llama's difference is that it almost never declines (see
  `../summary.json`, `ood_out_of_scope`), so these arm effects are about one model and these prompts.
