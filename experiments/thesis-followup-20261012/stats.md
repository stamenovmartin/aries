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
- The optional mixed-effects logistic model was **not run**, because `statsmodels` is not installed.
