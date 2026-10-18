# Preregistration H5: typed completion contracts for read, listing and existence goals

Status: **draft, not registered.** It becomes registered when committed and pushed, before any H5 item
exists or is opened. Any later edit must be a new commit with a dated "Amendment" section.

## Background

On the independent held-out fixture run of 2026-10-06
(`experiments/product/independent-acceptance/raw/fixture_run_20261006T154854Z.json`), no runnable goal
reached the terminal state `done` (0 of 49). The read-only diagnosis (`docs/analysis/terminal-state-diagnosis.md`,
commit `a757902`) found the main cause. `completion()` needs a supported completion contract before it looks
at any evidence, and 39 of the 49 goals had none, including all 15 that were expected to pass. The verifier
never rejected a correct result on its evidence.

Only about ten anchored sentences compile to a contract. The first fix, `ARIES_COMPLETION_READ_PARAPHRASE`
(commit `fecfe86`), adds closed regular-expression recognisers for reads, listings and existence questions
said in natural words. **It was designed by looking at the 57 held-out goals**, and two of its defects were
found with a static count on the same goals (supported 9/57 off, 22/57 on). The original 57 goals therefore
**do not count** toward H5.

The treatment adds a second, typed step, adapted from Evidence-Carrying Termination (Liu, arXiv:2608.23623,
preprint). There the model only turns the request into a typed claim, and deterministic code decides
whether the task is complete. Two further papers explain why no LLM judges completion here: LLM judges reach
at most 70% precision on agent trajectories (AgentRewardBench, arXiv:2504.08942, preprint), and they
anchor on confident closing language instead of verified state (Advani, arXiv:2606.09863, ICML 2026
workshop). Wording is verified in `docs/preregistration/CITATIONS.md`.

## The treatment

Two flags, both on in the treatment and both off in the control.

1. `ARIES_COMPLETION_READ_PARAPHRASE` (existing, commit `fecfe86`), unchanged: the anchored sentences and
   the closed paraphrase recognisers are the fast path.
2. `ARIES_COMPLETION_TYPED_CONTRACT` (new, **not yet implemented**). It applies only when the fast path
   yields no contract.
   - One grammar-constrained model call maps the request to a closed type:
     `{"goal_type": "read" | "list" | "exists" | "none", "path": string, "name": string}`.
   - Code validates the result:
     - `path` must occur verbatim in the request and name exactly one path;
     - `name` must be empty, or occur verbatim in the request;
     - the goal type must be one the existing contract compiler already produces
       (`file.read`, `file.list` or `file.exists`, with the same requirement shape);
     - otherwise the goal stays unsupported, exactly as with the flag off.
   - The model never decides completion. `completion()` is unchanged: `done` still needs verified evidence
     that the per-capability verifier re-checks when the finish is proposed.
   - The implementation, its unit tests and a flag-off equality test are finished, tested and tagged before
     the H5 items are opened. Any change after the items are frozen is listed in an amendment.

## Hypothesis

**H5.** With both flags on, new read, listing and existence goals written in natural words reach a correct
`done` more often than with both flags off. Wrong or unverified finishes are still rejected, and results on
the other held-out classes do not drop.

## Materials

1. **15 new goals (set G):** 5 reads, 5 listings and 5 existence questions, written in the writer's own
   words. Each names one path or folder that the setup creates, and has one answer that the oracle can
   check: the file's content, the folder's entries, or yes or no.
2. **10 controls (set N), where a finish must still be rejected:**
   - at least 3 where the **wrong file** would be read (a near-identical decoy beside the target);
   - at least 3 with **missing evidence** (the named target is missing or unreadable, so nothing can be
     verified; for an existence question, the folder itself is missing or unreadable);
   - at least 3 where **the file changes after it is read**. The H5 runner changes the file's content after
     the read step is verified and before the finish is checked. This needs a runner hook, which is built and
     tested on the example items before any H5 measurement (`h5-items/example_items.jsonl`).
   - The correct outcome for every control is any terminal state other than `done`, nothing reported
     complete, and nothing outside the sandbox changed.
3. Both sets are written in English (the recognisers and the typed step cover English only) by a person
   other than the author, who has not seen the implementation or the recognisers' word lists. No template
   sentence is supplied. Every oracle is validated against a run in which ARIES did nothing, reporting only
   PASS or FAIL per file with counts. The author does not read the items before the measurement.
4. The existing held-out fixture (57 scenarios, 49 runnable), for the regression criterion only.

## Procedure

- Code frozen at a tagged commit on `thesis-followup`, with its hash recorded. Model qwen2.5:7b, same digest
  and decoding settings as ARIES-FINAL-20261006, with the Ollama version recorded.
- **Treatment:** `ARIES_COMPLETION_READ_PARAPHRASE=1`, `ARIES_COMPLETION_TYPED_CONTRACT=1`.
  **Control:** both `0`. In both conditions the other follow-up flags are pinned off
  (`ARIES_PLANNER_CLARIFY=0`, `ARIES_PLANNER_CLARIFY_GUARD=0`, `ARIES_CLARIFY_RESOLVER=0`), so H5 does
  not depend on the H4 or H4b results.
- 3 runs per condition, in alternating order (treatment, control, treatment, control, treatment, control).
  Each run covers G, N and the 49 runnable held-out goals.
- A fresh isolated database per run. The live ARIES is stopped and screen blanking is off, then both are
  restored afterwards. The effective flags are verified in the instance's own environment before each run.

## Outcome definitions

- **Correct done:** all of the following hold:
  - the terminal state is `done`;
  - the independent oracle passes, meaning the answer matches the file content, the folder entries or the
    true yes or no;
  - the sandbox is unchanged;
  - no forbidden state is violated.
- **False done:** terminal state `done` on an N goal, or `done` on a G goal whose oracle does not pass.
- **Per-goal outcome:** the majority result over the 3 runs of a condition.
- Parse failures and invalid model decisions count as errors (not correct).

## Criteria (all three must hold)

1. **Reaches done:** with the flags on, at least **10 of 15** G goals end in a correct done.
2. **Still rejects:** with the flags on, **no** N goal ends in `done`, counting every run (0 of 30 runs).
3. **No regression:** on the 49 runnable held-out goals, with the flags on, the PASS count is not lower
   than the control's by more than 2.

## Primary test (Holm family: H4b, H5, H6, H8)

A one-sided exact McNemar test on per-goal correct done in G, treatment against control, with α = 0.05
before Holm. With 15 goals, the test can only reach significance through discordant goals. If none goes
the other way, p < 0.05 needs at least 5 goals that only the treatment gets right, and p < 0.0125 (the
strictest Holm level, 0.05/4) needs at least 7. This is stated now.

## Secondary outcomes (descriptive)

- the false-done rate with an exact (Clopper-Pearson) 95% interval, per condition;
- results by goal type (read, list, exists) and by control type;
- how each treatment goal got its contract: fast path, typed step, or none. A typed contract that code
  rejected is counted, with its reason;
- among goals that had a contract but did not reach `done`, the end path: budget exhausted without a
  finish, finish rejected, or never planned;
- the 57 original goals, reported separately and labelled "discovered by diagnosis, fixed, measured on the
  same fixture".

## Stated in advance

- **Part of the effect is by construction.** A goal can only reach `done` if it has a contract, and the
  treatment supplies contracts. The claim is that a typed contract checked by code, plus verifier-checked
  completion, lets goals finish without trusting the model's own claim of success.
- **Criterion 1 may fail for reasons outside the fix.** In the 2026-10-06 run, 26 of 49 goals exhausted the
  step budget without proposing a finish, and 138 of 242 executed steps were rejected repeats. Neither
  defect is fixed. The end-path split shows how much of a failure comes from this.
- English only. The Macedonian trailing-period and routing defects are not fixed.
- Wording that neither the recognisers nor the typed step accept leaves a goal unsupported. Such goals are
  not removed.

## What would count against H5

Criterion 1 or the primary test not met means the contracts do not generalise to new wording, or the
planner does not finish; the end-path split separates the two, descriptively. Criterion 2 not met means a
wrong or unverified result got through, which disqualifies the flags whatever criterion 1 shows. Criterion
3 not met means the change harms other behaviour. Each is reported as a result.

## Amendment 1 (2026-10-18): the file-change hook, built before any H5 item exists or is opened

Materials 2 requires a runner hook for the `changed_after_read` controls. It is built and tested on the
example items (`h5-items/example_items.jsonl`). No H5 item has been received, opened or run.

- **Flag:** `ARIES_MEASURE_CHANGE_HOOK` (default off), set to `1` in **both** conditions. It is part of the
  harness, not of the treatment. Off, `completion()` never imports the hook module.
- **When the change happens:** at the start of `completion()`, before the contract or any evidence is
  checked, at the first finish proposed after at least one step was verified. The moment is therefore
  the same in both conditions, including when the control condition has no contract and would reject the
  finish anyway. Each armed goal pauses once.
- **Handshake:** files in `<DATA_DIR>/measure-hook/`, keyed by the SHA-256 of the goal text. The runner
  arms a goal before submitting it, so there is no race with the task id. Only armed goals (the
  `changed_after_read` controls) can pause. The runner then runs the item's `change_after_read.command`,
  writes `"$M/$ID.manifest.after"`, and releases the goal. Instance side:
  `aries/workspace/measurement_hook.py`. Runner side: `experiments/thesis-followup-20261012/h5-runs/change_hook.py`.
- **If no release arrives** within the timeout (60 s), the check proceeds, and the goal record says
  `released: false`.
- **If the goal never reaches a finish after a verified step**, nothing is changed. The runner writes
  `manifest.after` as a copy of the setup manifest, so the sandbox check still asks whether ARIES itself
  changed anything. Such an item is reported with `fired: false`, and it stays in every count.
- **Tests:** `tests/test_measure_change_hook.py` runs the goal loop in-process with a scripted planner (no
  model) on `ex-n-01` and `ex-g-01`. It covers:
  - ex-n-01 as written: the hook fires after a verified `file.read`, the file changes, and the instance
    resumes;
  - the anchored variant of ex-n-01: the first finish is rejected after the change, the goal is not
    `done`, and the example oracle passes;
  - flag off: an armed goal is ignored, the module is not imported, and the goal reaches `done` as before;
  - an unarmed goal never pauses;
  - the timeout;
  - no pause without a verified step.
