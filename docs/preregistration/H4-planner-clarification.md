# Preregistration H4: planner-level clarification on ambiguous targets

Status: **registered before any measurement of the change.** The commit that adds this
file is the registration timestamp. Any later edit to this file must be a new commit
with a dated "Amendment" section; the original text stays unchanged.

## Background

On the independent held-out fixture run of 2026-10-06
(`experiments/product/independent-acceptance/raw/fixture_run_20261006T154854Z.json`),
the class `ambiguous_target` scored 0 of 5. Every case failed safely (sandbox unchanged,
nothing reported complete) but none produced a question. Code analysis showed the
planner had no action for asking: `execute`, `finish`, `fail`, `ask_approval`.

The change under test adds `ask_clarification` behind the flag `ARIES_PLANNER_CLARIFY`.
A question is accepted only after a verified observation and only if at least two
choices name a path or name taken from verified step results.

The five original ambiguous cases motivated the change and are therefore **not**
held-out for this hypothesis. They are reported separately and do not count toward H4.

## Hypothesis

**H4.** With `ARIES_PLANNER_CLARIFY` on, the agent asks a grounded clarification on
new ambiguous goals, without asking on matched goals that have exactly one fitting
target, and without lowering results on the other held-out classes.

## Materials

1. **New ambiguous set (A):** 10 scenarios, each with two or more existing targets that
   fit the goal and no information that selects one.
2. **Matched control set (C):** 10 scenarios built from the same templates as A, but
   with exactly one fitting target, so the correct behaviour is to act, not to ask.
3. Both sets are written by a person other than the author, who has not seen the
   implementation. The author does not read the scenarios before the measurement.
   Oracles are validated against a do-nothing run before measurement.
4. The existing held-out fixture (57 scenarios, 49 runnable) for regression.

## Procedure

- Code frozen at a tagged commit on branch `thesis-followup`; hash recorded.
- Model qwen2.5:7b, same digest and decoding settings as ARIES-FINAL-20261006.
- Two conditions: `ARIES_PLANNER_CLARIFY=1` (treatment) and `=0` (control).
- 3 runs per condition, condition order alternated (on, off, on, off, on, off).
- Fresh isolated database per run.

## Outcome definitions

- **Grounded question:** terminal state `needs_clarification` with `clarification.source
  == "planner"`, at least 2 choices, sandbox unchanged, no target read or written.
- **Per-scenario outcome:** the majority result over the 3 runs of a condition.

## Criteria (all three must hold)

1. **Asks when it should:** in set A, treatment produces a grounded question in
   **at least 7 of 10** scenarios.
2. **Does not ask when it should not:** in set C, treatment asks in **at most 1 of 10**
   scenarios.
3. **No regression:** on the 44 runnable non-ambiguous held-out scenarios, the
   treatment PASS count is **not lower than the control PASS count by more than 2**.

Criterion 1 is also reported against the control condition. The expected control
result is 0 of 10, since the control condition cannot ask after planning begins.

## Analysis

- Primary: the three criteria above, reported exactly as defined, whatever the result.
- Secondary (descriptive): per-run counts, Wilson 95% intervals for criteria 1 and 2,
  exact McNemar on per-scenario majority outcomes (treatment vs control) for set A,
  and the original five ambiguous cases reported separately.
- No scenario is removed after the measurement. INCONCLUSIVE oracle results are
  reported as such and count as not meeting criterion 1 for that scenario.

## What would count against H4

Criterion 1 not met means the structural fix is insufficient for this model.
Criterion 2 not met means the model asks too readily. Criterion 3 not met means
the option harms other behaviour. Each of these is reported as a result.

## Amendment 1 (2026-10-12), before any measurement

Added after registration and before any H4 measurement. The text above is unchanged.

**Why.** A second behaviour change now exists on the branch: `ARIES_COMPLETION_READ_PARAPHRASE` (commit
`fecfe86`), the fix for the missing completion contracts found in `docs/analysis/terminal-state-diagnosis.md`.
If it differed between the two H4 conditions, or were left to its default, a difference between conditions
could come from completion rather than from asking.

**What is fixed.**

1. `ARIES_COMPLETION_READ_PARAPHRASE=0` in **both** H4 conditions (`ARIES_PLANNER_CLARIFY=1` and `=0`). H4 was
   registered for the system without that fix, so H4 measures only the registered change. The flag's default is
   on, so each run sets it explicitly. A run whose recorded effective value (`aries.flags.describe()` read from
   the running instance) differs is invalid and is reported, not rerun silently.
2. The completion fix is measured **separately** and labelled as such: `ARIES_PLANNER_CLARIFY=1` with
   `ARIES_COMPLETION_READ_PARAPHRASE=1`, 3 runs, on the same materials. It is **not** part of H4 and does not
   enter criteria 1–3. Because the fix was designed after looking at the held-out fixture, its result on that
   fixture is reported as "discovered by diagnosis, fixed, measured on the same fixture", with no claim of
   generalisation.
3. All other flags stay at the values recorded in each run's artifact; none is changed between conditions.

**Not an amendment, recorded for completeness.** The code under test includes `1a4bc47`, which restricts
grounding to path-like observations and their final component. This implements the registered rule ("a path or
name taken from verified step results") and does not change it.
