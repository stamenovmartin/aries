# X1: H5 and H4b re-run with the remedies designed after their results (registered exploratory)

**Registered:** 2026-10-22, after the H5 and H4b results (`experiments/thesis-followup-20261012/RESULTS.md`
§10–§11) and before any run below. Committed before those runs.

**Label: exploratory.** The items are the same frozen H5 and H4b items, already measured, and the remedies were
designed after their results. This file fixes the conditions, the number of runs and what is compared, so
that runs cannot be chosen afterwards. Nothing here changes H5 or H4b, enters the Holm family, or counts as a
confirmation; a confirmatory test needs new items (H5b, H4c), which have not been written.

## The remedies (each behind its own flag, default off; tests in `tests/test_h5_h4b_remedies.py`)

| flag | designed after | what it changes |
|---|---|---|
| `ARIES_CONTRACT_FILENAME_JOIN` | H5: a read or existence goal naming a folder and a bare file name compiled to a contract on the folder; file.read can never satisfy it, and an existence check on the folder passes, which is a wrong `done` | the bare name is joined to the folder; a folder read with no single name gets no contract; "show me" a path with an extension is a read |
| `ARIES_TYPED_CONTRACT_CODE_PATH` | H5: the typed step was rejected in 15 runs because the path the model wrote did not occur verbatim | the model returns only the goal type and a name; code supplies the one path the request names |
| `ARIES_RESOLVER_CODE_SELECT` | H4b: the resolver's model call answered `ask` in all 240 item-runs, so twins were always over-asked | no model call; code selects the one candidate a request word or order word singles out, with the check that guarded the model's selection, otherwise ARIES asks |

## Conditions and runs (`experiments/thesis-improvements-20261022/run_followup_rerun.py`)

The registered runners (`h5-runs/run_h5.py`, `h4b-runs/run_h4b.py`) are used unchanged; the wrapper only points
them at the frozen items, at this checkout's code, and at a new output folder, and adds the conditions:

- **H5 `remedies`** = the H5 treatment flags + `ARIES_CONTRACT_FILENAME_JOIN` + `ARIES_TYPED_CONTRACT_CODE_PATH`,
  3 runs (15 G goals, 10 N controls, 49 held-out goals each), as H5.
- **H5 `consolidated`** = `remedies` + `ARIES_READ_PATH_STRICT` + `ARIES_LOOP_GUARD` + `ARIES_PLAN_DISPATCH_FIX`
  (the fixes of `docs/AUDIT.md` designed after the held-out run), 1 run, descriptive: the held-out goals with
  every remedy on.
- **H4b `code-select`** = the H4b treatment flags + `ARIES_RESOLVER_CODE_SELECT`, 3 runs (40 pairs each).

All with the live ARIES stopped, the H5/H4b preflight checks, qwen2.5:7b.

## What is compared (descriptive; no test is counted as confirmation)

- H5: correct `done` on G (majority of 3) and false `done` over G and N item-runs, `remedies` against the
  recorded H5 treatment and control runs (`h5-runs/outcomes.json`), with H5's three criteria applied to
  `remedies` as a reading aid; held-out PASS and `done` counts per condition; contract sources.
- H4b: ambiguous asked, twins correct and pairs correct (majority of 3), `code-select` against the recorded
  treatment and baseline (`h4b-runs/outcomes.json`).
- A McNemar p against the earlier treatment is reported for orientation only.

Expected directions, stated now: `remedies` raises correct `done` on G and lowers false `done` against the H5
treatment; `code-select` gets most ambiguous items asked and most twins acted on, so pairs correct rise above 0.

## Limitations stated in advance

Same items, designed-after remedies: these numbers can show that the diagnosed defects were the cause, not
that the remedies generalise. Items written by a model, not a person. One machine.
