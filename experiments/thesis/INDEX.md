# Thesis evidence: path map

This folder is an index. **Nothing has been moved into it.** Each entry is listed at its current
path. The frozen trees, and everything a frozen file names by exact path or by hash, stay where
they are (`docs/AUDIT.md` §1.2, §1.6). A later move is allowed only with a symlink left at the old
path.

Status labels follow the README evaluation map.

## Frozen, in place

| path | what | status | why it is not moved |
|---|---|---|---|
| `experiments/thesis-final-20261006/` | router experiment, arms A0–A3, qwen2.5:7b | confirmatory (criterion not met) | frozen |
| `experiments/thesis-followup-20261012/` | follow-up: H4b, H5, H6, H8, stats, terminal diagnosis, thesis tables | mixed, see its `RESULTS.md` | frozen; `thesis-tables/check.py` reads fixed paths |
| `experiments/router-ood/` | out-of-distribution router fixture | input to the above | pinned by sha256 in `thesis-final-20261006/semantic_labels.json:9-10` |
| `experiments/product/independent-acceptance/` | held-out end-to-end fixture and raw runs | descriptive | read by `thesis-tables/check.py` and named in the preregistrations |
| `verification/` | frozen verifier ledger, `build_facts.py`, `reproduce.sh` | descriptive | `check.py` reads `verification/ledger_frozen.json` |
| `scripts/thesis_stats.py` | statistics used by `check.py` and `h6-power/power.py` | — | read by frozen code |

## Thesis precursors, in place (the audit proposes moving them here later)

Each one has references outside itself, so moving it needs the references rewritten or a symlink.

| path | what | refs outside |
|---|---|---:|
| `experiments/operator/` | Operator v0.1, 372 trials, where the verification argument started | 12 |
| `experiments/planner/` | planner prompt variants, 2026-09-30 and 2026-10-03 | 3 |
| `experiments/clarification-references/` | unresolved references ask before planning; precursor of H4/H4b | 1 |
| `experiments/verification/` | verifier coverage and strength analysis scripts | 3 |
| `experiments/verification-feedback/` | does independent verification feedback change what the agent does next | 88 |
| `experiments/router-en/` | English router fixture with its own `check.py` | 3 |

## Preregistrations and amendments

All of these are in `docs/preregistration/` (frozen). `docs/INDEX.md` lists the amendments.

| hypothesis | file | status |
|---|---|---|
| H4 planner clarification | `docs/preregistration/H4-planner-clarification.md` | registered, not run |
| H4b clarification resolver | `docs/preregistration/H4b-clarify-resolver.md` | confirmatory, measured (not met) |
| H5 completion paraphrase / typed contract | `docs/preregistration/H5-completion-paraphrase.md` | confirmatory, measured (not met) |
| H6 abstention replication | `docs/preregistration/H6-abstention-replication.md` | confirmatory, measured |
| H8 verifier fault injection | `docs/preregistration/H8-verifier-fault-injection.md` | confirmatory, measured |
| R1 public data (NL2Bash, CLINC150) | `docs/preregistration/R1-real-data-benchmarks.md` | confirmatory (own family), measured; data in `experiments/thesis-r1-real-data/` |
| R1b remedies on new public samples | `docs/preregistration/R1b-improved-router-planner.md` | confirmatory (own family, 3 of 4), measured |
| M2 four local language models | `docs/preregistration/M2-local-models.md` | confirmatory (own family, 6 of 6), measured |
| X1 H5 and H4b re-run with the remedies | `docs/preregistration/X1-remedy-reruns.md` | registered exploratory, measured |
| HAL1 hallucination measures | `docs/preregistration/HAL1-hallucination-measures.md` | registered descriptive, measured |

## After the diagnosis (2026-10-22/23), in place

| path | what | status |
|---|---|---|
| `experiments/thesis-r1-real-data/` | R1: NL2Bash and CLINC150 samples, labels, runner, analysis | confirmatory (own family) |
| `experiments/thesis-r1b/` | R1b: new samples and labels, development log, runner, analysis | confirmatory (own family) |
| `experiments/thesis-m2-models/` | M2: the R1b systems with four local models | confirmatory (own family) |
| `experiments/thesis-improvements-20261022/` | X1 reruns, HAL1 hallucination measures, the results index `RESULTS.md` | exploratory / descriptive |

## Exploratory work designed after a confirmatory result

| path | what | status |
|---|---|---|
| `experiments/exploratory/h8-verify-scope/` | H8 harness rerun with `ARIES_VERIFY_SCOPE` (differential side-effect check) | run: side-effect mutants 12/14 killed, as predicted (`docs/AUDIT.md` §7) |
