# Thesis improvements (2026-10-22/23): results index

Every number below is read from the file named next to it. Confirmatory = registered family with Holm;
exploratory/descriptive = outside any family. Raw files with item texts are not committed.

| Batch | Registration | Label | Result | File |
|---|---|---|---|---|
| R1b: R1 remedies on new public samples | `docs/preregistration/R1b-improved-router-planner.md` | confirmatory (4 tests, 3 significant) | NL2Bash T 348/500 vs frozen 233/500 and zero-shot 320/500; CLINC150 342/600 vs 268/600, vs zero-shot 334/600 n.s. (Holm p 0.48); in scope weaker (92/219 vs 120/219) | `experiments/thesis-r1b/summary.json` |
| R1b exploratory configurations | same, outside Holm | exploratory | NL2Bash C3 338, G 327, S 303, C0 253 (/500); CLINC150 C3 341, G 338, S 316, C0 286 (/600) | `experiments/thesis-r1b/summary.json` |
| M2: four local models | `docs/preregistration/M2-local-models.md` | confirmatory (6 tests, 6 significant) | T vs F, NL2Bash: llama3.1:8b 225 vs 110, qwen2.5:1.5b 281 vs 109, qwen2.5:14b 349 vs 210 (/500); CLINC150: 327 vs 222, 245 vs 219, 354 vs 316 (/600). qwen2.5:1.5b's planner fails on all 479 calls, so its NL2Bash score is refusals only (in scope 0/219) | `experiments/thesis-m2-models/summary.json` |
| P1: latency, resources, reliability | `docs/preregistration/P1-performance.md` | descriptive | decision median/p90: 1.2/1.4 s (1.5b), 1.2/3.2 s (7b), 2.9/3.7 s (8b), 2.8/6.5 s (14b); cold load 1.9-27.6 s; VRAM max 1.7/5.2/5.9/10.0 GB; installed system 63/85 per run, 89/90 same outcome, B8 was 88/90; diagnosis (exploratory): 8 blanked screen (ARIES Background Mode), 9 context over budget, 6 invalid planner output, 2 unverifiable, 2 as in B8. Amendment 1: C2 (screen awake) 69/70/70 of 90, C3 (+ dispatch fix) 70/70/70; Amendment 2 (C4, the remedies on the live system) not run: deploying the current source to the live service needs the owner's approval | `experiments/thesis-p1-performance/summary.json`, `diagnosis.json` |
| X1: H5/H4b reruns with remedies | `docs/preregistration/X1-remedy-reruns.md` | exploratory (items already seen) | H4b code-select 32/40 pairs (8/40 twins over-asked); H5 G correct done 12/45 vs 6/45 and 0/45, false done 15/75 vs 12/75 and 3/75; held-out PASS 86/147 vs 87/147 and 92/147 | `outcomes-reruns.json`, `summary-reruns.json` |
| HAL1: hallucinations | `docs/preregistration/HAL1-hallucination-measures.md` (+ Amendment 1) | descriptive | invented evidence 0/50, 0/26, 0/8; invalid planner output 126/449 (R1 frozen) -> 2/208 (R1b C1); done while the oracle fails on held-out 0/147, 9/147, 18/147 | `hallucination-summary.json` |
| M1: memory and news | `docs/preregistration/M1-*.md` | exploratory | LoCoMo hit@5 0.620 with hybrid + similarity rank vs BM25 0.500 (+0.120 [0.098, 0.147]); MIND MMR AUC 0.611 vs round-robin 0.578; relative learning +0.000 (expectation wrong) | `experiments/iis/real-data/{locomo,mind}/results/` |

## What it means

- The capability gate and per-capability grammar (code, not prompt text) carry the R1b gain, and M2 shows the gain
  over the frozen system does not depend on the model. Against the model alone the gain holds on NL2Bash only, and
  the cost is in-scope accuracy for the Qwen family.
- The model does not invent evidence; false successes come from completion contracts that accept real evidence for
  the wrong goal. Widening the contracts (H5 remedies) completes more goals and more false ones.

## Unresolved

- Completion contracts that check the goal, not only the evidence.
- The in-scope cost of the capability gate.
- One repetition for R1b and M2; LLM labels; prompts tuned on qwen2.5:7b.
