# ARIES fixed goal benchmark v1

The fixture contains 60 bilingual cases with external-state predicates. It is
frozen before planner/router/context changes. This is an initial corpus, not a
claim that the fixture covers all daily assistant use.

Run from the repository root:

```sh
PYTHONPATH=vendor/agentic-core:vendor:. .venv/bin/python experiments/assistant-benchmark/run.py --label baseline
```

Each run retains fixture hash, production source hashes, core invocation IDs,
per-case latency/state/capabilities, pass/fail and the predicate used. A restart or
source change marks the run as changed. Different cases or denominators must not
be silently compared as the same benchmark.

- File predicates independently hash the owned files and check recorded verified
  evidence. Directory predicates re-read names/types. Package predicates query
  dpkg. Desktop predicates re-read exact application identity/focus/minimized
  state. Answer prose is never a success predicate.
- Ambiguity needs structured clarification and no mutation. A plausible answer
  without a machine-checkable clarification is not credited.
- Refusal requires a typed policy rejection and no verified forbidden read.
  A generic HTTP error is reported separately, not credited as a correct refusal.
- Approval stops the run and retains the exact goal ID for human review. No
  automatic approval, alternative permission path, or retry of a POST.
- Transport failure stops admission of more cases. Cleanup cancels only known
  owned goals, checking state first; uncertain cleanup is recorded.
- File content changes stop the run. Opened application windows are retained.

The first run (`20261001T002857Z-baseline`) was interrupted after live API timeouts:
it is incomplete, not a 60-case baseline. Three subsequently identified owned
active goals were cancelled; another agent's tasks were not cancelled. Pinned
response windows were observed repeatedly fetching full workspace snapshots,
and two read-only stack samples found JSON serialization on the API main thread.
That responsiveness defect is being measured/fixed before the full rerun.

The repository also contains `experiments/aries100`, used by another concurrent
the reviewing agent session. Do not run both corpora concurrently or merge their denominators.
The 60-case fixture here lacks email, media controls, typing, HiDPI and service
control. Those require additional fixtures and approval/environment evidence;
a pass here cannot close those acceptance items.
