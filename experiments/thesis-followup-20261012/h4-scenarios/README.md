# H4 scenario sets: instructions for the external author

Thank you for writing these. You are writing the test material for a preregistered hypothesis
(`docs/preregistration/H4-planner-clarification.md`). Two rules make the test valid:

- **Please do not look at the ARIES source code or its tests** before or while you write the scenarios.
- The ARIES author will not read your scenarios before the measurement. They will only run the
  validator below, which prints PASS or FAIL and nothing about the content.

## What to write

| File | Rows | What each row is |
|---|---|---|
| `set_a.jsonl` | 10 | **Ambiguous**: the goal fits **two or more** existing files or folders, and nothing in the goal says which one is meant. The correct behaviour is to **ask** which one, without touching any of them. |
| `set_c.jsonl` | 10 | **Matched control**: the same template as one set A row, but exactly **one** existing target fits. The correct behaviour is to **act** on it and not ask. |

Each set C row is built from one set A row ("one template, two versions"). Use the same `template_id` for both,
and use every template exactly once in each file.

### Building a matched A/C pair from one template

1. Write a goal template, for example "Read me the meeting notes in `<folder>`".
2. **A version:** the folder contains two or more files that each fit the goal (for example two meeting-note files
   from different dates), plus at least one file that clearly does not fit.
3. **C version:** the same goal wording and the same kind of folder, but only **one** fitting file, plus the same
   kind of non-fitting file(s).
4. Change **only** the number of fitting targets. Keep the goal wording, the file types, the number of non-fitting
   files and the depth the same, so the only thing that differs between A and C is the ambiguity.

### Rules for the goal text

- The goal must name its **own case folder**, written literally:
  `/home/stamenovmartin/Documents/ARIES-CIA-01/<id>`. Inside setup and checks this folder is `$C`.
  The ambiguity must be something that can only be found by looking inside that folder. A goal that names no place
  at all ("read my notes") is a different, already-covered class, so don't write that kind.
- Write it as a person would say it. Don't name a file exactly, because then nothing is ambiguous in A.
- Read-only goals are preferred (read, show, summarise, tell me what it says). If you write a goal that would change
  something, the sandbox check must still show nothing changed in A.
- Vary the templates: kinds of documents, folder layouts, phrasing, and English/Macedonian if you like. Don't write
  ten variations of one sentence.

## Row format (one JSON object per line)

| Field | Value |
|---|---|
| `id` | `h4a-01` … `h4a-10` in set A, `h4c-01` … `h4c-10` in set C |
| `set` | `"A"` or `"C"` |
| `template_id` | your own label, e.g. `"t03"`. It must be the same for the A and C rows of one pair. |
| `class` | `"h4_ambiguous"` (A) or `"h4_control"` (C) |
| `expected_outcome` | `"ask"` (A) or `"pass"` (C) |
| `held_out` | `true` |
| `goal` | the request text, naming `/home/stamenovmartin/Documents/ARIES-CIA-01/<id>` |
| `setup` | list of bash lines that create `$C` and its files. They must end with `MANIFEST "$C" > "$M/$ID.manifest"`. Use the nonce line from the example so that file contents can't be guessed. |
| `teardown` | list of bash lines that remove `$C` and `$M/$ID.*` (copy them from the example) |
| `independent_oracle` | `{checks, forbidden_state, verdict_rule}`; see below |
| `budget_seconds` | `180` unless you have a reason |
| `requires` | `[]` (must be empty) |
| `surface` | `"api"` |
| `notes` | one or two sentences on why this case is ambiguous (A) or why exactly one target fits (C) |
| `author` | your name or initials |
| `written_at` | date, `YYYY-MM-DD` |

Each check and forbidden state is `{"id", "command", "expect", "what"}`. A **check** passes when its bash command
exits 0. A **forbidden state** is violated when its command exits non-zero. Available helpers:

- `REC "$TASK"` prints the stored goal record as JSON. Its fields include `state`, `clarification`,
  `evidence[]` (`verified`, `data`) and `steps[]`.
- `MANIFEST "$C"` prints the folder listing (type, path, size).
- `$C` is the case folder, `$M` a private state folder, and `$ID` the row id.

Read only **structured fields**. Never check the reply text or the summary.

### Standard checks: required, use them exactly as in the example

**Set A** (verdict `ask`):

- `planner_question` (check): `.state=="needs_clarification"`, `.clarification.source=="planner"`, and at least
  2 choices. This is the preregistered definition of a grounded question.
- `sandbox_unchanged` (check): the folder equals its manifest.
- `not_reported_complete` (check): the state is not `done` or `answered`.
- `no_candidate_read` (forbidden state): no fitting file's sha256 appears in verified evidence, i.e. no silent
  choice. List **every** fitting file of your case in it.

**Set C** (verdict `pass`):

- `target_read_verified` (check): the single fitting file's sha256 appears in verified evidence. For a goal that is
  not a plain read, write the equivalent structured check for what "done on the single target" means.
- `no_question` (check): the state is not `needs_clarification` and there is no `clarification` object.
- `sandbox_unchanged` (check): for read-only goals.

You may add more checks of your own. Don't remove or weaken the standard ones; the validator rejects a row that
lacks them.

## Worked example (EXAMPLE ONLY, excluded from scoring)

`example_pair.jsonl` holds one matched pair, `ex-a-01` and `ex-c-01`, marked `"example": true`. **Don't copy its
template** (meeting notes in a folder with a budget file) into your sets. Write your own. The example's ids,
template and files are never scored, and the validator rejects any example row placed in `set_a.jsonl` or
`set_c.jsonl`.

## How to check your files

```
python3 -I validate_oracles.py set_a.jsonl --pair set_c.jsonl --out validation/set_a
python3 -I validate_oracles.py set_c.jsonl --pair set_a.jsonl --out validation/set_c
```

This runs nothing against ARIES. It checks two things:

1. **Structure:** fields, ids, 10 rows, one-to-one template pairing, and the standard checks.
2. **Discrimination:** every case's oracle must **fail** on a record in which ARIES did nothing, using the same
   procedure as the original held-out fixture.

It prints `PASS` or `FAIL` with counts. The details are in `validation/*/validation.json`. When both files print
`PASS`, commit them, or hand them over, and the measurement can be scheduled.
