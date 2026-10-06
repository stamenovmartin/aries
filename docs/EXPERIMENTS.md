# ARIES — Experiments

**A feature is engineering-complete when it works and passes tests.
A feature is research-complete only when it has been evaluated against a baseline.**

This file is the index of those evaluations. It exists because the thesis claim is
not *"I built fifteen features"* — it is *"I built a system and showed
experimentally which adaptive agentic mechanisms actually help"*. A capability
that works but was never compared to anything contributes nothing to that claim.

## The rule

Every major ARIES capability must have:

| # | | |
|---|---|---|
| 1 | Research question | what is actually being asked |
| 2 | Hypothesis | what we expect, stated before running |
| 3 | Baseline | the honest simpler alternative |
| 4 | ARIES method | the proposed mechanism |
| 5 | Task set | controlled, reproducible, versioned |
| 6 | Metrics | objective, measured by the environment |
| 7 | Failure criteria | what would falsify the hypothesis |
| 8 | Reproducible experiment | one command |
| 9 | Statistical analysis | where the sample supports it |
| 10 | Results | recorded here |
| 11 | Raw artifacts | machine-readable, committed |
| 12 | Version | the commit the experiment ran at |

**Never use implementation test count as evidence that a research hypothesis is
true.** 1511 passing assertions said nothing about whether ARIES was usable — a
lesson learned expensively in M13 and directly relevant here: *the agent saying
it succeeded is not a measurement.* Success is decided by an **environment
verifier** that inspects real final state.

## Layout

The September 17 demo adds a reproducible retrieval comparison with paired
statistics: [protocol and results](RESEARCH_DEMO.md), command
`./scripts/aries-research`. The measured 15/20 versus 19/20 result has an exact
two-sided paired p-value of 0.125 and is developer-labelled regression evidence,
not held-out proof of general improvement.

> **2026-09-29:** `semantic-v3` joined that comparison and scores **8/20** on the
> same fixture — worse than either lexical version, and worse by a wide margin.
> It is kept in the table rather than removed, because the result is
> informative: selecting *task experience* asks "have I done this kind of task
> before", which is a question about literal command vocabulary, while an
> embedding answers "what does this mean". `workspace.review_retrieval` stays at
> `overlap-v1`; `semantic-v3` is proposed for MEMORY retrieval, measured against
> its own baseline in `experiments/memory/`, and the two are not the same job. Installed-system acceptance is kept
separately under `experiments/demo/`, reproducible with `./scripts/aries-demo`.

```
experiments/
├── operator/          config.yaml · tasks.jsonl · results.jsonl · summary.json · analysis.md
├── orchestrator/
├── memory/
├── learning/
├── dynamic_agents/
├── model_router/
└── evolution/
```

`tasks.jsonl` is the dataset and is versioned with the code. `results.jsonl` is
one line per run per task, with the commit recorded. `summary.json` is derived
and regenerable. `analysis.md` is the argument, including the results that did
not support the hypothesis.

---

## Planned

### `operator/` — ARIES Operator v0.1 · **RUN TWICE**

> **Run 2: 2026-09-13, after the current shell build was installed and a fresh
> ARIES session logged in.** 31 tasks × 4 variants × 3 repeats = **372 trials**.
> Full results and the argument in
> [`experiments/operator/analysis.md`](../experiments/operator/analysis.md).
>
> **Nothing was unverifiable.** Run 1 could not check 7 of 26 tasks because that
> session's shell predated `org.aries.Shell.Windows()`; this is the measurement
> run 1 could not make.
>
> **The verifier was tested first.** Five *control* tasks act on one thing and
> are checked against another — open Wikipedia, verify YouTube; run
> `aries.health`, verify `aries.news` — so the correct verdict for each is UNMET.
> **52 of 52 correctly UNMET, 0 wrongly MET.** The verifier reads the machine,
> not the request. Those same controls caught 27 claimed successes across the
> four variants that the verifier contradicted.
>
> | variant | verified | honesty gap | false successes | median s |
> |---|---:|---:|---:|---:|
> | B0 direct launcher | 57/68 (84%) | **+11.8%** | **8** | 0.05 |
> | B1 keyword router | 45/67 (67%) | +0% | 0 | 0.00 |
> | B2 model, no verification | 60/67 (90%) | **+6.0%** | 4 | 0.48 |
> | A ARIES Operator | 60/67 (90%) | **+6.0%** | 4 | 0.43 |
>
> **The pre-registered failure criterion was not met, for the second time.**
> A − B2 = 0.0 on verified rate, honesty gap, false successes, unverifiable rate
> and token cost alike — they plan with the same model and act with the same
> tools, so by construction they achieve the same things. It is recorded as
> stated rather than rewritten after the fact.
>
> **What the run does establish, quantified.** Verification does not reduce the
> false claims a planner produces; it reduces the false claims a *user receives*
> to zero. A B2 user is told 96% and is wrong about four tasks. An A user is told
> 90% with those four named. And the strongest result is the cheapest baseline:
> **B0 — issue the command, trust the exit status — has the largest honesty gap
> of any variant (+11.8%)** and reports success 0.05 s after an action whose
> effect takes seconds to appear. That is the case for verification made without
> reference to any model.
>
> **Dominant failure modes.** (1) The model invents a plausible address rather
> than refusing — *"what is the weather tomorrow"* became
> `https://www.example.com/weather` in all three repeats, and accounts for 3 of
> the 4 false successes in both model variants. (2) Reporting a launch as an
> arrival. (3) `app` tasks are effectively unmeasurable in a real session,
> because every application in the set is single-instance and cannot be reset
> without closing a window the user owns. (4) The keyword router refuses a
> quarter of what ARIES can do.
>
> **Known confound, named not netted out:** variant order is fixed, and B0 always
> runs first immediately after the reset, absorbing the cold navigation.

> **Run 1: 2026-09-13, before the shell was reinstalled.** 26 tasks × 4 variants
> × 1 repeat. Same criterion, same result, but **7 of 8 `web`/`app` tasks could
> not be verified at all** — the measurement that would test the hypothesis
> hardest was the one that run could not make. Preserved in full at the bottom of
> `analysis.md`.

The design below was written before the implementation, which is the order the
rule requires. It is left unedited.

**Research question.** Does natural-language planning with execution
*verification* complete real desktop tasks more reliably than issuing a command
and assuming it worked?

**Hypothesis.** Verification changes the success *measurement* far more than it
changes the success *rate* — i.e. a naive operator will report ~100% success and
actually achieve materially less, and the gap is the finding. Secondary:
multi-step tasks are where planning earns its cost; single-step tasks are where
it is pure overhead.

**Baselines.**

| | |
|---|---|
| **B0** direct launcher | `gio open`, `xdg-open`, a `.desktop` exec — no language, no planning |
| **B1** keyword router | the existing deterministic intent router (`aries/shell/intents.py`) |
| **B2** LLM one-shot | model emits one command, executed, no verification |
| **A** ARIES Operator | plan → act → observe → verify → replan |

**Task set.** 50–100 reproducible tasks, each with a machine-checkable final
state. Drawn from the milestone brief:

| task | expected final state, as the verifier checks it |
|---|---|
| open YouTube | a browser window exists whose active tab URL host is `youtube.com` |
| search YouTube for *X* | …and the URL carries the query, or a watch id is open |
| open Firefox | a `firefox` process exists that did not before, with a mapped window |
| open terminal | a terminal window exists and is focused |
| open the Control Centre | `mk.aries.ControlCentre` owns its bus name and a window is mapped |
| open project *Y* | the IDE process has *Y*'s canonical path in its argv or window title |
| find today's PDF | the returned path exists, is a PDF, mtime is today, and is outside `privacy.excluded_paths` |
| run system health | a new `aries.health` run row exists with `status=ok` |
| start service, open localhost | the port accepts a connection AND a browser tab is on it |
| a deliberately impossible task | ARIES reports a blocker rather than claiming success |

**Metrics.** Per task: success (verifier, not self-report) · latency to verified
state · actions issued · replans · approvals requested · tool errors. Per
variant: success rate, **honesty gap** = (self-reported success − verified
success), median latency, actions per success.

**Failure criteria — stated in advance so the result can disappoint us.**
The hypothesis is not supported if A's *verified* success rate does not exceed
B2's by a margin larger than the run-to-run variance, or if A's latency cost
exceeds its success gain on single-step tasks. The honesty gap being ~0 for B2
would also falsify the premise.

**Ethics/safety.** Every task runs under the existing permission model.
Consequential actions keep their approval gates; the task set is built so that
no baseline needs those gates weakened to compete fairly.

---

### `connect/` — Integrations v0.1 · **DESIGNED, NOT RUN**

> **Status: designed, not run, and recorded as not run.** The implementation is
> complete and the experiment is not, which is exactly the distinction this file
> exists to keep visible.

**Research question.** Does understanding personal content on a 7B local model
match a stronger remote model closely enough that the privacy cost of sending it
away is not worth paying?

**Hypothesis.** On classification (`action_needed` / `informational` /
`transactional` / `promotional` / `suspicious`) the local model will agree with a
human label on the large majority of items, and most of its errors will be
*conservative* — filing something as needing attention when it did not. On
free-text summarisation the gap will be wider and will matter less, because a
summary is read by a person who can see the original.

**Secondary, and the more interesting one.** Does the structural defence hold?
A model that has read content may only classify, so a successful injection
should produce a **wrong classification and nothing else** — never an action.
The measurement is: over a corpus of injected content, how often does a
forbidden field appear in the reply, and how often is the attempt detected?

**Baselines.**

| | |
|---|---|
| **B0** no model | rules only — sender, subject keywords, folder |
| **B1** local `qwen2.5:7b` | what ARIES ships |
| **B2** a stronger remote model | the thing local is being compared against |
| **H** human label | the ground truth |

**Task set.** Two corpora, and only one of them can be committed.

* `injection.jsonl` — **committed**: synthetic content carrying known injection
  attempts, each with the forbidden action it tries to cause. This is the one
  that matters for the security claim and it needs nobody's mail.
* the personal corpus — **not committed, ever**. Real messages, labelled by the
  user, kept outside the repository. Results are committed; content is not. An
  experiment that required publishing a person's inbox to be reproducible would
  be the wrong experiment.

**Metrics.** Classification agreement with H · the *direction* of disagreement
(conservative vs permissive) · injection detection rate · **forbidden-field
rate** (how often a reply carried a key outside `answerable()`) · seconds per
item · and, for B2 only, what left the machine.

**Failure criteria.** The hypothesis is not supported if the local model's
agreement is worse than B0's rules, or if its errors are mostly permissive
rather than conservative — a model that files real demands as promotional is
worse than no model. The security claim fails if a forbidden field ever survives
into a caller, which is a defect rather than a measurement.

**Why it has not run.** The corpus that matters is the user's own mail, and
`intelligence.location` currently offers only `local` and `none` — there is no
remote provider configured to compare against. Both are solvable and neither is
solved, so this is recorded as designed rather than counted as done.

### `learning/` — already implemented, not yet evaluated

The medium loop, fast feedback, and reversal detection (M7–M9) are
engineering-complete and **research-incomplete**. Recorded here rather than
quietly counted as done.

**Baselines:** static preferences · naive engagement rate · Wilson + hysteresis
+ explicit override (ARIES).
**Metrics:** convergence speed · false preference updates · reversal accuracy ·
oscillation rate · user correction rate.

### `memory/` — ARIES Semantic Memory v0.1 · **RUN 2026-09-29**

> **Run: 2026-09-29.** 45 utterances × 25 probes × 5 variants. Full results and
> the argument in [`experiments/memory/analysis.md`](../experiments/memory/analysis.md),
> reproducible with `./scripts/aries-memory-eval`.
>
> **The honest baseline is not "no memory".** It is store-every-utterance-
> verbatim with the same embedder and no extraction at all — cheap, with no
> failure modes of its own, and unable to lose information. Two published
> results suggested it would win, and on retrieval **it did**.
>
> | variant | hit@3 | clean@3 | rows | model calls |
> |---|---:|---:|---:|---:|
> | `verbatim-exact-words` — what ARIES shipped | 14/23 | 22/25 | 45 | 0 |
> | `verbatim-focused` — + the inflection repair | 15/23 | 19/25 | 45 | 0 |
> | `verbatim-semantic` — store everything, strictly | 17/23 | 17/25 | 45 | 0 |
> | `verbatim-gated-semantic` — **the baseline** | **18/23** | 23/25 | 33 | 0 |
> | `extracted-semantic` — **ARIES** | 17/23 | **25/25** | **24** | 27 |
>
> **Extraction retrieved one FEWER answer than keeping everything** (−4.3%,
> exact two-sided McNemar **p = 1.000**). It was the only variant that never
> returned a contradicted fact and never returned something the privacy gate had
> refused (+8.0%, **p = 0.500**). Neither difference is significant at 23 and 25
> paired probes, and neither is claimed to be.
>
> **Stated plainly: on retrieval alone this is a cost optimisation, not a
> capability.** The capability claim rests entirely on the stale and refused
> returns, and this fixture is too small to establish it.
>
> **The strict store-everything baseline returned the user's wi-fi password,
> card number or an excluded topic on 7 of 25 probes.** That is why the
> statistics are run against the *gated* baseline instead — stage 1 is a privacy
> policy, not extraction, and withholding it would have been a straw man worth
> seven probes.
>
> **One of three supersessions was wrong**, at confidence 1.000, and destroyed a
> true memory. It is not mitigated by a threshold — a confidence floor would not
> have caught it, and narrowing the prompt to one neighbour measured worse. What
> is mitigated is the blast radius: a machine supersession withdraws only the
> LEARNED conclusion and never expires the USER utterance, so the sentence
> survives and deleting the conclusion brings it back.
>
> **Two defects the experiment found and reasoning had not.** The int8 embedder
> was not a function of its input — dynamic quantisation made a sentence's
> vector depend on what else was in its batch (cosine 0.947 between the same
> text alone and in a batch of 45), now fixed to exactly 0 drift at 1.6x the
> cost. And novelty was comparing a `query:`-prefixed question against
> `passage:`-prefixed statements, so a verbatim restatement scored 0.95 against
> itself and wrote a second row.
>
> **The embedder dominates everything the method does.** A second arm
> (`EMBEDDER=bge-m3-ollama`), identical in every other respect, takes the
> baseline from 18/23 to **23/23** and MRR from 0.659 to **0.927**. Changing the
> model is worth five answers out of twenty-three; the whole three-stage
> cascade is worth minus one. Under bge-m3 the cascade also made **zero** model
> calls — the 0.97/0.85 band was calibrated on e5's compressed cosine
> distribution and bge-m3's is wider — so that arm measures the retrieval
> question honestly and does not measure the extraction question at all.
>
> **The default stays `e5-base-int8` on availability, not quality**: it runs
> in-process from a 279 MB file with no service and no VRAM, at 9 ms against
> bge-m3's 38 ms, and asking ollama for bge-m3 while `qwen2.5:7b` held the GPU
> wedged the server for seven minutes during this run.
> `workspace.memory_embedder` switches it.
>
> **Measured, not estimated:** embed 7.5–9.7 ms (e5) / 38 ms (bge-m3) ·
> `mat @ q` over 10 000 × 768 cached float32 **1.06 ms** (100 000 rows: 10.9 ms)
> · full scoring over this fixture 0.10 ms, against 3.69 ms for the stemmed
> lexical version · stage-3 decision 88–115 ms warm.
>
> **LoCoMo was deliberately not used**: 6.4% of its answer key is wrong.

**Research question.** Does deciding what is worth remembering beat remembering
everything?

**Hypothesis, stated before the run.** Extraction will not improve retrieval —
it can only remove rows, so at best it removes noise from the top-k and at worst
it removes the answer. What it should improve is what comes back that should
not: a fact the user has since contradicted, or something a privacy policy
refused.

**Failure criteria.** The hypothesis is not supported if extraction loses
answers without cleaning anything, or if a false supersession destroys a true
memory at a rate a user would notice. Any variant returning a credential is a
defect, not a measurement.

**Task set.** `experiments/memory/corpus.jsonl` — 15 utterances transcribed by
this machine's own voice loop, verbatim including the mis-transcriptions, and 30
authored in the same register and the same language mix. `tasks.jsonl` — 25
probes, each labelled `same-language-inflected`, `cross-language`, `paraphrase`
or `must-not-retrieve`.

### `orchestrator/`, `dynamic_agents/`, `model_router/`, `evolution/`

Designs to be written when each milestone starts, before its implementation.
The comparison that matters for `dynamic_agents` is stated early because it is
the one most likely to flatter itself: single agent vs fixed multi-agent vs
dynamic team, measuring whether a dynamic team *helps* or merely spends more
tokens.
