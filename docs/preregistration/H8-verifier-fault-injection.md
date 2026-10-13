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
