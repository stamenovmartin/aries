"""Runner side of the H5 file-change hook (changed_after_read controls).

The instance runs with ARIES_MEASURE_CHANGE_HOOK=1. For each changed_after_read control the runner:

1. arms the goal **before** submitting it: `hook.arm(goal_text)` writes `<key>.watch`;
2. starts `hook.serve(goal_text, apply, wait_seconds)` in a thread while it waits for the goal;
3. the instance writes `<key>.paused` at the first finish proposed after a step was verified, before the
   contract or any evidence is checked; `serve` then calls `apply()`, which runs the item's `change_after_read.command` and writes
   `"$M/$ID.manifest.after"`, and then writes `<key>.released`;
4. after the goal ends, `hook.finish(goal_text)` returns the record and removes the handshake files.

If the goal never reaches a checked finish, nothing is changed, and `apply_unfired()` writes
`manifest.after` as a copy of the setup manifest, so the sandbox check still asks whether ARIES itself
changed anything. The record says `fired: false`, and that is reported per item.

See aries/workspace/measurement_hook.py for the instance side and the file protocol.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path

POLL_SECONDS = 0.1


def key(goal_text: str) -> str:
    return hashlib.sha256(goal_text.encode('utf-8')).hexdigest()


def file_sha(path: Path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class ChangeHook:
    def __init__(self, folder, timeout_seconds=60):
        self.folder = Path(folder)
        self.timeout = timeout_seconds
        self.records = {}
        self.stops = {}

    def paths(self, goal_text):
        k = key(goal_text)
        return {s: self.folder / f'{k}.{s}' for s in ('watch', 'paused', 'released')}

    def arm(self, goal_text):
        p = self.paths(goal_text)
        self.folder.mkdir(parents=True, exist_ok=True)
        stale = [s for s, path in p.items() if path.exists()]
        if stale:
            raise RuntimeError(f'hook files already exist for this goal: {stale}')
        p['watch'].write_text(json.dumps({'timeout_seconds': self.timeout}))
        self.records[key(goal_text)] = {'key': key(goal_text), 'armed_at': time.time(), 'fired': False}
        self.stops[key(goal_text)] = threading.Event()
        return key(goal_text)

    def serve(self, goal_text, apply, wait_seconds):
        """Block until the instance pauses (or wait_seconds pass); apply the change; release it."""
        p, rec, stop = self.paths(goal_text), self.records[key(goal_text)], self.stops[key(goal_text)]
        deadline = time.monotonic() + wait_seconds
        while not p['paused'].exists() and time.monotonic() < deadline and not stop.is_set():
            time.sleep(POLL_SECONDS)
        if not p['paused'].exists():
            return rec
        rec.update(fired=True, paused=json.loads(p['paused'].read_text()), change_started_at=time.time())
        try:
            rec['change'] = apply()
        finally:
            p['released'].write_text(json.dumps({'at': time.time()}))
            rec['released_at'] = time.time()
        return rec

    def start(self, goal_text, apply, wait_seconds):
        thread = threading.Thread(target=self.serve, args=(goal_text, apply, wait_seconds), daemon=True)
        thread.start()
        return thread

    def finish(self, goal_text, thread=None):
        """Called after the goal ended: stop serving, then remove the handshake files."""
        p = self.paths(goal_text)
        p['watch'].unlink(missing_ok=True)          # a goal that already ended cannot pause any more
        self.stops.pop(key(goal_text)).set()
        if thread is not None:
            thread.join(timeout=self.timeout + 5)
        for path in p.values():
            path.unlink(missing_ok=True)
        return self.records.pop(key(goal_text))


def shell_apply(sh, preamble, item, case_dir, sandbox):
    """The apply() for one item: its change command, then the manifest after the change."""
    target = Path(case_dir) / item['change_after_read']['file']

    def apply():
        before = file_sha(target)
        code, _, err = sh(preamble + '\n' + item['change_after_read']['command']
                          + '\nMANIFEST "$C" > "$M/$ID.manifest.after"', str(sandbox))
        return {'file': item['change_after_read']['file'], 'sha256_before': before, 'sha256_after': file_sha(target),
                'exit': code, 'stderr': err[-300:] if code else ''}
    return apply


def apply_unfired(manifest_dir, item_id):
    """No checked finish happened: the runner changed nothing, so 'after' equals the setup manifest."""
    m = Path(manifest_dir)
    shutil.copyfile(m / f'{item_id}.manifest', m / f'{item_id}.manifest.after')
    os.chmod(m / f'{item_id}.manifest.after', 0o600)
