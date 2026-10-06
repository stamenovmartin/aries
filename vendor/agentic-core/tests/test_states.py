"""The state machines hold their four invariants."""
from _harness import bootstrap, check, run_module
bootstrap("states")

from agentic_core.orchestrator import states as S  # noqa: E402


def test_invariants_hold():
    S._verify_invariants()
    check("cancelled never reaches execution", not (S.reachable(S.TaskState.CANCELLED) & S.LIVE_STATES))
    for f in S.FAILURE_STATES:
        check(f"{f.value} never → succeeded", S.ExecutionState.SUCCEEDED not in S.ALLOWED_TRANSITIONS[f])
    check("partially_done never → done directly", S.TaskState.DONE not in S.ALLOWED_TRANSITIONS[S.TaskState.PARTIALLY_DONE])


def test_edit_invalidates_approval():
    check("approved → draft on edit", S.invalidate_approval("approved") is S.TaskState.DRAFT)
    check("scheduled → draft on edit", S.invalidate_approval("scheduled") is S.TaskState.DRAFT)
    check("draft unchanged", S.invalidate_approval("draft") is S.TaskState.DRAFT)
    try:
        S.invalidate_approval("done"); check("live task refuses edit", False)
    except S.IllegalTransition:
        check("live task refuses edit", True)


def test_transitions_and_aliases():
    check("legacy 'pending_approval' parses", S.parse_task("pending_approval") is S.TaskState.AWAITING_APPROVAL)
    check("legacy 'published' parses", S.parse_task("published") is S.TaskState.DONE)
    check("bare failed is permanent", S.parse_execution("failed") is S.ExecutionState.PERMANENT_FAILURE)
    check("failed+transient is retryable", S.execution_state_from_operation("failed", "transient") is S.ExecutionState.RETRYABLE_FAILURE)
    check("advance_task returns storage string", S.advance_task("draft", S.TaskState.RUNNING) == "running")
    try:
        S.advance_task("done", S.TaskState.RUNNING); check("done → running refused", False)
    except S.IllegalTransition as e:
        check("done → running refused", "Illegal transition" in str(e))
    try:
        S.transition(S.TaskState.DRAFT, S.ExecutionState.RUNNING); check("machines do not mix", False)
    except S.IllegalTransition:
        check("machines do not mix", True)


def test_rollup_never_overclaims():
    T = S.TaskState
    check("all done → done", S.rollup_outcome(total=3, done=3, failed=0) is T.DONE)
    check("uncertain → partially_done", S.rollup_outcome(total=3, done=2, failed=0, uncertain=1) is T.PARTIALLY_DONE)
    check("mixed → partially_done", S.rollup_outcome(total=3, done=1, failed=2) is T.PARTIALLY_DONE)
    check("only failures → failed", S.rollup_outcome(total=2, done=0, failed=2) is T.FAILED)
    check("pending → approved (still actionable)", S.rollup_outcome(total=2, done=1, failed=0, pending=1) is T.APPROVED)


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
