"""The data lifecycle: what ARIES keeps, and what it must never quietly lose.

The rule this package exists for is the browser one — open a page, read it,
close it, the page is gone; what survives is a bookmark, not the HTML. These
tests pin the two halves that are easy to get wrong: deleting something a
dependant still needs, and keeping something that should have been released.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-lifecycle")

from sqlalchemy import text  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.lifecycle import policy, service, working  # noqa: E402


# ── the declarations themselves ─────────────────────────────────────────────

async def test_every_policy_names_a_column_that_exists():
    """The first bug this package had. Every timestamp column was assumed to be
    `created_at`, and five tables use something else — so the very first preview
    raised `no such column` instead of quietly deleting the wrong thing, which
    is the one mercy in it."""
    await reset_db()
    async with async_session() as db:
        for rule in policy.POLICIES:
            exists = (await db.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
                {"t": rule.table})).first()
            if not exists:
                continue
            columns = [row[1] for row in (await db.execute(
                text(f'PRAGMA table_info("{rule.table}")'))).fetchall()]
            ok = rule.timestamp_column in columns
            check(f"{rule.table}.{rule.timestamp_column} exists"
                  f"{'' if ok else f' — has {columns[:6]}'}", ok)


async def test_no_table_is_left_undecided():
    """A table nobody wrote a policy for is a table that grows forever by
    accident. Every table ARIES creates must appear in the register."""
    await reset_db()
    async with async_session() as db:
        tables = {row[0] for row in (await db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' "
                 "AND name NOT LIKE 'sqlite_%'"))).fetchall()}
    undecided = sorted(t for t in tables if t not in policy.BY_TABLE)
    check(f"every table has a retention policy"
          f"{'' if not undecided else ': ' + str(undecided)}", undecided == [])


async def test_audit_is_never_deleted_automatically():
    """A cleaner that erased the evidence of its own deletions would be the one
    part of this system nobody could check (§29)."""
    audit = policy.get("audit_events")
    check("audit_events is classed as audit", audit.kind == policy.AUDIT)
    check("and has no window at all", audit.forever)
    for rule in policy.POLICIES:
        if rule.kind == policy.AUDIT:
            check(f"{rule.table} is never on a timer", rule.forever)


async def test_memory_is_not_on_a_timer():
    """Preferences that expire are not preferences."""
    for name in ("aries_settings", "aries_interests", "aries_feedback",
                 "aries_learning_changes"):
        rule = policy.get(name)
        check(f"{name} is kept until the user removes it",
              rule is not None and rule.forever)


async def test_every_operational_window_declares_who_reads_it():
    """The interesting failure is not a crash. A circuit breaker with no run
    history does not error — it decides the automation is fine."""
    for rule in policy.POLICIES:
        if rule.kind != policy.OPERATIONAL:
            continue
        check(f"{rule.table} names its dependants", len(rule.dependants) > 0)
        check(f"{rule.table} declares a minimum window", rule.minimum_days > 0)
        check(f"{rule.table}'s default is at or above its own minimum",
              rule.default_days >= rule.minimum_days)


# ── applying it ─────────────────────────────────────────────────────────────

async def test_a_window_below_the_minimum_is_refused_at_the_door():
    """The settings schema carries each policy's minimum, so a window that would
    starve a dependant cannot be set at all — the refusal happens where the user
    is, with a message, rather than being silently clamped later."""
    await reset_db()
    from aries.settings import SettingsService
    from aries.settings.schema import SettingError

    rule = policy.get("aries_automation_runs")
    async with async_session() as db:
        refused = ""
        try:
            await SettingsService(db).set(rule.setting, 1, set_by="user")
        except SettingError as error:
            refused = str(error)
    check("a window below the minimum is refused", bool(refused))
    check(f"naming the minimum ({rule.minimum_days} days): {refused[:60]}",
          str(rule.minimum_days) in refused)


async def test_the_service_defends_the_minimum_too():
    """Defence in depth: the schema stops it at the door, and the cleaner checks
    again — because a value can reach the database another way (a migration, a
    direct write) and the cost of being wrong here is a subsystem that quietly
    starts answering differently."""
    await reset_db()
    from aries.settings import SettingsService
    rule = policy.get("aries_automation_runs")
    async with async_session() as db:
        # Straight past the schema, as a bad migration would.
        # Straight into the table, bypassing the schema entirely.
        from aries.settings import Layer
        await db.execute(text(
            "INSERT INTO aries_settings (key, layer, value_json, set_by, scope) "
            "VALUES (:k, :layer, '1', 'test', '')"),
            {"k": rule.setting, "layer": int(Layer.USER)})
        await db.commit()
        plan = await service.preview(db)
        line = next(t for t in plan["tables"] if t["table"] == rule.table)
    check(f"the cleaner uses the minimum, not the stored value (used {line['days']})",
          line["days"] == rule.minimum_days)
    check(f"and says what reads it: {line['why'][:60]}", "circuit breaker" in line["why"])


async def test_preview_touches_nothing():
    await reset_db()
    async with async_session() as db:
        before = (await db.execute(text("SELECT COUNT(*) FROM aries_settings"))).scalar()
        await service.preview(db)
        after = (await db.execute(text("SELECT COUNT(*) FROM aries_settings"))).scalar()
    check("a preview is a rehearsal, not a pass", before == after)


async def test_the_first_real_pass_only_rehearses():
    """Anything that deletes should be boring by the time it runs."""
    await reset_db()
    async with async_session() as db:
        outcome = await service.apply(db)
    check("nothing is removed on the first pass", outcome["removed"] == 0)
    check("and it says it rehearsed", "rehearsed" in outcome.get("note", ""))
    async with async_session() as db:
        rows = (await db.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE action = 'data.rehearsed'"))).scalar()
    check("the rehearsal is in the audit log", rows == 1)


async def test_old_rows_are_removed_and_recent_ones_are_not():
    await reset_db()
    from aries.settings import SettingsService
    async with async_session() as db:
        await SettingsService(db).set("data.dry_run_first", False, set_by="user")
        await db.commit()
        # Two log rows: one ancient, one from today.
        await db.execute(text(
            "INSERT INTO automation_logs (action, source, details, status, created_at) "
            "VALUES ('ancient', 'test', '{}', 'ok', datetime('now', '-400 days'))"))
        await db.execute(text(
            "INSERT INTO automation_logs (action, source, details, status, created_at) "
            "VALUES ('today', 'test', '{}', 'ok', datetime('now'))"))
        await db.commit()
        outcome = await service.apply(db)
        remaining = [r[0] for r in (await db.execute(
            text("SELECT action FROM automation_logs"))).fetchall()]
    check("the old row is gone", "ancient" not in remaining)
    check("the recent row is kept", "today" in remaining)
    check("and the pass reports what it removed", outcome["removed"] >= 1)
    async with async_session() as db:
        logged = (await db.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE action = 'data.cleaned'"))).scalar()
    check("the deletion is audited", logged == 1)


# ── the working set ─────────────────────────────────────────────────────────

async def test_the_working_set_is_released_when_the_task_ends():
    """The browser tab closes. What ARIES read to answer a question is not kept
    because the question was answered."""
    await reset_db()
    async with async_session() as db:
        await working.put(db, "task-1", label="inbox", source="mail",
                          content="a private message body", sensitive=True)
        await working.put(db, "task-1", label="calendar", source="calendar",
                          content="tomorrow: dentist")
        await working.put(db, "task-2", label="other", source="files", content="x")
        await db.commit()
        held = await working.summary(db)
    check("context is held while the task runs", held["held"] == 3)
    check("and sensitive items are counted", held["sensitive"] == 1)

    async with async_session() as db:
        released = await working.release(db, "task-1")
        await db.commit()
        after = await working.summary(db)
    check("finishing a task releases exactly its own context", released == 2)
    check("another task's context is untouched", after["held"] == 1)
    check("and nothing of the finished task remains", "task-1" not in after["tasks"])


async def test_a_dead_task_leaves_nothing_behind_for_long():
    """A task that crashed cannot release its own context, which is the only
    reason a working set has an age at all."""
    await reset_db()
    async with async_session() as db:
        await db.execute(text(
            "INSERT INTO aries_working_set (task_id, label, source, sensitive, content, created_at) "
            "VALUES ('dead', 'orphan', 'mail', 1, 'left behind', datetime('now', '-2 days'))"))
        await working.put(db, "alive", label="current", source="files", content="in use")
        await db.commit()
        swept = await working.sweep(db)
        await db.commit()
        after = await working.summary(db)
    check("the abandoned context is collected", swept["swept"] == 1)
    check("naming the task it belonged to", swept["tasks"] == ["dead"])
    check("and live work is left alone", after["tasks"] == ["alive"])


async def test_the_working_set_governs_itself_not_by_a_window():
    """It is in the register — no table may be undecided — but it is the one
    entry with no window in days. A day-window would either cut live work short
    or keep what a finished task read; the task's own end is the boundary."""
    rule = policy.get("aries_working_set")
    check("the working set is in the register", rule is not None)
    check("classed as working", rule.kind == policy.WORKING)
    check("with no window in days", rule.default_days is None and rule.setting is None)
    check("its sweep is measured in hours instead", working.SWEEP_HOURS > 0)


async def test_a_real_run_releases_its_working_set_even_when_it_fails():
    """The release is wired into the run path, not into each automation's body.

    Written after noticing the working set had a `release()` nobody called: the
    design said "released when the task ends" and nothing in the system ended a
    task. The failing case is the one that matters — a pass that died halfway is
    exactly the one still holding borrowed mail bodies.
    """
    await reset_db()
    from agentic_core.orchestrator.lifecycle import LifecyclePolicy
    from agentic_core.scheduler.queue import register_kind

    from aries.automations import runner
    from aries.automations.genome import AutomationSpec, get, register

    KIND = "aries.test.holds_then_dies"

    async def _execute(task, ctx):
        # Borrow context the way a real automation would, then die holding it.
        async with async_session() as db:
            await working.put(db, task.id, label="a borrowed email",
                              source="test", content="body")
            await db.commit()
        raise RuntimeError("the network went away mid-task")

    if get("aries.test.holds") is None:
        register(AutomationSpec(
            automation_id="aries.test.holds", name="Holds then dies", version="1.0.0",
            purpose="fails on purpose, holding borrowed context",
            run=lambda ctx: None, task_kind=KIND, risk="low",
            enabled_setting="automations.worker_enabled"))
        register_kind(KIND, executor=_execute,
                      policy=LifecyclePolicy(max_retries=0, max_replans=0))

    out = await runner.run_automation(get("aries.test.holds"), trigger="test", force=True)
    check(f"the run did not succeed (status: {out.get('status')})",
          out.get("status") != "ok")

    async with async_session() as db:
        held = await working.summary(db)
    check(f"and it is holding nothing afterwards "
          f"({held['held']} row(s) left behind)", held["held"] == 0)


# ── the automation ──────────────────────────────────────────────────────────

async def test_the_cleaner_is_a_declared_automation_and_ships_off():
    """A process that deletes the user's data from a place they cannot see is
    the one automation that must not be invisible."""
    from aries.automations.genome import get as get_automation
    from aries.settings import get_def

    spec = get_automation("aries.data")
    check("it exists as an automation", spec is not None)
    check("with a purpose a person can read", "hoard" in spec.purpose or "retention" in spec.purpose)
    check("it is classed as medium risk — it deletes", spec.risk == "medium")
    check("it ships disabled, like every automation (§11)",
          get_def(spec.enabled_setting).default is False)
    check("and deleting at all is a separate switch again",
          get_def("data.cleaning_enabled").default is False)
    check("only a person may turn that on",
          get_def("data.cleaning_enabled").user_only is True)


async def test_nothing_is_deleted_while_cleaning_is_off():
    await reset_db()
    async with async_session() as db:
        await db.execute(text(
            "INSERT INTO automation_logs (action, source, details, status, created_at) "
            "VALUES ('ancient', 'test', '{}', 'ok', datetime('now', '-400 days'))"))
        await db.commit()
        from aries.lifecycle.automation import run
        out = await run({"db": db, "trigger": "test"})
        remaining = (await db.execute(text("SELECT COUNT(*) FROM automation_logs"))).scalar()
    check("the pass runs", out["status"] == "ok")
    check("and removes nothing while automatic deletion is off", out["removed"] == 0)
    check("the old row is still there", remaining == 1)
    check("and it says why", "off" in out["summary"])


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
