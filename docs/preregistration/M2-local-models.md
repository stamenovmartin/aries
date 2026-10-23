# M2: the same architecture with four local language models (R1b samples)

**Registered:** 2026-10-23, before any output of llama3.1:8b, qwen2.5:1.5b or qwen2.5:14b exists on the R1b samples. The R1b
results for qwen2.5:7b are known (`experiments/thesis-r1b/summary.json`); M2 asks whether what they show depends
on the model. Committed before any M2 run. Any later change goes into a dated Amendment section in a new commit.

**Family:** M2 is its own family of six tests (below), Holm inside M2. It is separate from R1, R1b and the
H4b/H5/H6/H8 family; nothing there is changed or re-tested.

**Why:** the thesis compares context configurations and local models. The existing model comparisons are
router-only (ARIES-FINAL-20261006 A0–A3 with llama3.1:8b, `thesis-followup-20261012/task6-model`; H6 with
llama3.1:8b, `h6-llama`), both exploratory. M2 measures the whole decision (router, capability gate, planner)
and the frozen system with each model on the public R1b samples, so the claim "the architecture, not the model,
makes the difference" can be checked.

## Models (Ollama, local, Q4_K_M; digests recorded in every raw header)

- **qwen2.5:7b**: the primary model; its R1b outputs are reused unchanged (no new run).
- **llama3.1:8b** (digest `46e0c10c…`): a model of another family and similar size.
- **qwen2.5:1.5b**: a smaller model of the same family: does the architecture still keep false actions and
  false claims down when the model is weak?
- **qwen2.5:14b**: a larger model of the same family, the largest that fits the machine's 12 GB GPU: do the
  remedies still help when the model is stronger? With 1.5b, 7b and 14b the comparison is also a size curve.

No prompt, schema, threshold or flag is changed or tuned for llama3.1:8b, qwen2.5:1.5b or qwen2.5:14b; the prompts were
written for qwen2.5:7b. Nothing in M2 was tried on the R1b samples with these models before this file.

## Data, labels, systems, prediction rules

R1b's: the NL2Bash r1b sample (500, frozen LLM labels) and the CLINC150 r1b sample (600, R1's frozen intent
labels); for each model **T** (current source, configuration C1, the R1b treatment), **F** (frozen
ARIES-FINAL-20261006 source, frozen A1 prompt, frozen planner) and **zero-shot** (R1's zero-shot instruction and
schema, that model). Runner: `experiments/thesis-m2-models/run_m2.py` (it calls `run_r1b.py` with `--model` for
T and F, and runs R1's zero-shot request with the model named); raw files in `experiments/thesis-r1b/raw/`,
named by model. Prediction rules and metrics are R1b's functions.

## Tests (family M2, two-sided exact McNemar on per-item correctness, Holm at α = 0.05 over the six)

| id | model | dataset | comparison |
|---|---|---|---|
| M2-a | llama3.1:8b | NL2Bash r1b | `T` vs `F` |
| M2-b | llama3.1:8b | CLINC150 r1b | `T` vs `F` |
| M2-c | qwen2.5:1.5b | NL2Bash r1b | `T` vs `F` |
| M2-d | qwen2.5:1.5b | CLINC150 r1b | `T` vs `F` |
| M2-e | qwen2.5:14b | NL2Bash r1b | `T` vs `F` |
| M2-f | qwen2.5:14b | CLINC150 r1b | `T` vs `F` |

No direction is assumed; each result is reported with its direction, b, c, raw and Holm p.

## Descriptive, outside Holm

- `T` vs zero-shot for each model; the qwen2.5:7b rows from R1b, for comparison.
- Stage counts per model (router acts, gate OUT_OF_SCOPE, planner invalid, planner fail), time per request.
- HAL1's model-level measures on these files: M1 planner outputs that fail validation, by kind, and M5 confident
  action (≥ 0.9) on gold OUT_OF_SCOPE items.
- A table that puts the existing router-only comparisons (A0–A3 on the author fixture; H6) next to M2, with
  their own labels (exploratory).

## Procedure

1. This file, `run_m2.py`, `analyze_m2.py` and `run-m2.sh` are committed. 2. With the live ARIES stopped (as
in R1 and R1b), for llama3.1:8b, then qwen2.5:1.5b, then qwen2.5:14b: F router and planner (NL2Bash), F router (CLINC150), T on
both, zero-shot on both. 3. `analyze_m2.py` writes `experiments/thesis-m2-models/summary.json`.

## Limitations stated in advance

- The prompts and the remedies were developed with qwen2.5:7b; the other models get them untuned, which favours
  qwen2.5:7b. A null or negative result for another model may mean "untuned", not "the architecture fails".
- The R1b samples were already used for qwen2.5:7b, and the author has seen those results.
- LLM gold labels (R1b), one repetition at temperature 0.1, one machine.
- qwen2.5:14b nearly fills the GPU; if part of it runs on the CPU it is slower, and a timeout counts as a wrong
  answer (R1's rule: errors are wrong in every fixed denominator). Errors and time per request are reported.
