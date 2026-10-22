# History attribution audit (2026-10-22)

Search over all branches for commits whose author, committer or message contains Claude, Anthropic, Codex,
OpenAI, `Co-Authored-By` or "Generated with". **No history was rewritten**: rewriting would change the hashes
of the preregistration and amendment commits, which are the evidence of registration before measurement.
The owner decides what, if anything, to do.

- Commits searched: 177 (all refs). Author and committer of every commit is Martin Stamenov; no identity matches.
- Matching commits: 139. Of these, 73 are only on the local `master` branch (never pushed; it holds
  private files in its history) and are counted, not listed.
- `origin/main` (2 commits): no matches.
- "Mention" rows are factual content, e.g. "items written by OpenAI Codex (gpt-6-astra)" in the H4b/H5/H6
  amendments; they are provenance, not attribution trailers.
- Column "prereg" marks commits that touch `docs/preregistration/`.
- From 2026-10-22 a `commit-msg` hook (`scripts/hooks/commit-msg`) rejects AI attribution trailers.

| commit | date | subject | match | pushed | prereg |
|---|---|---|---|---|---|
| `2495b07` | 2026-10-19 | COORDINATION: H6 llama, H4b runner, H5 pilot | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `b3ca8df` | 2026-10-19 | H5 pilot on the example items: 4 item-runs, all failed (folder-only goal, repeated-step lo | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `b045710` | 2026-10-19 | RESULTS §9: H6 llama3.1:8b exploratory secondary; h6_abstention.csv adds its recounted row | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `12e5fc6` | 2026-10-19 | H5 pilot: first attempt refused by the runner (screen blanked, nothing submitted); wake th | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `96bd619` | 2026-10-19 | H6 llama3.1:8b exploratory secondary (outside Holm): b=28, c=20, p=0.156 | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `2297419` | 2026-10-19 | H5 pilot driver: the two example items, treatment and control, under the run-h5.sh conditi | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `73cc1d9` | 2026-10-19 | H4b runner, analysis and tests; H4b Amendment 2 (before any measurement) | Co-Authored-By: Claude Opus 5.5 | yes | yes |
| `6094324` | 2026-10-19 | RESULTS §9 H6 confirmatory; thesis-tables h6_abstention.csv recounted from raw | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `525fb92` | 2026-10-19 | H6 llama3.1:8b exploratory secondary: setup before the run | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `4f56bdb` | 2026-10-18 | COORDINATION: H6 complete, H4b/H5 frozen | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `6db0c99` | 2026-10-18 | Merge h4b-h5-prep: H4b resolver (tag h4b-frozen-20261018) and H5 typed contract, runner, a | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `7e5c2b2` | 2026-10-18 | H6 results (confirmatory): A1 vs A0 on 300 new requests, McNemar b=43 c=9, p=1.02e-06; com | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `a1c70d5` | 2026-10-18 | H5: ARIES_COMPLETION_TYPED_CONTRACT (default off), H5 runner and analysis; H5 Amendment 3; | Co-Authored-By: Claude Opus 5.5 | yes | yes |
| `2b530ee` | 2026-10-18 | H4b: ARIES_CLARIFY_RESOLVER (default off) with tests, frozen before any H4b measurement | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `5fd183b` | 2026-10-18 | H6 run setup, committed before any inference; H6 Amendment 3 | Co-Authored-By: Claude Opus 5.5 | yes | yes |
| `1976eba` | 2026-10-18 | H6 Amendment 2: row 1 replaced (repeated an earlier ARIES request), before any measurement | Co-Authored-By: Claude Opus 5.5; mention in body: Codex | yes | yes |
| `e7a21d8` | 2026-10-18 | H4b/H5/H6 amendments: items written by OpenAI Codex (gpt-6-astra), setup, timeline, limita | Co-Authored-By: Claude Opus 5.5; mention in body: Codex; mention in subject: OpenAI | yes | yes |
| `2e41249` | 2026-10-18 | thesis-tables: h8 provenance line names the preregistration with Amendment 3 (6275533); ch | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `6275533` | 2026-10-18 | H5 file-change hook (ARIES_MEASURE_CHANGE_HOOK, default off) before any H5 measurement; H8 | Co-Authored-By: Claude Opus 5.5 | yes | yes |
| `9194396` | 2026-10-18 | H8 into RESULTS.md as confirmatory, thesis table h8_fault_injection.csv, COORDINATION entr | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `46ca46f` | 2026-10-18 | H8: commit the used sealed mutant set and the Amendment 1 pre-check script | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `1d03163` | 2026-10-18 | H8 hardened, sealed-set and exploratory runs, committed as they ran, with RESULTS.md | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `2373dfd` | 2026-10-18 | H8 Amendment 2 and ARIES_VERIFY_HARDENED: hardened verifiers for the 23, committed before  | Co-Authored-By: Claude Opus 5.5 | yes | yes |
| `2af6112` | 2026-10-18 | H8 second baseline (Amendment 1 harness, frozen verifiers), committed as it ran | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `2a1e66b` | 2026-10-18 | H8 Amendment 1: harness fixes after the baseline, before a second baseline | Co-Authored-By: Claude Opus 5.5 | yes | yes |
| `be79cbb` | 2026-10-13 | H8 baseline run (public set, frozen verifiers), committed as it ran, with the analysis scr | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `77f3144` | 2026-10-13 | H8 mutant runner, committed before the baseline run | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `0731857` | 2026-10-13 | Preregister H4b, H5, H6 and H8 (Holm family), with the H8 mutant manifest and sealed set h | Co-Authored-By: Claude Opus 5.5 | yes | yes |
| `f7be488` | 2026-10-13 | docs: UI review 2026-10-13 — findings, fixes, and the owner's live checks | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `7732d90` | 2026-10-13 | shell: restamp BUILD for the fixed extension sources | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `4a28f93` | 2026-10-13 | control centre: dragging a tab no longer loses track of it | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `642b38f` | 2026-10-13 | control centre: refreshes keep the scroll position and wait for the user | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `b7a2b0e` | 2026-10-13 | control centre: reopening after closing the main window builds a new one | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `a8f194b` | 2026-10-13 | shell: close the quick-settings audio mixer on disable() | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `93ce604` | 2026-10-13 | shell: a poll superseded by teardown is not delivered | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `17cce13` | 2026-10-13 | shell: FocusWindow over D-Bus also closes the overview | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `268b93b` | 2026-10-13 | shell: launching a running app focuses it instead of opening another window | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `626455c` | 2026-10-13 | shell: ARIES Search and the launcher let go of the desktop properly | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `916ffbc` | 2026-10-13 | shell: raise the Control Centre with an activation token, not a guess | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `f095441` | 2026-10-13 | shell: destroy the dock that is actually there on disable() | Co-Authored-By: Claude Opus 5.5 | no (local) |  |
| `d865447` | 2026-10-13 | thesis-tables: one CSV per thesis table with source provenance, and check.py (10/10 match) | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `62fe362` | 2026-10-13 | Stop tracking run databases and flag files; commit redacted H4 dev runs and the frozen fil | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `27a5401` | 2026-10-13 | RESULTS.md: abstention counts are for A1–A3 | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `43b98e6` | 2026-10-13 | RESULTS.md: every follow-up result with source, commit and confirmatory/exploratory label | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `1fc8509` | 2026-10-13 | Router stats for llama3.1:8b with the same tests (McNemar, Cochran Q, GLMM, GEE) | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `6fa5d87` | 2026-10-12 | Task 6: llama3.1:8b router run complete (2,700 decisions, model and frozen source stable) | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `a7f2151` | 2026-10-12 | Task 6: started early on author instruction (timer cancelled), screen blanking off for the | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `00f6544` | 2026-10-12 | Planner 72 with the H4 treatment flags on a2d1609: confirmation after the fix (69/72) | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `a2d1609` | 2026-10-12 | H4 preregistration: Amendment 2 — treatment is CLARIFY=1 + GUARD=1 (round-3 guard), histor | Co-Authored-By: Claude Opus 5.5 | yes | yes |
| `7b75a70` | 2026-10-12 | H4 dev log: round 3 and summary; tuning stopped after the 3 allowed rounds | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `09bec79` | 2026-10-12 | CLARIFY_GUARD round 3 (last): reads need no approval; folders are not candidates | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `5c7c8b1` | 2026-10-12 | CLARIFY_GUARD round 2: explicit decision step after listing a goal folder | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `46a5266` | 2026-10-12 | H4 dev log: baseline refused (session locked), nothing run | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `5590f41` | 2026-10-12 | ARIES_PLANNER_CLARIFY_GUARD (default off) and the H4 development set | Co-Authored-By: Claude Opus 5.5; mention in body: Claude | yes |  |
| `070f97b` | 2026-10-12 | Task 6: overnight run with live ARIES stopped (scheduled 2026-10-13 01:00 CEST) | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `dc3ffb6` | 2026-10-12 | Task 3.2: planner 72 and demo 3 on follow-up code | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `e483357` | 2026-10-12 | Task 6: abort the first llama run (live service was running); keep it, excluded | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `79d1f23` | 2026-10-12 | Task 6 setup: router protocol with llama3.1:8b (model is the only change) | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `1f005d4` | 2026-10-12 | Undo the export's word substitution in experiment and eval records | Co-Authored-By: Claude Opus 5.5; mention in body: claude | yes |  |
| `2cbd5e2` | 2026-10-12 | Undo the public export's word substitution in code and docs | Co-Authored-By: Claude Opus 5.5; mention in body: claude | yes |  |
| `0916fd8` | 2026-10-12 | ledger_frozen.json: dated erratum field for the stale 56/58 verifier count | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `c791741` | 2026-10-12 | Router stats: mixed-effects logistic model (variational GLMM) and GEE check | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `e122d3f` | 2026-10-12 | H4 isolated-database runner, measurement README and smoke test | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `d005022` | 2026-10-12 | H4 preregistration: Amendment 1 — fix ARIES_COMPLETION_READ_PARAPHRASE=0 in both condition | Co-Authored-By: Claude Opus 5.5 | yes | yes |
| `fecfe86` | 2026-10-12 | Completion contracts for natural read/list/existence goals (ARIES_COMPLETION_READ_PARAPHRA | Co-Authored-By: Claude Opus 5.5 | yes |  |
| `a757902` | 2026-10-12 | Thesis follow-up: terminal-state diagnosis, router statistics, H4 scenario template, READM | Co-Authored-By: Claude Opus 5.5 | yes |  |
