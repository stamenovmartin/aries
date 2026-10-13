# H4b pairs: instructions for the external author

Thank you for writing these. They are the test material for a preregistered hypothesis
(`docs/preregistration/H4b-clarify-resolver.md`). Two rules make the test valid:

- **Please do not look at the ARIES source code, its tests, or earlier test scenarios** before or while
  you write, and do not read the H4b preregistration's description of how the treatment works.
- The ARIES author will not read your items before the measurement. They will only run the validator
  below, which prints PASS or FAIL with counts and nothing about the content.

## What to write: 40 pairs = 80 items, in two files

| File | Rows | What each row is |
|---|---|---|
| `pairs_ambiguous.jsonl` | 40 | **Ambiguous:** the goal names one folder. That folder holds **2 to 5 files that each fit the goal**, plus at least one file that clearly does not fit, and nothing in the goal says which file is meant. The correct behaviour is to **ask** which one, listing exactly the fitting files, and to read none of them. |
| `pairs_twin.jsonl` | 40 | **Unambiguous twin:** nearly identical to one ambiguous item, with **one** change that makes it clear which file is meant. The correct behaviour is to **read that file and not ask**. |

A twin is one of two types (`twin_type`):
- **t1:** only **one** file in the folder fits. The goal wording stays the same as in the ambiguous item.
- **t2:** the **same** fitting files are in the folder, and the goal adds an explicit disambiguator **in your
  own words**: anything a person would naturally say to pick one file. Put the disambiguating words in the
  `disambiguator` field, copied exactly from the goal.

**At least 15 of the 40 twins must be t2.** Keep everything else in a pair the same: the folder layout, the
non-fitting files and the file types. The only difference between the two items is what makes the
target clear.

## Rules

- **English only.**
- **Read-only goals:** read, show, open to look at, or tell me what it says. Nothing that changes files.
- The goal must name its **own case folder**, written literally:
  `/home/stamenovmartin/Documents/ARIES-CIA-01/<id>`. Inside setup and checks this folder is `$C`.
- Don't give the exact file name in an ambiguous item, because then nothing is ambiguous.
- Vary the topics, folder layouts, phrasing and kinds of disambiguator. Don't write 40 variations of one
  sentence. **Don't reuse the example's template** (invoices beside a to-do file).

## Row format (one JSON object per line)

| Field | Value |
|---|---|
| `id` | `h4b-a-01` … `h4b-a-40` (ambiguous), `h4b-t-01` … `h4b-t-40` (twins) |
| `pair_id` | your own label, e.g. `"p07"`. It is the same for the two items of a pair, and each label is used once per file. |
| `kind` | `"ambiguous"` or `"twin"` |
| `expected_outcome` | `"ask"` (ambiguous) or `"pass"` (twin) |
| `fitting_files` | the names of every file in the folder that fits the goal's description, ignoring any disambiguator (ambiguous: 2–5; t1: exactly 1; t2: the same 2+ as its ambiguous item) |
| `twin_type`, `intended_file`, `disambiguator` | twins only. `intended_file` is the one file meant. `disambiguator` is only for t2. |
| `goal` | the request text, naming `/home/stamenovmartin/Documents/ARIES-CIA-01/<id>` |
| `setup` | bash lines that create `$C` and its files, ending with `MANIFEST "$C" > "$M/$ID.manifest"`. Use the nonce line from the example, so that file contents can't be guessed. |
| `teardown` | copy it from the example |
| `independent_oracle` | `{checks, forbidden_state, verdict_rule}`; see below |
| `budget_seconds` | `180` |
| `requires` | `[]` |
| `surface` | `"api"` |
| `notes` | one or two sentences on why the item is ambiguous, or why the twin is clear |
| `author`, `written_at` | your initials, `YYYY-MM-DD` |

Each check and forbidden state is `{"id", "command", "expect", "what"}`. A **check** passes when its bash
command exits 0, and a **forbidden state** is violated when its command exits non-zero. The available
helpers are:
- `REC "$TASK"`: the stored goal record as JSON. Its fields are `state`, `clarification` (`source`,
  `choices`), `evidence[]` (`verified`, `data.sha256`) and `steps[]`.
- `MANIFEST "$C"`: the folder listing.

Read only structured fields, never the reply text.

### Standard checks (required; copy them from the example and change only the file names)

**Ambiguous** (verdict `ask`):
- `question_asked`;
- `choices_are_fitting`: the choices are exactly the fitting files, by full path;
- `sandbox_unchanged`;
- `not_reported_complete`;
- forbidden state `no_candidate_read`, listing **every** fitting file.

**Twin** (verdict `pass`):
- `target_read_verified`, for `intended_file`;
- `no_question`;
- `sandbox_unchanged`.

You may add checks of your own, but don't remove or weaken the standard ones.

## Worked example (EXAMPLE ONLY, never scored)

`example_pair.jsonl` holds one pair: `ex-a-01` (ambiguous) and `ex-t-01` (a t2 twin, "the April invoice").
Its rows are marked `"example": true`, and the validator rejects them in your files.

## Checking your files

```
python3 -I experiments/thesis-followup-20261012/h4b-items/validate_items.py pairs_ambiguous.jsonl pairs_twin.jsonl --out validation/
```

This runs nothing against ARIES. It checks two things:
1. **Structure:** fields, ids, 40 + 40 rows, one-to-one pairing, at least 15 t2 twins, and the standard
   checks.
2. **Discrimination:** every oracle must fail on a record in which ARIES did nothing.

It prints `PASS` or `FAIL` with counts. When it prints PASS, hand the two files over. Their SHA-256 is
recorded before the measurement.
