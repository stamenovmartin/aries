"""ARIES_LOOP_GUARD: stop a goal whose planner keeps proposing the same action.

docs/AUDIT.md section 4b. The executor already rejects a repeated mutation, a
repeated verified action and a repeated non-retryable one as a duplicate, but the
rejected step still uses a step of the budget and the planner is simply asked
again; in the held-out run 138 of 242 steps were such rejections. This module only
counts. The fingerprint of a proposal is its capability plus the canonical JSON of
its arguments; when a proposal would be the SECOND duplicate of a fingerprint in
one goal (the third proposal of it), `repeated` returns the record the agent stores
before it ends the goal with stop_reason REPEATED_ACTION. Read by agent.py only
when the flag is on.
"""
from __future__ import annotations

import hashlib
import json

#: Proposals of one fingerprint allowed in a goal: the original and one duplicate.
ALLOWED = 2


def canonical(arguments) -> str:
    return json.dumps(arguments or {}, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


def fingerprint(capability, arguments) -> str:
    return hashlib.sha256(f'{capability}\n{canonical(arguments)}'.encode()).hexdigest()[:16]


def repeated(steps, capability, arguments):
    """The record for a proposal that is the second duplicate of its fingerprint, else None."""
    mark = fingerprint(capability, arguments)
    earlier = [s for s in steps if fingerprint(s.get('capability'), s.get('args')) == mark]
    count = len(earlier) + 1
    if count <= ALLOWED:
        return None
    return {'fingerprint': mark, 'capability': capability, 'arguments': arguments,
            'count': count, 'duplicates': count - 1, 'step_ids': [s.get('step_id') for s in earlier]}
