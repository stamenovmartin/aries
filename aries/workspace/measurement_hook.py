"""Measurement hook: pause before a finish is checked, so a runner can change a file in between (H5).

H5 (docs/preregistration/H5-completion-paraphrase.md, Materials 2) has controls in which the file changes
after ARIES has read it and before the finish is checked. ARIES runs as its own server process, so the
runner cannot reach that moment from outside. With ARIES_MEASURE_CHANGE_HOOK on, completion() calls
pause() first, before it looks at the contract or the evidence, so the change happens at the same moment in
both H5 conditions: the first finish proposed after at least one step was verified.

The handshake goes through files in <DATA_DIR>/measure-hook/, keyed by the SHA-256 of the goal text, so the
runner arms a goal before submitting it and there is no race with the task id:

    <key>.watch     written by the runner: {"timeout_seconds": n}
    <key>.paused    written here, once per watched goal: {"task_id", "at", "verified_steps"}
    <key>.released  written by the runner after its change; the finish check then proceeds

An unwatched goal, or a goal already paused once, returns at once. If no release comes within the timeout,
the check proceeds and the record says so. The model is never told, and nothing here decides completion.
Off, completion() never imports this module.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

POLL_SECONDS = 0.1
DEFAULT_TIMEOUT = 60.0


def hook_dir() -> Path:
    from agentic_core.config.settings import settings
    return Path(settings.data_dir) / 'measure-hook'


def key(goal_text: str) -> str:
    return hashlib.sha256(goal_text.encode('utf-8')).hexdigest()


def _write_once(path: Path, payload: dict) -> bool:
    """Create the file atomically; False if it already exists."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'w') as f:
        json.dump(payload, f)
    return True


async def pause(task_id, goal_text, data) -> dict | None:
    """Wait for the runner when this goal is watched; record what happened in the goal's agent data."""
    folder = hook_dir()
    k = key(goal_text)
    watch = folder / f'{k}.watch'
    if not watch.exists():
        return None
    verified = [{'step_id': s.get('step_id'), 'capability': s.get('capability')}
                for s in data.get('steps', []) if s.get('verification_status') == 'verified']
    if not verified:
        return None                                 # nothing has been read yet; wait for a later finish
    at = datetime.now(timezone.utc).isoformat()
    if not _write_once(folder / f'{k}.paused', {'task_id': task_id, 'at': at, 'verified_steps': verified}):
        return None
    try:
        timeout = float(json.loads(watch.read_text()).get('timeout_seconds', DEFAULT_TIMEOUT))
    except (OSError, ValueError, AttributeError):
        timeout = DEFAULT_TIMEOUT
    released = folder / f'{k}.released'
    deadline = time.monotonic() + timeout
    while not released.exists() and time.monotonic() < deadline:
        await asyncio.sleep(POLL_SECONDS)
    record = {'key': k, 'paused_at': at, 'verified_steps': verified, 'released': released.exists(),
              'resumed_at': datetime.now(timezone.utc).isoformat()}
    data.setdefault('agent', {})['measurement_hook'] = record
    return record
