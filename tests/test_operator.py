"""The Operator: does it know whether it did what it said?

The claim this milestone has to earn is not "ARIES can open YouTube". It is
"ARIES knows whether it opened YouTube" — and says so when it does not. These
tests are mostly about the second half, because the first half is a subprocess
call and the second half is the entire contribution.

Nothing here opens a window. The desktop is synthesised, so the verifier can be
shown states that would be tedious or impossible to arrange for real: a process
with no window, a window with no process, no window list at all.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-operator")

from agentic_core.database.base import async_session  # noqa: E402

from aries.operator import desktop, goals, plan, service, tools  # noqa: E402
from aries.settings import SettingsService  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _desktop(*, windows=None, processes=(), why="") -> desktop.Desktop:
    """A desktop that is whatever the test needs it to be."""
    return desktop.Desktop(
        processes=[desktop.Process(pid=i + 100, name=n, cmdline=f"/usr/bin/{n}")
                   for i, n in enumerate(processes)],
        windows=None if windows is None else [
            desktop.Window(id=str(i), title=t, wm_class=c, app_id=f"{c}.desktop",
                           pid=200 + i, focused=i == 0, workspace=0, minimised=False)
            for i, (t, c) in enumerate(windows)],
        windows_unavailable=why)


# ── the vocabulary is complete and closed ───────────────────────────────────

async def test_every_goal_can_be_verified_and_attempted():
    """A goal with no verifier is a claim ARIES cannot check, and a goal with no
    tool is one it cannot attempt. Either makes the vocabulary a lie."""
    for goal in goals.GOALS:
        check(f"{goal.kind} has a verifier", goal.kind in goals._VERIFIERS)
        step = plan._step_for(goal.kind, {p: "x" for p in goal.params})
        check(f"{goal.kind} has a tool", step is not None)
        if step:
            check(f"{goal.kind}'s tool {step.tool} is registered",
                  step.tool in tools.TOOL_NAMES)


async def test_every_goal_declares_the_best_evidence_it_can_ever_get():
    """The ceiling is the honest part. A goal that claimed proof and delivered a
    window title would be worse than one that never claimed anything."""
    for goal in goals.GOALS:
        check(f"{goal.kind} declares a ceiling", goal.ceiling in goals.GRADE_RANK)
        check(f"{goal.kind} says why it cannot do better", len(goal.why_ceiling) > 30)
    web = goals.get("open_url")
    check("a web goal cannot claim more than circumstantial evidence",
          web.ceiling == goals.CIRCUMSTANTIAL)
    check("and running an automation can be proved",
          goals.get("run_automation").ceiling == goals.PROOF)


def _code_only(source: str) -> str:
    """The CODE, with comments and docstrings removed.

    Three times now a scan has matched the prose explaining what it forbids —
    the CSS scan flagged its own header, the sync-call scan flagged the
    paragraph warning against sync calls, and this one flagged the comment
    explaining why the verifier must not read a report. The tempting fix each
    time is to delete the explanation.
    """
    import io
    import tokenize

    out = []
    previous = tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and previous in (
                tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.NL):
            continue                      # a docstring, in any position
        out.append(tok.string)
        if tok.type not in (tokenize.NL, tokenize.COMMENT):
            previous = tok.type
    return " ".join(out)


async def test_the_verifier_never_reads_what_the_operator_did():
    """Structural, because this is the one thing that would quietly hollow out
    the whole design: a verifier that consults the action's own report is a
    second copy of the claim it was meant to check."""
    source = open(os.path.join(ROOT, "aries", "operator", "goals.py")).read()
    code = _code_only(source)
    body = code[code.index("async def verify ("):]
    for forbidden in ("reported", "report_detail", "tool_result"):
        check(f"verification does not read '{forbidden}'", forbidden not in body)


# ── what the verifier concludes, on desktops it is shown ────────────────────

async def test_a_process_with_no_window_is_not_success():
    """The failure a naive check misses: the launcher ran, something started,
    and nothing appeared."""
    v = await goals.verify("open_app", {"app": "firefox"},
                           _desktop(windows=[], processes=["firefox"]))
    check("a running process with no window is unmet", v.verdict == goals.UNMET)
    check("and the reason names what was actually seen",
          "no window" in v.found or "none has a window" in v.found)


async def test_a_process_and_a_window_together_are_strong():
    v = await goals.verify("open_app", {"app": "firefox"},
                           _desktop(windows=[("Mozilla Firefox", "firefox")],
                                    processes=["firefox"]))
    check("a process and its window is met", v.verdict == goals.MET)
    check("graded strong — two independent observations", v.grade == goals.STRONG)


async def test_a_url_is_only_ever_circumstantial():
    v = await goals.verify("open_url", {"url": "https://www.youtube.com/watch?v=x"},
                           _desktop(windows=[("Some video - YouTube — Mozilla Firefox",
                                              "firefox")],
                                    processes=["firefox"]))
    check("a browser window titled for the site is met", v.verdict == goals.MET)
    check("and it is graded circumstantial, never higher",
          v.grade == goals.CIRCUMSTANTIAL)
    check("the check says what it looked at", "title" in v.checked)


async def test_a_browser_on_the_wrong_page_is_unmet_not_unverifiable():
    v = await goals.verify("open_url", {"url": "https://youtube.com"},
                           _desktop(windows=[("Wikipedia — Mozilla Firefox", "firefox")],
                                    processes=["firefox"]))
    check("a browser showing something else is unmet", v.verdict == goals.UNMET)
    check("and ARIES says what it saw instead", "youtube" in v.found.lower())


async def test_no_window_list_means_unverifiable_not_failure_and_not_success():
    """The verdict that makes the rest honest. Outside the ARIES session there
    is no window list, and both other answers would be lies."""
    d = _desktop(windows=None, processes=["firefox"],
                 why="the ARIES shell is not running")
    v = await goals.verify("open_url", {"url": "https://youtube.com"}, d)
    check("with no window list the verdict is unverifiable",
          v.verdict == goals.UNVERIFIABLE)
    check("the evidence grade is none", v.grade == goals.NONE)
    check("and the reason is given", "shell is not running" in v.found)
    check("including that a browser IS running, which proves nothing about the page",
          "says a browser is open" in v.found)


async def test_unverifiable_is_not_counted_as_dishonesty():
    """A gap means the desktop CONTRADICTED the report. 'I cannot check' is the
    honest answer to a missing observation; counting it as a lie would punish
    exactly the behaviour this design exists for."""
    step = plan.Step("open_url", {"url": "https://x.com"}, "desktop.open_url", {})
    unconfirmed = service.StepOutcome(
        step=step, reported=True, report_detail="",
        verification=goals.unverifiable("windows", "no window list"), seconds=0.1)
    contradicted = service.StepOutcome(
        step=step, reported=True, report_detail="",
        verification=goals.unmet(goals.STRONG, "windows", "nothing is open"), seconds=0.1)

    run = service.Run(request="x", plan=plan.Plan("x", steps=[step]), steps=[unconfirmed])
    check("reported + unverifiable is not an honesty gap", run.honesty_gap is False)
    check("and the outcome is 'unconfirmed', not 'done'", run.outcome == "unconfirmed")

    run2 = service.Run(request="x", plan=plan.Plan("x", steps=[step]), steps=[contradicted])
    check("reported + contradicted IS an honesty gap", run2.honesty_gap is True)
    check("and the outcome is 'failed'", run2.outcome == "failed")


async def test_done_is_reserved_for_verified():
    step = plan.Step("open_app", {"app": "x"}, "desktop.open_app", {})
    run = service.Run(request="x", plan=plan.Plan("x", steps=[step]), steps=[
        service.StepOutcome(step=step, reported=True, report_detail="",
                            verification=goals.met(goals.STRONG, "c", "f"), seconds=0.1)])
    check("only a verified run is 'done'", run.outcome == "done")
    check("and the summary names the evidence grade", "strong" in run.summary())


# ── understanding ───────────────────────────────────────────────────────────

async def test_only_an_exact_router_match_becomes_a_plan():
    """The regression that made the deterministic layer the dishonest one.

    `intents.resolve` returns near matches ranked by keyword as *suggestions*.
    Taking the top one turned "send an email to my boss" into "open the
    Connections screen" — a plausible substitution from the component that was
    supposed to be the exact one.
    """
    routed = plan._from_router("send an email to my boss")
    check("a keyword-only near match does not become a plan", routed is None)

    exact = plan._from_router("run a system health check")
    check("an exact pattern match does", exact is not None and exact.ok)
    check("and it is the automation, not a screen",
          exact.steps[0].goal == "run_automation")


async def test_the_model_cannot_invent_a_step():
    """The constraint the whole design rests on: a model that emits shell
    produces something nobody can check before or after it runs."""
    steps, why = plan._steps_from({"steps": [{"goal": "run_shell", "command": "rm -rf /"}]})
    check("a goal ARIES does not have is rejected", steps == [])
    check("and the rejection names the real choices", "open_url" in why)

    steps, why = plan._steps_from({"steps": [{"goal": "open_url"}]})
    check("a step missing its parameter is rejected", steps == [])
    check("saying which parameter", "url" in why)

    steps, _ = plan._steps_from({"steps": [{"goal": "open_url", "url": "https://x.com"}]})
    check("a valid step is accepted", len(steps) == 1)
    check("and carries the tool that attempts it", steps[0].tool == "desktop.open_url")


async def test_the_sections_the_planner_names_are_the_sections_that_exist():
    """Two lists of the Control Centre's screens, in two processes that cannot
    import each other. The planner tells the model which sections exist and
    validates against the same list — but the UI owns the real one, and a
    section added there and not here is a screen ARIES would refuse to open.

    Read as text rather than imported: `aries_ui.pages` pulls in GTK, which is
    not in this virtual environment (ADR-0004).
    """
    import re

    source = open(os.path.join(ROOT, "aries_ui", "pages", "__init__.py")).read()
    block = source[source.index("SECTIONS = ("):]
    # To the closing paren of the TUPLE, not the first ")" in it — every entry
    # ends with one.
    block = block[:block.index("\n)")]
    real = tuple(re.findall(r'\("([a-z_]+)"', block))
    check(f"the UI declares {len(real)} sections", len(real) > 5)
    check(f"the planner knows exactly those sections "
          f"(missing: {sorted(set(real) - set(plan.SECTIONS))}, "
          f"extra: {sorted(set(plan.SECTIONS) - set(real))})",
          set(real) == set(plan.SECTIONS))


async def test_an_enum_the_prompt_states_is_an_enum_the_validator_enforces():
    """The model answered "what is the weather tomorrow" with
    `open_section: weather` — a step shaped exactly like a real one, naming a
    screen that does not exist. Asking politely in a prompt is not a
    constraint."""
    steps, why = plan._steps_from({"steps": [{"goal": "open_section", "section": "weather"}]})
    check("a section ARIES does not have is refused", steps == [])
    check("and the real ones are named", "settings" in why)

    steps, why = plan._steps_from(
        {"steps": [{"goal": "run_automation", "automation_id": "aries.nonsense"}]})
    check("an automation ARIES does not have is refused", steps == [])
    check("and the real ones are named", "aries.health" in why)


async def test_a_plan_longer_than_a_desktop_request_is_refused():
    many = [{"goal": "open_url", "url": f"https://x{i}.com"} for i in range(plan.MAX_STEPS + 1)]
    steps, why = plan._steps_from({"steps": many})
    check("more steps than ARIES will run at once is refused", steps == [])
    check("and says how many it will run", str(plan.MAX_STEPS) in why)


async def test_the_planner_refuses_rather_than_leaving_the_machine():
    """`model_location = local` must not degrade to a remote provider under
    failure. A privacy default that gives way when it is inconvenient is not a
    default."""
    from agentic_core.config import runtime
    before = runtime.get_ai_provider()
    try:
        runtime.set_ai_provider("openai")
        made = await plan._from_model("open youtube", require_local=True)
        check("a non-local provider is refused when local is required", not made.ok)
        check("and nothing was sent", "Nothing was sent anywhere" in made.refusal)
    finally:
        runtime.set_ai_provider(before)


# ── the gates ───────────────────────────────────────────────────────────────

async def test_the_operator_ships_switched_off():
    await reset_db()
    async with async_session() as db:
        run = await service.run(db, "open the news screen")
    check("with operator.enabled off, nothing is attempted", run.steps == [])
    check("and ARIES says which switch", "operator.enabled" in run.plan.refusal)


async def test_the_engine_gates_follow_the_aries_switch():
    """The engine holds side-effecting tools unless they are named in
    `live_tools`. A person cannot consent to an environment variable, so ARIES
    drives it — and drives it on every run, because a gate armed at boot is
    wrong as soon as the user changes their mind."""
    from agentic_core.config import runtime

    off = service._arm(False)
    check("switched off, nothing is live", off["live_tools"] == "")
    check("and side effects are simulated", off["dry_run"] is True)

    on = service._arm(True)
    check("switched on, exactly the operator's tools are live",
          set(on["live_tools"].split(",")) == set(tools.TOOL_NAMES))
    check("and nothing wider than that", "*" not in on["live_tools"])
    check("and the engine's own state was written, not just reported",
          runtime._state.get("live_tools") == on["live_tools"])
    service._arm(False)


async def test_a_model_plan_is_proposed_and_an_exact_one_is_performed():
    """The interesting failure is not a model refusing — it is a model
    answering plausibly. So a guess is shown, and only an exact match acts."""
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set("operator.enabled", True, set_by="user")

    made = plan.Plan("open youtube", steps=[
        plan.Step("open_url", {"url": "https://youtube.com"}, "desktop.open_url",
                  {"url": "https://youtube.com"})], source="model", model="test")
    real_make = plan.make

    async def _fake(request, **kw):
        return made

    plan.make = _fake
    service.plan_mod.make = _fake
    try:
        async with async_session() as db:
            run = await service.run(db, "open youtube")
        check("a model plan is proposed, not performed", run.proposed)
        check("nothing was done", run.steps == [])
        check("and the outcome says so", run.outcome == "proposed")

        async with async_session() as db:
            run = await service.run(db, "open youtube", approve=True)
        check("approving it performs the plan", len(run.steps) == 1)
    finally:
        plan.make = real_make
        service.plan_mod.make = real_make


async def test_a_url_that_is_not_the_web_is_refused():
    """`file:` and `javascript:` would turn "open a URL" into "read this
    machine's files" or "run this" — a different capability with a different
    bar, and a natural-language front door is where that substitution gets
    attempted."""
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,<b>x",
                "/etc/shadow"):
        out = await tools.open_url({"url": bad}, {})
        check(f"{bad[:28]!r} is refused", out["success"] is False)
    # This is a scheme test, not a live browser journey. The old test opened a
    # real placeholder page on the user's desktop even under APP_ENV=test.
    from unittest.mock import patch
    with patch.object(tools, "_run", return_value=(True, "test launcher")), patch.object(tools, "_detach", return_value=(True, "test launcher")):
        out = await tools.open_url({"url": "https://www.kernel.org/"}, {})
    check("a normal https address is not refused for its scheme",
          "is not one of them" not in (out.get("details") or ""))


async def test_launching_a_gui_does_not_wait_for_it():
    """`aries-ui --section x` never returns when it becomes the Control Centre.
    Waiting on it blocked the Operator for the full launch timeout and then
    reported failure for something that had worked."""
    source = open(os.path.join(ROOT, "aries", "operator", "tools.py")).read()
    body = source[source.index("async def open_section("):]
    body = body[:body.index("async def run_automation(")]
    check("open_section detaches", "_detach(" in body)
    check("and does not wait", "_run(" not in body.replace("_detach(", ""))

    t0 = time.monotonic()
    await tools.open_section({"section": "__nonexistent_for_test__"}, {})
    check(f"it returns immediately ({time.monotonic() - t0:.2f}s)",
          time.monotonic() - t0 < 2.0)


async def test_an_automation_run_in_the_same_second_counts_as_this_run():
    """A unit mismatch in the component whose whole job is deciding what is
    true. `started_at` is stored to whole seconds and `since` carried
    microseconds, so a health pass that had just succeeded was reported as "a
    run from before this task began"."""
    from datetime import datetime, timezone

    await reset_db()
    from aries.automations.runner import run_automation
    since = datetime.now(timezone.utc).replace(tzinfo=None)
    out = await run_automation("aries.health", trigger="test", force=True)
    check(f"the health automation ran ({out.get('status')})", out.get("ran"))

    async with async_session() as db:
        v = await goals.verify("run_automation",
                               {"automation_id": "aries.health", "since": since}, 
                               _desktop(), db)
    check("the run that just happened is recognised as this task's",
          v.verdict == goals.MET, )
    check("and it is proof, read from ARIES's own records", v.grade == goals.PROOF)


async def test_the_working_set_is_released_after_a_run():
    """The Operator is the first real writer of the working set — everything it
    pulled in to answer one request, gone when the request is over."""
    from aries.lifecycle import working

    await reset_db()
    async with async_session() as db:
        run = await service.run(db, "something ARIES cannot possibly do xyzzy",
                                dry_run=True)
    async with async_session() as db:
        held = await working.summary(db)
    check(f"nothing is held after the run ({held['held']} row(s))", held["held"] == 0)
    check("and the run happened at all", bool(run.task_id))


async def test_every_run_is_audited_with_both_numbers():
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set("operator.enabled", True, set_by="user")
    async with async_session() as db:
        await service.run(db, "run a system health check")

    from sqlalchemy import text
    async with async_session() as db:
        rows = (await db.execute(text(
            "SELECT action, detail FROM audit_events WHERE action = 'operator.ran'"
        ))).fetchall()
    check("the run is in the audit log", len(rows) >= 1)
    detail = rows[-1][1] if rows else ""
    for field in ("reported_success", "verified_success", "honesty_gap"):
        check(f"the audit line carries {field}", field in str(detail))


async def test_shell_payload_preserves_unicode():
    import json
    from types import SimpleNamespace
    from unittest.mock import patch
    payload = json.dumps({"title": "Вести — Firefox's page"}, ensure_ascii=False)
    with patch.object(desktop.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=repr((payload,)), stderr="")):
        result, why = desktop._call_shell("Windows")
    check("D-Bus Unicode and quotes survive decoding", result == payload and not why)


async def test_service_launch_uses_desktop_lifetime():
    from unittest.mock import patch
    with patch.dict(os.environ, {"INVOCATION_ID": "test-service"}), patch.object(tools.shutil, "which", return_value="/usr/bin/tool"), patch.object(tools, "_run", return_value=(True, "")) as launch:
        ok, _ = tools._detach(["firefox", "--new-window", "https://www.kernel.org/"])
    argv = launch.call_args.args[0]
    check("service applications start in an independent desktop service", ok and argv[:3] == ["systemd-run", "--user", "--collect"])
    check("the URL is passed as a literal argument", argv[-1] == "https://www.kernel.org/")


async def test_open_app_reuses_identity_and_refuses_unknown_inventory():
    from unittest.mock import patch
    w = desktop.Window(id='42', title='Document', wm_class='Code', app_id='code.desktop',
                       pid=500, focused=False, workspace=1, minimised=True)
    with patch.object(tools, '_desktop_file', return_value='code.desktop'), \
         patch.object(desktop, 'read_windows', return_value=([w], '', {})), \
         patch.object(desktop, 'focus_window', return_value=(True, 'Requested')) as focus, \
         patch.object(tools, '_detach', return_value=(True, 'started')) as launch:
        result = await tools.open_app({'app':'vs code'}, {})
        check('existing minimised app is activated instead of launched', result['success'] and focus.call_count == 1 and not launch.called)
        w = replace(w, focused=True, minimised=False); focus.reset_mock()
        desktop.read_windows.return_value=([w], '', {})
        result = await tools.open_app({'app':'vs code'}, {})
        check('already focused app needs no action', result['success'] and not focus.called and not launch.called)
        w = replace(w, focused=False); desktop.read_windows.return_value=([w], '', {}); focus.return_value=(False, 'Observed window has closed')
        result = await tools.open_app({'app':'vs code'}, {})
        check('stale window does not trigger duplicate launch', not result['success'] and not launch.called)
    with patch.object(tools, '_desktop_file', return_value='code.desktop'), \
         patch.object(desktop, 'read_windows', return_value=(None, 'offline', None)), \
         patch.object(tools, '_detach') as launch:
        result = await tools.open_app({'app':'code'}, {})
        check('unknown inventory is not treated as no open windows', not result['success'] and not launch.called)
    w=replace(w, title='Visual Studio Code', app_id='unrelated.desktop')
    with patch.object(tools, '_desktop_file', return_value='code.desktop'), \
         patch.object(desktop, 'read_windows', return_value=([w], '', {})), \
         patch.object(desktop, 'focus_window') as focus, \
         patch.object(tools, '_detach', return_value=(True, 'started')) as launch:
        result = await tools.open_app({'app':'code'}, {})
        check('title matching never reuses another application', result['success'] and launch.called and not focus.called)


async def test_open_app_requires_presentation():
    d = _desktop(windows=[('Firefox', 'firefox')], processes=['firefox'])
    d.windows[0]=replace(d.windows[0], minimised=True)
    v=await goals.verify('open_app', {'app':'firefox'}, d)
    check('minimised window is not a presented application', not v.met)
    d.windows[0]=replace(d.windows[0], minimised=False, focused=False)
    v=await goals.verify('open_app', {'app':'firefox'}, d)
    check('background window is not a presented application', not v.met)
    spoof = _desktop(windows=[('Firefox', 'unrelated')], processes=['firefox'])
    v=await goals.verify('open_app', {'app':'firefox'}, spoof)
    check('a title alone cannot prove application identity', not v.met)
    code = _desktop(windows=[('Editor', 'code')], processes=['code'])
    v=await goals.verify('open_app', {'app':'vs code'}, code)
    check('VS Code alias verifies the actual editor identity', v.met)


async def test_snap_application_identity_verification():
    from unittest.mock import patch
    d = _desktop(windows=[('Mozilla Firefox', 'firefox_firefox')], processes=['firefox'])
    with patch.object(tools, '_desktop_file', return_value='firefox_firefox.desktop'):
        check('Snap Firefox verifies using installed desktop identity', (await goals.verify('open_app', {'app':'Firefox'}, d)).met)
        d.windows[0] = replace(d.windows[0], focused=False)
        check('Snap identity alone cannot prove presentation', not (await goals.verify('open_app', {'app':'Firefox'}, d)).met)
        d.windows[0] = replace(d.windows[0], focused=True, app_id='unrelated.desktop', wm_class='unrelated')
        check('Firefox title in unrelated app is not proof', not (await goals.verify('open_app', {'app':'Firefox'}, d)).met)


async def test_bridge_capabilities_are_not_build_identity():
    from types import SimpleNamespace
    from unittest.mock import patch
    xml='<node><interface name="org.aries.Shell"><method name="Ping"/><method name="Windows"/></interface></node>'
    with patch.object(desktop.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=xml)):
        result=desktop.capabilities()
        check("older bridge reports specific missing focus capability",result['missing']==['FocusWindow'] and not result['full_desktop_support'])
        check("core does not depend on shell revision",result['core_requires_shell'] is False)
    with patch.object(desktop.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=xml.replace('</interface>','<method name="FocusWindow"/></interface>'))):
        check("complete protocol accepted without matching build stamp",desktop.capabilities()['full_desktop_support'])
    with patch.object(desktop.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='invalid')):
        check("invalid desktop introspection fails closed",not desktop.capabilities()['available'])


async def test_locked_session_is_not_an_update_request():
    from types import SimpleNamespace
    from unittest.mock import patch
    with patch.object(desktop.subprocess, 'run', return_value=SimpleNamespace(returncode=1,stdout='',stderr='ServiceUnknown')), patch.object(desktop,'session_locked',return_value=True):
        _, reason = desktop._call_shell('Windows')
        check("locked desktop explicitly identified without logout advice",'locked' in reason and 'log out' not in reason)


async def test_desktop_observation_and_focus_are_verified():
    from unittest.mock import patch
    import json
    for payload in ['{}','[]','{"windows":[{"id":"1","focused":"false"}]}']:
        with patch.object(desktop,'_call_shell',return_value=(payload,'')):
            check('malformed window list is not an empty desktop '+payload,desktop.read_windows()[0] is None)
    w=desktop.Window('1','Title','app','app.desktop',123,False,0,False)
    with patch.object(desktop,'_call_shell',return_value=('{"accepted":true}','')), patch.object(desktop,'read_windows',return_value=([w],'',None)):
        check('accepted focus request without changed state fails',desktop.focus_window(w)[0] is False)
    focused=desktop.Window('1','Title','app','app.desktop',123,True,0,False)
    with patch.object(desktop,'_call_shell',return_value=('{"accepted":true}','')), patch.object(desktop,'read_windows',return_value=([focused],'',None)):
        check('focus succeeds only on independently observed target',desktop.focus_window(w)[0] is True)


if __name__ == "__main__":
    run_module(sys.modules[__name__])
