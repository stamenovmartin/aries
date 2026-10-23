# Thesis evidence

The agent: the router (act, ask or refuse), the planner (which capability, with which arguments), the
verifiers, the completion contract and clarification. All results in one place:
[`../thesis-improvements-20261022/RESULTS.md`](../thesis-improvements-20261022/RESULTS.md) (after the
diagnosis) and [`../thesis-followup-20261012/RESULTS.md`](../thesis-followup-20261012/RESULTS.md) (before it).

## Measurements, frozen in place

They stay at the top of `experiments/`: other frozen files, `thesis-tables/check.py` and the thesis build
read them by exact path and hash.

| path | what | status |
|---|---|---|
| `experiments/thesis-final-20261006/` | router experiment, arms A0–A3, qwen2.5:7b, 2,700 decisions | confirmatory (criterion not met) |
| `experiments/thesis-followup-20261012/` | H4b, H5, H6, H8, statistics, terminal diagnosis, thesis tables | confirmatory family of four, see its `RESULTS.md` |
| `experiments/thesis-r1-real-data/` | R1: NL2Bash and CLINC150 samples, labels, runner, analysis | confirmatory (own family) |
| `experiments/thesis-r1b/` | R1b: new samples and labels, development log, runner, analysis | confirmatory (own family) |
| `experiments/thesis-m2-models/` | M2: the R1b systems with four local models | confirmatory (own family) |
| `experiments/thesis-improvements-20261022/` | X1 reruns, HAL1 hallucination measures, results index | exploratory / descriptive |
| `experiments/router-ood/` | out-of-distribution router fixture | input; pinned by sha256 in `thesis-final-20261006/semantic_labels.json` |
| `experiments/router-en/` | English router fixture with its own `check.py` | descriptive |
| `experiments/product/independent-acceptance/` | held-out end-to-end fixture and raw runs | descriptive; read by `check.py` |
| `experiments/verification-feedback/` | does independent verification feedback change what the agent does next | fixture for `eval/research_feedback/` |
| `verification/` | frozen verifier ledger, `build_facts.py`, `reproduce.sh` | descriptive; read by `check.py` |

## Precursors, in this folder

| path | what |
|---|---|
| [`operator/`](operator/) | Operator v0.1, 372 trials, where the verification argument started |
| [`planner/`](planner/) | planner prompt variants, 2026-09-30 and 2026-10-03 |
| [`clarification-references/`](clarification-references/) | unresolved references ask before planning; precursor of H4/H4b |
| [`verification/`](verification/) | verifier coverage and strength analysis scripts |

## Registrations

All in [`docs/preregistration/`](../../docs/preregistration/README.md), with the families and corrections.

| registration | status |
|---|---|
| H4 planner clarification | registered, not run |
| H4b clarification resolver | confirmatory, not met |
| H5 completion paraphrase / typed contract | confirmatory, not met |
| H6 abstention replication | confirmatory, met |
| H8 verifier fault injection | confirmatory, met |
| R1 public data (NL2Bash, CLINC150) | confirmatory (own family); ARIES lost to the baselines |
| R1b remedies on new public samples | confirmatory (own family), 3 of 4 |
| M2 four local language models | confirmatory (own family), 6 of 6 |
| X1 H5 and H4b with the remedies | registered exploratory |
| HAL1 hallucination measures | registered descriptive |

## Exploratory work designed after a confirmatory result

| path | what | status |
|---|---|---|
| `experiments/exploratory/h8-verify-scope/` | H8 harness rerun with `ARIES_VERIFY_SCOPE` (differential side-effect check) | run: side-effect mutants 12/14 killed, as predicted (`docs/AUDIT.md` §7) |
