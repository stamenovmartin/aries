"""What is true on this desktop right now, for the planner to read before it plans.

WHY THE PLANNER NEEDED THIS
---------------------------
Until 2026-10-03 the planner was told `home`, `demo_directory` and `now` — three
facts, none of them about the machine's current state. So "close it", "make that
fullscreen" or "turn it down" had nothing to resolve against, and a plan for
"split the screen" was made without knowing whether anything was open. The model was
being asked to act on a desktop it could not see.

EVERY FIELD CAN FAIL, AND SAYS SO
---------------------------------
The screen was locked while this was written, which is exactly the condition that
makes half of it unavailable: with the session locked `org.aries.Shell.Windows`
stops existing and the HDMI sink disappears with the monitor. A snapshot that
raised would take the planner down with it; one that silently returned `{}` would
tell the model "no windows are open", which is a different and worse lie than "I
could not look". So each section is either a reading or an `unavailable` string
naming the reason, and the planner sees which.

Nothing here mutates anything, and every probe is bounded in time: a planner call
that waits on a hung compositor is worse than one that plans without the snapshot.
"""
from __future__ import annotations

import time
from datetime import datetime

#: How long a whole snapshot may take before the missing parts are reported as
#: unavailable. The planner call behind it costs seconds; this must not.
BUDGET_SECONDS = 2.5


def _windows(deadline):
    """Open windows, focused first, from the shell extension's own observation."""
    if time.monotonic() > deadline:
        return {'unavailable': 'skipped: the snapshot budget was already spent'}
    try:
        from aries.operator.desktop import observe
        seen = observe()
    except Exception as exc:                                   # noqa: BLE001
        return {'unavailable': f'{type(exc).__name__}: {exc}'[:160]}
    if seen is None or getattr(seen, 'windows', None) is None:
        return {'unavailable': 'the shell extension returned no window list; the session may be locked'}
    windows = [{'title': w.title[:90], 'app': getattr(w, 'app', None) or getattr(w, 'wm_class', None),
                'focused': bool(getattr(w, 'focused', False)),
                'minimised': bool(getattr(w, 'minimised', False)),
                'monitor': getattr(w, 'monitor', None)}
               for w in seen.windows]
    windows.sort(key=lambda w: (not w['focused'], w['minimised']))
    focused = next((w for w in windows if w['focused']), None)
    return {'count': len(windows), 'focused': focused, 'windows': windows[:8]}


def _audio(deadline):
    """Output volume, mute, and whether anything is playing."""
    if time.monotonic() > deadline:
        return {'unavailable': 'skipped: the snapshot budget was already spent'}
    out = {}
    try:
        from aries.workspace import media
        reading = media.volume()
        if reading.get('ok'):
            out['volume'] = reading.get('volume')
            out['muted'] = reading.get('muted')
        else:
            out['unavailable'] = str(reading.get('detail'))[:160]
    except Exception as exc:                                   # noqa: BLE001
        out['unavailable'] = f'{type(exc).__name__}: {exc}'[:160]
    try:
        from aries.workspace import media
        players, why = media.players()
        if why:
            out['players_unavailable'] = why[:120]
        else:
            playing = [p for p in players if p.get('status') == 'Playing']
            out['players'] = [{'name': p['identity'] or p['name'], 'status': p['status']}
                              for p in players[:4]]
            out['playing'] = bool(playing)
    except Exception as exc:                                   # noqa: BLE001
        out['players_unavailable'] = f'{type(exc).__name__}: {exc}'[:120]
    return out


def recent_actions(data, limit=5):
    """The last few steps of THIS goal with what the verifier concluded.

    Not history for its own sake: the planner already receives step history. This is
    the shorter, verified-only view, so that "what have I actually achieved" does not
    have to be re-derived from eight raw step records on every call.
    """
    steps = (data or {}).get('steps') or []
    out = []
    for step in steps[-limit:]:
        verification = step.get('verification') or {}
        out.append({'capability': step.get('capability') or step.get('kind'),
                    'state': step.get('execution_status') or step.get('state'),
                    'verified': verification.get('met'),
                    'unverifiable': bool(verification.get('unverifiable')),
                    'error': (step.get('error') or {}).get('code') if isinstance(step.get('error'), dict)
                             else step.get('error')})
    return out


def snapshot(data=None, *, budget_seconds=BUDGET_SECONDS):
    """Everything the planner should know about now. Never raises."""
    started = time.monotonic()
    deadline = started + budget_seconds
    out = {
        'now': datetime.now().astimezone().isoformat(timespec='seconds'),
        'windows': _windows(deadline),
        'audio': _audio(deadline),
    }
    if data is not None:
        out['recent_verified_actions'] = recent_actions(data)
    out['snapshot_ms'] = round((time.monotonic() - started) * 1000)
    # Said plainly so the model does not read an absent section as an empty one.
    missing = [name for name, value in out.items()
               if isinstance(value, dict) and value.get('unavailable')]
    if missing:
        out['note'] = ('Could not read: ' + ', '.join(missing)
                       + '. Absent is not empty — do not conclude anything from a missing section.')
    return out
