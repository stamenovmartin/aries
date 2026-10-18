# ARIES thesis follow-up: all results in one place

Every number below is copied from the file named next to it. Paths are relative to this folder unless they start
with `docs/`, `scripts/` or `verification/`. "Commit" is the commit that added or last changed that file on branch
`thesis-followup`. Nothing here changes a result reported in ARIES-FINAL-20261006 (`thesis/`, `dokazi/`).

## How to read the labels

| Label | Meaning |
|---|---|
| **Confirmatory** | The hypothesis, materials and pass criteria were registered before any data was seen, and the result counts whatever it is. |
| **Regression check** | A fixed earlier protocol replayed unchanged on new code. No outcome was predicted, so it is descriptive. A drop is reported as a result. |
| **Exploratory** | Diagnosis, post-hoc analysis, development or a descriptive comparison. It may motivate a hypothesis but does not confirm one. |

**One confirmatory follow-up result exists: H8** (§8). The Holm family of confirmatory tests is H4b, H5, H6 and H8.
H4b, H5 and H6 have not been measured yet: they wait for external items. H4 (registered earlier, outside the Holm
family) waits for the external sets A and C.

## Summary

| # | Result | Label | Source | Commit |
|---|---|---|---|---|
| 1 | Why no held-out goal reached `done`: the completion contract was missing for 39 of 49 goals, and for all 15 that should have passed | Exploratory (diagnosis) | `docs/analysis/terminal-state-diagnosis.md`, `terminal-diagnosis/goals.json` | `a757902` |
| 2 | Contract coverage with `ARIES_COMPLETION_READ_PARAPHRASE`: 9/57 → 22/57 | Exploratory (static count, same fixture) | `terminal-diagnosis/contract-coverage-static.txt` | `fecfe86` |
| 3 | Planner 72 with `ARIES_PLANNER_CLARIFY`: **68/72 → 60/72** | Regression check | `task3-summary.json` | `dc3ffb6` |
| 4 | Demo 3 scenarios: 3/3 | Regression check | `task3-summary.json` | `dc3ffb6` |
| 5 | Planner 72 with clarify + guard: 69/72 | Exploratory: **confirmation after the fix, not independent evidence** | `task3-planner-guard/confirmation.json` | `00f6544` |
| 6 | H4 development: baseline + 3 rounds, no round met both goals | Exploratory (development) | `h4-dev/DEVLOG.md` | `7b75a70` |
| 7 | qwen2.5:7b router statistics: A1 > A0 robust; A3 = A1; A2 vs A1 not robust | Exploratory (post-hoc tests on the frozen confirmatory data) | `stats.json`, `stats.md` | `c791741` |
| 8 | llama3.1:8b on the same router protocol: lower in every arm, almost never declines | Exploratory (descriptive second model) | `task6-model/summary.json` | `6fa5d87` |
| 9 | llama3.1:8b router statistics: arms differ, but no pairwise effect is robust | Exploratory | `task6-model/stats/stats.json`, `stats.md` | `1fc8509` |
| 10 | Verifier count: 57 of 58 executed (the "56" is stale) | Exploratory (recount, no re-execution) | `verifier-count.md`, `verification/ledger_frozen.json` (`errata_20261012`) | `0916fd8` |
| 11 | Test suites on the code under test: all pass | Engineering check | `task1-tests/`, `task2-tests/`, `guard-tests/`, `h4-frozen-tests/` | see §6 |
| 12 | H8: hardening 23 verifiers raises the mutant kill rate, 155/218 → 188/218, McNemar b = 33, c = 0, p = 1.16 × 10⁻¹⁰; criteria 1 and 3 met, criterion 2 not met | **Confirmatory** (Holm family H4b/H5/H6/H8) | `h8/RESULTS.md`, `h8/runs/*/summary.json`, `thesis-tables/h8_fault_injection.csv` | `1d03163` |
| — | H4: does the planner ask on new ambiguous goals? | **Confirmatory, not run** | `docs/preregistration/H4-planner-clarification.md` (Amendments 1, 2) | `a2d1609` |

## 1. Task 2: terminal-state diagnosis (exploratory)

Source: `docs/analysis/terminal-state-diagnosis.md`, from `terminal-diagnosis/extract.py` → `goals.json`. These are
read-only extractions of the 2026-10-06 held-out run (49 goals) and its database rows. Commit `a757902`; the
follow-up section was added in `fecfe86`.

| End path | Goals |
|---|---|
| step budget exhausted, finish never proposed | 26 (16 partial, 10 failed) |
| finish proposed, rejected for missing contract | 8 |
| never planned (cause unknown, reported as such) | 6 |
| invalid decisions | 5 |
| awaiting approval | 3 |
| terminal read failure | 1 |

- **The main cause:** `completion()` needs a supported contract. 39 of the 49 goals had none, including every one
  of the 15 goals expected to pass (12 unsupported, 3 never reached the planner). The verifier never rejected a
  correct result on its evidence.
- **Amplifier:** 138 of the 242 executed steps were rejected repeats of an identical action. This is reported, not
  fixed, by the author's decision.
- **Separate defect:** a trailing sentence period is kept as part of the path (`rv-05`).
- **The fix, behind `ARIES_COMPLETION_READ_PARAPHRASE`** (commit `fecfe86`): static contract coverage rises from
  9/57 to 22/57, and from 2/17 to 8/17 for goals expected to pass (`terminal-diagnosis/contract-coverage-static.txt`).
  These are coverage counts, not outcomes. The fix was designed after looking at these goals. Any measurement on
  this fixture must be labelled "discovered by diagnosis, fixed, measured on the same fixture". No outcome
  measurement of the fix has been run.

## 2. Task 3: planner and demo regression checks

### 3.2 on `79d1f23`: clarify on, guard not yet written (regression check)

Source: `task3-summary.json`. Runs: `task3-planner/runs/20261012T171631.114537Z` and
`task3-demo/runs/20261012T171845.798750Z`. Commit `dc3ffb6`.

| Planner, 72 attempts | Frozen ARIES-FINAL-20261006 | Follow-up |
|---|---|---|
| Schema valid | 72/72 | 63/72 |
| Strict (capability + arguments) | 68/72 | **60/72** |
| p20–p22 strict | 9/9 | **0/9** |
| other 21 cases strict | 59/63 | 60/63 |

- The **drop of 68 → 60 is a reported result.** In all 9 attempts on p20–p22 (unambiguous `browser.read`), the model
  chose `ask_clarification` as a confirmation and attached arguments, which `Decision` rejects.
- The independent recalculation passed 22/22 checks.
- **Demo: 3/3**, the same as frozen (success `done`, clarification `needs_clarification`, refusal `failed`).

### On `a2d1609`: clarify + guard, confirmation after the fix (exploratory)

Source: `task3-planner-guard/confirmation.json`, run `task3-planner-guard/runs/20261012T193022.180980Z`. Commit
`00f6544`.

| Planner, 72 attempts | Schema valid | Strict |
|---|---|---|
| frozen | 72/72 | 68/72 |
| clarify alone (3.2) | 63/72 | 60/72 |
| clarify + guard | 72/72 | 69/72 |

- p20–p22 each went from 0/3 to 3/3. The only remaining failure is p12, at 0/3 in both follow-up runs.
- The independent recalculation passed 22/22 checks.
- **This is not independent evidence.** The guard was designed with the p20–p22 failure in view. 69 versus 68 is
  one attempt in one run and is not claimed as an improvement.

## 3. H4 development log (exploratory, development only)

Source: `h4-dev/DEVLOG.md`, runs in `h4-runs/20261012T17*-dev-*`. Commits `5590f41` to `7b75a70`. The development
set `h4-dev/dev.jsonl` has 7 scenarios: 4 ambiguous and 3 controls. They were written by the agent, are never
scored for H4, and the runner refuses them in an H4 run. The limit was 3 rounds, every round logged.

| Run | Ambiguous asked (of 4) | Controls correct (of 3) | Main failure |
|---|---|---|---|
| baseline (guard off) | 0 | 0 | reads the folder itself, guesses a file name, repeats |
| round 1 (`5590f41`) | 0 | 2 | lists, then reads one candidate silently |
| round 2 (`5c7c8b1`) | 2 | 0 | asks for approval to read; offers a folder as a choice |
| round 3 (`09bec79`) | 0 | 2 | lists, then reads one candidate silently |

- **What held in every guarded round:** the folder is listed first (the baseline did so in 1/7), and there were no
  invalid questions.
- **What did not hold:** asking instead of choosing silently, without becoming over-cautious on the controls.
- **Registered in Amendment 2** (commit `a2d1609`, tag `h4-frozen-20261012`): the round-3 guard is the H4 treatment.
  The amendment states in advance that criterion 1 is expected to fail.
- **Separate defect, not fixed:** `dev-a-04`, a Macedonian goal, never reached the planner. `service.plan` keeps the
  sentence period in the legacy `read_file` path.

## 4. Task 5: router statistics, qwen2.5:7b (exploratory)

Source: `stats.json`, `stats.md`, from `scripts/thesis_stats.py` on the 2,700 frozen decisions. Commit `c791741`.
The reproduction gate passed: the hashes and the published totals A0 385, A1 463, A2 440 and A3 463 of 675 match.
These tests were chosen after the frozen evaluation, so they are post-hoc analyses of confirmatory data. The
frozen confirmatory result itself (A3 vs A1 criterion not met) is in `dokazi/` and is not restated here.

| Comparison | McNemar (majority of 3) | GEE p | GLMM log-odds (≈95%) | Reading |
|---|---|---|---|---|
| A1 vs A0 | 36 vs 11, p = 0.00035 | 8 × 10⁻⁵ | A0: −1.886 (−2.199, −1.573) | **robust: A1 better** |
| A3 vs A1 | 24 vs 23, p = 1.000 | 1.00 | +0.035 (−0.273, +0.344) | **null** |
| A2 vs A1 | 16 vs 24, p = 0.268 | 0.21 | −0.530 (−0.834, −0.226) | not robust; report the direction only |

Cochran's Q = 23.89, df 3, p = 2.6 × 10⁻⁵. No multiple-comparison correction was applied; with Bonferroni, only
A1 vs A0 remains significant.

## 5. Task 6: second local model, llama3.1:8b (exploratory)

Source: `task6-model/summary.json` (frozen scorer `analyze_router.py`) and `task6-model/stats/` (same tests as
§4). Commits `6fa5d87` and `1fc8509`.

- **Run:** 2026-10-12 19:35–20:06 UTC, live ARIES stopped (`task6-model/run-conditions.json`). 2,700 decisions,
  0 errors, model digest `46e0c10c…` stable, frozen source stable.
- **Only change:** the model. The prompts were written for qwen and not re-tuned.
- **Earlier aborted run:** an attempt with the live service running is kept unscored in
  `task6-model/aborted/`.

| Arm | Binary, llama / qwen | Native semantic, llama / qwen | OOD false action, llama / qwen | OOD out-of-scope, llama / qwen |
|---|---|---|---|---|
| A0 | 55.7% / 57.0% | 45.2% / 44.6% | 59.2% / 71.7% | 0.0% / 0.0% |
| A1 | 57.8% / 68.6% | 42.9% / 42.9% | 62.5% / 41.7% | 0.8% / 38.3% |
| A2 | 60.0% / 65.2% | 60.7% / 47.6% | 53.3% / 46.7% | 1.7% / 27.5% |
| A3 | 62.1% / 68.6% | 57.1% / 44.6% | 56.7% / 45.0% | 0.8% / 24.2% |

| Comparison, llama | McNemar | GEE p | GLMM log-odds (≈95%) |
|---|---|---|---|
| A3 vs A1 | 19 vs 8, p = 0.052 | 0.0495 | +0.937 (+0.586, +1.289) |
| A2 vs A1 | 14 vs 8, p = 0.286 | 0.26 | +0.487 (+0.137, +0.837) |
| A1 vs A0 | 15 vs 10, p = 0.424 | 0.29 | A0: −0.454 (−0.813, −0.096) |

- **Cochran's Q** = 11.53, p = 0.0092.
- **Bootstrap:** A3 − A1 = +4.3 pp, case-bootstrap 95% interval [0.0, +8.7].
- **Reading:**
  - llama is lower in every arm and almost never declines: 6–8 abstentions per arm in A1–A3 (0 in A0), versus 73–160 for qwen.
  - A3 vs A1 leans towards A3, but the evidence is borderline and not robust.
  - qwen's robust A1 > A0 does not replicate.
  - The predeclared qwen criterion is met for llama, but only descriptively, because it was not declared for llama.

## 6. Engineering checks (tests)

| Code | Source | Commit | Result |
|---|---|---|---|
| `1ac3e55` (patch applied) | `task1-tests/summary.txt` | `a757902` | 11 suites, 0 failures |
| `fecfe86` (completion fix) | `task2-tests/summary.txt` | `fecfe86` | 22 suites, 0 failures; `test_completion_read_paraphrase` 27, including flag-off equality with the frozen `contracts.py` |
| `5590f41` (guard round 1) | `guard-tests/summary.txt` | `5590f41` | 11 suites, 0 failures |
| `a2d1609` (H4 freeze) | `h4-frozen-tests/summary.txt` | the commit adding `RESULTS.md` | 11 suites, 0 failures; `test_planner_clarify_guard` 19 |

## 7. Task 7: verifier count (exploratory recount)

Source: `verifier-count.md`. The per-capability entries of
`experiments/product/independent-acceptance/raw/review_verifier_integrity.json` give **57 executed and 1 source-only
of 58**. "Executed" includes runs with substituted collaborators. The stale narrative "56 of 58" in
`verification/ledger_frozen.json` received a dated `errata_20261012` field; the original text is unchanged (commit
`0916fd8`). Nothing was re-executed.

## 8. H8: verifier strength by fault injection (confirmatory)

Preregistration: `docs/preregistration/H8-verifier-fault-injection.md`, with Amendment 1 (harness fixes, baseline-2
as the McNemar baseline) and Amendment 2 (Option 1, the hardening design and the exploratory condition), both dated
2026-10-18 and committed before the runs they govern. Full write-up: `h8/RESULTS.md`. Every number below is from the
`summary.json` of the run folder named, and is recounted from its `records.jsonl` by `thesis-tables/check.py`
(table `h8_fault_injection.csv`). All runs after run 1 used the same harness (`h8/run_mutants.py`, SHA-256
`4f17771d…`). Offline, one process, against fakes.

**Primary test.** One-sided exact McNemar, paired by mutant, hardened (`runs/20261018T154826Z-hardened`,
`ARIES_VERIFY_HARDENED=1`) against baseline-2 (`runs/20261018T153000Z-baseline2`, frozen verifiers): b = 33 (killed
now, not before), c = 0, 218 pairs, **p = 1.16 × 10⁻¹⁰**. Because p < 0.05/4, H8 is rejected under Holm whatever the
other three p-values are; its Holm-adjusted p is at most 4p = 4.7 × 10⁻¹⁰. Commit `1d03163`.

| | baseline-2 (frozen) | hardened |
|---|---|---|
| Killed | 155/218 = 0.711 [0.646, 0.770] | 188/218 = 0.862 [0.809, 0.905] |
| Mean kill rate over 58 capabilities | 0.684 | 0.873 |
| TRIVIAL / SELF_REPORT / PLANNER_SUPPLIED / INDEPENDENT | 10/36, 24/34, 4/4, 117/144 | 34/36, 33/34, 4/4, 117/144 |
| `noop_success` survivors | 15 | 3 |
| False alarms on clean replays | 0/174 | 0/174 [0, 0.021] |

**Criteria (hardened run).**
1. Mean kill rate ≥ 0.80: 0.873, **met**.
2. No `noop_success` survivor: **not met.** `notification.send`, `system.disk` and `system.status` survive. The first
   two are INDEPENDENT verifiers that the registered design does not change (Option 1, Amendment 2). This is a
   finding: two independent verifiers do not catch an executor that does nothing. All three are probably equivalent
   mutants (stated in Amendment 2 before the hardened run): the twin world does not include the database, so the
   `notification.send` noop writes the real row; `system.disk` and `system.status` read the real machine, so the
   noop report is true.
3. False alarms ≤ 2%: 0/174, **met**.

**Sealed second set** (generalisation check, not a criterion; `sealed/mutants-sealed.json`, SHA-256 `fa8556e9…`
checked before opening, committed after use in `46ca46f`). Frozen: 155/218, all verdicts identical to baseline-2.
Hardened: 187/218 = 0.858 [0.804, 0.901], mean 0.868, 0/174 false alarms; McNemar against the frozen sealed run
b = 32, c = 0. **Limit:** the set seed changes only the wrong values, not the targets, so this is a weak check.

**Exploratory "hardened-23+2, designed after baseline-2"** (not confirmatory, outside the Holm family;
`runs/20261018T155139Z-exploratory-hardened-23plus2`, both flags, see its `conditions.md`). Identical to the hardened
run: 188/218, mean 0.873, 0/174. `notification.send` stays at 1/3 and `system.disk` at 2/3, which is consistent with
their noop mutants being equivalent.

**Not changed by hardening:** `side_effect_outside_scope` 0/14 before and after (no verifier checks for changes
outside the requested target). Engineering check: with both flags off, all 58 verifier fingerprints equal those of
`2af6112` (`tests/test_verify_hardened.py`, 16/16; "17" in Amendment 2 is a miscount, corrected in Amendment 3).

## Pending

- **H4b, H5, H6 (confirmatory, Holm family with H8):** wait for the external items (H4b 80, H5 25, H6 300). The H5
  file-change hook is written before any H5 measurement.
- **H4 (confirmatory):** waits for sets A and C from the external author. When they arrive, they are only validated
  (`h4-scenarios/validate_oracles.py`), never opened. Then they are run as `on-guard`/`off` ×3 alternated, plus
  `completion-fix` ×3 as a separate labelled condition.
- **Out of scope, unchanged:**
  - SQLite "database is locked";
  - the repeated-identical-step loop;
  - the `service.plan` period-in-path routing defect;
  - the 6 never-planned goals (cause unknown);
  - human re-annotation;
  - voice;
  - Task 8 (cloud), not started.
