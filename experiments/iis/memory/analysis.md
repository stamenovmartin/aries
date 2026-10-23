# `memory/` — ARIES Semantic Memory v0.1 · **RUN 2026-09-29**

> **The pre-registered hypothesis was supported on one metric and not on the
> other, and the honest summary is the disappointing half.** Deciding what to
> remember did **not** retrieve more answers than remembering everything — it
> retrieved **one fewer** (17/23 against 18/23, exact two-sided McNemar
> **p = 1.000**). It was the only variant that never returned a fact the user
> had since contradicted and never returned anything the privacy gate had
> refused (25/25 clean against 23/25, **p = 0.500**), and it did that on 24 rows
> instead of 33, at 27 local model calls.
>
> **On retrieval alone this is a cost optimisation and not a capability.** The
> capability claim rests entirely on the two stale returns it avoided, and 25
> probes cannot establish that. It is recorded as measured.

> **And a second run changed which question matters.** Swapping the embedder for
> `bge-m3` and changing nothing else took the baseline from 18/23 to **23/23**
> and MRR from 0.659 to **0.927**. The embedder is worth five answers out of
> twenty-three; the extraction is worth minus one. See
> [the second arm](#the-second-arm-bge-m3) below.

Reproduce: `./scripts/aries-memory-eval` (default) ·
`EMBEDDER=bge-m3-ollama ./scripts/aries-memory-eval` (second arm)
Raw: [`summary.json`](summary.json) · [`results.jsonl`](results.jsonl) ·
[`summary-bge-m3.json`](summary-bge-m3.json) ·
[`results-bge-m3.jsonl`](results-bge-m3.jsonl) · design: [`config.yaml`](config.yaml)
Fixture `6afa34b20cb50877…` · implementation `2c78a76a1ca36024…` ·
commit `3eb5f46` · embedder `e5-base-int8` · decision model `qwen2.5:7b` · k = 3

## Results

| variant | hit@3 | clean@3 | recall@3 | MRR | rows | model calls | credential / excluded returns | stale returns |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `verbatim-exact-words` — what shipped | 14/23 | 22/25 | 0.587 | 0.558 | 45 | 0 | 2 | 1 |
| `verbatim-focused` — + the inflection repair | 15/23 | 19/25 | 0.630 | 0.580 | 45 | 0 | 4 | 2 |
| `verbatim-semantic` — store everything, strictly | 17/23 | 17/25 | 0.696 | 0.623 | 45 | 0 | **7** | 2 |
| `verbatim-gated-semantic` — **the baseline** | **18/23** | 23/25 | **0.739** | **0.659** | 33 | 0 | 0 | 2 |
| `extracted-semantic` — **ARIES** | 17/23 | **25/25** | 0.696 | 0.580 | **24** | 27 | 0 | **0** |

Paired, `extracted-semantic` against `verbatim-gated-semantic`:

| outcome | difference | improved | regressed | exact two-sided McNemar |
|---|---:|---:|---:|---:|
| hit@3 | −4.3% | 2 | 3 | **p = 1.000** |
| clean@3 | +8.0% | 2 | 0 | **p = 0.500** |

Neither is significant. At 23 and 25 paired probes, neither could have been.

## What the numbers actually say

**1. The biggest single win has nothing to do with extraction.** Going from the
predicate ARIES shipped (`verbatim-exact-words` — whole words longer than three
characters) to any semantic variant is +3 to +4 answers. Nearly all of it is
cross-language: the old predicate answers **1 of 7** cross-language probes,
semantic answers 3 or 4. A Macedonian speaker whose assistant also reads English
could not reach their own memory before. That is a bug fix, not a research
result, and it should not be counted as one.

**2. Store-everything really is a strong baseline, and it wins on retrieval.**
It has the highest hit@3, the highest recall@3 and the highest MRR of the five.
This is neither surprising nor a flaw in the extraction: a variant that stores
strictly fewer rows can only lose answers. The two published results that
predicted this were right on this fixture.

**3. The strict reading of store-everything returns credentials.** With no stage
1 at all, `verbatim-semantic` returned the wi-fi password, the card number or
the excluded therapy topic on **7 of 25 probes**. That is why the statistics are
run against `verbatim-gated-semantic` instead: stage 1 is a privacy policy, not
extraction, and withholding it from the baseline would have been a straw man
worth 7 probes.

**4. Where extraction earns its place is contradictions, and only there.**
`verbatim-gated-semantic` cannot help returning the old mentor when asked who
the mentor is — both statements are stored and both are about mentors, so both
come back. `extracted-semantic` withdrew the superseded belief and returned only
the current one, on both contradiction probes. That is the whole of the +2.

**5. Extraction lost three answers, and one of the three is a defect rather than
a property of the design.**

| lost | why |
|---|---|
| `fact-brother-birthday` | the model labelled it ABORT at confidence 0.995. Simply wrong. |
| `plan-monitor` | the model labelled it ABORT at confidence 0.975. Simply wrong. |
| `pref-news-mk` | **a false supersession** — below |

**6. The false supersession is the most important finding here.** Of three
supersessions the cascade made, **two were right and one was wrong**:
"Не ми се допаѓа кога АРИЕС отвора прозорци без да прашам" was judged to
contradict "Сакам вестите да ми ги читаш на македонски", at confidence **1.000**
and cosine 0.901. Both are preferences about how ARIES should behave; neither
contradicts the other. A wrong APPEND costs a redundant row. A wrong SUPERSEDE
destroys a true memory.

It is **not mitigated by a threshold**, deliberately. A confidence floor would
not have caught it — the model was maximally confident. Narrowing the prompt to
a single neighbour was tried and measured *worse*: asked pairwise, the same
model called the same sentence a supersession at confidence 1.000, where with
four neighbours in view it correctly said COEXIST at 0.442.

What is mitigated is the blast radius, and structurally: a machine supersession
withdraws only the LEARNED conclusion and never expires the USER utterance
(`store.observe`, `store.withdrawn_sources`, asserted by
`tests/test_memory.py::test_a_machine_supersession_never_unsays_what_the_user_said`).
The sentence the user spoke is still in the database, verbatim, and removing the
conclusion that withdrew it brings it back. That is the layer model doing the
job it exists for, and it is why this defect is survivable rather than
destructive.

**7. The cascade's cost profile.** 12 of 45 utterances never reached a model
because stage 1 refused them (27%); 6 more were settled by cosine alone (13%).
**27 of 45 escalated — a 60% escalation rate**, far above SAGE's reported 16–18%
saving. The reason is measurable and belongs to the embedder rather than the
method: e5's cosine for short sentences occupies a narrow band. On this corpus a
verbatim restatement scores 0.992, a genuine contradiction 0.950, a
circumstantial qualification 0.939, and completely unrelated pairs bottom out at
**0.827**. The whole usable range is 0.83–0.99, so any band wide enough to keep
contradictions out of the "already known" bucket is also wide enough to send
most things to the model. A textbook 0.90 / 0.50 band would have filed the
mentor change as a duplicate and thrown it away.

## Measured, on this machine

| | |
|---|---:|
| embed one utterance (e5-base-int8, ONNX, 4 CPU threads) | **7.5–9.7 ms** median |
| search 10 000 × 768 cached float32, `mat @ q` | **1.06 ms** |
| search 1 000 × 768 | 0.052 ms |
| search 100 000 × 768 (293 MB) | 10.9 ms |
| full scoring over this fixture (24–45 rows) | 0.10 ms |
| the same rows through lexical `focused-v2` | 3.69 ms — **36× slower** |
| stage-3 decision, warm ollama qwen2.5:7b | 88–115 ms |
| embed one utterance (bge-m3, 1024-dim, via ollama) | 38 ms median |
| embedder load (e5, in process) | 0.82 s |

The lexical row is worth reading twice. The stemmed word-overlap version is the
slowest retrieval in the table, because it re-tokenises every stored memory for
every query, while the semantic version is one BLAS call over a matrix already
in RAM. The 1.06 ms at 10 000 rows reproduces the earlier measurement that
motivated having no vector index at all.

## Corrections the experiment forced on the implementation

Two defects were found by building this rather than by reasoning about it. Both
are recorded because neither was predicted.

**The int8 embedder was not a function of its input.** `multilingual-e5-base` is
*dynamically* quantised: the int8 scales for each activation tensor are computed
at run time from that tensor, so a padded batch changes the scales and therefore
the answer. Measured: `play some music.` embedded alone and inside a batch of 45
differed by **cosine 0.947**, with hidden states at real token positions drifting
13% relative. Masking was honoured — an all-ones mask was three times worse — so
this is quantisation, not attention. A vector that depends on its neighbours
cannot be compared with one stored last week, so `OnnxE5.encode` now runs one
sequence per graph call. Cost: 7.5 ms per text instead of 4.7 ms at batch 16.
Drift after the fix: exactly 0.

**Novelty was comparing a question with a statement.** The first implementation
embedded an incoming utterance with e5's `query: ` prefix and compared it against
stored `passage: ` vectors. That is the right asymmetric form for retrieval and
the wrong one for deduplication: a sentence scored 0.95 against a verbatim copy
of itself, below the redundancy threshold, so restating something wrote a second
row. Novelty now embeds as a passage, which also halves the embedding cost of an
observation.

## Limitations, stated rather than worked around

* **25 probes, 45 utterances, one user, one developer writing the labels.** The
  p-values are 1.000 and 0.500; this fixture cannot establish either difference
  and is not claimed to.
* **The probes were authored after the corpus, by the person who wrote the
  corpus.** They were written to be answerable and to be inflected differently
  from the memory that answers them, which is the real condition — but this is
  not a held-out set.
* **LoCoMo was deliberately not used**: 6.4% of its answer key is wrong, and
  tuning against it teaches those errors.
* **The stage-2 thresholds were calibrated on this fixture** (0.97 / 0.85) and
  are specific to `e5-base-int8`. A different embedder has a different cosine
  distribution and needs its own band, which is why `Cascade` takes them as
  arguments instead of reading the constants.
* **The `bge-m3` arm ran, and its thresholds are wrong.** See below — the band
  is e5's, and under bge-m3 it escalated nothing at all, so that arm measures
  the retrieval question and not the extraction question.
* **The evaluation drives `extraction`, `vectors` and `retrieval` directly, not
  through SQLAlchemy.** The database adds nothing to the research question and
  would make the run minutes long. In the live store an observation writes an
  utterance *and* a conclusion, and supersession withdraws only the conclusion;
  here the two are 1:1 by construction, so one row stands for the pair. The
  retrieval-visible effect is identical; the layer rule is checked in
  `tests/test_memory.py` instead.
* **15 of 45 utterances are real transcriptions; 30 were authored.** Real voice
  traffic on this machine is almost entirely commands — the journal's addressed
  utterances are `play some music`, `split the screen left and right`,
  `отвори YouTube и пушти песната`. Nobody has yet told this assistant anything
  about themselves, because until today it could not have kept it. The authored
  half is written in the same register, with the same language mixing and the
  same ASR artefacts, and every line is marked `observed` or `authored` in
  `corpus.jsonl`.
* **`cmd-news-mk` ("што има денас од вести") pollutes the top three of many
  probes** in every semantic variant. It is a short question that e5 places near
  most other short questions, and the gate does not catch it because it is not
  imperative. An unfixed weakness of stage 1.

## The second arm: `bge-m3`

`EMBEDDER=bge-m3-ollama ./scripts/aries-memory-eval` · 1024 dimensions, served
by ollama. Same fixture, same probes, same decision model, same code.

| variant | hit@3 | clean@3 | MRR | rows | model calls |
|---|---:|---:|---:|---:|---:|
| `verbatim-exact-words` | 14/23 | 22/25 | 0.558 | 45 | 0 |
| `verbatim-focused` | 15/23 | 19/25 | 0.580 | 45 | 0 |
| `verbatim-semantic` | 22/23 | 19/25 | 0.891 | 45 | 0 |
| `verbatim-gated-semantic` | **23/23** | 23/25 | **0.927** | 33 | 0 |
| `extracted-semantic` | **23/23** | 23/25 | **0.927** | 32 | **0** |

**The embedder dominates everything else in this experiment.** Holding the
method fixed and changing only the model takes the baseline from 18/23 to 23/23
and MRR from 0.659 to 0.927. For comparison, the entire extraction cascade —
three stages, a local model, 27 calls — moves the same number by −1. The
published benchmark gap that chose e5 in the first place is 90.4 against 92.9
nDCG@10 on `mkd_Cyrl`; on this fixture the gap is far larger than that number
would lead anyone to expect, and every cross-language miss e5 had is gone.

**The extraction became inert, and that is the point about thresholds.** Under
bge-m3 the cascade made **zero model calls** and dropped one row. The band
(0.97 / 0.85) was calibrated on e5's compressed distribution; bge-m3's is wider,
so nothing landed between the thresholds and stage 2 settled everything. With no
stage 3 there were no supersessions, so the two stale returns came back and
`clean@3` stayed at 23/25 instead of 25/25. This arm therefore measures the
*retrieval* question honestly and does **not** measure the extraction question
at all — a re-calibrated band would be a different experiment, and it has not
been run.

**The default is still `e5-base-int8`, and that is an availability decision, not
a quality one.** e5 runs in this process from a 279 MB file with no service, no
VRAM and no network; bge-m3 needs ollama up, 1.2 GB of VRAM it must share with
the decision model, and — measured here — **38 ms per embedding against e5's
9 ms**. While this was being run, asking ollama for bge-m3 while `qwen2.5:7b`
held the GPU wedged the server for seven minutes and it had to be restarted.
A memory system whose write path stops working when a model server is busy is
worse than one that is five answers less accurate. `workspace.memory_embedder`
switches it for anyone who disagrees, and the evidence for disagreeing is in
this table.

## What would change the verdict

A fixture large enough for the clean@3 difference to be testable — on the order
of 200 probes over a corpus with a realistic density of contradictions. At
23/23, the bge-m3 arm has also saturated hit@3, so a harder probe set is now
needed for that metric to say anything at all.

And a re-calibrated band for bge-m3. The extraction question has only been asked
of one embedder, because under the other the cascade never ran. Calibrating the
band against bge-m3's own distribution and re-running is the single cheapest
thing left, and until it is done the only honest statement about extraction is
the one measured on e5: **minus one answer, plus two clean probes, neither
significant.**
