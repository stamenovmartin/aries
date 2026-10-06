# Experimental protocol

Fixed before any run. Deviations get recorded as deviations, with the reason, in the
result file — not edited into this document afterwards.

## Design

```
fault_mode_i  ×  repetition_j  ×  condition{control, treatment}  →  outcome
```

15 goals × 2 conditions × 20 repetitions = **600 runs**. Repetitions are not optional
here: a text-to-speech gate on this same machine moved from 0.0321 to 0.0884 with no code
changed, because the speech model's duration predictor is stochastic. A single run of a
sampling language model is worth the same.

Conditions differ in one variable, `ARIES_VERIFY_FEEDBACK`:

| | control | treatment |
|---|---|---|
| `observation` reaching the planner | the tool's own report | the verifier's independent re-read |
| `verification_status` | withheld | present |
| `evidence_refs` | **present** | **present** |
| `observed_satisfied` grounded in | the tool reported success | a verifier confirmed it |
| loop, retries, typed errors, state snapshot, step history, budget | identical | identical |

The control is a system somebody could ship — one that trusts its tools — not a crippled
treatment. Asserted in code, not assumed: the symmetry check prints the fields that differ
between arms and fails if anything but those two does.

## Recorded per run

`goal_id · fault_mode · condition · repetition · seed · steps · planner_calls ·
contradiction_detected · refused_before_acting · reroute_attempted · reroute_verified ·
terminal · why · tokens_in · tokens_out · latency_s · source_hashes · flags.describe()`

## Outcomes, in four stages

One label for the final state, three flags for how it got there. The first version of this
classifier credited "verified something else" as a recovery, which scored a capability
*refusing to act* the same as an agent noticing a contradiction and finding a working
alternative. Those are different events.

| stage | question | field |
|---|---|---|
| detection | did it notice the action did not establish the state? | `contradiction_detected` |
| decision | stop, retry, or another route | `reroute_attempted` |
| execution | did the alternative work? | `reroute_verified` |
| final state | success, honest failure, or false success | `terminal` |

`terminal` ∈ `false_success` · `safe_stop` · `reroute_verified` · `reroute_attempted` ·
`budget_exhausted` · `skipped` · `error`. Mutually exclusive. `skipped` means the fault was
never reached, is reported, and is never scored.

`refused_before_acting` exists to keep a refusal out of the recovery numbers: if the
capability declined, no action happened, so there was no claim to contradict and nothing to
recover from.

## Statistics

**Primary outcome: false-success rate.** Pooled rate per condition with a Wilson 95%
interval, and the paired comparison across the 15 goals rather than across the 600 runs —
runs within a goal are not independent, and treating them as 600 independent trials would
shrink every interval by a factor it has not earned.

- per goal, per condition: false-success proportion over 20 repetitions
- paired across the 15 goals: exact two-sided McNemar on the per-goal majority outcome,
  using `aries.workspace.learning_eval.paired_statistics`, which the project already uses
  for retrieval A/B and which reports `improved`, `regressed` and both Wilson intervals
- reported as: absolute difference, relative reduction, 95% interval, p, and **n at every
  level** — 15 goals, 20 repetitions, 600 runs

With 15 pairs, McNemar's exact test can reach p < 0.05 only with roughly 6 discordant
pairs all in one direction. That is stated in advance so a null result is read as "this
design could not resolve an effect smaller than that" rather than as "no effect exists".

**Secondary, each with its own interval:** `safe_stop` rate, `reroute_verified` rate,
`contradiction_detected` rate, steps to resolution, token overhead, latency overhead. Token
counts come from the provider where it reports them; where it does not, the field is null
rather than a character-count heuristic.

## Why fault injection is the method and not a shortcut

Under ordinary operation, contradictory tool-state observations were rare in this
deployment: **0 contradictions across 336 verified steps.** Controlled fault injection was
therefore required to obtain enough observations of the failure mode for a comparative
evaluation. The injection rate is a declared design parameter, and every injected mode
reproduces a failure this machine really produces — none was invented for the experiment.

## Threats this protocol does not remove

- **One model, one prompt.** `qwen2.5:7b` under this instruction. Not a claim about LLM
  agents as a class.
- **In-process surface.** The loop, planner and capability execution run in the measuring
  process so the fault is reachable; the service boundary is not exercised. Recorded in
  every result file.
- **Authored fixture.** 15 goals written by one author. They are the phrasings that were
  thought of.
- **Detection is inferred from behaviour**, not from the agent's words, because its words
  are not evidence. An agent that privately noticed a contradiction and still claimed
  success is scored as not having detected it. That is deliberate and it is a limit.
