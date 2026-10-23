# Datasets

Every dataset used in an evaluation, where it comes from, what it measures, and what of it is in this
repository. The datasets themselves are not committed (their licences, and the rule that external data is never
committed); each folder has a `download.sh` that fetches them into `~/data-ext/`, and the SHA-256 of the files
used is recorded in the registration and in the sample manifests. Models: [`ENVIRONMENT.md`](ENVIRONMENT.md).

## Public datasets

| Dataset | Source and licence | Component measured | What is used | In this repository |
|---|---|---|---|---|
| **NL2Bash** (Lin et al., LREC 2018) | [TellinaTool/nl2bash](https://github.com/TellinaTool/nl2bash), `data/bash/all.nl`, `all.cm`; GPL-3.0 | tool selection: router + planner pick one of 58 capabilities, or refuse | R1: 500 test + 100 dev lines, stratified, seed 20261022; R1b: 500 new lines, disjoint from R1, seed 20261101 | sample manifests (line ids, data SHA-256), labels from two LLM annotators + adjudication (κ 0.649 R1, 0.733 R1b), per-item predictions and summaries |
| **CLINC150** (Larson et al., EMNLP 2019) | [clinc/oos-eval](https://github.com/clinc/oos-eval), `data/data_full.json`; CC BY 3.0 | act or refuse: out-of-scope detection | R1: 600 test utterances (200 supported, 200 unsupported intents, 200 out-of-scope), seed 20261024; R1b: 600 new | sample manifests, intent-to-capability labels (κ 0.826), summaries |
| **LoCoMo** (Maharana et al., ACL 2024) | [snap-research/locomo](https://github.com/snap-research/locomo); CC BY-NC 4.0 | semantic memory: are the annotated evidence turns retrieved in the top 5? | all 10 conversations, 1,982 questions | evaluation script, result files with the data hash |
| **MIND-small** (Wu et al., ACL 2020) | [msnews.github.io](https://msnews.github.io/), via Hugging Face `Recommenders/MIND`; Microsoft Research License Terms (research use) | news ranking and online learning from clicks | dev split: 73,152 impressions, 50,000 users | evaluation script, result files, published reference numbers |

| Dataset | Folder | Registration |
|---|---|---|
| NL2Bash, CLINC150 (R1) | [`experiments/thesis-r1-real-data/`](../experiments/thesis-r1-real-data/) | [`R1-real-data-benchmarks.md`](preregistration/R1-real-data-benchmarks.md) |
| NL2Bash, CLINC150 (R1b, M2) | [`experiments/thesis-r1b/`](../experiments/thesis-r1b/), [`experiments/thesis-m2-models/`](../experiments/thesis-m2-models/) | [`R1b-improved-router-planner.md`](preregistration/R1b-improved-router-planner.md), [`M2-local-models.md`](preregistration/M2-local-models.md) |
| LoCoMo, MIND-small | [`experiments/iis/real-data/`](../experiments/iis/real-data/README.md) | [`M1-information-layer-remedies.md`](preregistration/M1-information-layer-remedies.md) (the remedies) |

## Item sets written for this project

| Set | Written by | Size | Used in | In this repository |
|---|---|---|---|---|
| H6 requests | another LLM (Codex) in a separate session, without access to the ARIES code | 300 | H6 | [`h6-items/h6_requests.jsonl`](../experiments/thesis-followup-20261012/h6-items/h6_requests.jsonl) and summaries |
| H4b pairs | the same | 40 pairs | H4b, X1 | format, validator and one example pair; summaries. The item texts are not committed |
| H5 goals | the same | 25 | H5, X1 | format, validator and example items; summaries. The item texts are not committed |
| H8 mutants | generated from the verifiers, sealed by hash before the run | 218 | H8 | [`h8/mutants.json`](../experiments/thesis-followup-20261012/h8/mutants.json) |
| Held-out end-to-end goals | an LLM in a separate session | 57 generated, 49 run | held-out run, H5, X1 | [`independent-acceptance/`](../experiments/product/independent-acceptance/) |
| Router OOD fixture | the author | 225 | A0–A3 | [`router-ood/`](../experiments/router-ood/) |

## Limits

- The NL2Bash and CLINC150 labels for ARIES's 58 capabilities are LLM labels (two annotators, a third session
  for disagreements), not human labels.
- The H4b, H5 and H6 items were written by an LLM, not collected from users.
- LoCoMo and MIND are English; ARIES's main language is Macedonian.
