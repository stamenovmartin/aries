"""Plans that already worked, offered to the planner as examples.

WHY THIS READS HISTORY INSTEAD OF STORING PLANS
-----------------------------------------------
The build plan asks to "store successful plans with their goal text". They are
already stored: `aries_workspace_goals` holds 6,861 goals in state `done`, each with
its request and its steps. A second table would be a copy that can disagree with the
first, and the project has paid for a hand-maintained copy of derived truth before.
So this derives.

WHAT COUNTS AS AN EXAMPLE WORTH COPYING
---------------------------------------
Not "the goal ended done". A goal can end `done` with steps nothing ever verified —
of 425 steps that look successful, 89 were never independently checked. Copying one
of those teaches the planner a route whose effect was never observed. So an example
must have at least one step the verifier confirmed, and the unverified steps are
dropped from the example rather than shown as if they had worked.

WHY LEXICAL RANKING
-------------------
Same argument as the capability selector in `agent_planner.relevant()`: deterministic,
auditable, free, and this project measured that its focused retrieval did not beat
store-everything under paired statistics. A SQL prefilter on the most distinctive word
keeps the candidate set small so a planning call does not read 6,861 rows.

WHAT THIS CANNOT DO
-------------------
It cannot tell a good plan from a lucky one. A route that worked once on a machine in
one state is evidence, not instruction, and the examples are labelled as such. If
few-shot examples make the planner worse, `ARIES_TRACE_FEWSHOT` is how that gets
measured rather than argued.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import text

#: Candidate rows pulled before ranking. Large enough that a common verb still finds
#: specific matches, small enough that planning does not wait on the database.
CANDIDATES = 120
SUCCEEDED = ('done', 'answered')

#: Request texts that describe the MECHANISM rather than the goal. 'Plan and execute a
#: goal using observed results' is the registry description of `agent_task`, and it is
#: the stored request text for most planner-path goals — so matching against it matches
#: noise. Measured 2026-10-03: asked for "read a text file and report what it contains",
#: ranking over these returned examples about disk usage and a browser session, because
#: the shared words were "report" and "and".
UNINFORMATIVE = ('plan and execute a goal using observed results',)
_STOP = frozenset('the a an my me it this that to of in on for and or is are be do does '
                  'open show tell give make let get go please now then there here with at'.split())


def _words(value):
    return [w for w in re.findall(r"[^\W\d_]+", str(value).casefold())
            if len(w) > 2 and w not in _STOP]


def _distinctive(words):
    """The longest word, as the cheapest proxy for the most selective one."""
    return max(words, key=len) if words else ''


def _plan_of(blob):
    """The verified spine of a finished goal: capability names and the arguments
    that identify them, with unverified steps dropped rather than shown."""
    try:
        data = json.loads(blob) or {}
    except (TypeError, ValueError):
        return []
    plan = []
    for step in (data.get('steps') or []):
        verification = step.get('verification') or {}
        if verification.get('met') is not True:
            continue
        name = step.get('capability') or step.get('kind')
        if not name:
            continue
        args = step.get('args') or {}
        # Keep the shape of the arguments, not the person's data: a path or a URL from
        # an old goal is not relevant to a new one and may be private.
        plan.append({'capability': name, 'arguments': sorted(args)[:6]})
    return plan


async def successes(db, goal, *, limit=3, allowed=None):
    """Up to `limit` past goals that resemble this one and verifiably worked.

    `allowed` is the set of capability names the planner may actually call. It is not
    optional in spirit: ARIES has two capability surfaces — the spoken catalogue and
    the planner registry — and they are not the same set. Asked for "turn the volume
    down" this returned the past goal `volume 45 -> set_volume`, a SPOKEN capability
    with no planner tool behind it, which would have taught the planner to call
    something it does not have.
    """
    words = _words(goal)
    if not words:
        return []
    if allowed is None:
        from aries.workspace.registry import registry
        allowed = {cap['name'] for cap in registry.describe_allowed()}
    rows = []
    # The longest word is the cheapest proxy for the most selective one; if it finds
    # too little, the next longest gets a turn before giving up.
    for word in sorted(set(words), key=len, reverse=True)[:2]:
        rows += (await db.execute(text(
            "SELECT request, result_json FROM aries_workspace_goals "
            "WHERE state IN ('done','answered') AND request LIKE :like "
            "ORDER BY created_at DESC LIMIT :n"),
            {'like': f'%{word}%', 'n': CANDIDATES})).all()
        if len(rows) >= CANDIDATES:
            break
    wanted = set(words)
    scored = []
    for request, blob in rows:
        plan = _plan_of(blob)
        if not plan:
            continue                       # nothing in it was ever verified
        if any(step['capability'] not in allowed for step in plan):
            continue                       # it used a surface the planner cannot reach
        if str(request).strip().casefold().startswith(UNINFORMATIVE):
            continue                       # the stored text describes the mechanism, not the goal
        overlap = len(wanted & set(_words(request)))
        if overlap:
            scored.append((overlap, len(plan), request, plan))
    # Most similar first; among equals prefer the SHORTER plan, because a short
    # verified route is a better example than a long one that wandered.
    scored.sort(key=lambda row: (-row[0], row[1]))
    seen, out = set(), []
    for _, _, request, plan in scored:
        spine = tuple(step['capability'] for step in plan)
        if spine in seen:
            continue                       # three copies of one route teach nothing
        seen.add(spine)
        out.append({'goal': request[:160], 'verified_steps': plan})
        if len(out) >= limit:
            break
    return out


async def failures(db, *, days=7, limit=200):
    """Goals that did not succeed, for the weekly review queue."""
    rows = (await db.execute(text(
        "SELECT id, request, state, created_at, result_json FROM aries_workspace_goals "
        "WHERE state IN ('failed','partial') "
        "AND created_at >= datetime('now', :window) "
        "ORDER BY created_at DESC LIMIT :n"), {'window': f'-{int(days)} days', 'n': limit})).all()
    out = []
    for goal_id, request, state, created_at, blob in rows:
        try:
            data = json.loads(blob) or {}
        except (TypeError, ValueError):
            data = {}
        steps = data.get('steps') or []
        codes = []
        for step in steps:
            error = step.get('error')
            code = error.get('code') if isinstance(error, dict) else None
            if code:
                codes.append(code)
        out.append({'id': goal_id, 'request': request, 'state': state,
                    'created_at': str(created_at), 'steps': len(steps),
                    'error_codes': codes,
                    'last_summary': str(data.get('summary') or '')[:200]})
    return out
