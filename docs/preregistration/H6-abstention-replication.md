# Preregistration H6: replication of the abstention-instruction effect (A1 vs A0) on new requests

Status: **draft, not registered.** It becomes registered when committed and pushed, before any H6 item
exists or is opened. Any later edit must be a new commit with a dated "Amendment" section.

## Background

In ARIES-FINAL-20261006 (frozen router run, qwen2.5:7b, 225 requests, 3 repetitions), the instruction
that allows the router to answer ASK or OUT_OF_SCOPE (arm A1, `ARIES_ROUTER_ABSTAIN`) raised binary
accuracy over the arm without it (A0). Per request (majority of 3), exact McNemar gave A1 right and A0
wrong on 36 requests, the reverse on 11, p = 0.00035 (`experiments/thesis-followup-20261012/stats.json`).
That test was post hoc, on the same 225 requests that suggested the arms. H6 tests the effect on new
requests.

The original split by class (`experiments/thesis-followup-20261012/h6-power/power.json`) shows where
the effect comes from and what it costs:

| class | A1 right, A0 wrong | A1 wrong, A0 right | n |
|---|---|---|---|
| actionable | 0 | 11 | 100 |
| ambiguous | 22 | 0 | 55 |
| out of scope | 11 | 0 | 40 |
| unsafe | 3 | 0 | 30 |

The instruction makes the router hold more often: that helps on everything that should not be acted on,
and hurts on actionable requests.

Related work (wording verified in `docs/preregistration/CITATIONS.md`): all models, LLMs included, have
poor OOS recall, which depends on the label space (Arora et al., EMNLP 2024 Industry); small models often
"hallucinate a tool call" instead of asking (Ross et al., When2Call, NAACL 2025); format and instruction
effects transfer poorly between models (Sclar et al., ICLR 2024), which is why llama3.1:8b is only
exploratory here.

## Hypothesis (directional)

**H6.** On new requests, the frozen router with the abstention instruction (A1) has higher per-request
binary accuracy than without it (A0), for qwen2.5:7b.

## Materials

- **New requests, written and labelled by another person** who has not seen the original 225 requests,
  the ARIES code or the router prompts. The class definitions they get are the four classes of the
  frozen fixture, in plain words: actionable (ARIES can and should do it), ambiguous (cannot be done
  without asking what is meant), out of scope (not something ARIES can do), unsafe (should not be done).
  A template and a README for the author are in `experiments/thesis-followup-20261012/h6-items/`.
- **Size and mix: 300 requests**, with the class shares of the master plan's 120: 100 actionable,
  75 ambiguous, 62 out of scope, 63 unsafe. The size was raised from 120 to 300 before any H6 item exists,
  because of the power analysis below.
- **Language.** Half English, half Macedonian in every class, as in the original fixture.
- The file's SHA-256 is recorded before the run. The author of ARIES does not read the requests before
  the run. A validator checks only the structure (fields, classes, counts, unique ids, no duplicate
  utterances, no overlap with the 225 original utterances) and reports PASS or FAIL with counts.

## Procedure

- The frozen ARIES-FINAL-20261006 router protocol and runner, unchanged
  (`experiments/thesis-final-20261006/run_router.py`, `protocol.json`): same prompts, decoding,
  `keep_alive`, model digest of qwen2.5:7b, and the frozen scorer (`analyze_router.py`, binary `correct()`).
- Arms A0 and A1 only. 3 repetitions. As in the frozen protocol, the arm order and the request order of
  each repetition are shuffled with its fixed seeds (`random.Random(26061006 + rep)` for arms,
  `26100000 + rep` for requests), at temperature 0.1: the Ollama adapter exposes no sampling seed.
- The runner is a byte copy of the frozen one, with only the fixture path, the arm list and the output
  folder changed. Task 6 did the same for llama3.1:8b
  (`experiments/thesis-followup-20261012/task6-model/`), and the diff is recorded.
- The live ARIES is stopped during the run, screen blanking is off and restored afterwards, the Ollama
  version and model digest are recorded before and after, and the run is refused if either changes.
- Parse failures and invalid decisions count as wrong, as in the frozen scorer.

## Primary outcome and test

Per request, the majority of 3 repetitions is correct or not. **One-sided exact McNemar test** of A1
against A0 on the discordant requests (b = A1 right and A0 wrong, c = the reverse), H1: b > c, α = 0.05
**before** the Holm correction across the primary tests of the four confirmatory hypotheses H4b, H5, H6
and H8. Reported: b, c,
the exact p-value, the Holm-adjusted p-value, the difference in binary accuracy with an exact
(Clopper-Pearson-based, paired) 95% interval, and b/c.

## Power (computed before any H6 data exists)

From the original per-class split reweighted to the H6 class mix, by simulation of the exact McNemar
test (`h6-power/power.py`, seed 61013, 20,000 draws per scenario; power counts only significant results
with b > c), one-sided α = 0.05:

| n | observed effect | effect halved | effect quartered |
|---|---|---|---|
| 120 | 0.96 | 0.44 | 0.16 |
| 200 | 1.00 | 0.64 | 0.24 |
| 300 | 1.00 | 0.82 | 0.33 |

An effect estimated on the set that suggested it is usually too large, so the "halved" column is the
realistic one. With 300 requests, power for a halved effect is 0.82 at α = 0.05. Under the Holm
correction across 4 tests, the strictest level is 0.05/4 = 0.0125, so power is lower than the table shows.
That is why 300 requests are used and not 120: with 120, a real but halved effect would be missed more
often than found. This is stated now so that a non-significant result is read correctly.

## Secondary outcomes (descriptive)

- abstention precision and recall, per arm (frozen scorer);
- binary accuracy by class, per arm, with exact intervals;
- over-abstention: the share of actionable requests held (ASK, OUT_OF_SCOPE, UNKNOWN), per arm. It is
  expected in advance to be higher with A1, as in the original split (0 vs 11);
- llama3.1:8b, the same protocol, exploratory, with a small or null effect expected (in the original run
  its A1 vs A0 split was 15 vs 10, p = 0.42).

## What would count against H6

A non-significant primary test means the effect did not replicate at this sample size (see Power). A
significant result with b < c would contradict the original finding. Either is reported as a result.
