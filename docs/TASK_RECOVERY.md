# Verified continuation of bounded tasks

An interrupted/unsuccessful task now offers **Check and continue**. This creates
one linked child goal rather than rewriting the original attempt. Repeated
requests for the same parent return that child; its dashboard links back to the
original evidence. A failed continuation can itself be checked again explicitly.
Cancelled tasks are not resumed by this mechanism.

Before queueing, ARIES checks every saved mutation through its existing verifier:
exact file bytes, folder existence, move/Trash identity, installed revision or
project artifacts. An uncertain action is never reissued: if its requested effect
is already independently confirmed, it can be marked as currently satisfied in
the continuation. That does not prove the original interrupted action caused it.

Verification happens again after queueing and before execution. Changed path
resolution, missing evidence or changed file content stops continuation. This is
not a filesystem transaction against concurrent manual edits, but no mutation is
replayed during recovery. Exact-file verification uses bounded reads, so replacing
a small expected file with a huge one does not cause an unbounded verification read.

Supported read capabilities and research are refreshed, including reads that
previously succeeded. Static writes remain inherited, visibly marked as rechecked
and excluded from the count of newly executed actions in evaluation. The original
failed attempt remains in historical results.

Current limits:

- Saved bounded plans and M14 histories consisting entirely of non-browser reads
  can continue. Other dynamic engines, histories containing mutations, and opaque
  desktop actions are refused. No browser-session reconstruction is claimed.
- No failed installation, deletion, move, edit, UI action or shell text is replayed.
- A sequence whose earlier intermediate artifact was intentionally moved away
  can fail verification; recovery does not invent an alternative verifier.
- This is explicit continuation, not automatic retry or autonomous recovery of
  arbitrary apps. The existing queue limit, resource locks and command gates apply.

API: `POST /api/aries/workspace/{goal_id}/recover`. A missing task returns 404;
unsupported, changed or unverifiable tasks return 409. The response names the
continuation and indicates whether it already existed.

Validation: `tests/test_workspace_recovery.py` checks duplicate requests, unchanged
parent failure, no repeated write, a fresh successful read, no double-counted
mutation, a target edited while queued, uncertain effects and unsupported agents.

Installed-system validation: `experiments/workspace/verify_recovery.json` passed
6/6 checks using a real folder and a missing file later supplied: original failure
preserved, child completed, duplicate request reused the child, folder inherited
without execution, inode unchanged and fresh file contents read. The standard
suite passed, including 10 dedicated recovery checks and 419 UI client checks.
Historical review context also distinguishes inherited effects from new actions.

## M14 read-only recovery hardening — 1 October 2026

A dynamic continuation retains its remaining original step and planner-call
budgets. Exhausted budgets, removed capabilities and incompatible arguments are
refused before creating a child. Current policy is checked again before every
refresh; a `False` approval result cannot authorize even a read-only capability.

The original attempt retains its old evidence, answer and observations. The child
starts without old final evidence, answer cards or planner context and re-observes
each saved read under its own task ID. A failed refresh records fresh failure
evidence and cannot leave an old verified payload attached. Only literal boolean
`True` counts as verification success.

`tests/test_workspace_recovery.py` now checks 26 conditions, including an actual
queue flow from read → partial result → linked recovery → fresh observation →
independently verified completion. The planner is deterministic in this test;
the queue, file reads and verifiers are real. This is not evidence of arbitrary
model planning quality or automatic mutation recovery.
