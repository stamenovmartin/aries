# aries100 — superseded as the project's measuring stick, 2026-10-03

67 declarative goals with external-state probes. Built 2026-10-01 in this session;
**not the benchmark to quote any more.** Use
`experiments/assistant-benchmark/` (60 cases, Codex's), which does three things
this one does not:

- it hashes the production sources and the fixture into every result, so a run
  cannot be silently compared across a code change;
- it distinguishes a **typed policy refusal** from a generic HTTP error, which
  this one scores as the same thing;
- it requires a machine-checkable clarification for ambiguity rather than
  accepting a plausible answer.

Its current figure is **54/60** (`ambiguous 8/8`, `refusal 6/8`, `desktop 0/4`,
run `20261003T125438Z-after-failure-and-clarification`), verified independently by
reading its `results.json` rather than taking the number on trust.

**Do not merge the two denominators and do not run both corpora at once.** Sixty
and sixty-seven different cases are two different questions; averaging them
produces a number that answers neither.

## What is still worth taking from here

The tier structure, which `assistant-benchmark` expresses differently: `one-step`,
`multi-step`, `ambiguous`, `out-of-scope`, `must-refuse`, where the last three
invert scoring so that **success means not acting**. That idea outlived this
harness and is now carried further by `experiments/router-ood/` (225 utterances),
which asks the prior question — whether the decision *preceding* execution can
express "ask" or "cannot" at all.

The 69.5% figure once reported from `bench1.txt` is **contaminated** and must not
be quoted: 66 goals were submitted into a capacity-3 queue with 75-second budgets,
so 18 unfinished goals were scored as failures. The harness was corrected
afterwards (200 s budget, unfinished counted as `skip`, queue drained between
goals) but never re-run, because the better instrument already existed.
