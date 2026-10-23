# H7 (exploratory, future work): a hybrid scope gate (sentence encoder + LLM router) for out-of-scope requests

Status: **postponed to exploratory / future work (author's decision, 2026-10-13).** This is kept as a
design and is not a confirmatory hypothesis. It is not in the Holm family, and no external items are
prepared for it. If it is ever run, it is reported as exploratory, unless it is first registered on its
own with new items. llama3.1:8b stays descriptive.

## Background

In ARIES-FINAL-20261006, the router's OOS recall was the share of decisions on out-of-scope requests
that were OUT_OF_SCOPE (40 requests × 3 repetitions = 120 decisions). For arm A3, it was 29 of 120
(24.2%) with qwen2.5:7b (`experiments/thesis-followup-20261012/inputs/final-evaluation.json`) and 1 of
120 (0.8%) with llama3.1:8b (Task 6, `experiments/thesis-followup-20261012/task6-model/summary.json`).
For A1, it was 46 of 120 (38.3%) with qwen. The
literature describes the same pattern and a hybrid remedy (wording verified in
`docs/preregistration/CITATIONS.md`):
- all models, LLMs included, have poor OOS recall, and it depends on the label space. A hybrid that sends
  a query to the LLM only when an encoder is uncertain works better (Arora et al., EMNLP 2024 Industry;
  UDRIL, Zaera et al., ACL 2025 Industry);
- top-k tool retrieval keeps the choice small (ToolScope, arXiv:2510.20036; Toollery, arXiv:2609.22218,
  preprint);
- on BFCL irrelevance, Llama-3.1-8B scores 41.62 and Qwen2.5-7B 64.95 (iTool, arXiv:2501.09766);
- constrained decoding can push small models toward naming a tool instead of abstaining (Lee,
  arXiv:2608.13959, preprint, 0.6B–4B models).

## The treatment (`ARIES_SCOPE_GATE`, not yet implemented)

1. **Encoder score.** Before the LLM router, the request is embedded with the local encoder ARIES already
   ships (`intfloat/multilingual-e5-base`, int8 ONNX, CPU; `aries/workspace/memory/embedding.py`). It is
   compared with fixed exemplars, 10–30 paraphrases per capability in English and Macedonian, written by
   the author **before any test item exists** and frozen by SHA-256 at registration. The score is the
   maximum cosine similarity, and the best-matching capabilities are ranked.
2. **Three zones:**
   - score ≥ τ_high: the normal router, shown only the top-k capabilities (k fixed at registration,
     between 5 and 8);
   - score < τ_low: OUT_OF_SCOPE, decided by code with no model call;
   - between the two: the existing LLM router, shown only the top-k capabilities and the machine limits.
3. **Router schema order** (only with the flag on): `matched_capability_ids` (taken from the top-k,
   possibly empty), then a short `scope_reason`, then the decision. Putting a short reason before the
   label is **our inference** from Tam et al. (EMNLP 2024 Industry): that paper only shows the order
   problem and does not test this recommendation.
4. **Optional, exploratory only:** decision-token logprobs from Ollama, if this version (0.34.0) exposes
   them, are logged for a per-model threshold analysis. They are not part of any criterion.

## Thresholds: calibration set only

- **Calibration set:** the 225 requests of the frozen ARIES-FINAL-20261006 fixture. It is not H7 test
  data, covers all four classes in both languages, and its labels are frozen (`semantic_labels.json`).
  Thresholds are computed from encoder scores only, with no LLM call, by a script committed at
  registration.
- **τ_low:** the highest value at which, among calibration requests scoring below it, at least 87% are
  non-actionable (out of scope, unsafe or ambiguous). Holding is the correct binary outcome for all of
  these.
- **τ_high:** the lowest value at which at least 95% of the calibration requests scoring at or above it
  are actionable (the author's rule, 2026-10-13).
- Both values and k are written into an amendment **before** the test items are opened, and never
  changed afterwards.

## Hypothesis

**H7.** With the gate on, the router declares OUT_OF_SCOPE on more out-of-scope requests (OOS recall)
than with the gate off, for qwen2.5:7b. In-scope behaviour stays within a 3-point margin.

## Materials

New items written by another person who has not seen the code, the exemplars or the 225 original
requests. Half are English and half Macedonian, and each item is labelled with its class by that person:
- at least 160 out-of-scope requests;
- at least 160 in-scope requests: actionable ones, each with the intended capability;
- 60 ambiguous requests.

The structure is validated (fields, classes, counts, no overlap with the 225 or with the exemplars),
with PASS or FAIL and counts reported. The author does not read the items before the measurement.

## Procedure

- The frozen router protocol runner, copied and changed only in fixture, flags and output paths. Gate
  off is the A3 configuration of ARIES-FINAL-20261006; gate on is A3 plus `ARIES_SCOPE_GATE=1`.
- 3 repetitions, with the frozen seeds for request and arm order, at temperature 0.1.
- Both models, each on the same items. The live ARIES is stopped, screen blanking is off and restored
  afterwards, and the Ollama version, model digests and quantisation are recorded before and after.
- Parse failures count as errors.

## Primary outcome and test

OOS recall: the share of out-of-scope items answered OUT_OF_SCOPE, by per-item majority of 3. Gate on
vs off, **qwen2.5:7b**, one-sided exact McNemar at α = 0.05 (exploratory, not in the Holm family).
Reported with b, c, b/c, the difference in proportions and an exact 95% interval. llama3.1:8b is
descriptive.

## Non-inferiority guards (qwen2.5:7b), margin 3 percentage points

Each guard uses the paired difference (gate on minus gate off). It is met if the one-sided 95% Newcombe
bound is within 3 points:
1. ACT accuracy on in-scope items;
2. false OOS rate on in-scope items;
3. ask rate on clear in-scope items.

With 160 in-scope items, these bounds are tight: a few extra errors can already fail a guard. This is
stated now.

## Secondary outcomes (descriptive)

- the same measures for llama3.1:8b;
- the qwen vs llama gap in OOS recall, with the gate on and off;
- retrieval Recall@k: how often the intended capability of an in-scope item is in the top-k;
- the share of items in each zone;
- latency per request, with the gate on and off;
- binary accuracy by class.

## Stated in advance

- **Part of the effect is by construction.** Below τ_low, code declares OUT_OF_SCOPE with no model
  call. The claim is that a hybrid gate beats LLM-only judgement for local 7–8B models, not that the
  model learned to abstain.
- Exemplars written by the ARIES author encode the author's idea of each capability. The test items
  come from someone else, so this is part of what the test measures.

## What would count against H7

A non-significant primary means the gate does not raise OOS recall measurably. A failed guard means it
buys recall with in-scope errors. Either is reported as a result.
