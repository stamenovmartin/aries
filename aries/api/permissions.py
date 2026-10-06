"""What each ARIES route demands.

The engine's permission table (`security/permissions.py`) is a list of prefixes,
longest match wins, and it **fails closed**: a path it does not recognise falls
back to the method defaults, where any mutation needs `EDIT_TASK`. So ARIES's
routes are already safe without this module — but they would be safe by accident
and at the wrong permission. Registering them explicitly says what each actually
requires.

Importing this module appends ARIES's entries to that table. It is registration,
not modification: no engine file is edited, and the engine's own entries are
untouched.

The mapping, and the reasoning:

  /api/aries/settings      GET → VIEW_DATA, writes → MANAGE_TOOLS
        Changing a preference reconfigures how every agent and automation
        behaves. That is an operator's act, not an editor's.

  /api/aries/automations   GET → VIEW_DATA, writes → SCHEDULE
        Pausing or resuming an automation is scheduling. Note that the engine
        upgrades any path containing a `run` segment to EXECUTE, so
        POST /automations/{id}/run demands EXECUTE automatically — running work
        and scheduling it stay separate permissions, as the engine intends.

  /api/aries/worker        GET → VIEW_DATA, writes → EXECUTE
        Ticking the dispatcher runs whatever is due.
"""
from __future__ import annotations

from agentic_core.security.permissions import P, _POLICY

_ARIES_POLICY = [
    ("/api/aries/intelligence", {"GET": P.VIEW_DATA, "*": P.MANAGE_TOOLS}),
    ("/api/aries/workspace", {"GET": P.VIEW_DATA, "*": P.MANAGE_TOOLS}),
    ("/api/aries/workspace/memories", {"GET": P.VIEW_DATA, "*": P.EDIT_TASK}),
    ("/api/aries/settings", {"GET": P.VIEW_DATA, "*": P.MANAGE_TOOLS}),
    ("/api/aries/automations", {"GET": P.VIEW_DATA, "*": P.SCHEDULE}),
    ("/api/aries/worker", {"GET": P.VIEW_DATA, "*": P.EXECUTE}),
    ("/api/aries/analytics", {"GET": P.VIEW_DATA}),
    ("/api/aries/notifications", {"GET": P.VIEW_DATA}),
    ("/api/aries/health", {"GET": P.VIEW_DATA}),
    ("/api/aries/news", {"GET": P.VIEW_DATA, "*": P.EDIT_TASK}),
    ("/api/aries/learning", {"GET": P.VIEW_DATA, "*": P.EDIT_TASK}),
    ("/api/aries/learning/controls", {"GET": P.VIEW_DATA, "*": P.MANAGE_TOOLS}),
    ("/api/aries/brief", {"GET": P.VIEW_DATA, "*": P.EDIT_TASK}),
    ("/api/aries/home", {"GET": P.VIEW_DATA}),
    ("/api/aries/maintenance", {"GET": P.VIEW_DATA, "*": P.MANAGE_TOOLS}),
    ("/api/aries/runtime", {"GET": P.VIEW_DATA}),
    # Preventing the machine from sleeping is a change to how the computer
    # behaves, not a content edit — it sits with the other system controls.
    ("/api/aries/power", {"GET": P.VIEW_DATA, "*": P.MANAGE_TOOLS}),
    ("/api/aries/connections", {"GET": P.VIEW_DATA}),
    # The command bar resolves what the user meant; it changes nothing by
    # itself, so reading it is view_data. Carrying an action out goes through
    # /shell/act, which needs execute — the same permission a "Run now" button
    # needs, because it is the same act.
    ("/api/aries/command", {"GET": P.VIEW_DATA, "*": P.VIEW_DATA}),
    ("/api/aries/shell/act", {"*": P.EXECUTE}),
    ("/api/aries/shell", {"GET": P.VIEW_DATA, "*": P.MANAGE_TOOLS}),
    # Adding a source names somewhere ARIES will later GO. That is configuration
    # of the system's reach, not content editing, so it sits with settings at
    # manage_tools rather than the edit_task a POST would otherwise default to.
    ("/api/aries/sources", {"GET": P.VIEW_DATA, "*": P.MANAGE_TOOLS}),
    # The interest profile shapes what reaches the user, but names nowhere ARIES
    # will go — so editing it is configuration of preference, not of reach.
    ("/api/aries/interests", {"GET": P.VIEW_DATA, "*": P.EDIT_TASK}),
]

_registered = False


def install() -> None:
    """Append ARIES's route policy. Idempotent."""
    global _registered
    if _registered:
        return
    existing = {prefix for prefix, _ in _POLICY}
    for prefix, table in _ARIES_POLICY:
        if prefix not in existing:
            _POLICY.append((prefix, table))
    _registered = True


install()
