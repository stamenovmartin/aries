"""Verification coverage as an invariant, not a dashboard reading.

`aries.analytics.verification_honesty` measures how much of what ARIES calls
success was independently checked. Measured on the live database on 2026-09-30 it
was 34 of 215 apparently-successful steps, and 32 of those 34 came from a verifier
that returns `met: True` on every code path. Two different problems, and this file
locks in the two invariants that stop either of them growing back quietly:

  1. A CAPABILITY MAY NOT BE ADDED WITHOUT A DECISION ABOUT ITS VERIFICATION.
     Every entry in `capabilities.CATALOGUE` is listed below as verified or as
     unverified-with-a-reason. A new capability fails this file until it is
     placed in one of the two sets. That is the point: the 89% gap grew because
     capabilities could be added to the spoken surface without anyone deciding.

  2. A VERIFIER THAT CANNOT RETURN FALSE IS A DELIBERATE CHOICE, NOT A DEFAULT.
     `verify_probe`, `verify_observe`, `verify_tabs`, `verify_read_brightness` and
     `verify_targets` prove the subject is still observable, not that the executor
     was right. They are legitimate for a read of a live tree and the code says so
     — but they carried 32 of 34 `verified` steps, so the set of them is frozen
     here by name. A new one fails until it is added on purpose.

Nothing here touches the live database. The harness gives each test process its
own sqlite file.
"""
from __future__ import annotations

import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-verification-coverage")

from sqlalchemy import text                                          # noqa: E402
from agentic_core.database.base import async_session                 # noqa: E402

from aries import analytics                                          # noqa: E402
from aries.analytics.core import Window                              # noqa: E402
from aries.workspace import capabilities                             # noqa: E402
from aries.workspace.registry import registry                        # noqa: E402

# Spoken capabilities that attach a `verification` on their success path, read
# from the source of `capabilities.execute()` on 2026-09-30.
VERIFIED_SPOKEN = {
    'read_file', 'list_folder', 'package_info', 'services', 'disk', 'open_app', 'open_url', 'search_web', 'refresh_news', 'brief', 'health',
    "abilities", "browser_close", "browser_fill", "browser_follow", "browser_open",
    "build_python", "clipboard_read", "clipboard_write", "create_file", "create_folder",
    "install_app", "media_control", "move_file", "open_path", "play_music",
    "python_project", "read_screen", "say", "screenshot", "service_control",
    "set_brightness", "set_volume", "trash_file", "type_text", "ui_action",
    "wifi_connect",
}

# The gap, with the reason each one is in it. A reason is required so that
# "nobody got round to it" cannot hide among the genuine cases.
UNVERIFIED_SPOKEN = {
    "research": "no verifier on any path; 144 of 288 steps in the last week. See "
                "experiments/verification/analysis.md",
    "system": "system.status in the registry verifies the same probes; the spoken path does not call it",
    "find_files": "needs a match-set re-read; file.search's verifier is unconditional",
    "processes": "needs a PID-identity re-read; system.processes' verifier is unconditional",
    "list_apps": "no verifier anywhere, and no registry twin",
    "brightness": "display.brightness exists; its verifier is unconditional anyway",
    "network_status": "network.status exists and is not called",
    "wifi_list": "network.wifi_list exists and is not called",
    "editable_fields": "input.editable_targets exists; its verifier is unconditional",
    "browser_inspect": "browser.observe exists and is not called",
    "agent_task": "the M14 agent verifies every inner step; the outer step is left blank",
    "read_article": "a local-model summary of one fetched page; provenance is checkable, truth is not",
    "remember": "a row was written; re-reading it verifies the write, not the fact",
    "can_you": "an answer about ARIES itself, produced by running the real parser",
    "evaluation": "reports other steps' outcomes; verifying it verifies the report, not the work",
    "learning_eval": "compares retrieval variants; verifying it verifies the comparison",
    "inspect_app": "an AT-SPI snapshot of a live tree; a re-read cannot contradict it",
}

# Verifiers whose every `met` is the literal True. Frozen on purpose — see the
# module docstring.
UNCONDITIONAL = {
    "browser.tabs", "desktop.observe", "desktop.windows", "display.brightness",
    "file.list", "file.search", "input.editable_targets", "system.processes",
    "system.status", "system.storage", "task.inspect",
}

MET = re.compile(r"""(?:['"]met['"]\s*:|\bmet=)\s*(.+?)\s*[,})]""")


def _unconditional(cap) -> bool:
    """Every `met` this verifier returns is the literal True."""
    try:
        values = {m.group(1).strip() for m in MET.finditer(inspect.getsource(cap.verifier))}
    except (OSError, TypeError):
        return False
    return bool(values) and values == {"True"}


def test_every_registered_capability_has_a_verifier():
    """Structural, and it holds because `Capability.verifier` is a required field."""
    missing = [n for n, c in registry._items.items() if c.verifier is None]
    check("no registered capability is missing a verifier", missing == [])
    check("and there are capabilities to check", len(registry._items) > 40)


def test_a_verifier_with_no_failure_mode_is_declared():
    found = {n for n, c in registry._items.items() if _unconditional(c)}
    new = sorted(found - UNCONDITIONAL)
    gone = sorted(UNCONDITIONAL - found)
    check("no undeclared verifier that cannot return met=False: " + str(new), not new)
    check("the declared list has no stale entries: " + str(gone), not gone)
    # The ratio is the thing that misleads a dashboard, so state it out loud.
    print(f"      {len(found)} of {len(registry._items)} verifiers have no failure mode")


def test_every_spoken_capability_has_a_verification_decision():
    names = {k for k, _t, _e in capabilities.CATALOGUE}
    decided = VERIFIED_SPOKEN | set(UNVERIFIED_SPOKEN)
    check("every catalogue capability is declared verified or unverified-with-a-reason: "
          + str(sorted(names - decided)), names <= decided)
    check("and nothing is declared that is no longer in the catalogue: "
          + str(sorted(decided - names)), decided <= names)
    check("the two sets do not overlap",
          not (VERIFIED_SPOKEN & set(UNVERIFIED_SPOKEN)))
    check("every unverified capability carries a reason",
          all(len(v) > 20 for v in UNVERIFIED_SPOKEN.values()))
    print(f"      {len(VERIFIED_SPOKEN)} of {len(names)} spoken capabilities attach a verification")


def test_research_never_reaches_the_capability_executor():
    """The routing that produces the largest share of the gap, asserted.

    `validate_action` stamps `kind: 'research'` and `service.py` handles those
    steps in a loop of its own, so `execute()` has no branch for it. If that ever
    changes, this file should change with it — deliberately.
    """
    action, _request = capabilities.validate_action("research", {"query": "ai"})
    check("a research action is routed by kind, not as a capability step",
          action["kind"] == "research" and action["capability"] == "research")
    src = inspect.getsource(capabilities.execute)
    check("and execute() has no research branch", '"research"' not in src
          and "'research'" not in src)


async def test_a_nested_verification_is_invisible_to_the_bucket():
    """The bug, in the shape the live rows have it.

    A step whose verdict sits in `result.verification` is bucketed `accepted` —
    "nothing checked it" — because `analytics.core.STEP_BUCKET` reads only the
    step's own `verification_status`. Three `open_url` steps on the live database
    are in exactly this state.
    """
    import json
    await reset_db()
    async with async_session() as db:
        async def goal(gid, steps):
            await db.execute(text(
                "INSERT INTO aries_workspace_goals (id, request, state, created_at,"
                " updated_at, result_json) VALUES (:id, :r, 'done', datetime('now','-1 hours'),"
                " datetime('now','-1 hours'), :j)"),
                {"id": gid, "r": gid, "j": json.dumps({"steps": steps})})

        await goal("nested", [{"kind": "capability", "capability": "open_url", "state": "done",
                               "result": {"state": "done",
                                          "verification": {"met": True, "evidence": "DOM"}}}])
        await goal("operator", [{"kind": "capability", "capability": "play_music", "state": "done",
                                 "result": {"state": "done",
                                            "operator": {"verified_success": True,
                                                         "honesty_gap": False}}}])
        await goal("lifted", [{"kind": "capability", "capability": "open_url", "state": "done",
                               "verification_status": "verified",
                               "result": {"state": "done",
                                          "verification": {"met": True, "evidence": "DOM"}}}])
        await db.commit()

        h = await analytics.verification_honesty(db, Window(days=7))
        b = h["buckets"]
        check("a verdict nested in result.verification is counted as unverified",
              b.get("accepted") == 2)
        check("only the lifted verdict is counted as verified", b.get("verified") == 1)
        check("so coverage is 1 of 3 while 3 of 3 were actually checked",
              h["coverage"]["successes"] == 1 and h["coverage"]["trials"] == 3)

        verdict = getattr(capabilities, "verdict", None)
        if verdict is None:
            print("SKIP  capabilities.verdict() is not applied yet — see "
                  "experiments/verification/analysis.md, patch P1")
            return
        check("verdict() lifts a nested affirmative verification",
              verdict({"verification": {"met": True}}) == "verified")
        check("verdict() lifts the operator's verified_success",
              verdict({"operator": {"verified_success": True}}) == "verified")
        check("verdict() calls the operator's honesty_gap a contradiction",
              verdict({"operator": {"honesty_gap": True}}) == "verification_failed")
        check("verdict() does NOT turn a met=False into a contradiction: a branch that "
              "called itself unconfirmed meant it",
              verdict({"verification": {"met": False}}) is None)
        check("verdict() says None when nothing checked anything",
              verdict({"state": "done"}) is None)


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
