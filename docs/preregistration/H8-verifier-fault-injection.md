# Preregistration H8: verifier strength by fault injection, before and after hardening

Status: **registered before any mutant is run.** The commit that adds this file, together with the mutant
manifest `experiments/thesis-followup-20261012/h8/mutants.json`, is the registration timestamp. Any later
edit to this file must be a new commit with a dated "Amendment" section; the original text stays unchanged.

## Background

ARIES has 58 registered capabilities, each with a verifier that runs after the executor. The frozen code
review (`experiments/product/independent-acceptance/raw/review_verifier_integrity.json`, in ARIES-FINAL-20261006)
classed them by their `met` predicate:

| Class | Count | Meaning |
|---|---|---|
| INDEPENDENT | 35 | `met` is decided on freshly re-read state |
| TRIVIAL | 12 | no world state makes a wrong answer fail |
| SELF_REPORT | 10 | `met` is checked only against the executor's own report |
| PLANNER_SUPPLIED | 1 | `browser.click`: the reference value comes from the model's arguments |

The review also found a mitigation: the TRIVIAL verifiers re-run the observation and store the **fresh**
result as evidence, so a false report does not reach the answer. What is missing is the verdict. Those
labels come from reading the code and running the verifiers on synthetic inputs; they do not measure what
each verifier catches.

Audits show that weak checkers distort agent results (wording verified in
`docs/preregistration/CITATIONS.md`):
- 15.3% of FAIL verdicts were wrong in 150 computer-use trajectories (Dong et al., arXiv:2607.28367,
  preprint);
- near-perfect scores were reached without solving tasks (BenchJack, arXiv:2605.12673, preprint);
- an executable-contract audit confirmed 7 tool defects among 34 mutating tools (Bellibatlu et al.,
  arXiv:2609.37315, preprint);
- outcome validity and checker quality are central to agentic benchmarks (Zhu et al., NeurIPS 2025 D&B).

H8 needs no external author. It is part of the Holm family of confirmatory tests: H4b, H5, H6 and H8.

## Mutants (frozen at registration)

`experiments/thesis-followup-20261012/h8/mutants.json`, built by `h8/build_manifest.py` from the frozen
review. It covers 58 capabilities with **218 mutants** and **174 clean replays** (3 per capability).
Each mutant carries a `variant_seed`, derived from the set seed (61013 for this public set) and its id.
The runner derives the concrete wrong value, wrong target or partial cut from that seed.

| Operator | What changes | Mutants |
|---|---|---|
| noop_success | the executor does nothing and returns its normal success shape | 58 |
| wrong_target | the effect, or the report, concerns a different target | 56 |
| wrong_value | right target, different value or content, or a falsified report of it | 56 |
| partial_effect | only part of a multi-part effect happens | 6 |
| side_effect_outside_scope | the effect happens, plus a change outside the allowed scope | 14 |
| undone_after_report | the effect happens and is reverted before the verifier runs | 28 |

Applicability depends on the effect type and is fixed in the manifest. Read-only capabilities get only
noop_success, wrong_target and wrong_value, and those mutants falsify the report, because there is no
effect to undo or to spill over.

Mutants by verifier class: INDEPENDENT 144, TRIVIAL 36, SELF_REPORT 34, PLANNER_SUPPLIED 4.

## How mutants run: never on the live system

The approach is the frozen review's own: a verifier is executed with its collaborators replaced. Each
capability runs in a fresh **fake world**, a set of state stores that the harness creates for that one
mutant or clean replay and discards afterwards.

### Where the fakes keep state

| Family | Capabilities | State store | Executor writes through | Verifier reads through |
|---|---|---|---|---|
| Files | `file.*` (12), `browser.download` (file part) | real files in a fresh temporary folder under the home directory (so `path_for` scoping applies) | the capability's own OS calls (open, write, rename, copy) | its own re-open, `stat` and hash (`open_nofollow`, `file_snapshot`) |
| Database | `notification.send`, `task.inspect` | a fresh isolated SQLite test database | the capability's own insert | its own `SELECT` in a new session |
| System probes | `system.status`, `system.storage`, `system.disk`, `system.processes` | the real machine, **read-only** (`/proc`, `statvfs`); nothing is written | `/proc` and `statvfs` reads | a second read of the same sources |
| Browser | `browser.*` (except `download`'s file) | a `FakeBrowser` dict: sessions → `{url, title, text, scroll, elements[{handle, text, value}], owner}` | fake navigation, click, type and scroll functions that change the dict | fake observe, elements, read and tabs functions that copy from the dict |
| Desktop | `desktop.*` | a `FakeDesktop` dict: windows → `{id, app, title, geometry, maximized, minimized, focused}`, plus installed apps | the fake window-action and launch functions | the fake `observe()` |
| Input | `input.*` | a clipboard string and a dict of editable AT-SPI nodes (`identity → text`) | the fake clipboard-set and type functions | the fake clipboard-get and `read_node` |
| Screen | `screen.*` | a framebuffer (bytes) with its recognised text | — (read-only) | the fake capture and recognition |
| Network | `network.*` | a dict of connections, the active profile, Wi-Fi networks and internet reachability | the fake `nmcli` connect function | the fake connection-state and scan functions |
| Display | `display.*` | a brightness integer | the fake set function | the fake get function |
| Services | `system.service`, `system.services`, `system.service_control`, `system.packages` | a dict of units → `{load_state, active_state, sub_state, invocation_id}` and a dict of installed packages | the fake `systemctl` start, stop and restart | the fake `systemctl show` and the package query |

The exact stub table (which module attribute is replaced, by which fake function) is in
`h8/run_mutants.py`. It is committed before the baseline, and any difference from this table is listed
in an amendment.

### The verifier never reads through the mutated path

- **A mutation changes only two things.** It replaces the `executor` entry of the capability being
  tested, as the harness calls it. Depending on the operator, it then either changes the fake world or
  changes the report the executor returns.
- **Verifiers call the original, unwrapped functions.** When a verifier re-observes, it does not go
  through the mutated `executor` entry. That holds for the 18 verifiers that re-run the executor's own
  function (`h8/read_paths.py`, `read_paths.json`: `verify_probe` closures and direct calls) and for all
  others. A falsified report therefore cannot leak into the verifier's own observation; only the fake
  world, which the mutation may have changed as its operator says, is shared.
- **The harness checks this for every mutant.** It counts the calls to the mutated `executor` entry. A
  mutant is invalid, and reported as such, if the verifier caused any call to it.
- **For those 18 verifiers, the read path and the write path are the same code.** The verifier's read
  is a second call of the executor function, so it is independent in time but not in implementation.
  This is recorded as a property of the frozen verifiers. Adding a different read channel is part of the
  hardening.

### Limitation: fakes

**Mutants are run against fakes, not against the real browser, desktop, AT-SPI, screen, NetworkManager,
brightness or systemd.**
- A kill here shows that the verifier's logic rejects a wrong world state when it reads that state.
- It does not show that the real collaborator would report that state correctly, or that the real
  executor could fail in this exact way.
- File, database and read-only system-probe mutants use the real channel, so only the remaining
  families depend on the fakes.
- This is the same limit as in the frozen review. It is reported with every result.

The harness runs one process, with a memory limit, and the live ARIES may stay stopped. The 20-process
stress test of 2026-10-13 exhausted memory (`experiments/thesis-followup-20261012/e1-sqlite/README.md`),
so nothing here runs in parallel.

The harness (`h8/run_mutants.py`) is written and committed **after** this registration and **before** the
baseline. While building it, only the clean replays of two capabilities (`file.read`, `file.write`) are
run, as a smoke test. No mutant is run before the baseline.

## Procedure

1. **Baseline:** every mutant and clean replay, against the frozen verifiers (flag off).
2. **Hardening:** the 23 verifiers of classes TRIVIAL, SELF_REPORT and PLANNER_SUPPLIED are
   strengthened behind `ARIES_VERIFY_HARDENED` (not yet implemented).
   - This includes `browser.click`. The master plan named only the 12 TRIVIAL and 10 SELF_REPORT
     verifiers, but the review's finding F2 is the weakest verifier of all.
   - The means:
     - re-read through a different channel than the executor used;
     - a before/after check of the expected change;
     - per-capability invariants;
     - a status UNVERIFIED that never counts as done.
   - The hardening is designed from each capability's contract, not from the baseline outcome of
     individual mutants. Every hardening change made after the baseline is listed with its diff in an
     amendment.
   - With the flag off, every verifier is byte-identical to the frozen one, and a test checks this.
3. **Hardened:** the same mutants and clean replays, with `ARIES_VERIFY_HARDENED=1`.

## Outcomes

- **Primary outcome: the verdict.** A mutant is **killed** if and only if the verifier's verdict is
  negative: `met` is not true, or the status is UNVERIFIED. Every criterion and the primary test use only
  this definition.
- **Secondary outcome: whether the false value reached the evidence.** The stored verified evidence
  (`verification.data`) either contains the mutant's false value or claims the absent effect, or it does
  not. A mutant that survives with fresh, correct evidence is reported as "survived, harmless". It still
  counts as **survived** for the primary outcome and for every criterion.
- **Kill rate:** killed / applicable mutants, per capability. The mean is taken over the 58 capabilities.
- **False alarm:** a clean replay that the verifier does not confirm.

## Criteria (hardened verifiers; all three must hold)

1. Mean kill rate across the 58 capabilities ≥ 0.80.
2. No capability lets its noop_success mutant survive (0 of 58).
3. False alarms ≤ 2% of the 174 clean replays (at most 3).

## Generalisation check: a sealed second mutant set

A second set, built with the same operators and applicability but a different random set seed (other
wrong values and targets), was generated at registration (`h8/build_manifest.py --sealed`). Only its
SHA-256 and size are committed (`h8/sealed/SEALED.sha256`: `fa8556e996d52bfff1e16fef56b1b6f9781dd8bca4d66a5849a9d62f9023daa4`,
69,913 bytes). The file is git-ignored, and it is not opened before the hardened run.
- **How it runs:** after the hardened run of the public set, the sealed set is run once with the hardened
  verifiers, and once with the frozen ones for comparison. Its SHA-256 is checked before opening.
- **What it reports:** the kill rate on the sealed set (verdict definition), per class. It is a
  **generalisation check**, not a criterion, and it is not in the Holm family.
- **How to read it:** a much lower kill rate than on the public set would mean the hardening was fitted to
  the public variants.

## Primary test (Holm family: H4b, H5, H6, H8)

One-sided exact McNemar, paired by mutant (all 218): killed after hardening against killed at baseline.
α = 0.05 before Holm. Reported with b, c, b/c, and Clopper-Pearson 95% intervals for both kill rates and
for the false-alarm rate.

## Secondary (descriptive)

- kill rate by operator and by verifier class, before and after;
- harm-reached rate (the evidence definition), before and after;
- per-capability results for the 23 hardened verifiers;
- the baseline kill rate of the 35 INDEPENDENT verifiers, as a check on the review's classification.

## Stated in advance

- **The improvement is partly by construction.** The operators are known when the hardening is designed,
  so H8 tests whether the hardening does what it was built to do. It is not evidence about unknown
  faults. The false-alarm criterion guards against hardening that simply rejects more.
- **Stubs test the verifier's logic, not the real operating-system channel.** A verifier that kills a
  mutant here could still be fooled by a real collaborator that misreports. This is the same limit as in
  the frozen review.
- The review's TRIVIAL label may overstate some verifiers. The `verify_probe` factory compares the
  snapshot against a second read for directory, search and task state (`probe_verification.agrees`), so
  some of those mutants may already be killed at baseline. The baseline will show this. The labels are
  not changed after the fact.
- The INDEPENDENT verifiers are not changed. Their baseline kill rate is reported whatever it is.

## What would count against H8

Criterion 1 or 2 not met means the hardening leaves known faults undetected. Criterion 3 not met means
it rejects correct work. A non-significant primary means no measurable improvement. Each is reported as a
result.

## Amendment 1 (2026-10-18): harness fixes after the baseline, and a second baseline

**Why.** The baseline run (`h8/runs/20261013T211134Z-baseline`, commit be79cbb) had 26 invalid mutants and
3 false alarms caused by the harness, not by the verifiers. These fixes are made **after** seeing the
baseline results. Run 1 stays committed unchanged and is reported as it ran.

**What changed in the harness** (`h8/run_mutants.py`; the diff is in the commit that adds this amendment).
No verifier, executor, manifest entry, operator or criterion changes.

1. **An exception raised by the verifier is a negative verdict.** ARIES does exactly this
   (`aries/workspace/agent.py`, the `except` after the verifier call sets `met: False`,
   `type: verification_error`). Run 1 recorded these as harness errors, so they were invalid. The runner now
   records the verdict as not met and stores the exception in `verifier_exception`. An exception raised
   before the verifier (in setup, the executor or the mutation) is still a harness error, so the mutant is
   still invalid. In run 1, 19 of the 26 invalid mutants had error types consistent with the verifier
   (15 `FileNotFoundError` on a missing destination, 4 `PermissionError` from `verify_browser`). Run 1 did
   not record where each exception was raised, so this split is inferred. Run 2 records it.
2. **`task.inspect` setup** inserted its two task rows with `add`. The database is shared by the whole run,
   so the second item failed with `IntegrityError` (3 mutants, 2 clean replays). Setup now uses `merge`.
3. **`browser.open` and `browser.search` had no `wrong_target` spec** (`TypeError`, 2 mutants). They now
   have one. `browser.open` opens `site2` and the report is relabelled to the requested `site1`.
   `browser.search` searches the other site (YouTube instead of web) and the report URL is relabelled to
   the requested search URL.
4. **`browser.click` `wrong_target`** clicked `Next 1` in session `s9`, where that element does not exist
   (`ValueError`, 1 mutant). It now clicks `Next 4`, which exists there.
5. **`desktop.close` `side_effect_outside_scope`** chose the other window by list index 1. After a close,
   only one window is left (`IndexError`, 1 mutant). The other window is now selected by id `102`.
6. **The fake browser had no page for search-result URLs**, so the title was empty and all 3
   `browser.search` clean replays were false alarms. A real results page has a title. The fake now gives a
   DuckDuckGo or YouTube results URL a page titled "Search results".
7. Bookkeeping: `--selftest-out` names the self-test file, and the runner refuses to overwrite an earlier
   one. `analyze.py` also lists the mutants killed by a verifier exception.

**Checks before the second baseline.** No mutant verdict was produced between run 1 and this commit.
- The self-test passed 58 of 58 (`h8/selftest-amendment1.json`).
- Only setup and mutation, **never the verifier**, were run for the 11 items affected by fixes 2–6.
  All 11 completed. This check prints only completion, so it gives no verdict.

**Second baseline.** The same manifest is run once with the frozen verifiers and the fixed harness
(`--label baseline2`).
- **Baseline for the primary McNemar test:** run 2. The hardened run and the sealed-set runs use the same
  fixed harness, so run 2 is the comparable baseline. Run 1 is reported next to it.
- **Rule for later fixes:** any further harness fix needs its own amendment and a new baseline before any
  hardened run.

**Direction of the change.** Fix 1 can only add baseline kills, and fix 6 can only remove baseline false
alarms. Both make the baseline look stronger, which makes an improvement from hardening harder to show.

## Amendment 2 (2026-10-18): the hardening, an exploratory condition, and equivalent mutants

Written after baseline-2 and **before** any hardened run.

**Decision on criterion 2 (the user's, Option 1).** The confirmatory test and its three criteria stay as
registered. In baseline-2, two INDEPENDENT verifiers (`notification.send`, `system.disk`) let their
noop_success mutant survive. INDEPENDENT verifiers are not changed, so criterion 2 cannot be met by the
hardening. It is evaluated anyway and reported as not met, with this reason, as a finding.

**The hardening** (`aries/workspace/hardened_verifiers.py`, behind `ARIES_VERIFY_HARDENED`, default off).
It covers the 23 capabilities in `mutants.json` → `hardened_capabilities`, designed from each
capability's contract. The frozen verdict stays one of the checks. Added:
- **agreement:** the report's stable fields must equal a fresh read;
- **a different channel** where one exists:
  - `/proc/meminfo`, `/proc/loadavg` and `os.statvfs` read directly, for `system.status` and
    `system.storage`;
  - the process table for windows;
  - each listed tab's own page;
  - a direct SQL row for `task.inspect`;
  - `os.scandir` and `lstat` for `file.list` and `file.search`;
  - `list-units` for `system.service`, whose executor used `show`;
- **per-capability invariants**, for example a count equals its list, `characters` equals `len(text)`,
  and `highest` or `fullest` is the maximum;
- **volatile values:** two fresh reads, and the allowed difference is the drift the verifier measured
  plus a stated resolution (`TOLERANCE`). A CPU sample, which cannot be taken again, is range-checked
  only, and the evidence says so (`range_only`);
- **UNVERIFIED:** any exception in the verifier's own reads gives `{'met': False, 'status': 'UNVERIFIED'}`.

`browser.click` keeps the planner's `expected_url` as its reference (finding F2). It adds agreement
with the page now shown. The page the click started from cannot be re-observed after the click, so
F2 is only narrowed, not removed.

Off, nothing changes. The flag is read when the registry is imported, and the hardened module is not
imported at all. `tests/test_verify_hardened.py` (17 checks) compares every verifier's code fingerprint
with `h8/frozen_verifiers.json`, which was recorded from a clean worktree of 2af6112 (the baseline-2
commit) by `h8/frozen_verifiers.py`:
- off: all 58 fingerprints are identical;
- on: exactly the 23 are replaced;
- `ARIES_VERIFY_HARDENED_EXTRA` alone: exactly the 2;
- both flags: 25.

A first version of the fingerprint used the `repr` of set constants, which follows the process's hash
seed. It was fixed (sorted members) and re-recorded before this commit. Existing suites with the flags
off: test_agent_execution 65, test_browser 7, test_capability_failure_evidence 18,
test_execution_boundaries 15, test_api 95, all passing.

**Development check, disclosed.** `h8/dev_check_hardened.py` ran each of the 25 hardened verifiers once
on an **honest** execution in a fake world, seeded 7 and not from the manifest. No mutation operator was
applied. Result: 25/25 verified (`h8/dev_check_hardened-r1.json`). This is the only run of the hardened
code before the measured run.

**Runs, all with the Amendment 1 harness** (`run_mutants.py` SHA-256 `4f17771d…`, unchanged since
2a1e66b, the same as baseline-2):
1. **hardened:** public set, `--hardened` (`ARIES_VERIFY_HARDENED=1`, EXTRA off). The primary McNemar
   test is against baseline-2.
2. **sealed set:** run twice. First its SHA-256 is checked. Then it is run with `--hardened`, and once
   more with the frozen verifiers.
3. **Exploratory "hardened-23+2, designed after baseline-2":** public set, with
   `ARIES_VERIFY_HARDENED_EXTRA=1` as well. It is reported separately. It is not in the confirmatory
   criteria or the Holm family.

**Equivalent mutants (found while designing the exploratory condition, before any hardened run).**
In mutation testing, an equivalent mutant is one whose behaviour cannot be told apart from the
original. Three noop_success mutants are probably equivalent here, so no correct verifier can kill
them:
- **`notification.send`:** the twin world does not include the database, so the executor run in the
  twin writes the real row. The effect really happens.
- **`system.disk` and `system.status`:** they read the real machine. The twin cannot change what they
  read, and their reports differ from a real read only in volatile samples, so the harness did not
  fabricate a value. The report is a true, slightly earlier observation.

The harness is not changed for this, since the user asked for the same harness. These mutants stay in
every count. They are reported as probably equivalent, and so as a limit of criterion 2 and of the
operator.
