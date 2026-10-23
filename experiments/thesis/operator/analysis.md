# `operator/` — ARIES Operator v0.1

**Run 2:** 2026-09-13 · commit `45de099-dirty` · 31 tasks × 4 variants × 3 repeats = **372 trials**
**Raw:** [`results.jsonl`](results.jsonl) · [`summary.json`](summary.json) · [`tasks.jsonl`](tasks.jsonl) · [`config.yaml`](config.yaml)

The first run could not verify 7 of its 26 tasks, because the shell in that
session predated `org.aries.Shell.Windows()`. This run was made after the
current shell build was installed and a fresh ARIES session logged in, so the
window list exists and **nothing is unverifiable**. That is the measurement run
1 could not make.

---

## 1. Does the verifier work? — asked first, because nothing else counts if it does not

Five **control** tasks were added. Each acts on one thing and is checked against
another: open Wikipedia, verify YouTube; launch the calculator, verify GIMP;
navigate to News, verify Interests; launch a name that cannot launch; run
`aries.health`, verify `aries.news`. The correct verdict for every one of them
is **UNMET**. A verifier that grades the plan instead of the machine returns MET
here, and every other number in this file would then be worthless.

| | |
|---|---:|
| control trials scored | **52** |
| correctly **UNMET** | **52** |
| wrongly **MET** | **0** |

The verifier reads the machine, not the request. Separately, the controls caught
**27 claimed successes across the four variants that the verifier contradicted**
— 7 for B0, 6 for B1, 7 for B2, 7 for A. That is the honesty gap in its purest
form: on these tasks, *every* variant would have told the user it had done
something it had not.

**An error worth recording.** The first version of this integrity block reported
8 verifier failures. It had not applied its own exclusion rule: a YouTube window
left open by an earlier task, in a *second* Firefox window the neutral-page reset
could not reach, had already been caught by the precondition check and marked
`contaminated`. The verifier had read the machine correctly; the summary had not
read its own rule. Fixed by correcting the derivation and recomputing from the
raw rows — never by re-running the trials, which would have changed the
measurement in order to repair a report of it.

---

## 2. Results

Four exclusions, each counted out loud: **held at a gate** measures the gate,
**unverifiable** measures the session, **contaminated** means the expectation was
already satisfied before the trial began, **control** tasks are scored above
instead.

| variant | n | contam | unver | checkable | reported | verified | verified rate | honesty gap | false successes | median s | plan tokens/task |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **B0** direct launcher | 78 | 10 | **0** | 68 | 65 | **57** | 83.8% | **+11.8%** | **8** | 0.05 | 0 |
| **B1** keyword router | 78 | 11 | **0** | 67 | 45 | **45** | 67.2% | +0.0% | 0 | 0.00 | 0 |
| **B2** model, no verification | 78 | 11 | **0** | 67 | 64 | **60** | 89.6% | **+6.0%** | 4 | 0.48 | 284.6 |
| **A** ARIES Operator | 78 | 11 | **0** | 67 | 64 | **60** | 89.6% | **+6.0%** | 4 | 0.43 | 284.5 |

By task class, verified / checkable:

| variant | aries | web | app | impossible | ambiguous |
|---|---:|---:|---:|---:|---:|
| B0 | 36/36 | 2/10 | 1/4 | 15/15 | 3/3 |
| B1 | 27/36 | 0/10 | 0/3 | 15/15 | 3/3 |
| B2 | 36/36 | **9/10** | 0/3 | 15/15 | **0/3** |
| A | 36/36 | **9/10** | 0/3 | 15/15 | **0/3** |

---

## 3. A versus B2 — the comparison the hypothesis is about

| | A | B2 | difference |
|---|---:|---:|---:|
| verified success rate | 89.6% | 89.6% | **0.0** |
| honesty gap | +6.0% | +6.0% | **0.0** |
| false successes | 4 | 4 | **0** |
| unverifiable rate | 0.0% | 0.0% | 0.0 |
| median latency | 0.43 s | 0.48 s | −0.05 s |
| planning tokens / task | 284.5 | 284.6 | −0.1 |

**They are identical on every axis.** With 3 repeats, zero unverifiable trials,
and a verifier proved sound by 52 controls, A and B2 achieved exactly the same
things at exactly the same cost.

### The preregistered failure criterion, unchanged

> *"The hypothesis is not supported if A's verified success rate does not exceed
> B2's by a margin larger than the run-to-run variance."*

**A − B2 = 0.0. The criterion is not met, for the second time, on a much stronger
measurement.** It is recorded as stated and not rewritten.

The criterion was badly posed and the hypothesis said so in its own next
sentence: *verification changes the success measurement far more than it changes
the success rate*. A and B2 plan with the same model and act with the same
tools, so by construction they achieve the same things. What the criterion
should have compared is not what each variant achieves but **what each variant
tells the user** — and that is the one place where they differ completely:

* a **B2** user is told **64 of 67 succeeded — 96%**, because B2 has no verifier and the tool's return value is all it has to report;
* an **A** user is told **60 verified of 67 — 90%**, with the other 4 named, what was checked, and what was found instead.

**The 6% is what a B2 user would have been wrong about**, and now — unlike run 1
— it is measured over a task set with nothing unverifiable in it.

---

## 4. Does verification materially reduce false-success claims? — quantified

This is the question worth answering, and the answer is not the one the
criterion asked for.

| what the user is told | B0 | B1 | B2 | A |
|---|---:|---:|---:|---:|
| claimed successes | 65 | 45 | 64 | 64 |
| of those, actually achieved | 57 | 45 | 60 | 60 |
| **claims that were false** | **8** | **0** | **4** | **4** |
| false-claim rate | **12.3%** | 0.0% | 6.3% | 6.3% |

Verification does not reduce the number of false claims a planner *produces* —
A and B2 produce four each. It reduces the number a user *receives* to **zero**,
because A does not report the four; it reports them as contradicted. The
mechanism is not better planning, it is refusing to pass on an unchecked claim.

**The strongest result in the table is B0.** The simplest, fastest and most
common way to build this — issue the command, trust the exit status — has the
**largest honesty gap of any variant, +11.8%**, and reports success 0.05 s after
issuing an action whose effect takes seconds to appear. It is the cheapest
variant and the most dishonest one, and that is the case for verification stated
without reference to any model.

---

## 5. Dominant failure modes

**1 · The model invents a plausible address rather than refusing.** `imp-weather`
— *"what is the weather tomorrow"* — produced, in all three repeats and for both
model variants:

```json
{"tool": "desktop.open_url", "payload": {"url": "https://www.example.com/weather"}}
```

It opened a browser at a made-up address and reported success. This single task
accounts for **3 of the 4 false successes** in both B2 and A. B0 and B1 score
3/3 here precisely because they cannot invent: B0 has no language and B1's
router has no pattern for it. **A model that must produce an action will produce
one**, and the structural defence against that is a vocabulary it cannot leave —
which the Operator has for tools, and does not have for the *contents* of a URL.

**2 · Reporting a launch as an arrival.** B0's web trials failed 8 of 10 with the
verifier recording, 8 seconds later, that the browser still showed the neutral
reset page. `xdg-open` had returned 0 and B0 reported success at t+0.05 s. The
mechanism is exactly the one this milestone exists to measure — *a command that
exits 0 is not a page that loaded* — but the **magnitude here is inflated by
variant order**: B0 always runs first, immediately after the reset, and absorbs
the cold navigation, while B2 and A inherit a warm browser. Both halves are
true, and the confound is named rather than netted out.

**3 · `app` is effectively unmeasurable in a real session.** Every desktop
application in the task set is single-instance, so a trial cannot be reset
without closing a window the user may own — for `app-terminal`, the one this
experiment runs in. 10–11 trials per variant were excluded as contaminated, and
of what survived, the clean trials mostly failed for reason 2. **This class needs
a different design, not more repeats.**

**4 · The keyword router refuses a quarter of what ARIES can do.** B1 verified
27/36 `aries` tasks: it has no pattern for *"show me what ARIES has learned"* or
*"show me the data screen"*. Its honesty gap is a perfect +0.0% — it never claims
anything it did not do — which is the trade the router makes and the reason it
is a baseline rather than the product.

---

## 6. Threats to validity

* **Variant order is fixed** (B0, B1, B2, A) and the reset immediately precedes
  B0. Reason 2 above is partly an artefact of this. Randomising order is the
  first change the next run should make.
* **`app` and part of `web` remain contaminable.** 10–11 of 78 trials per variant
  were excluded on this ground. They are excluded, not counted — but the
  surviving sample for `app` is 3–4 trials, which is too small to carry a claim.
* **One machine, one session, one model.** `qwen2.5:7b` on an RTX 3060. Nothing
  here generalises to another model without re-running.
* **`imp-weather` dominates the model variants' false successes.** Three of four
  come from one task repeated three times. The honesty gap for B2 and A is
  therefore a statement about one failure mode, not four independent ones.
* **The verifier's strongest grade is unevenly available.** 36 of 60 A-verified
  trials are `proof` (the Control Centre answering for itself); 9 are
  `circumstantial` (a browser window title). A window title is evidence, not
  proof, and the grades say so rather than averaging them together.

---

## 7. What would make the next run decisive

1. **Randomise variant order** per trial, and report the order with each row.
2. **Give `open_url` a closed vocabulary** the way tools have one — the
   `example.com/weather` failure is a planner allowed to write free text into a
   field the verifier must then check.
3. **Measure `app` in a dedicated session** with no user windows, where closing
   is legitimate — or drop the class and say so.
4. **Compare against a stronger model** for planning quality; `intelligence.location`
   offers only `local` and `none` today, so this cannot be run yet.

---

# Run 1 — 2026-09-13, before the shell was reinstalled

*Kept unedited. Its dominant limitation — 7 of 8 `web`/`app` tasks unverifiable
because the session predated `Windows()` — is the reason run 2 exists.*

**Run:** 2026-09-13 · commit `5274455-dirty` · 26 tasks × 4 variants, 1 repeat
**Raw:** [`results.jsonl`](results.jsonl) · [`summary.json`](summary.json) · [`tasks.jsonl`](tasks.jsonl) · [`config.yaml`](config.yaml)

---

### Results

| variant | n | held | unverifiable | checkable | reported | verified | honesty gap | median s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **B0** direct launcher | 26 | 1 | 7 | 18 | 17 | **17** (94%) | +0% | 0.04 |
| **B1** keyword router | 26 | 1 | 7 | 18 | 14 | **14** (78%) | +0% | 0.00 |
| **B2** model, no verification | 26 | 1 | 7 | 18 | 17 | **16** (89%) | **+6%** | 0.45 |
| **A** ARIES Operator | 26 | 1 | 7 | 18 | 17 | **16** (89%) | **+6%** | 0.43 |

`held` = stopped by a gate (the News Radar's circuit breaker, in all four cases — excluded, it
measures the breaker). `unverifiable` = no window list available in this session — excluded, it
measures the session.

---

### The pre-registered failure criterion was NOT met

Stated in advance: *"the hypothesis is not supported if A's verified success rate does not exceed
B2's by a margin larger than the run-to-run variance."*

**A and B2 verified identically: 16/18 each.** By the criterion as written, the hypothesis is not
supported, and that is recorded here rather than quietly reframed.

It should not have been written that way, and the hypothesis itself says so in its next sentence:
*"verification changes the success measurement far more than it changes the success rate"*. A and
B2 plan with the same model and act with the same tools, so of course they achieve the same
things. The whole difference is what they **tell the user**:

* a **B2** user is told **17 of 18 succeeded (94%)** — the reported column, because B2 has no
  verifier and nothing else to report;
* an **A** user is told **16 verified, 1 contradicted (89%)** — and shown which one, what was
  checked, and what was found instead.

**The 6% is what a B2 user would have been wrong about.** A falsification criterion that compares
achievement between two variants that achieve the same thing by construction was the wrong
criterion; the right one compares *what each variant claims* against *what the environment says*,
which is what the honesty-gap column is. Recording this properly matters more than the number: a
pre-registered criterion that turns out to be badly posed is a result about the experiment, and
rewriting it after seeing the data would make every other number here worth less.

---

### What the numbers actually say

**1. The deterministic router is the cheapest honest system, and it is not enough.**
B1 verified 14/18 with a **0% honesty gap** and a median latency of 0 ms — when it acts it
succeeds, and when it has no pattern it refuses. It is beaten only on coverage: it refused three
section requests phrased in ways its table does not contain (*"show me what ARIES has learned"*,
*"show me the data screen"*, *"open the home screen"*). This is the strongest argument in the run
for a model at all — and it is an argument about **vocabulary**, not about reasoning.

**2. The model costs 430 ms at the median and buys 2 tasks.**
A and B2 recover exactly the requests B1 refused. That is a real gain on a small task set, and it
is the gain a *0.43-second local* model bought — no network, no account, nothing leaving the
machine.

**3. The honesty gap is small here, and the reason is the most important sentence in this file.**
+6% is one task. The task set is dominated by ARIES's own surfaces — sections and automations —
which verify at **proof** grade: read from a run row, or from the Control Centre answering for
itself. Those are precisely the cases where a tool's own report is *already* reliable, so there is
little for a verifier to catch.

The cases where a naive operator would most plausibly be wrong are `web` and `app` — where the
launcher returns 0 whether or not anything appears. **Seven of those eight tasks could not be
verified at all in this run**, because there was no window list: the ARIES shell in this session
predates the `Windows()` method added for this milestone, and Wayland gives no other way to
enumerate windows.

So the measurement that would test the hypothesis hardest is exactly the one this run could not
make. The honest statement is: *on proof-verifiable tasks the gap is small (+6%), and the gap on
window-verifiable tasks is unmeasured.* Anything stronger would be the failure this milestone
exists to name.

**4. `unverifiable` behaved as designed, under real conditions.**
Every one of the 7 unverifiable results came with the reason and with what ARIES *could* still
establish — *"1 'nautilus' process is running, but the ARIES shell is not running, so ARIES cannot
tell whether it has a window on screen or is a background process."* No variant reported those as
successes; A reported them as `unconfirmed`. This was not arranged for the experiment — it is the
session the experiment happened to run in, which is the best possible test of an honesty
mechanism.

**5. The one measured contradiction is a mislabelled task, and it is left in.**
`imp-weather` (*"what is the weather tomorrow"*) was written as an impossible request. The model
answered *"open the Weather application"*, which is a defensible reading; it fails here only
because no weather application is installed on this machine. It has been **reclassified as
`ambiguous`** with that note in `tasks.jsonl` rather than deleted. A task set is a hypothesis too,
and one that was wrong should be visible.

The same task exposed a genuine bug on a second sampling: the model answered `open_section:
weather` — a step shaped exactly like a real one, naming a screen that does not exist. The prompt
listed the valid sections and the validator did not check them. **Asking politely in a prompt is
not a constraint**; both enums are now enforced, and a test pins the planner's section list to the
Control Centre's.

---

### What building this found that the numbers do not show

Four real defects, all surfaced by the verifier rather than by a test:

* **`aries-ui` was broken for every invocation by name**, which is how the shell launches it — so
  every navigate action from the ARIES desktop had been dead. The e2e called the repository path
  and passed. (Second failure at this seam; see Entry 017.)
* **The News Radar was inserting duplicate `item_id`s**, poisoning its session with
  `PendingRollbackError` and, after three passes, opening its own circuit breaker. It hid because
  the pass returned `success: True` from its body while the lifecycle recorded `failed` — two
  answers about one run that nothing compared until the Operator did.
* **`run_automation` reported `ran` as success.** An automation whose body failed has
  `ran: True, status: "failed"`. A tool that lies to its own verifier makes the verifier do
  avoidable work and would be believed anywhere the verifier is not.
* **The at-most-once register replayed the second "open the news screen"** as a duplicate of the
  first and returned success without doing anything — correct for sending an email, exactly wrong
  for opening a window.

Two defects in the harness itself, both of which would have produced wrong results:

* **Trials contaminated each other.** Four variants ran the same task in sequence, so a variant
  that refused and did nothing inherited the previous one's success — B1 "verified" three section
  tasks it had explicitly refused. Trials are now reset, and the reset is confirmed before the
  trial starts.
* **The engine's hourly action cap fired mid-run** (30 actions) and was recorded as planning
  failure. A rate limiter looked like a planner collapsing. Gated runs are now counted separately
  and excluded.

---

### Threats to validity

* **n is small.** 18 checkable tasks, one repeat. No confidence intervals are claimed and none
  should be read into the table.
* **7 of 26 tasks are unverifiable in this session**, and they are the ones that matter most for
  the hypothesis. This is the dominant limitation.
* **`web` and `app` trials are contaminable** — an application cannot be un-opened without closing
  windows the user may own, so a later variant can inherit an earlier one's window. Marked in the
  results as `reset: contaminable`.
* **B0 is not a fair "no-language" baseline for coverage**, only for execution: it is handed the
  expected parameters, so it measures whether the tools work, not whether a system could have
  worked out what to do.
* **One model, one machine, one day.** Nothing here says anything about a different model.

---

### What would make the next run decisive

1. **Log in to the ARIES session with the shell build that has `Windows()`.** That alone converts 7
   unverifiable results into verifiable ones and moves the experiment onto the tasks where the
   hypothesis has teeth.
2. **More repeats**, for run-to-run variance on a stochastic planner.
3. **Tasks where the launcher succeeds and the goal does not** — a `.desktop` file for an
   application that is not really installed, a URL that redirects elsewhere, an application that
   starts and maps no window. Those are the honesty gap's natural habitat, and this task set does
   not contain them.
4. **A fairer B1**, given the vocabulary gap is what the model is actually buying: adding three
   patterns to the router would close most of the measured difference, and knowing that is worth
   more than the 2-task gain.
