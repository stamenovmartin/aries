"""Task attribution propagated through router/planner calls and child coroutines."""
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar('aries_inference_context', default=None)


def current():
    return dict(_current.get() or {})


@contextmanager
def task_context(task_id, *, root_id=None, agent_id=None, budgeted=False):
    token = _current.set({'task_id': task_id, 'root_id': root_id or task_id,
                          'agent_id': agent_id or task_id,'budgeted':budgeted})
    try:
        yield
    finally:
        _current.reset(token)
