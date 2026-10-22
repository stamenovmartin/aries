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

## Amendment 2 (2026-10-18): who wrote the H5 items, and how

This amendment concerns Materials 3 ("by a person other than the author"). It changes no hypothesis, criterion, test or procedure.

- **Who wrote them:** OpenAI Codex (model `gpt-6-astra`, Codex CLI 0.154.0, `codex-tui`), not a person.
  The user started one fresh session per hypothesis, three in all (H6, H5, H4b), on 2026-10-18 between
  16:56Z and 16:58Z. Each session ran in its own empty folder (`~/h-author/h6`, `~/h-author/h5`,
  `~/h-author/h4b`), which held only that hypothesis's README. No session had memory of another, and none had
  the ARIES conversation context.
- **The setup did not isolate the repository.** The sessions ran with Codex's `danger-full-access` sandbox,
  so the repository was readable. This was checked from the session logs, by listing only the commands that
  name a repository path (no item content was read):
  - H6: no command names the repository.
  - H5: read `h5-items/example_items.jsonl` and `h5-items/validate_items.py`, and used both in its own
    validation script.
  - H4b: read `h4b-items/example_pair.jsonl`, copied it into its folder, and ran `h4b-items/validate_items.py`.
  - No command names ARIES source code, tests, or earlier scenarios. Both files read are ones the README
    points to. The validators contain the format rules, not ARIES's recognisers or prompts.
- **Validators run by the writer:** the H5 and H4b sessions ran the validators themselves and may have
  revised their items until they passed. The validators check format and consistency only (fields, counts and,
  for H4b and H5, that each oracle fails on a do-nothing record), not ARIES behaviour, so passing them reveals nothing
  about how ARIES will do on an item.
- **Timeline:** the items were written (last change 16:58Z H6, 16:59Z H5, 17:02Z H4b) and copied into the
  repository (17:05Z) **before this amendment was committed**. That was still before any measurement, and the
  author has not read them. This amendment records their SHA-256 before the validators are run in the
  repository and before any measurement.
- **Limitation (deviation from the registered materials):** the preregistration requires items written by
  **a person** other than the author. They were written by a language model. Independence from the
  implementation rests on the sessions' isolation, described above. A model-written set may be more
  uniform than human writing, and may share wording habits with the model under test. Every result on
  these items is reported with this limitation.
- **Frozen items:**
  - `experiments/thesis-followup-20261012/h5-items/goals.jsonl`: SHA-256 `4cecf03fd3d0dc70125dfe76001af72600b2a1add9384f148cca818045613d58`, 27017 bytes
  - `experiments/thesis-followup-20261012/h5-items/controls.jsonl`: SHA-256 `a47370363fac0b2f5f69fdac93d2acb86a519a730751ef8c85a3263dc3d8f142`, 16196 bytes

## Amendment 3 (2026-10-18): the typed step, the runner and the analysis, frozen before any H5 item is opened

The H5 items (Amendment 2) exist, but the author has not opened them. Only the validator has run on them.
This amendment records what was built and tagged before the measurement.

**`ARIES_COMPLETION_TYPED_CONTRACT`** (`aries/workspace/typed_contract.py`, default off; called in `agent.py`
right after `compile_goal`, and only when the fast path gives no contract):
- One call through the existing grammar-constrained `structured()` (purpose `workspace.typed-contract`,
  at most 120 tokens). The schema is the registered one, `goal_type` ∈ {read, list, exists, none},
  `path`, `name`. Only a string enum and strings are used, which are among the shapes measured safe.
- Code validation, as registered:
  - the request names exactly one path (the same path tokens as the fast path);
  - `path` occurs verbatim and, after stripping sentence punctuation, is that path;
  - `name` is empty or occurs verbatim.
- **Stated additions, all stricter than the registered rules:**
  - `name` must be a single path component (no `/`, not `.` or `..`);
  - a `list` claim must have an empty name;
  - a malformed reply, or a failed call, leaves the goal unsupported.
- **Shapes:**
  - read → `file.read` of the path, or of path/name when a name is given;
  - list → `file.list` with `answer: listing`;
  - exists → `file.exists` of path or path/name, with `answer: existence`.

  These are the `paraphrased()` shapes. The typed result and its reason are recorded in the contract
  (`typed`).
- **English only:** a Cyrillic request is not sent. `completion()` and `contracts.py` are unchanged; the
  test checks `contracts.py` against the commit before H5.
- **Tests:**
  - `tests/test_typed_contract.py`, 28 checks, model mocked: the validation rules, flag off (no call,
    module never imported, contract exactly `compile_goal`'s), done only through verified and re-checked
    evidence, a fast-path contract never replaced, and Cyrillic.
  - `tests/test_h5_runner.py`, 11 checks.

**Runner** (`h5-runs/run_h5.py`, adapted from `run_h4.py`) and **wrapper** (`h5-runs/run-h5.sh`):
- **Conditions:**
  - treatment: PARAPHRASE=1, TYPED=1;
  - control: both 0;
  - in both: CLARIFY, GUARD and RESOLVER pinned 0, and the hook flag at 1.

  The effective flags are resolved in the instance's environment, and the run refuses on any mismatch.
- **Isolation:** a fresh isolated database per run, as for H4. The live service is stopped for the whole
  measurement, so its environment is captured once before it is stopped. The copy goes to
  `~/.local/state/aries-h5/service-env` (mode 600, never committed). The runner refuses while `aries-core`
  is active or `idle-delay` is not 0.
- **Item checks:** before submitting anything, the unchanged validator is re-run into the run folder and
  must print PASS for the Amendment 2 hashes.
- **Order and sets:** six runs, T, C, T, C, T, C. Sets G (15), N (10), and the 49 runnable held-out goals.
- **Hook:** as in Amendment 1.
- **Recorded per item:** the run_fixtures verdict and the H5 outcomes (correct done, false done, contract
  source, end path).
- **End paths:**
  - finish rejected = the last completion check failed;
  - budget exhausted without a finish = planned but no completion check;
  - never planned = no decision.

**Analysis** (`h5-runs/analyze_h5.py`, written now):
- the three criteria and the primary McNemar test exactly as registered;
- the secondary outcomes as listed;
- it refuses unless there are 3 + 3 complete runs at one commit, with model and code stable;
- it was smoke-tested on synthetic folders only.

## Amendment 4 (2026-10-22): the measurement script wakes an already blanked screen, before any measurement

- **What changed:** `h5-runs/run-h5.sh` now calls `org.gnome.ScreenSaver.SetActive false` once, after setting idle-delay 0
  and before the first run, and logs the screensaver state after the wake. It is the same step the H5 pilot
  script got in `12e5fc6`.
- **Why:** the first H5 pilot (`h5-runs/pilot-h5-refused-1.log`) was refused by the runner's preflight because the
  screen was blanked (not locked; LockedHint=no, lock disabled). Nothing was submitted in that attempt.
- **What did not change:** the runner, the conditions, the items and their SHA-256s, the analysis, the outcome
  rules and the criteria. The runner's own refusal on a locked or blanked session is kept.
- **Order:** H5 is measured first and H4b directly after it, each with its own script, on one commit.
