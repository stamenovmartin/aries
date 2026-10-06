"""The two lifecycles as a table of legal edges, with four invariants verified
at import. Lifted from backend/app/domain/states.py, vocabulary generalised:

  Campaign  → Task            researching→planning, generating→running,
                              generated→completed_unverified, publishing→executing,
                              partially_published→partially_done, published→done

Rules that must not be edited away:
  1. An edit to an approved task invalidates the approval (→ DRAFT).
  2. A cancelled task can never reach execution (one exit: ARCHIVED).
  3. A failed operation can never be reported as succeeded.
  4. PARTIALLY_DONE is resumable, never silently "done".
"""
from __future__ import annotations

from enum import Enum


class TaskState(Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED_UNVERIFIED = "completed_unverified"
    VALIDATION_FAILED = "validation_failed"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    PARTIALLY_DONE = "partially_done"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"

    def __str__(self):
        return self.value


class ExecutionState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"

    def __str__(self):
        return self.value


State = TaskState | ExecutionState
_T, _E = TaskState, ExecutionState

ALLOWED_TRANSITIONS: dict[State, frozenset] = {
    _T.DRAFT: frozenset({_T.PLANNING, _T.RUNNING, _T.AWAITING_APPROVAL, _T.CANCELLED, _T.ARCHIVED}),
    _T.PLANNING: frozenset({_T.RUNNING, _T.DRAFT, _T.FAILED, _T.CANCELLED}),
    _T.RUNNING: frozenset({_T.COMPLETED_UNVERIFIED, _T.AWAITING_APPROVAL, _T.VALIDATION_FAILED,
                           _T.FAILED, _T.CANCELLED, _T.PLANNING}),
    _T.COMPLETED_UNVERIFIED: frozenset({_T.AWAITING_APPROVAL, _T.VALIDATION_FAILED, _T.RUNNING,
                                        _T.DRAFT, _T.CANCELLED, _T.DONE}),
    # A validation failure is fixed or re-run; it is never approved as-is.
    _T.VALIDATION_FAILED: frozenset({_T.RUNNING, _T.PLANNING, _T.DRAFT, _T.CANCELLED, _T.ARCHIVED}),
    _T.AWAITING_APPROVAL: frozenset({_T.APPROVED, _T.REJECTED, _T.DRAFT, _T.CANCELLED}),
    _T.REJECTED: frozenset({_T.DRAFT, _T.RUNNING, _T.PLANNING, _T.CANCELLED, _T.ARCHIVED}),
    _T.APPROVED: frozenset({_T.SCHEDULED, _T.EXECUTING, _T.DRAFT, _T.CANCELLED}),   # rule 1
    _T.SCHEDULED: frozenset({_T.EXECUTING, _T.APPROVED, _T.DRAFT, _T.FAILED, _T.CANCELLED}),
    # No EXECUTING → CANCELLED: once actions are in flight, "cancelled" would be
    # a claim about the outside world. EXECUTING → APPROVED is the crash sweep.
    _T.EXECUTING: frozenset({_T.DONE, _T.PARTIALLY_DONE, _T.FAILED, _T.APPROVED}),
    _T.PARTIALLY_DONE: frozenset({_T.EXECUTING, _T.ARCHIVED}),                       # rule 4
    _T.DONE: frozenset({_T.ARCHIVED}),
    _T.FAILED: frozenset({_T.EXECUTING, _T.APPROVED, _T.DRAFT, _T.PLANNING, _T.CANCELLED, _T.ARCHIVED}),
    _T.CANCELLED: frozenset({_T.ARCHIVED}),                                          # rule 2
    _T.ARCHIVED: frozenset(),

    _E.PENDING: frozenset({_E.RUNNING, _E.CANCELLED}),
    _E.RUNNING: frozenset({_E.SUCCEEDED, _E.RETRYABLE_FAILURE, _E.PERMANENT_FAILURE, _E.RECONCILIATION_REQUIRED}),
    _E.RETRYABLE_FAILURE: frozenset({_E.RUNNING, _E.PERMANENT_FAILURE, _E.CANCELLED}),
    _E.RECONCILIATION_REQUIRED: frozenset({_E.SUCCEEDED, _E.RETRYABLE_FAILURE, _E.PERMANENT_FAILURE, _E.CANCELLED}),
    _E.PERMANENT_FAILURE: frozenset(),
    _E.SUCCEEDED: frozenset(),
    _E.CANCELLED: frozenset(),
}

FAILURE_STATES = frozenset({_E.RETRYABLE_FAILURE, _E.PERMANENT_FAILURE})
APPROVAL_BEARING = frozenset({_T.AWAITING_APPROVAL, _T.APPROVED, _T.SCHEDULED})
LIVE_STATES = frozenset({_T.EXECUTING, _T.PARTIALLY_DONE, _T.DONE})


class StateError(RuntimeError):
    pass


class UnknownState(StateError):
    pass


class IllegalTransition(StateError):
    def __init__(self, frm, to, *, extra: str = ""):
        self.frm, self.to = frm, to
        allowed = ALLOWED_TRANSITIONS.get(frm)
        if allowed is None:
            whither = "unknown source state"
        elif not allowed:
            whither = "that is a terminal state — it has no exit"
        else:
            whither = "allowed only to: " + ", ".join(f"'{s.value}'" for s in sorted(allowed, key=lambda s: s.value))
        super().__init__(f"Illegal transition '{_name(frm)}' → '{_name(to)}': {whither}." + (f" {extra}" if extra else ""))


class InvariantBroken(StateError):
    pass


def _name(x):
    return x.value if isinstance(x, Enum) else str(x)


# Legacy/storage aliases — the marketing vocabulary reads into this machine.
_TASK_ALIASES = {
    "pending_approval": _T.AWAITING_APPROVAL, "ready_for_approval": _T.AWAITING_APPROVAL,
    "pending": _T.AWAITING_APPROVAL, "researching": _T.PLANNING, "generating": _T.RUNNING,
    "generated": _T.COMPLETED_UNVERIFIED, "partial": _T.PARTIALLY_DONE,
    "partially_published": _T.PARTIALLY_DONE, "publishing": _T.EXECUTING, "posting": _T.EXECUTING,
    "published": _T.DONE, "posted": _T.DONE, "success": _T.DONE, "completed": _T.DONE,
    "qa_failed": _T.VALIDATION_FAILED, "validating": _T.RUNNING,
}
_EXECUTION_ALIASES = {
    "sent": _E.RUNNING, "uncertain": _E.RECONCILIATION_REQUIRED, "queued": _E.PENDING,
    "posted": _E.SUCCEEDED, "success": _E.SUCCEEDED, "skipped": _E.CANCELLED,
    # Bare 'failed' carries no class → read fail-closed as PERMANENT.
    "failed": _E.PERMANENT_FAILURE,
}


def parse_task(raw) -> TaskState:
    if isinstance(raw, TaskState):
        return raw
    key = (raw or "").strip().lower()
    try:
        return TaskState(key)
    except ValueError:
        pass
    if key in _TASK_ALIASES:
        return _TASK_ALIASES[key]
    raise UnknownState(f"Unknown task state: '{raw}'.")


def parse_execution(raw) -> ExecutionState:
    if isinstance(raw, ExecutionState):
        return raw
    key = (raw or "").strip().lower()
    try:
        return ExecutionState(key)
    except ValueError:
        pass
    if key in _EXECUTION_ALIASES:
        return _EXECUTION_ALIASES[key]
    raise UnknownState(f"Unknown execution state: '{raw}'.")


def execution_state_from_operation(state: str, error_class: str | None = None) -> ExecutionState:
    """Only a transient error is retryable; every other class is PERMANENT."""
    st = parse_execution(state)
    if st is _E.PERMANENT_FAILURE and (error_class or "").strip().lower() == "transient":
        return _E.RETRYABLE_FAILURE
    return st


_EXECUTION_STORAGE = {_E.RUNNING: "sent", _E.RETRYABLE_FAILURE: "failed", _E.PERMANENT_FAILURE: "failed",
                      _E.RECONCILIATION_REQUIRED: "uncertain", _E.CANCELLED: "skipped"}


def storage_value(state: State) -> str:
    if isinstance(state, TaskState):
        return state.value
    return _EXECUTION_STORAGE.get(state, state.value)


def can(frm: State, to: State) -> bool:
    if type(frm) is not type(to):
        return False
    if frm is to:
        return True
    return to in ALLOWED_TRANSITIONS.get(frm, frozenset())


def transition(frm: State, to: State) -> State:
    if type(frm) is not type(to):
        raise IllegalTransition(frm, to, extra="States belong to different machines.")
    if not can(frm, to):
        raise IllegalTransition(frm, to)
    return to


def is_terminal(state: State) -> bool:
    return not ALLOWED_TRANSITIONS.get(state, frozenset())


def reachable(frm: State) -> set:
    seen: set = set(); queue = [frm]
    while queue:
        cur = queue.pop()
        for nxt in ALLOWED_TRANSITIONS.get(cur, frozenset()):
            if nxt not in seen:
                seen.add(nxt); queue.append(nxt)
    return seen


def advance_task(current, to) -> str:
    """`task.status = advance_task(task.status, TaskState.APPROVED)`"""
    return storage_value(transition(parse_task(current), parse_task(to)))


def advance_execution(current, to, *, error_class: str | None = None) -> str:
    frm = execution_state_from_operation(current, error_class) if isinstance(current, str) else current
    return storage_value(transition(frm, parse_execution(to)))


def invalidate_approval(current) -> TaskState:
    """Rule 1: editing an approved task revokes the approval — back to DRAFT."""
    state = parse_task(current)
    if state in LIVE_STATES:
        raise IllegalTransition(state, _T.DRAFT, extra="A task that is (or may be) executed is not edited — create a new one.")
    if state not in APPROVAL_BEARING:
        return state
    return transition(state, _T.DRAFT)


def rollup_outcome(*, total: int, done: int, failed: int, pending: int = 0, uncertain: int = 0) -> TaskState:
    """Rule 4 in arithmetic: DONE requires every part done, none failed/pending/uncertain."""
    if total <= 0 or pending > 0:
        return _T.APPROVED
    if uncertain > 0:
        return _T.PARTIALLY_DONE
    if failed == 0 and done >= total:
        return _T.DONE
    if done > 0 and failed > 0:
        return _T.PARTIALLY_DONE
    if failed > 0 and done == 0:
        return _T.FAILED
    return _T.APPROVED


def can_resume(current) -> bool:
    return _T.EXECUTING in ALLOWED_TRANSITIONS.get(parse_task(current), frozenset())


def _verify_invariants() -> None:
    for state, exits in ALLOWED_TRANSITIONS.items():
        for nxt in exits:
            if type(nxt) is not type(state):
                raise InvariantBroken(f"Cross-machine edge: {_name(state)} → {_name(nxt)}.")
            if nxt not in ALLOWED_TRANSITIONS:
                raise InvariantBroken(f"State '{_name(nxt)}' has no row.")
    for machine in (TaskState, ExecutionState):
        missing = [s for s in machine if s not in ALLOWED_TRANSITIONS]
        if missing:
            raise InvariantBroken("States without a row: " + ", ".join(_name(s) for s in missing))
    forbidden = reachable(_T.CANCELLED) & {_T.EXECUTING, _T.PARTIALLY_DONE, _T.DONE}
    if forbidden:
        raise InvariantBroken("A cancelled task can reach: " + ", ".join(sorted(_name(s) for s in forbidden)))
    for failure in FAILURE_STATES:
        if _E.SUCCEEDED in ALLOWED_TRANSITIONS.get(failure, frozenset()):
            raise InvariantBroken(f"'{_name(failure)}' leads directly to 'succeeded'.")
    if _T.DONE in ALLOWED_TRANSITIONS.get(_T.PARTIALLY_DONE, frozenset()):
        raise InvariantBroken("'partially_done' leads directly to 'done'.")
    into_done = sorted(_name(s) for s, exits in ALLOWED_TRANSITIONS.items() if _T.DONE in exits)
    if into_done != sorted([_name(_T.EXECUTING), _name(_T.COMPLETED_UNVERIFIED)]):
        raise InvariantBroken("'done' is entered from unexpected states: " + ", ".join(into_done))


_verify_invariants()
