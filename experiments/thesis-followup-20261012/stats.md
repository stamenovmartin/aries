# Router statistics on ARIES-FINAL-20261006 (re-analysis, no new inference)

- **Script:** `scripts/thesis_stats.py`. **Output:** `stats.json` in this folder. Every number below is copied from `stats.json`.
- **Input:** `inputs/final-evaluation.json`, extracted unchanged from `thesis/ARIES_Diplomska_Paket_20261006.zip:dokazi/final-evaluation.json`
  (sha256 `d187f4c3…2973`). Raw data: `experiments/thesis-final-20261006/raw/r{1,2,3}-A{0..3}.jsonl`.
- **Scoring:** the frozen `analyze_router.py::correct`, imported rather than re-implemented.

## Reproduction gate (passed)

- All 12 raw files match `router.raw_sha256`: 225 requests × 4 arms × 3 repetitions = 2,700 decisions.
- Binary correctness: **A0 385/675, A1 463/675, A2 440/675, A3 463/675**. These equal the published totals.
- A3 vs A1 per-case means: **26 improved, 25 worse, 174 equal**. These equal the published values.

## Per-request majority (correct in ≥ 2 of 3 repetitions), n = 225

| Arm | Majority-correct requests |
|---|---|
| A0 | 129 / 225 |
| A1 | 154 / 225 |
| A2 | 146 / 225 |
| A3 | 155 / 225 |

## Exact McNemar tests (two-sided)

| Comparison | First right, second wrong | First wrong, second right | Both right | Both wrong | p |
|---|---|---|---|---|---|
| A3 vs A1 | 24 | 23 | 131 | 47 | 1.000 |
| A2 vs A1 | 16 | 24 | 130 | 55 | 0.268 |
| A1 vs A0 | 36 | 11 | 118 | 60 | 0.00035 |

## Cochran's Q across A0–A3

Q = 23.89, df = 3, p = 2.6 × 10⁻⁵ (n = 225).

## Reading

- The arms differ overall (Cochran's Q). That difference comes from **A1 vs A0**: 36 requests improved and
  11 got worse, p = 0.00035.
- **A3 vs A1 shows no difference**: 24 vs 23 discordant requests, p = 1.0. This matches the published null
  result and the predeclared criterion that was not met.
- **A2 vs A1** is not significant (p = 0.27). Its direction is towards A2 being worse.

## Limits

- The p-values are not corrected for multiple comparisons. With Bonferroni over the three McNemar tests
  (α = 0.0167), only A1 vs A0 remains significant.
- The test fixture is the author's own, so this analysis cannot generalise beyond it.
- The mixed model below was run with `var/venv-stats/bin/python` (statsmodels 0.15.0), a separate analysis
  environment, so the ARIES runtime venv was not changed.

## Mixed-effects logistic model (all 2,700 decisions, reference arm A1)

statsmodels has no maximum-likelihood mixed logistic model. The requested model (arm fixed, random intercept per
request) is therefore `BinomialBayesMixedGLM`, fitted by **variational Bayes**. Its intervals are the posterior
mean ± 1.96 SD, not frequentist confidence intervals. A GEE logistic model clustered by request (exchangeable
working correlation 0.71) is the frequentist cross-check. It estimates population-averaged effects, which are
smaller than the GLMM's per-request effects.

| vs A1 | GLMM log-odds (≈95%) | GLMM odds ratio | GEE log-odds ± robust SE | GEE p |
|---|---|---|---|---|
| A0 | −1.886 (−2.199, −1.573) | 0.15 | −0.498 ± 0.126 | 8 × 10⁻⁵ |
| A2 | −0.530 (−0.834, −0.226) | 0.59 | −0.154 ± 0.122 | 0.21 |
| A3 | +0.035 (−0.273, +0.344) | 1.04 | 0.000 ± 0.138 | 1.00 |

Between-request variation is very large: the random-effect log-SD is 1.76 (posterior SD 0.05).

**Reading the models together with McNemar:**
- **A3 vs A1** is null in all three analyses.
- **A1 is better than A0** in all three.
- **A2 vs A1** is not robust. Only the variational GLMM interval excludes 0, while GEE (p = 0.21) and McNemar on
  majorities (p = 0.27) do not. Report the direction (A2 worse than A1), not a significant effect.
