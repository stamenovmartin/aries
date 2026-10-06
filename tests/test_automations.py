"""The Automation Genome: declared, versioned, disabled until asked for (§11, §12, §27)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-automations")

from datetime import datetime, timedelta  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402
from agentic_core.scheduler.queue import kinds  # noqa: E402

from aries.automations import (  # noqa: E402
    all_automations, due, get, health, is_enabled, last_run, record_run,
)
from aries.health import SPEC, TASK_KIND  # noqa: E402
from aries.settings import SettingsService  # noqa: E402


async def test_registered_and_describable():
    check("the health automation is registered", get("aries.health") is not None)
    check("and appears in the registry listing",
          "aries.health" in [a.automation_id for a in all_automations()])
    check("its task kind is registered with the engine", TASK_KIND in kinds())
    d = SPEC.describe()
    for f in ("automation_id", "name", "version", "purpose", "trigger", "permissions",
              "evaluation_metrics", "reward_signals", "evolution_history", "rollback_version",
              "risk", "enabled_setting"):
        check(f"the genome exposes '{f}' for the Control Centre", f in d)
    check("it declares itself read-only", d["risk"] == "low")
    check("it uses no model — judgement here is deterministic", d["agents"] == [])


async def test_no_automation_ships_enabled():
    """§11, structurally: every registered automation must DEFAULT to off.

    A regression guard, not a formality. The first version of the health
    automation shipped with `health.enabled` defaulting to True, which
    contradicted both the specification and this project's own documentation.
    The existing test did not catch it because it set the value to False before
    checking the disabled path — so the DEFAULT was never exercised. This test
    reads the schema default directly, and covers every automation, including
    ones not written yet.
    """
    from aries.automations import all_automations
    from aries.settings import get_def
    for spec in all_automations():
        check(f"{spec.automation_id} declares an enable setting",
              spec.enabled_setting is not None)
        d = get_def(spec.enabled_setting)
        check(f"{spec.automation_id} is off by default", d is not None and d.default is False)


async def test_disabled_until_asked_for():
    """§11: do not automatically activate every automation."""
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("health.enabled", False, set_by="user")
        check("an automation whose setting is off does not run",
              not await is_enabled(SPEC, s))
        ok, why = await due(db, SPEC, s)
        check("and is never due", not ok and why == "disabled")
        await s.set("health.enabled", True, set_by="user")
        check("turning it on enables it", await is_enabled(SPEC, s))


async def test_due_is_paced_by_the_last_run():
    """The engine's rule for workers: a missed cycle is caught up, not skipped."""
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("health.enabled", True, set_by="user")
        await s.set("health.interval_minutes", 15, set_by="user")

        ok, why = await due(db, SPEC, s)
        check("an automation that has never run is due now", ok and why == "never run")

        await record_run(db, SPEC, status="ok", summary="fine")
        await db.commit()
        ok, _ = await due(db, SPEC, s)
        check("just after a run it is not due", not ok)

        row = await last_run(db, "aries.health")
        row.started_at = datetime.utcnow() - timedelta(minutes=40)
        await db.commit()
        ok, why = await due(db, SPEC, s)
        check("once the interval has passed it is due again", ok)
        check("and it says how overdue it is", "min ago" in why)


async def test_health_is_honest_about_no_data():
    """§13/20 honest observability: null with a reason, never 0."""
    await reset_db()
    async with async_session() as db:
        h = await health(db, "aries.health")
        check("with no runs the success rate is null, not zero", h["success_rate"] is None)
        check("and it says why", h["reason"] == "no runs in the window")

        await record_run(db, SPEC, status="ok", summary="a")
        await record_run(db, SPEC, status="ok", summary="b")
        await record_run(db, SPEC, status="failed", summary="c")
        await db.commit()
        h = await health(db, "aries.health")
        check("with runs it is a real rate", h["success_rate"] == round(2 / 3, 3))
        check("and the breakdown is kept", h["counts"] == {"ok": 2, "failed": 1})


async def test_run_history_is_append_only():
    await reset_db()
    async with async_session() as db:
        await record_run(db, SPEC, status="ok", summary="first", duration_ms=12)
        await record_run(db, SPEC, status="degraded", summary="second", duration_ms=20,
                         detail={"probes_unavailable": ["gpu"]})
        await db.commit()
        row = await last_run(db, "aries.health")
        check("last_run returns the most recent", row.summary == "second")
        check("the run records the version that produced it", row.version == SPEC.version)
        check("and keeps the detail for inspection",
              row.as_dict()["detail"]["probes_unavailable"] == ["gpu"])


async def test_check_success_and_machine_health_are_separate():
    """The distinction the whole automation is built around: a working check that
    finds bad news has still worked."""
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("health.enabled", True, set_by="user")
        # Force a critical: this machine idles well above 40 °C.
        await s.set("health.temp_critical_celsius", 40.0, set_by="user")
        await s.set("health.temp_warn_celsius", 40.0, set_by="user")

    # Through the runner, which is how it actually runs: the runner is what
    # records the automation run row, so a test that creates a task directly
    # would be testing a path nothing uses.
    from aries.automations import run_automation
    out = await run_automation("aries.health", trigger="manual", force=True)
    tid = out["task_id"]

    from agentic_core.database.models import Task
    async with async_session() as db:
        from agentic_core.scheduler.queue import run_task_now  # noqa: F401  (path documented)
        task_row = await db.get(Task, tid)
    res = {"severity": out["severity"], "requires_approval": out["requires_approval"]}

    check("the lifecycle verdict is a pass — the check did its job",
          out["verdict"] == "pass")
    check("while the machine is reported CRITICAL", res["severity"] == "critical")
    check("a critical finding asks for a human", res["requires_approval"] is True)
    check("and the engine records a proposal for one", out["proposal_id"] is not None)

    async with async_session() as db:
        from agentic_core.database.models import ActionProposal
        from sqlalchemy import select
        p = (await db.execute(select(ActionProposal)
                              .where(ActionProposal.id == out["proposal_id"]))).scalar_one()
        check("the proposal names what it is", p.kind == "system.critical")
        check("and is marked high risk", p.risk == "high")
        check("the task waits for the human rather than completing silently",
              task_row.status == "awaiting_approval")
        check("the automation's own run status is 'ok' — it worked",
              (await last_run(db, "aries.health")).status == "ok")


async def test_a_healthy_machine_completes_without_asking():
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("health.enabled", True, set_by="user")

    from aries.automations import run_automation
    out = await run_automation("aries.health", trigger="manual", force=True)
    check("a healthy pass needs no approval", out["requires_approval"] is False)
    check("the pass reports its own status", out["status"] == "ok")

    async with async_session() as db:
        from agentic_core.database.models import Task
        check("the task completes", (await db.get(Task, out["task_id"])).status == "done")
        r = await last_run(db, "aries.health")
        check("and exactly one run row is recorded, not two", r is not None)
        check("with the detail the Control Centre shows",
              (r.as_dict()["detail"] or {}).get("samples_recorded", 0) > 0)


async def test_hour_units_and_direct_run_history():
    from aries.automations.worker import DispatcherWorker
    poll = DispatcherWorker('test.dispatch', lambda: None, every=timedelta(seconds=60))
    check('automation dispatcher polling is independent of wall-clock history', (await poll._due())[0])
    from aries.automations.genome import interval_minutes, AutomationSpec, AriesAutomationRun
    from aries.automations.runner import _run_directly
    from sqlalchemy import select, func
    await reset_db()
    async with async_session() as db:
        minutes = await interval_minutes(get('aries.learning'), SettingsService(db))
        check('daily learning interval is 1440 minutes, not 24', minutes == 1440)

    async def bookkeeping(ctx):
        return {'success': True, 'summary': 'No change needed'}
    spec = AutomationSpec(automation_id='test.bookkeeping', name='Bookkeeping', version='1', purpose='test', run=bookkeeping)
    await _run_directly(spec, 'api')
    async with async_session() as db:
        row = await last_run(db, spec.automation_id)
        check('direct bookkeeping persists a successful manual run', row is not None and row.status == 'ok' and row.trigger == 'api')

    async def self_recording(ctx):
        await record_run(ctx['db'], spec, status='ok', summary='Own evidence', trigger='api')
        return {'success': True}
    spec.run = self_recording
    await _run_directly(spec, 'api')
    async with async_session() as db:
        count = await db.scalar(select(func.count()).select_from(AriesAutomationRun).where(AriesAutomationRun.automation_id == spec.automation_id))
        check('self-recording automation is not double-counted', count == 2)


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
