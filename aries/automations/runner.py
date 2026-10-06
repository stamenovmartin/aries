"""Running an automation — the ONE path the worker, the API and the CLI all take.

The engine's rule, inherited: "the chat calls the same handler the dashboard
button does". If a scheduled run and a "Run now" button take different routes,
they drift, and the one that runs unattended at 03:00 is the one nobody tested.
So `run_automation` is the only way an automation ever runs, and the three
callers differ only in the `trigger` string they pass.

Through the task lifecycle, not around it
-----------------------------------------
An automation with a `task_kind` is not simply called. A Task is created and
handed to `run_task_now`, so the run inherits everything the engine already
guarantees: a durable record, an evaluation, the retry/replan/escalate decision,
an ActionProposal when a human is needed, a correlation id, an audit trail. An
automation that bypassed the lifecycle would have to reimplement all of it, worse.

An automation without a `task_kind` is called directly — the escape hatch for
work that is pure bookkeeping and has nothing to evaluate.

Resource policy
---------------
Between "is it enabled?" and "is it broken?" sits a third question Entry 013
added: *may the machine do this kind of work right now?* It is asked here, in
the one run path, for the same reason everything else is — a heavy job started
from the Control Centre must meet the same temperature limit as one started by
the dispatcher at 3 a.m., and a check that lived in the worker would not be
asked of either the API or the CLI.

Lightweight work answers instantly and measures nothing, so the check costs
nothing for every automation that exists today.

Overlap
-------
A pass that takes longer than its interval must not be started twice. Each
automation has an in-process lock and a second attempt is REFUSED, not queued:
queueing would let a slow automation accumulate a backlog it can never work off,
and for a periodic measurement the next scheduled pass is a better answer than a
stale queued one. The refusal is recorded as a `skipped` run so it is visible
rather than silent.
"""
from __future__ import annotations

import asyncio
import logging
import time

from agentic_core.database.base import async_session

from aries.automations.breaker import check as breaker_check
from aries.automations.genome import AutomationSpec, due, get, is_enabled, record_run
from aries.power import governor
from aries.settings import SettingsService

logger = logging.getLogger(__name__)

_locks: dict[str, asyncio.Lock] = {}


def _lock(automation_id: str) -> asyncio.Lock:
    lock = _locks.get(automation_id)
    if lock is None:
        lock = _locks[automation_id] = asyncio.Lock()
    return lock


def is_running(automation_id: str) -> bool:
    lock = _locks.get(automation_id)
    return bool(lock and lock.locked())


async def run_automation(spec: AutomationSpec | str, *, trigger: str = "manual",
                         force: bool = False) -> dict:
    """Run one automation once.

    `force` skips the enabled check — what "Run now" in the Control Centre does,
    so an operator can test a disabled automation without enabling it. It does
    NOT skip the overlap lock: two concurrent passes are always wrong.
    """
    if isinstance(spec, str):
        found = get(spec)
        if found is None:
            return {"ran": False, "reason": "unknown automation", "automation_id": spec}
        spec = found

    if not force:
        async with async_session() as db:
            if not await is_enabled(spec, SettingsService(db)):
                return {"ran": False, "reason": "disabled", "automation_id": spec.automation_id}

    # May the machine do this kind of work at all right now? Before the breaker
    # and before the lock, because this is the cheapest question and the one that
    # is about the machine rather than about the automation. `force` carries the
    # permission half of it — a person pressing "Run now" is the explicit consent
    # the policy asks for — but not the thermal half.
    async with async_session() as db:
        verdict = await governor.may_run(db, spec, force=force)
        await db.commit()
    if not verdict.allowed:
        async with async_session() as db:
            await record_run(db, spec, status="skipped",
                             summary=f"resource policy: {verdict.reason}"[:500],
                             detail={"resource_policy": verdict.as_dict()}, trigger=trigger)
            await db.commit()
        return {"ran": False, "reason": f"resource_policy:{verdict.code}",
                "automation_id": spec.automation_id, "resource_policy": verdict.as_dict()}

    # A failing automation is paused rather than retried forever (Entry 004's
    # debt). `force` does NOT bypass this: "Run now" on a broken automation
    # should tell the operator it is broken, not queue another failure. The
    # half-open state means it heals by itself when the world does.
    async with async_session() as db:
        breaker = await breaker_check(db, spec.automation_id)
    if not breaker.allows_run:
        async with async_session() as db:
            await record_run(db, spec, status="skipped",
                             summary=f"circuit breaker open: {breaker.consecutive_failures} "
                                     f"consecutive failures", trigger=trigger)
            await db.commit()
        return {"ran": False, "reason": "circuit_breaker_open",
                "automation_id": spec.automation_id, "breaker": breaker.as_dict()}

    lock = _lock(spec.automation_id)
    if lock.locked():
        async with async_session() as db:
            await record_run(db, spec, status="skipped",
                             summary="a previous pass was still running", trigger=trigger)
            await db.commit()
        return {"ran": False, "reason": "already running", "automation_id": spec.automation_id}

    async with lock:
        from aries.runtime import maintenance
        if maintenance.active():
            return {"ran":False,"reason":"maintenance","automation_id":spec.automation_id}
        t0 = time.monotonic()
        governor.note_start(spec)
        try:
            if spec.task_kind:
                return await _run_through_lifecycle(spec, trigger)
            return await _run_directly(spec, trigger)
        except Exception as e:                      # noqa: BLE001
            logger.exception("Automation %s raised", spec.automation_id)
            async with async_session() as db:
                await record_run(db, spec, status="failed", summary=f"{type(e).__name__}: {e}",
                                 duration_ms=int((time.monotonic() - t0) * 1000), trigger=trigger)
                await db.commit()
            return {"ran": True, "automation_id": spec.automation_id, "status": "failed",
                    "error": f"{type(e).__name__}: {e}"}
        finally:
            # In `finally` rather than after the call: a heavy job that raises
            # must not stay in the budget register for the lifetime of the
            # process, quietly holding a hold open against its own next run.
            governor.note_finish(spec.automation_id)


async def _run_through_lifecycle(spec: AutomationSpec, trigger: str) -> dict:
    from agentic_core.orchestrator.service import create_task
    from agentic_core.scheduler.queue import run_task_now

    async with async_session() as db:
        task = await create_task(db, kind=spec.task_kind, title=spec.name, brief=spec.purpose,
                                 input={"automation_id": spec.automation_id, "trigger": trigger},
                                 created_by=f"automation:{spec.automation_id}")
        task_id = task.id

    t0 = time.monotonic()
    try:
        out = await run_task_now(task_id, trigger=trigger)
    finally:
        # The task is over, whatever happened to it. Whatever it pulled in to do
        # its work goes now — the same reason a browser frees a page when the tab
        # closes, and for the same three outcomes: success, failure, escalation.
        # In `finally` because failure is when releasing matters most: a pass
        # that died halfway is exactly the one holding borrowed mail bodies.
        await _release_working_set(task_id)
    outcome = out.get("outcome") or {}
    result = outcome.get("result") or {}

    # Recorded HERE, for every automation that runs through a task kind, rather
    # than inside each automation's body.
    #
    # The News Radar originally recorded nothing, because it runs as a workflow
    # and there was no line in it that called `record_run`. The consequences were
    # not cosmetic: the Control Centre said "last run: never" after a successful
    # pass, `health()` had no data, and — worst — the circuit breaker reads that
    # table, so the one automation that talks to a network had no breaker at all.
    # Putting it in the single run path means a future automation cannot forget.
    #
    # A body that knows better may say so: `result["status"]` wins when present
    # (System Health uses it to report `degraded` when a probe could not run).
    status = result.get("status") or ("ok" if outcome.get("verdict") == "pass" else "failed")
    async with async_session() as db:
        await record_run(db, spec, status=status,
                         summary=str(result.get("summary") or outcome.get("verdict") or "")[:500],
                         # Health findings are kept: they exist nowhere else, and
                         # /api/aries/health/latest reads them. The news lists are
                         # dropped because every item has its own row in
                         # aries_news_items — duplicating them here would bloat
                         # every run row for no gain.
                         detail={k: v for k, v in result.items()
                                 if k not in ("delivered", "held")},
                         task_id=task_id, duration_ms=int((time.monotonic() - t0) * 1000),
                         trigger=trigger)
        await db.commit()

    return {"ran": True, "automation_id": spec.automation_id, "task_id": task_id,
            "verdict": outcome.get("verdict"), "status": status,
            "severity": result.get("severity"), "summary": result.get("summary"),
            "proposal_id": outcome.get("proposal_id"), "requires_approval": result.get("requires_approval"),
            "trigger": trigger}


async def _release_working_set(task_id) -> None:
    """Close the tab. Never allowed to turn a finished run into a failed one."""
    from aries.lifecycle import working
    try:
        async with async_session() as db:
            released = await working.release(db, task_id)
            await db.commit()
        if released:
            logger.debug("released %d working-set row(s) for task %s", released, task_id)
    except Exception:                               # noqa: BLE001
        # A cleanup that raises must not mask the outcome of the work itself.
        # The sweep collects what this misses, which is what the sweep is for.
        logger.exception("could not release the working set for task %s", task_id)


async def _run_directly(spec: AutomationSpec, trigger: str) -> dict:
    t0 = time.monotonic()
    from aries.automations.genome import last_run
    async with async_session() as db:
        before = await last_run(db, spec.automation_id)
        before_id = before.id if before else None
        out = await spec.run({"db": db, "trigger": trigger}) or {}
        after = await last_run(db, spec.automation_id)
        # Older bookkeeping automations may record their own run. Fill the gap
        # only when they did not, otherwise history and pacing double-count.
        if (after.id if after else None) == before_id:
            await record_run(db, spec, status=out.get('status') or ('failed' if out.get('success') is False else 'ok'),
                             summary=str(out.get('summary') or 'Completed bookkeeping pass'), detail=out,
                             duration_ms=int((time.monotonic() - t0) * 1000), trigger=trigger)
        await db.commit()
    return {"ran": True, "automation_id": spec.automation_id, "trigger": trigger,
            "duration_ms": int((time.monotonic() - t0) * 1000), **out}


async def run_due(*, trigger: str = "schedule") -> dict:
    """One dispatcher pass: run every automation whose interval has elapsed.

    This is the worker's body. It decides nothing about WHEN beyond asking each
    automation's own `due()`, which is paced by that automation's last recorded
    run — so a machine that was asleep catches up rather than skipping.
    """
    from aries.automations.genome import all_automations

    ran, skipped = [], []
    async with async_session() as db:
        settings = SettingsService(db)
        checks = [(spec, *await due(db, spec, settings)) for spec in all_automations()]

    for spec, ok, why in checks:
        if not ok:
            skipped.append({"automation_id": spec.automation_id, "why": why})
            continue
        out = await run_automation(spec, trigger=trigger)
        (ran if out.get("ran") else skipped).append(
            {"automation_id": spec.automation_id, **{k: v for k, v in out.items() if k != "automation_id"}})
    return {"ran": len(ran), "skipped": len(skipped), "runs": ran, "skips": skipped}
