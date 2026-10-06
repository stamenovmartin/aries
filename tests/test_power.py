"""Background Mode: the inhibitor, the reconciler, and what it refuses to touch.

These are fast and side-effect free. `state.write_idle_delay` is patched
throughout, because a test suite must not change the display timeout of the
machine it runs on — the one real gsettings write Background Mode makes is
exercised by the elapsed-time integration test, which also restores it.

The inhibitor itself is NOT mocked. It is the feature, it is cheap to take, and
mocking it would test the reconciler's opinion of logind rather than logind.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-power")

import httpx  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.power import governor, inhibit, reconcile, snapshot, state  # noqa: E402
from aries.settings import SettingsService  # noqa: E402

from aries.api.app import app  # noqa: E402

WRITES: list[int] = []


def _fake_write(seconds: int):
    WRITES.append(int(seconds))
    return True, "ok"


_real_write = state.write_idle_delay
_real_read = state.read_idle_delay


def _patch_display(current: int = 0):
    state.write_idle_delay = _fake_write
    state.read_idle_delay = lambda: (WRITES[-1] if WRITES else current)


def _unpatch():
    state.write_idle_delay = _real_write
    state.read_idle_delay = _real_read
    WRITES.clear()


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _set(**kw):
    async with async_session() as db:
        s = SettingsService(db)
        for key, value in kw.items():
            await s.set(f"power.{key}", value, set_by="user")


# ── the inhibitor itself ────────────────────────────────────────────────────

async def test_the_inhibitor_is_a_sleep_block_never_an_idle_one():
    """An idle inhibitor would keep the screen ON, which is the opposite of what
    Background Mode is for."""
    check("ARIES inhibits sleep", inhibit.WHAT == "sleep")
    check("and never idle, which would stop the display blanking",
          inhibit.WHAT != "idle")
    check("in block mode, so the suspend does not happen rather than being delayed",
          inhibit.MODE == "block")


async def test_taking_and_releasing_is_visible_to_logind():
    ok, reason = inhibit.available()
    if not ok:
        check(f"no systemd session, so the inhibitor is skipped ({reason})", True)
        return
    try:
        check("nothing is held to begin with", not inhibit.held())
        taken, detail = inhibit.acquire("test")
        check(f"the inhibitor can be taken ({detail})", taken)
        check("ARIES believes it holds it", inhibit.held())
        test_pid = inhibit._current.pid
        rows = inhibit.listed()
        check("and logind agrees it is held", len(rows) >= 1)
        check("as a sleep/block inhibitor",
              any(r["what"] == "sleep" and r["mode"] == "block" for r in rows))
        check("taking it again is idempotent", inhibit.acquire("test")[0] and inhibit.held())
    finally:
        released, _ = inhibit.release()
    check("releasing works", released)
    check("ARIES no longer believes it holds it", not inhibit.held())
    check("and logind no longer lists this test holder",
          all(int(r["pid"]) != test_pid for r in inhibit.listed()))
    check("releasing again is harmless", inhibit.release()[0])


async def test_a_dead_holder_is_noticed_not_assumed():
    """The holder can die without asking. An inhibitor ARIES believes it holds
    but does not is the one failure Background Mode must not have."""
    ok, _ = inhibit.available()
    if not ok:
        check("no systemd session, so the inhibitor is skipped", True)
        return
    inhibit.acquire("test")
    check("held", inhibit.held())
    test_pid = inhibit._current.pid
    inhibit._current.process.kill()          # the holder dies behind ARIES's back
    inhibit._current.process.wait(timeout=5)
    check("ARIES notices it is no longer held rather than trusting a flag",
          not inhibit.held())
    check("and logind agrees this test holder is gone",
          all(int(r["pid"]) != test_pid for r in inhibit.listed()))


# ── the reconciler ──────────────────────────────────────────────────────────

async def test_reconcile_takes_and_releases_with_the_setting():
    await reset_db()
    _patch_display(current=0)
    try:
        await _set(background_mode=True, display_off_after_minutes=10)
        async with async_session() as db:
            out = await reconcile(db, reason="test")
        if inhibit.available()[0]:
            check("switching Background Mode on takes the inhibitor", out["inhibitor_held"])
            check("and says so", any("took the sleep inhibitor" in a for a in out["actions"]))
        check("the display timeout is applied", 600 in WRITES)

        await _set(background_mode=False)
        async with async_session() as db:
            out = await reconcile(db, reason="test")
        check("switching it off releases the inhibitor", not out["inhibitor_held"])
        check("and restores the display timeout", WRITES[-1] == 0)
    finally:
        inhibit.release()
        _unpatch()


async def test_the_previous_display_timeout_is_recorded_before_it_is_changed():
    await reset_db()
    _patch_display(current=1800)
    try:
        await _set(background_mode=True, display_off_after_minutes=5)
        async with async_session() as db:
            await reconcile(db, reason="test")
            previous = await SettingsService(db).get("power.restore_idle_delay")
        check("what was there before is written down first", previous == 1800)
        check("before the new value is applied", WRITES == [300])

        await _set(background_mode=False)
        async with async_session() as db:
            await reconcile(db, reason="test")
            cleared = await SettingsService(db).get("power.restore_idle_delay")
        check("and put back exactly on the way out", WRITES[-1] == 1800)
        check("with nothing left to restore afterwards", cleared == -1)
    finally:
        inhibit.release()
        _unpatch()


async def test_allow_suspend_means_no_inhibitor():
    await reset_db()
    _patch_display()
    try:
        await _set(background_mode=True, allow_suspend=True)
        async with async_session() as db:
            out = await reconcile(db, reason="test")
        check("Background Mode with 'allow normal suspend' holds nothing back",
              not out["inhibitor_held"])
        check("but Background Mode is still on", out["background_mode"] is True)
    finally:
        inhibit.release()
        _unpatch()


async def test_reconcile_is_idempotent():
    await reset_db()
    _patch_display()
    try:
        await _set(background_mode=True, display_off_after_minutes=10)
        async with async_session() as db:
            first = await reconcile(db, reason="test")
            second = await reconcile(db, reason="test")
        check("the first pass does the work", first["actions"])
        check("the second does nothing, so it is safe on every tick",
              second["actions"] == [])
    finally:
        inhibit.release()
        _unpatch()


async def test_a_lost_inhibitor_is_retaken_on_the_next_tick():
    await reset_db()
    if not inhibit.available()[0]:
        check("no systemd session, so retake is skipped", True)
        return
    _patch_display()
    try:
        await _set(background_mode=True)
        async with async_session() as db:
            await reconcile(db, reason="test")
        check("held after the first reconcile", inhibit.held())
        inhibit._current.process.kill()
        inhibit._current.process.wait(timeout=5)
        check("and lost when its holder dies", not inhibit.held())
        async with async_session() as db:
            out = await reconcile(db, reason="tick")
        check("the next tick takes it again", out["inhibitor_held"])
    finally:
        inhibit.release()
        _unpatch()


# ── what it reports ─────────────────────────────────────────────────────────

async def test_the_snapshot_is_measured_not_remembered():
    await reset_db()
    _patch_display()
    try:
        async with async_session() as db:
            snap = await snapshot(db)
        for key in ("background_mode", "allow_suspend", "display", "system",
                    "inhibitor", "suspend_policy", "effect"):
            check(f"the snapshot reports '{key}'", key in snap)
        check("the display state is one of three honest answers",
              snap["display"]["state"] in ("on", "off", "unknown"))
        check("the inhibitor section names what and how",
              snap["inhibitor"]["what"] == "sleep" and snap["inhibitor"]["mode"] == "block")
        check("and whether it is actually active", snap["inhibitor"]["active"] is False)
        check("the GPU note distinguishes 'the gate is not built' from 'nothing "
              "meets it yet' — only the second is true now",
              "the gate is live" in snap["gpu_jobs_note"]
              and "No automation declares heavy GPU work yet" in snap["gpu_jobs_note"])
    finally:
        _unpatch()


async def test_it_does_not_claim_credit_it_has_not_earned():
    """On a machine set never to suspend on mains, the inhibitor changes nothing
    — and the panel must say so rather than implying it is holding back a
    suspend that was never coming."""
    await reset_db()
    _patch_display()
    real_policy = state.read_suspend_policy
    state.read_suspend_policy = lambda: {"sleep-inactive-ac-type": "nothing",
                                         "sleep-inactive-ac-timeout": "3600",
                                         "sleep-inactive-battery-type": "suspend",
                                         "sleep-inactive-battery-timeout": "900"}
    try:
        await _set(background_mode=True)
        async with async_session() as db:
            snap = await snapshot(db)
        check("it says the inhibitor changes nothing on mains power",
              "already set never to suspend" in snap["effect"])
        check("and that it still matters on battery", "battery" in snap["effect"])
    finally:
        state.read_suspend_policy = real_policy
        inhibit.release()
        _unpatch()


async def test_gsettings_type_prefix_is_not_read_as_a_value():
    """Regression: `gsettings get` prints `uint32 0`, and stripping every digit
    gave 320 seconds from a timeout of 0."""
    real = state._gsettings
    try:
        state._gsettings = lambda *a, **k: (True, "uint32 0")
        check("'uint32 0' reads as 0, not 320", state.read_idle_delay() == 0)
        state._gsettings = lambda *a, **k: (True, "uint32 1800")
        check("'uint32 1800' reads as 1800", state.read_idle_delay() == 1800)
        state._gsettings = lambda *a, **k: (True, "600")
        check("a bare number still reads", state.read_idle_delay() == 600)
        state._gsettings = lambda *a, **k: (False, "no such schema")
        check("an unreadable setting is None, not a guess", state.read_idle_delay() is None)
    finally:
        state._gsettings = real


# ── the API surface ─────────────────────────────────────────────────────────

async def test_the_api_toggles_and_reconciles_at_once():
    await reset_db()
    _patch_display()
    try:
        async with await _client() as c:
            r = await c.get("/api/aries/power")
            check("the power endpoint answers", r.status_code == 200)
            check("with Background Mode off to begin with",
                  r.json()["background_mode"] is False)

            r = await c.put("/api/aries/power", json={"background_mode": True})
            body = r.json()
            check("it can be switched on over the API", body["background_mode"] is True)
            check("and reconciled in the same request, not on the next tick",
                  "reconciled" in body)
            if inhibit.available()[0]:
                check("so the inhibitor is already held when the call returns",
                      body["inhibitor"]["active"] is True)

            r = await c.put("/api/aries/power", json={"background_mode": False})
            check("and switched off again", r.json()["inhibitor"]["active"] is False)

            r = await c.put("/api/aries/power", json={})
            check("an empty change is refused rather than silently doing nothing",
                  r.status_code == 400)
            r = await c.put("/api/aries/power", json={"display_off_after_minutes": 9999})
            check("an impossible display timeout is refused", r.status_code == 400)
    finally:
        inhibit.release()
        _unpatch()


async def test_changing_power_needs_more_than_edit_permission():
    from agentic_core.security.permissions import permission_for
    check("reading the power panel needs only view_data",
          permission_for("GET", "/api/aries/power").value == "view_data")
    check("stopping the machine sleeping is a system control, not a content edit",
          permission_for("PUT", "/api/aries/power").value == "manage_tools")


async def test_background_mode_is_user_only():
    """No learning loop may decide to keep the machine awake."""
    from aries.settings import get_def
    for key in ("power.background_mode", "power.allow_suspend", "power.allow_gpu_jobs"):
        check(f"{key} can only be set by a person", get_def(key).user_only is True)


# ── the resource policy ─────────────────────────────────────────────────────
#
# The governor is exercised against the real machine's sensors where they can
# be read, and against injected measurements where a real one cannot be
# produced on demand: a test must not need the machine to reach 85 °C to prove
# that 85 °C defers heavy work.


def _measurement(*, cpu=5.0, gpu=5.0, temp=45.0, temp_subject="x86_pkg_temp",
                 cpu_unavailable=None, gpu_unavailable=None, temp_unavailable=None):
    m = governor.Measurement()
    m.cpu_pct, m.cpu_unavailable, m.cpu_window = cpu, cpu_unavailable, "test"
    m.gpu_pct, m.gpu_unavailable, m.gpu_subject = gpu, gpu_unavailable, "gpu0"
    m.temperature_c, m.temperature_unavailable = temp, temp_unavailable
    m.temperature_subject = temp_subject
    return m


def _pin(m):
    """Freeze what the governor measures, without mocking the decision."""
    governor._cached = m
    governor._cached.at = __import__("time").time()


def _unpin():
    governor._cached = None
    governor._cpu_sample = None
    governor._clear_streak.clear()
    governor._running.clear()


def _spec(workload_class="heavy_cpu", *, stateful=False, automation_id="test.heavy",
          enabled_setting=None):
    from aries.automations.genome import AutomationSpec

    async def _noop(ctx):
        return {"status": "ok", "summary": "nothing"}

    return AutomationSpec(automation_id=automation_id, name="Test", version="1.0",
                          purpose="a test", run=_noop, workload=workload_class,
                          stateful=stateful, enabled_setting=enabled_setting)


async def test_lightweight_work_is_never_deferred():
    """Health checks, news and memory maintenance run whatever the machine is doing.

    Not an oversight — the health check is how ARIES finds out the machine is
    hot, and a policy that silenced its own thermometer to save heat would be
    measuring nothing and protecting nothing.
    """
    await reset_db()
    _pin(_measurement(cpu=99.0, gpu=99.0, temp=99.0))
    try:
        async with async_session() as db:
            for cls in ("light", "inference_light"):
                v = await governor.may_run(db, _spec(cls))
                check(f"{cls} work runs at 99 °C and 99 % CPU", v.allowed)
                check(f"and says why: {v.reason}", "always runs" in v.reason)
            check("nothing was recorded, because nothing was refused",
                  await governor.recent_events(db) == [])
    finally:
        _unpin()


async def test_heavy_work_is_blocked_unattended_until_it_is_enabled():
    await reset_db()
    _pin(_measurement())
    real_display = governor.state.display_state
    governor.state.display_state = lambda: ("off", "test: the screen is blanked")
    try:
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_cpu"))
            check("sustained CPU work is refused while the display is off", not v.allowed)
            check("with the reason 'not enabled', not a threshold", v.code == "not_enabled")
            check("and names the setting that would allow it",
                  "power.allow_heavy_cpu" in v.reason)
            v = await governor.may_run(db, _spec("heavy_gpu"))
            check("GPU work is refused for the same reason", v.code == "not_enabled")
            check("and names its own setting", "power.allow_gpu_jobs" in v.reason)
            await db.commit()

        await _set(allow_heavy_cpu=True)
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_cpu"))
            check("enabling it lets CPU work through", v.allowed)
            v = await governor.may_run(db, _spec("heavy_gpu"))
            check("and does not let GPU work through — the gates are separate",
                  not v.allowed)
            await db.commit()

        async with async_session() as db:
            events = await governor.recent_events(db)
        check("every refusal is recorded", len([e for e in events if e["kind"] == "blocked"]) == 3)
        check("with the workload it was about",
              {e["workload"] for e in events if e["kind"] == "blocked"} ==
              {"heavy_cpu", "heavy_gpu"})
    finally:
        governor.state.display_state = real_display
        _unpin()


async def test_a_person_pressing_run_now_is_the_explicit_consent():
    """`force` carries the permission gate — someone explicitly asked — but not
    the thermal one: no amount of wanting makes 88 °C a good place to start."""
    await reset_db()
    real_display = governor.state.display_state
    governor.state.display_state = lambda: ("off", "test")
    try:
        _pin(_measurement(temp=45.0))
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_gpu"), force=True)
            check("Run now runs heavy work that is not enabled for unattended use",
                  v.allowed)
            await db.commit()
        _pin(_measurement(temp=88.0))
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_gpu"), force=True)
            check("but Run now does not run it on an overheating machine", not v.allowed)
            check("and says which limit stopped it", v.code == "too_hot")
            check("naming the temperature and the limit",
                  "88.0 °C" in v.reason and "80 °C" in v.reason)
            await db.commit()
    finally:
        governor.state.display_state = real_display
        _unpin()


async def test_a_thermal_deferral_takes_a_hold_that_survives_the_reading_dropping():
    """The hysteresis lesson of Entry 010, in its second home.

    A hold released by the first reading under the limit restarts the job that
    caused the heat, and the machine oscillates. So resuming needs the margin
    AND a streak, and both are reachable.
    """
    await reset_db()
    await _set(allow_heavy_cpu=True, temperature_limit_celsius=80,
               thermal_resume_margin_celsius=5, thermal_clear_checks=2)
    try:
        _pin(_measurement(temp=84.0))
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_cpu"))
            check("84 °C defers heavy CPU work", not v.allowed and v.code == "too_hot")
            await db.commit()

        # Back under the limit, but not under the margin: still held.
        _pin(_measurement(temp=78.0))
        async with async_session() as db:
            released = await governor.release_holds(db)
            await db.commit()
        check("78 °C is under the 80 °C limit but not under the 75 °C margin — still held",
              released == [])
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_cpu"))
            check("so the work is still refused", not v.allowed)
            check("as held rather than as newly too hot", v.code == "held")
            await db.commit()

        # Under the margin, but only once.
        _pin(_measurement(temp=70.0))
        async with async_session() as db:
            released = await governor.release_holds(db)
            await db.commit()
        check("one cool reading is not enough — a sensor can blink", released == [])

        async with async_session() as db:
            released = await governor.release_holds(db)
            await db.commit()
        check("two in a row is a trend, and the hold is released", len(released) == 1)
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_cpu"))
            check("and the work runs again", v.allowed)
            events = await governor.recent_events(db)
        check("the release is recorded as well as the deferral",
              [e["kind"] for e in events[:2]] == ["resumed", "deferred"])
        check("with the evidence that released it", "70.0 °C" in events[0]["reason"])
    finally:
        _unpin()


async def test_the_margin_is_reachable():
    """An unreachable rule is the same as an absent one (Entry 010).

    Checked as arithmetic rather than as a sentence: the resume ceiling must sit
    below the limit and above absolute zero, for every value the settings allow.
    """
    from aries.settings import get_def
    limit_def = get_def("power.temperature_limit_celsius")
    margin_def = get_def("power.thermal_resume_margin_celsius")
    lowest_limit, highest_margin = limit_def.minimum, margin_def.maximum
    check("the coolest limit minus the widest margin is still a temperature a "
          "machine reaches", lowest_limit - highest_margin >= 10)
    check("and the margin may be zero, for someone who wants no hysteresis at all",
          margin_def.minimum == 0)


async def test_utilisation_defers_without_taking_a_hold():
    """Utilisation is a moment, not a condition: it needs no margin, because
    nothing about waiting makes the reading oscillate."""
    await reset_db()
    await _set(allow_heavy_cpu=True, allow_gpu_jobs=True, cpu_limit_pct=70, gpu_limit_pct=70)
    try:
        _pin(_measurement(cpu=85.0, gpu=10.0))
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_cpu"))
            check("a busy processor defers sustained CPU work", not v.allowed)
            check("with its own code", v.code == "cpu_busy")
            check("no hold is taken", await governor.active_hold(db, "heavy_cpu") is None)
            v = await governor.may_run(db, _spec("heavy_gpu"))
            check("and the GPU gate is not affected by the processor", v.allowed)
            await db.commit()

        _pin(_measurement(cpu=85.0, gpu=95.0))
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_gpu"))
            check("a busy GPU defers GPU work", not v.allowed and v.code == "gpu_busy")
            await db.commit()

        _pin(_measurement(cpu=5.0, gpu=5.0))
        async with async_session() as db:
            check("and a quiet machine takes it immediately, with nothing to release",
                  (await governor.may_run(db, _spec("heavy_cpu"))).allowed)
    finally:
        _unpin()


async def test_an_unreadable_sensor_defers_heavy_work():
    """Permission to run is not evidence of a safe machine temperature."""
    await reset_db()
    await _set(allow_heavy_cpu=True)
    try:
        _pin(_measurement(temp=None, temp_unavailable="no thermal zones"))
        async with async_session() as db:
            v = await governor.may_run(db, _spec("heavy_cpu"))
            check("heavy work waits when temperature cannot be read", not v.allowed)
            check("the verdict names the missing sensor",
                  v.code == "sensor_unavailable" and "temperature" in v.reason)
            check("and the measurement carries the reason, not a zero",
                  v.measurement["temperature_celsius"] is None
                  and v.measurement["temperature_unavailable"] == "no thermal zones")
            await db.commit()
    finally:
        _unpin()


async def test_a_hold_is_preserved_when_the_sensor_goes_blind():
    await reset_db()
    await _set(allow_heavy_cpu=True)
    try:
        _pin(_measurement(temp=90.0))
        async with async_session() as db:
            await governor.may_run(db, _spec("heavy_cpu"))
            await db.commit()
        _pin(_measurement(temp=None, temp_unavailable="sensor disappeared"))
        async with async_session() as db:
            released = await governor.release_holds(db)
            await db.commit()
        check("a missing sensor cannot establish cooling", released == [])
        async with async_session() as db:
            hold = await governor.active_hold(db, "heavy_cpu")
        check("the original thermal hold survives", hold is not None)
    finally:
        _unpin()


async def test_the_budget_never_silently_kills_stateful_work():
    await reset_db()
    await _set(heavy_job_max_minutes=1)
    import time as _time
    try:
        stateless, stateful = _spec("heavy_cpu", automation_id="a.stateless"), \
            _spec("heavy_cpu", stateful=True, automation_id="a.stateful")
        governor.note_start(stateless)
        governor.note_start(stateful)
        check("both are being watched", len(governor.running()) == 2)

        async with async_session() as db:
            check("neither is over budget yet", await governor.check_budgets(db) == [])
            await db.commit()

        for job in governor._running.values():          # pretend 90 seconds passed
            job.started_at = _time.monotonic() - 90

        async with async_session() as db:
            over = await governor.check_budgets(db)
            await db.commit()
        check("both are found over budget", len(over) == 2)
        check("the stateless one is asked to stop",
              governor.stop_requested("a.stateless"))
        check("the stateful one is NOT — it would lose work",
              not governor.stop_requested("a.stateful"))

        async with async_session() as db:
            events = await governor.recent_events(db)
        reasons = {e["automation_id"]: e["reason"] for e in events}
        check("and the record says which was left to finish, and why",
              "holds state" in reasons["a.stateful"]
              and "next run waits" in reasons["a.stateful"])
        check("nothing was cancelled — stopping is a flag a job reads, not a signal",
              all(j["automation_id"] in ("a.stateless", "a.stateful")
                  for j in governor.running()))

        async with async_session() as db:
            check("and it is recorded once, not on every tick afterwards",
                  await governor.check_budgets(db) == [])
    finally:
        _unpin()


async def test_only_heavy_work_is_budgeted_at_all():
    _unpin()
    governor.note_start(_spec("light", automation_id="a.light"))
    check("lightweight work is not in the budget register", governor.running() == [])
    governor.note_start(_spec("heavy_gpu", automation_id="a.gpu"))
    check("heavy work is", len(governor.running()) == 1)
    governor.note_finish("a.gpu")
    check("and leaves when it finishes", governor.running() == [])


async def test_the_runner_refuses_and_records_rather_than_running():
    """The gate is in the one run path, so the CLI, the API and the dispatcher
    all meet it."""
    await reset_db()
    from aries.automations import genome
    from aries.automations.runner import run_automation

    # Enabled, so the run reaches the resource gate rather than stopping at the
    # §11 switch before it. The two refusals are different and must not be
    # confused: "you have not switched this on" and "the machine may not do this
    # kind of work right now".
    spec = _spec("heavy_gpu", automation_id="test.gpu.runner",
                 enabled_setting="health.enabled")
    genome.register(spec, replace=True)
    async with async_session() as db:
        await SettingsService(db).set("health.enabled", True, set_by="user")
    real_display = governor.state.display_state
    governor.state.display_state = lambda: ("off", "test")
    _pin(_measurement())
    try:
        out = await run_automation(spec, trigger="schedule")
        check("a heavy automation does not run while the policy refuses it",
              out["ran"] is False)
        check("and the reason names the policy", out["reason"] == "resource_policy:not_enabled")
        async with async_session() as db:
            last = await genome.last_run(db, spec.automation_id)
        check("the refusal is recorded as a run, so it is visible rather than silent",
              last is not None and last.status == "skipped")
        check("with the policy's own words", "resource policy" in (last.summary or ""))
    finally:
        governor.state.display_state = real_display
        _unpin()
        genome._REGISTRY.pop(spec.automation_id, None)


async def test_a_lightweight_automation_measures_nothing():
    """The check costs nothing for every automation that exists today."""
    await reset_db()
    _unpin()
    calls = {"n": 0}
    real_measure = governor.measure

    async def counting(**kw):
        calls["n"] += 1
        return await real_measure(**kw)

    governor.measure = counting
    try:
        async with async_session() as db:
            await governor.may_run(db, _spec("light"))
        check("deciding about lightweight work reads no sensor", calls["n"] == 0)
    finally:
        governor.measure = real_measure


async def test_every_shipped_automation_declares_its_cost():
    """A field with a default is a field nobody has to think about — so the
    declaration is asserted, not assumed."""
    from aries.automations.genome import all_automations
    from aries.power import workload
    for spec in all_automations():
        check(f"{spec.automation_id} declares a workload class ARIES knows",
              spec.workload in workload.CLASSES)
    heavy = [s.automation_id for s in all_automations() if workload.get(s.workload).heavy]
    check("and nothing shipped today is heavy, so nothing is being refused yet",
          heavy == [])


async def test_measuring_the_real_machine():
    """Against the actual sensors, because a policy tested only on injected
    numbers is a policy that has never met a machine."""
    _unpin()
    m = await governor.measure(fresh=True)
    check("CPU utilisation reads as a percentage, or says why not",
          (m.cpu_pct is None) != (m.cpu_unavailable is None)
          or (m.cpu_pct is not None and 0.0 <= m.cpu_pct <= 100.0))
    if m.cpu_pct is not None:
        check(f"and it is a plausible number ({m.cpu_pct} %)", 0.0 <= m.cpu_pct <= 100.0)
    if m.temperature_c is not None:
        check(f"the hottest sensor is plausible ({m.temperature_c} °C, "
              f"{m.temperature_subject})", 0.0 < m.temperature_c < 125.0)
    else:
        check(f"or says why there is no temperature: {m.temperature_unavailable}",
              bool(m.temperature_unavailable))
    if m.gpu_pct is not None:
        check(f"the GPU reads as a percentage ({m.gpu_pct} %)", 0.0 <= m.gpu_pct <= 100.0)
    else:
        check(f"or says why not: {m.gpu_unavailable}", bool(m.gpu_unavailable))

    second = await governor.measure()
    check("a second reading inside the cache window is the same one",
          second.at == m.at)


async def test_the_resource_panel_is_served_and_predicts_the_gate():
    await reset_db()
    _pin(_measurement(temp=95.0))
    await _set(allow_heavy_cpu=True)
    try:
        async with await _client() as c:
            r = await c.get("/api/aries/power")
            check("the power endpoint carries the resource policy", r.status_code == 200)
            res = r.json()["resources"]
            check("with the measurement", res["measurement"]["temperature_celsius"] == 95.0)
            check("and the limits", res["limits"]["temperature_celsius"] == 80)
            by_name = {c_["name"]: c_ for c_ in res["classes"]}
            check("every workload class is listed, including the ones nothing uses",
                  set(by_name) == {"light", "inference_light", "heavy_cpu", "heavy_gpu"})
            check("light work shows as allowed", by_name["light"]["status"] == "allowed")
            check("and heavy CPU work shows what the gate would actually do",
                  by_name["heavy_cpu"]["status"] == "deferred")
            check("with the same reason the gate would give",
                  "95.0 °C" in by_name["heavy_cpu"]["why"])

            r = await c.get("/api/aries/power/workloads")
            check("the vocabulary is served, so the UI hard-codes nothing",
                  r.status_code == 200 and len(r.json()["classes"]) == 4)
            r = await c.get("/api/aries/power/events")
            check("and the decisions are queryable", r.status_code == 200)
    finally:
        _unpin()


async def test_thresholds_are_changeable_from_the_power_screen():
    await reset_db()
    _patch_display(current=0)
    try:
        async with await _client() as c:
            r = await c.put("/api/aries/power", json={"temperature_limit_celsius": 75,
                                                      "cpu_limit_pct": 55,
                                                      "heavy_job_max_minutes": 45,
                                                      "allow_heavy_cpu": True})
            check("the thresholds are writable through the power route", r.status_code == 200)
            lim = r.json()["resources"]["limits"]
            check("temperature", lim["temperature_celsius"] == 75)
            check("CPU", lim["cpu_pct"] == 55)
            check("budget", lim["heavy_job_max_minutes"] == 45)
            check("and the permission switch", lim["allow_heavy_cpu"] is True)
            r = await c.put("/api/aries/power", json={"temperature_limit_celsius": 500})
            check("an impossible temperature limit is refused by the schema",
                  r.status_code == 400)
    finally:
        _unpin()
        _unpatch()


async def test_heavy_work_permissions_are_user_only():
    from aries.settings import get_def
    for key in ("power.allow_heavy_cpu", "power.allow_gpu_jobs"):
        check(f"{key} can only be set by a person", get_def(key).user_only is True)


if __name__ == "__main__":
    try:
        sys.exit(run_module(sys.modules[__name__]))
    finally:
        inhibit.release()
