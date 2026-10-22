# H5 pilot on the two example items (2026-10-18, not scored)

`pilot-h5.sh`: one treatment and one control run on `h5-items/example_items.jsonl` (`ex-g-01`, `ex-n-01`), with
the live ARIES stopped (23:37:18Z–23:38:48Z) and screen blanking off. Its only use is the duration estimate.

- **First attempt refused** (`pilot-h5-refused-1.log`): the screen was already blanked (not locked) when the
  script started, and the runner refused before submitting anything. The script now wakes the screen after it
  sets idle-delay 0.
- **Runs:** `20261018T233720Z-pilot-treatment` (45 s) and `20261018T233805Z-pilot-control` (43 s). Effective
  flags equal the declared ones. The model is stable in both runs.
- **`code_stable: false` in the control run** comes from a commit made during that run (`b045710`, which
  touched `RESULTS.md` and `thesis-tables/` only). `git diff --stat 2297419 b045710 -- aries vendor tests
  aries_ui requirements.txt` is empty. Lesson: no commits during the full runs.
- **Outcome:** all 4 item-runs end `failed` after 9 planner calls ("budget exhausted without a finish"). The
  goal names only a folder. The planner calls `file.read` on the folder (IsADirectoryError) and then repeats
  that step 7 times; each repeat is rejected as a duplicate. This is the known repeated-identical-step loop
  (RESULTS.md, Pending). In the treatment, the paraphrase fast path made a contract that requires a
  `file.read` of that folder, so the typed step was not called. These are example items, never scored. No code
  was changed because of them.
- **Per item:** 16.1–24.1 s (mean 20.6 s), including setup and oracle.
