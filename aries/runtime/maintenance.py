"""Single-process update lease. New queued work waits; active work finishes.

Expires after four minutes if the updater disappears. Restart clears the lease.
This follows ARIES's existing single-core deployment constraint.
"""
import secrets
import time
_token = None
_deadline = 0.0

def active():
    return _token is not None and time.monotonic() < _deadline

def acquire():
    global _token, _deadline
    if active():
        raise ValueError('An update lease already exists')
    _token = secrets.token_hex(24)
    _deadline = time.monotonic() + 240
    return _token

def release(token):
    global _token, _deadline
    if not _token or not secrets.compare_digest(token,_token):
        raise ValueError('Invalid update lease')
    _token, _deadline = None, 0.0

def status():
    from aries.workspace import service
    from aries.automations import runner
    tasks = list(service._supervisors)
    automations = [key for key,lock in runner._locks.items() if lock.locked()]
    return {'active':active(),'expires_in_seconds':max(0,round(_deadline-time.monotonic())),
            'workspace_running':tasks,'automations_running':automations,
            'ready_to_restart':active() and not tasks and not automations,
            'scope':'Workspace queue and automation runner; existing single core process'}
