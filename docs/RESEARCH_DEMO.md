# Scientific component of the ARIES demo

## Question and methods

Does focused lexical retrieval select relevant prior task experience more
accurately than word overlap on a fixed developer-labelled corpus?

Baseline: `overlap-v1`. Candidate: `focused-v2`. Both receive the same eight
review records and twenty queries in `aries/workspace/fixtures/retrieval_v1.json`.
The outcome is exact equality between selected review IDs and expected IDs.
Empty expected selections measure abstention. Precision and recall additionally
measure unrelated inclusions and missed relevant records.

The hypothesis is higher exact-selection accuracy without regressions. The
paired comparison records every case, the fixture digest and implementation digest.
Run `./scripts/aries-research`; artifacts are timestamped under `experiments/learning/`.
The live `evaluate learning` command runs the same comparison through the durable
goal queue and displays it in a response window. Neither path promotes a version.

## Measured result, 17 September 2026

| Method | Exact selections | Accuracy | Descriptive 95% Wilson interval |
|---|---:|---:|---:|
| overlap-v1 | 15/20 | 75% | 53.13–88.81% |
| focused-v2 | 19/20 | 95% | 76.39–99.11% |

Paired improvement: 4 cases; regressions: 0; difference: +20 percentage points.
The two-sided exact McNemar calculation conditions on the four discordant pairs:
`2 × P(Binomial(4, 0.5) ≤ 0) = 0.125`. This does not meet a 0.05 threshold.
The Wilson intervals describe each proportion, not a confidence interval for
their paired difference. Unit tests include known exact discordance cases.

The candidate still confuses the sports/climate news case. This failure remains
in the fixture and report. Do not claim statistical significance, general agent
improvement, translation capability, or learned model weights from this result.

## Threats to validity

The labels and implementation were developed together. This is an exploratory
regression comparison, not an independently held-out experiment. Queries sharing
topics may be dependent, so the binomial inference assumptions are only an
illustrative analysis. Twenty cases are small. Retrieval timing is local CPU
time; it excludes model and end-to-end execution latency. Testing the same
fixture repeatedly does not increase the independent sample size.

A thesis extension should freeze candidate code and collect new task reviews
and relevance labels independently, define primary outcomes before observing
results, randomize method order for timing, and report all failures. For a true
agent comparison, compare fixed workflows and model planning on the same tasks
with independent final-state verifiers, measured tokens, latency and approvals.
That extension is not reported here as completed.

## Separate engineering evidence

`./scripts/aries-demo` measures installed-system acceptance: actual file bytes,
three-step workflow completion, missing-file negative control, automation runs,
desktop launch, news, briefing and agent browser observation. Results include
source digest, Git revision, dirty-working-tree flag, IDs and elapsed time.
It is not a randomized baseline comparison. `evaluate tasks` summarizes the
latest 500 operational goals; it is also not a controlled scientific benchmark.

Historical operator comparisons are preserved in `experiments/operator/analysis.md`
and [EXPERIMENTS.md](EXPERIMENTS.md). Their own null findings and fixed-order
confound remain valid caveats; new regression tests do not turn them into wins.

## M14: local-model multi-step acceptance

`./scripts/aries-agent-demo` executes four natural-language scenarios through the
real local model, persistent queue, capability registry and independent verifiers.
The first complete accepted run is `experiments/agent/20260917T204354Z-fb8722/`:

| Scenario | Outcome | Acceptance | Submission-to-result seconds |
|---|---|---|---:|
| File create and read-back | done | PASS | 10.734 |
| Highest filesystem usage | done | PASS | 4.166 |
| Missing-file negative control | failed, real read error | PASS | 4.154 |
| Python page navigation and observed title | done | PASS | 10.853 |

All four required checks passed. This is **not** 100% arbitrary task success:
correct failure recognition is one of the four checks. Every executed step has
persisted observations/evidence. Native local-model token counts and all decisions
are included in task JSON. The runner approves only its explicitly requested
new file and public Python navigation, preserving the user's confirmation setting.

Development attempts remain in `experiments/agent/`: grammar incompatibility,
service-start readiness, repeated reads, invented terminal evidence and refusal
without observing a missing path were encountered before this accepted run.
Prompt/grammar changes were made after observing those failures. This is therefore
an implementation acceptance fixture, **not held-out evidence** of model quality.
The grammar currently excludes finish before provisional completion evidence and
requires an attempt before failure on known supported inspectable contracts.
The runtime still independently verifies all terminal success claims.

The parser deliberately supports only bounded independently verifiable goal
conditions. Unsupported semantic goals remain partial even if individual actions
verify. M14 enables future Cold-vs-Learned evaluation but does not implement or
claim that experiment. See [AGENT_EXECUTION.md](AGENT_EXECUTION.md) and
[publication materials](publication/README.md).
