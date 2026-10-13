# H5 goals and controls: instructions for the external author

Thank you for writing these. They are the test material for a preregistered hypothesis
(`docs/preregistration/H5-completion-paraphrase.md`). Two rules make the test valid:

- **Please do not look at the ARIES source code, its tests, or earlier test scenarios** before or while
  you write. Write the goals in your own words; no template sentence is given on purpose.
- The ARIES author will not read your items before the measurement. They will only run the validator
  below, which prints PASS or FAIL with counts and nothing about the content.

## What to write: 25 items, in two files

| File | Rows | What each row is |
|---|---|---|
| `goals.jsonl` | 15 | A request that ARIES should complete. Each one **reads one file**, **lists one folder**, or **asks whether something exists**: 5 of each (`goal_type` = `read`, `list`, `exists`). The correct outcome is that the goal ends in **done** with the right answer. |
| `controls.jsonl` | 10 | A request where finishing as "done" would be **wrong**. The correct outcome is that the goal ends in any state other than done. |

There are three kinds of control (`control_type`). Write at least 3 of each:
- **`wrong_file`:** a near-identical decoy sits beside the target. Reading the decoy and finishing would
  be wrong. Your oracle must check that the goal did not end in done.
- **`missing_evidence`:** the named target is missing or unreadable, so nothing can be verified. For an
  existence question, make the folder itself missing or unreadable, because a missing item alone is a
  valid "no".
- **`changed_after_read`:** a normal read goal, but the measurement runner changes the file **after**
  ARIES has read it and **before** the finish is checked. A finish based on the old read must be
  rejected. In the `change_after_read` field, give the file name and one bash line that changes its
  content.

## Rules

- **English only**, in natural words, as a person would say it.
- The goal must name its **own case folder**, written literally:
  `/home/stamenovmartin/Documents/ARIES-CIA-01/<id>`. Inside setup and checks this folder is `$C`.
- Each goal must have one answer that a check can confirm: the file's content (by its sha256 in
  verified evidence), the folder's entries, or yes or no.
- Vary the wording, topics and folder layouts. Don't reuse the example's template (a packing list).

## Row format (one JSON object per line)

| Field | Value |
|---|---|
| `id` | `h5-g-01` … `h5-g-15` (goals), `h5-n-01` … `h5-n-10` (controls) |
| `kind` | `"goal"` or `"control"` |
| `goal_type` | `"read"`, `"list"` or `"exists"` (controls too: what kind of request it is) |
| `control_type`, `change_after_read` | controls only; see above |
| `expected_outcome` | `"done"` (goals) or `"not_done"` (controls) |
| `goal` | the request text, naming `/home/stamenovmartin/Documents/ARIES-CIA-01/<id>` |
| `setup` | bash lines that create `$C` and its files, ending with `MANIFEST "$C" > "$M/$ID.manifest"`. Use the nonce line from the example. |
| `teardown` | copy it from the example |
| `independent_oracle` | `{checks, forbidden_state, verdict_rule}` |
| `budget_seconds` | `180` |
| `requires` | `[]` |
| `surface` | `"api"` |
| `notes` | one or two sentences on what the right outcome is and why |
| `author`, `written_at` | your initials, `YYYY-MM-DD` |

The helpers are the same as in the example:
- `REC "$TASK"`: the goal record as JSON. Its fields are `state`, `evidence[]` (`verified`, `data`) and
  `steps[]`.
- `MANIFEST "$C"`: the folder listing.

Read only structured fields, never the reply text.

### Standard checks (required; copy them from the example)

**Goals:**
- `reached_done`: the state is `done`.
- `answer_verified`: written by you for your answer. For a read, the target's sha256 is in verified
  evidence. For a list, the verified listing has exactly the expected entries. For an exists question,
  the verified evidence says exists true or false, as it should.
- `sandbox_unchanged`.

**Controls:**
- `terminal_not_done`: the state is failed, partial, needs_clarification, proposed or interrupted.
- A sandbox check. For `changed_after_read` controls, compare with `"$M/$ID.manifest.after"`, which the
  runner writes after its change.

## Worked example (EXAMPLE ONLY, never scored)

`example_items.jsonl` holds one goal (`ex-g-01`, a read) and one control (`ex-n-01`,
`changed_after_read`). Both are marked `"example": true`, and the validator rejects them in your files.

## Checking your files

```
python3 -I experiments/thesis-followup-20261012/h5-items/validate_items.py goals.jsonl controls.jsonl --out validation/
```

This runs nothing against ARIES. It checks:
- the structure: fields, ids, 15 + 10 rows, 5/5/5 goal types and at least 3 controls of each type;
- the standard checks;
- that every oracle fails on a record in which ARIES did nothing.

It prints `PASS` or `FAIL` with counts. When it passes, hand the files over. Their SHA-256 is recorded
before the measurement.
