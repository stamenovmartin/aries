# Preregistration H6: replication of the abstention-instruction effect (A1 vs A0) on new requests

Status: **draft, not registered.** It becomes registered when committed and pushed, before any H6 item
exists or is opened. Any later edit must be a new commit with a dated "Amendment" section.

## Background

In ARIES-FINAL-20261006 (frozen router run, qwen2.5:7b, 225 requests, 3 repetitions), the instruction
that allows the router to answer ASK or OUT_OF_SCOPE (arm A1, `ARIES_ROUTER_ABSTAIN`) raised binary
accuracy over the arm without it (A0). Per request (majority of 3), exact McNemar gave A1 right and A0
wrong on 36 requests, the reverse on 11, p = 0.00035 (`experiments/thesis-followup-20261012/stats.json`).
That test was post hoc, on the same 225 requests that suggested the arms. H6 tests the effect on new
requests.

The original split by class (`experiments/thesis-followup-20261012/h6-power/power.json`) shows where
the effect comes from and what it costs:

| class | A1 right, A0 wrong | A1 wrong, A0 right | n |
|---|---|---|---|
| actionable | 0 | 11 | 100 |
| ambiguous | 22 | 0 | 55 |
| out of scope | 11 | 0 | 40 |
| unsafe | 3 | 0 | 30 |

The instruction makes the router hold more often: that helps on everything that should not be acted on,
and hurts on actionable requests.

Related work (wording verified in `docs/preregistration/CITATIONS.md`): all models, LLMs included, have
poor OOS recall, which depends on the label space (Arora et al., EMNLP 2024 Industry); small models often
"hallucinate a tool call" instead of asking (Ross et al., When2Call, NAACL 2025); format and instruction
effects transfer poorly between models (Sclar et al., ICLR 2024), which is why llama3.1:8b is only
exploratory here.

## Hypothesis (directional)

**H6.** On new requests, the frozen router with the abstention instruction (A1) has higher per-request
binary accuracy than without it (A0), for qwen2.5:7b.

## Materials

- **New requests, written and labelled by another person** who has not seen the original 225 requests,
  the ARIES code or the router prompts. The class definitions they get are the four classes of the
  frozen fixture, in plain words: actionable (ARIES can and should do it), ambiguous (cannot be done
  without asking what is meant), out of scope (not something ARIES can do), unsafe (should not be done).
  A template and a README for the author are in `experiments/thesis-followup-20261012/h6-items/`.
- **Size and mix: 300 requests**, with the class shares of the master plan's 120: 100 actionable,
  75 ambiguous, 62 out of scope, 63 unsafe. The size was raised from 120 to 300 before any H6 item exists,
  because of the power analysis below.
- **Language.** Half English, half Macedonian in every class, as in the original fixture.
- The file's SHA-256 is recorded before the run. The author of ARIES does not read the requests before
  the run. A validator checks only the structure (fields, classes, counts, unique ids, no duplicate
  utterances, no overlap with the 225 original utterances) and reports PASS or FAIL with counts.

## Procedure

- The frozen ARIES-FINAL-20261006 router protocol and runner, unchanged
  (`experiments/thesis-final-20261006/run_router.py`, `protocol.json`): same prompts, decoding,
  `keep_alive`, model digest of qwen2.5:7b, and the frozen scorer (`analyze_router.py`, binary `correct()`).
- Arms A0 and A1 only. 3 repetitions. As in the frozen protocol, the arm order and the request order of
  each repetition are shuffled with its fixed seeds (`random.Random(26061006 + rep)` for arms,
  `26100000 + rep` for requests), at temperature 0.1: the Ollama adapter exposes no sampling seed.
- The runner is a byte copy of the frozen one, with only the fixture path, the arm list and the output
  folder changed. Task 6 did the same for llama3.1:8b
  (`experiments/thesis-followup-20261012/task6-model/`), and the diff is recorded.
- The live ARIES is stopped during the run, screen blanking is off and restored afterwards, the Ollama
  version and model digest are recorded before and after, and the run is refused if either changes.
- Parse failures and invalid decisions count as wrong, as in the frozen scorer.

## Primary outcome and test

Per request, the majority of 3 repetitions is correct or not. **One-sided exact McNemar test** of A1
against A0 on the discordant requests (b = A1 right and A0 wrong, c = the reverse), H1: b > c, α = 0.05
**before** the Holm correction across the primary tests of the four confirmatory hypotheses H4b, H5, H6
and H8. Reported: b, c,
the exact p-value, the Holm-adjusted p-value, the difference in binary accuracy with an exact
(Clopper-Pearson-based, paired) 95% interval, and b/c.

## Power (computed before any H6 data exists)

From the original per-class split reweighted to the H6 class mix, by simulation of the exact McNemar
test (`h6-power/power.py`, seed 61013, 20,000 draws per scenario; power counts only significant results
with b > c), one-sided α = 0.05:

| n | observed effect | effect halved | effect quartered |
|---|---|---|---|
| 120 | 0.96 | 0.44 | 0.16 |
| 200 | 1.00 | 0.64 | 0.24 |
| 300 | 1.00 | 0.82 | 0.33 |

An effect estimated on the set that suggested it is usually too large, so the "halved" column is the
realistic one. With 300 requests, power for a halved effect is 0.82 at α = 0.05. Under the Holm
correction across 4 tests, the strictest level is 0.05/4 = 0.0125, so power is lower than the table shows.
That is why 300 requests are used and not 120: with 120, a real but halved effect would be missed more
often than found. This is stated now so that a non-significant result is read correctly.

## Secondary outcomes (descriptive)

- abstention precision and recall, per arm (frozen scorer);
- binary accuracy by class, per arm, with exact intervals;
- over-abstention: the share of actionable requests held (ASK, OUT_OF_SCOPE, UNKNOWN), per arm. It is
  expected in advance to be higher with A1, as in the original split (0 vs 11);
- llama3.1:8b, the same protocol, exploratory, with a small or null effect expected (in the original run
  its A1 vs A0 split was 15 vs 10, p = 0.42).

## What would count against H6

A non-significant primary test means the effect did not replicate at this sample size (see Power). A
significant result with b < c would contradict the original finding. Either is reported as a result.

## Amendment 1 (2026-10-18): who wrote the H6 items, and how

This amendment concerns Materials ("written and labelled by another person"). It changes no hypothesis, criterion, test or procedure.

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
  - `experiments/thesis-followup-20261012/h6-items/h6_requests.jsonl`: SHA-256 `2a422d71a2c093c07e27909cf7919a6213580e87d8dbae031808df54c66a302f`, 53651 bytes

## Amendment 2 (2026-10-18): row 1 replaced, before any measurement

**Why.** In the repository, the H6 validator (`h6-items/validate_items.py`, unchanged) gave **FAIL** on the
file frozen in Amendment 1 (SHA-256 `2a422d71…`). It found one problem: row 1 repeats a request from the
earlier ARIES tests (the 225 frozen router requests). Every other check passed. The author was told only the
row's id, class and language (`h6-0001`, `actionable`, `en`), not its text. The row was neither dropped nor
edited by the author. A replacement of the same class and language was requested from Codex instead.

**How the replacement was written.** The user's account is below, followed by what the Codex session logs
show. Only metadata and command lines were read from the logs, never item text.
- **The user's account:** a fresh Codex session (`gpt-6-astra`), in an empty folder `~/h-author/h6-r1`
  holding only the README and the example file, was asked for exactly one replacement item.
  - The user saw that one item's text in the Codex transcript and did not edit it.
  - A `replacement.jsonl` already existed in the folder before that session, and Codex overwrote it.
- **The session logs** (Codex CLI 0.154.0, `danger-full-access` sandbox) show three sessions, not one:
  1. **17:11:47Z, working folder `~`, not an empty folder.**
     - It listed README.md and AGENTS.md files across the home folder with `rg`, which takes in the home
       folder that holds the repository.
     - It read `~/h-author/h6/README.md` and wrote `~/replacement.jsonl`. That file was not used.
  2. **17:12:40Z, in `~/h-author/h6-r1`:** wrote the `replacement.jsonl` that existed before the final
     session.
  3. **17:16:51Z, in `~/h-author/h6-r1`:** the final session.
     - It ran `cat README.md replacement.jsonl`, so it **read the earlier attempt** before overwriting it at
       17:17:38Z.
     - The item used is the one this session wrote.
  - No command in the three sessions names a repository path. No example or template file was in
    `~/h-author/h6-r1` when it was listed (only `README.md` and `replacement.jsonl`).
- **Limitation:** the replacement item is not independent of the earlier attempt, and one item's text was
  seen by the user. This affects 1 of 300 requests. The limitation of Amendment 1 (a model, not a person)
  applies as well.

**The change.**
- Row 1 was replaced programmatically by the single line of `~/h-author/h6-r1/replacement.jsonl`
  (SHA-256 `2f60f15b…`, 182 bytes).
- Rows 2–300 are byte-identical (checked). The id, class and language are unchanged.
- Removed row: SHA-256 `3ee01bcbb54db42f1b0770316481dcf5a5646ddbcfb2702e1e8c1161718bd5a6`. Inserted row:
  SHA-256 `365c400fe93e3b5e1d1889d8f6a9d15177a13c0c4c5ddcd24ebf36e1313b048c`.
- File `experiments/thesis-followup-20261012/h6-items/h6_requests.jsonl`:
  - before: SHA-256 `2a422d71a2c093c07e27909cf7919a6213580e87d8dbae031808df54c66a302f`, 53651 bytes;
  - **after (frozen for H6):** SHA-256 `3068dd8d9b41b58987e6d2270b66629389c8b3b40937502ce9462b9ffce35348`,
    53697 bytes.

**Validation after the change:**

    PASS  rows=300  classes={'actionable': 100, 'ambiguous': 75, 'out_of_scope': 62, 'unsafe': 63}  problems=0

Nothing has been measured.

## Amendment 3 (2026-10-18): the unused file, and the run setup, before any H6 inference

- **The unused file:** the file written by the first replacement session (Amendment 2, session 1:
  `~/replacement.jsonl`, SHA-256 `2b6a4da6…`, 220 bytes) was not used. On the user's instruction it was moved,
  not deleted, to `~/h-author/h6-unused/replacement.jsonl`.
- **The run:** `experiments/thesis-followup-20261012/h6-run/`.
  - `run_router_h6.py` is the frozen `run_router.py` with only the fixture path, the arm list (A0, A1) and the
    output folder changed. The protocol's descriptive fields (question, arms, primary comparison,
    limitations) now name H6. The full diff is in `runner.diff`.
  - `protocol.json` was written by `--prepare`, without inference. Its A0 and A1 prompt hashes, settings and
    qwen2.5:7b digest (`845dbda0ea48…`) equal those of the frozen protocol.
  - The order is 1-A1, 1-A0, 2-A1, 2-A0, 3-A0, 3-A1, from the frozen seeds.
  - The fixture hash is the Amendment 2 file (`3068dd8d…`).
- **Procedure:** `run-h6.sh`, as in Task 6:
  - the live `aries.target` is stopped and always restarted;
  - screen blanking is off (idle-delay 0 plus an idle inhibitor) and restored;
  - the Ollama version and the model digest are recorded before and after.
- **Analysis:** `analyze_h6.py`, written before the run. It uses the frozen `correct()`/`score()`. It
  refuses to give a result if anything changed, and reports the primary test as registered.
