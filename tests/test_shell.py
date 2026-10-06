"""The ARIES Shell's core side: the router, the search, the status, the tokens.

WHAT IS AND IS NOT TESTED HERE
------------------------------
Everything the shell ASKS for. The extension itself is JavaScript inside
`gnome-shell` and cannot be imported by this suite at all — it is tested by
`./scripts/test-shell.sh`, which runs it in a headless nested GNOME Shell and
watches whether it loads, errors and tears down cleanly.

The split is the same one Entry 011 drew for the Control Centre: the process
boundary removes the compiler, so what crosses it is declared as data and pinned
from the side that can run tests. Two suites, one contract.
"""
from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-shell")

import httpx  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.shell import intents, search, tokens  # noqa: E402
from aries.shell.status import status  # noqa: E402

from aries.api.app import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _scan_js(forbidden: tuple[str, ...]) -> list[str]:
    """Search every shell source for constructs that must not appear — in the
    CODE only.

    Comments are stripped first, and that is not a detail: both of these scans
    first failed against the paragraphs explaining why the construct is
    forbidden. A checker that reads its own documentation as a violation is
    checking nothing, and would have been "fixed" by deleting the explanation.
    """
    base = os.path.join(ROOT, "shell", "aries@aries.local")
    offences = []
    for directory, _dirs, files in os.walk(base):
        for name in sorted(files):
            if not name.endswith(".js"):
                continue
            with open(os.path.join(directory, name)) as fh:
                body = fh.read()
            body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
            body = re.sub(r"^\s*//.*$", "", body, flags=re.M)
            for needle in forbidden:
                if needle in body:
                    offences.append(f"{name}: {needle}")
    return offences


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ── the router ──────────────────────────────────────────────────────────────

async def test_every_extension_module_parses():
    """A syntax error in the extension is the most expensive bug available here.

    On Wayland a shell that throws during startup cannot be restarted without
    logging out — there is no Alt+F2 'r' — so a stray brace does not produce a
    failing test, it produces a desktop the user has to log out of to recover.
    Nothing in the suite caught that: the JS scans read the files as *text*, and
    text with a syntax error scans perfectly well.

    ESM compiles a whole module before evaluating its imports, so `import()`
    reports a SyntaxError even though `gi://Meta` cannot resolve outside
    gnome-shell. The resolution failure is expected and ignored; a SyntaxError
    is not.
    """
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("gjs"):
        check("skipped — gjs is not installed", True)
        return

    files = sorted(glob.glob(os.path.join(ROOT, "shell", "**", "*.js"), recursive=True))
    check(f"found {len(files)} extension module(s) to parse", len(files) > 0)

    for path in files:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(f"import('file://{path}').then(() => print('LOADED'))"
                     f".catch(e => print('ERR ' + String(e)));\n")
            probe = fh.name
        try:
            out = subprocess.run(["gjs", "-m", probe], capture_output=True,
                                 text=True, timeout=30)
        finally:
            os.unlink(probe)
        text = (out.stdout or "") + (out.stderr or "")
        name = os.path.relpath(path, ROOT)
        ok = "SyntaxError" not in text
        check(f"{name} parses" + ("" if ok else f" — {text.strip()[:120]}"), ok)


async def test_navigating_raises_the_window_as_well_as_navigating_it():
    """On Wayland a process that is not focused cannot raise its own window:
    `present()` without an activation token is ignored and the window is marked
    as demanding attention instead.

    So asking ARIES for a section while the Control Centre sat behind a terminal
    navigated it correctly and left it exactly where it was — which reads as
    nothing happening. The compositor is allowed to raise it, and the extension
    runs inside the compositor. The Control Centre cannot fix this from its own
    side, which is why the test lives here.
    """
    ext = open(os.path.join(ROOT, "shell", "aries@aries.local", "extension.js")).read()
    check("the extension knows the Control Centre's .desktop id",
          "aries-control-centre.desktop" in ext)
    check("and raises the window rather than only spawning",
          "Main.activateWindow" in ext)

    body = ext[ext.index("    openControlCentre("):]
    body = body[:body.index("\n    /** Ask ARIES")] if "\n    /** Ask ARIES" in body else body[:2000]
    check("navigating asks for the raise", "raiseControlCentre" in body)

    installed = os.path.expanduser(
        "~/.local/share/applications/aries-control-centre.desktop")
    check("and that .desktop file is actually installed", os.path.exists(installed))


async def test_the_shell_exposes_windows_read_only():
    """The Operator can only verify its own work if it can see the desktop, and
    on Wayland only the compositor can. Reading is the whole of it: a method
    that could also focus or raise would mean the call ARIES makes to check its
    work could change it, after which no verification means anything."""
    dbus = open(os.path.join(ROOT, "shell", "aries@aries.local", "lib", "dbus.js")).read()
    check("the D-Bus surface declares Windows()", '<method name="Windows">' in dbus)
    check("and it returns a string", 'name="windows"' in dbus)

    start = dbus.index("    Windows() {")
    # Observation ends before the separate, explicit window-action method.
    body = dbus[start:dbus.index("    FocusWindow(", start)]
    for forbidden, why in (("activate(", "focusing a window"),
                           ("raise(", "raising a window"),
                           ("delete(", "closing a window"),
                           ("move_", "moving a window"),
                           ("minimize(", "minimising a window")):
        check(f"Windows() does not act: no {why}", forbidden not in body)


async def test_the_router_returns_actions_not_closures():
    """The whole reason it moved out of the GTK process: an action is data, so
    two front ends in two languages can both carry it out."""
    out = intents.resolve("scan for news")
    check("a phrase resolves", out["matched"] and out["exact"])
    action = out["results"][0]["action"]
    check("to an action describing what to do", action["kind"] == "run_automation")
    check("naming the automation", action["automation_id"] == "aries.news")
    check("and nothing in the reply is a callable",
          all(isinstance(v, (str, int, float, bool, list, dict, type(None)))
              for r in out["results"] for v in r["action"].values()))


async def test_actions_come_before_navigation():
    """Entry 011's bug, pinned in its new home: 'scan for news' must scan, not
    navigate to News. In a router with overlapping patterns order is precedence,
    and a verb is more specific than a noun."""
    for phrase, kind in (("scan for news", "run_automation"),
                         ("run system health", "run_automation"),
                         ("make my morning brief shorter", "feedback"),
                         ("show news", "navigate"),
                         ("show my brief", "navigate")):
        action = intents.resolve(phrase)["results"][0]["action"]
        check(f"'{phrase}' → {kind}", action["kind"] == kind)


async def test_a_captured_subject_reaches_the_action():
    out = intents.resolve("why do you think AI matters to me?")
    action = out["results"][0]["action"]
    check("an explain intent carries its subject", action["kind"] == "explain")
    check("captured from the sentence", action.get("subject") == "AI matters to me")
    out = intents.resolve("disable security news")
    check("and a topic reaches the avoid action",
          out["results"][0]["action"].get("topic") == "security")


async def test_unknown_input_is_refused_with_real_examples():
    out = intents.resolve("xyzzy plugh")
    check("nothing matches", out["results"] == [] and not out["matched"])
    check("and it says so plainly rather than inventing something",
          "cannot do" in out["unmatched_reason"])
    check("offering capabilities that actually exist", len(out["suggestions"]) >= 3)
    known = {i.example for i in intents.INTENTS}
    check("every suggestion is a real example from the table",
          all(s in known for s in out["suggestions"]))


async def test_an_empty_query_offers_somewhere_to_start():
    out = intents.resolve("")
    check("an empty command bar is not an empty list", len(out["results"]) > 0)
    check("and nothing claims to have matched", out["matched"] is False)


# ── search ──────────────────────────────────────────────────────────────────

async def test_file_search_refuses_to_look_where_privacy_forbids():
    """`privacy.excluded_paths` is ARIES policy. The shell asks rather than
    walking the filesystem itself precisely so this rule has one implementation."""
    # Deliberately NOT `~/.ssh`: the walk skips hidden entries anyway, so an
    # exclusion test using one proves nothing — it would pass with the exclusion
    # removed. A visible directory makes the exclusion the only thing that can
    # stop it, which is the property under test.
    home = os.path.expanduser("~")
    secret = os.path.join(home, "aries_privacy_probe_dir")
    os.makedirs(secret, exist_ok=True)
    probe = os.path.join(secret, "aries_search_probe_key")
    with open(probe, "w") as fh:
        fh.write("not a real key")
    try:
        out = search.search_files("aries_search_probe", excluded=[secret])
        check("a file inside an excluded path is never returned",
              all("aries_search_probe" not in r["title"] for r in out["results"]))
        # And the check is not merely "the name did not match": prove the walk
        # would otherwise have found it.
        allowed = search.search_files("aries_search_probe", excluded=[])
        found = any("aries_search_probe" in r["title"] for r in allowed["results"])
        check("and it WOULD have been found without the exclusion — so the "
              "exclusion is what stopped it, not the search being weak", found)
    finally:
        os.remove(probe)
        os.rmdir(secret)


async def test_file_search_is_bounded_and_says_when_it_stopped():
    out = search.search_files("e", excluded=[])
    check("one character is refused rather than walking the disk",
          out["results"] == [] and "two characters" in out["reason"])
    out = search.search_files("doc", excluded=[])
    check("a real query returns something", isinstance(out["results"], list))
    check("and reports how much it looked at", out["scanned"] > 0)
    check("truncation is reported rather than hidden", "truncated" in out)


async def test_hidden_files_are_skipped():
    home = os.path.expanduser("~")
    hidden = os.path.join(home, ".aries_hidden_probe_file")
    with open(hidden, "w") as fh:
        fh.write("x")
    try:
        out = search.search_files("aries_hidden_probe", excluded=[])
        check("a dotfile is not offered in a launcher",
              all("aries_hidden_probe" not in r["title"] for r in out["results"]))
    finally:
        os.remove(hidden)


async def test_settings_and_automations_are_searchable():
    hits = search.search_settings("temperature")
    check("settings are found by what they are called", len(hits) > 0)
    check("and offered as somewhere to go, not something to run",
          hits[0]["action"]["kind"] == "navigate")
    check("anchored at the setting itself", hits[0]["action"]["anchor"] == hits[0]["id"])

    runs = search.search_automations("news")
    check("an automation is found", len(runs) == 1)
    check("and offered as something to RUN — that is what a command bar is for",
          runs[0]["action"]["kind"] == "run_automation")


# ── the status the panel polls ──────────────────────────────────────────────

async def test_the_panel_status_is_small_and_judged_server_side():
    await reset_db()
    async with async_session() as db:
        out = await status(db)
    for key in ("severity", "state", "summary", "decisions", "notifications",
                "automations_enabled", "automations_total", "background_mode",
                "autonomy"):
        check(f"the panel is told '{key}'", key in out)
    check("severity is a word from the one vocabulary, not a number",
          out["severity"] in ("ok", "info", "notice", "warning", "critical"))
    check("the payload stays small — it is polled forever", len(out) < 25)
    check("and carries nothing that needs rendering",
          not any(isinstance(v, (list, dict)) for v in out.values()))


async def test_notification_severity_is_converted_not_passed_through():
    """`AriesNotification.severity` is an integer enum; the health judge's is a
    string. They look interchangeable and are not — reading one as the other put
    the number 1 where a severity name belonged."""
    await reset_db()
    from aries.health.findings import Severity
    from aries.notify.policy import AriesNotification
    async with async_session() as db:
        db.add(AriesNotification(key="t", source="test", level=2,
                                 severity=int(Severity.WARNING), title="t",
                                 disposition="delivered"))
        await db.commit()
        out = await status(db)
    check("the severity reaches the panel as a word", out["notification_severity"] == "warning")


# ── the HTTP surface ────────────────────────────────────────────────────────

async def test_the_shell_endpoints_serve_what_the_extension_reads():
    await reset_db()
    async with await _client() as c:
        r = await c.get("/api/aries/shell/status")
        check("the panel status is served", r.status_code == 200)

        r = await c.get("/api/aries/shell/config")
        check("the shell's configuration is served", r.status_code == 200)
        body = r.json()
        check("with the settings, keyed without the section prefix",
              "dock_position" in body["settings"] and "shell.dock" not in body["settings"])
        check("and the design tokens, so nothing is hard-coded in JavaScript",
              "space" in body["tokens"] and "dark" in body["tokens"])

        r = await c.post("/api/aries/command", json={"text": "temperature"})
        check("the command router is served", r.status_code == 200)
        kinds = {x["kind"] for x in r.json()["results"]}
        check("mixing commands, automations and settings in one list",
              {"command", "setting"} <= kinds)

        r = await c.post("/api/aries/command", json={"text": ""})
        check("an empty query is a suggestion list, not an error",
              r.status_code == 200 and len(r.json()["results"]) > 0)


async def test_the_shell_cannot_ask_aries_for_anything_it_likes():
    async with await _client() as c:
        r = await c.post("/api/aries/shell/act", json={"kind": "rm_rf"})
        check("an unknown action is refused", r.status_code == 400)
        r = await c.post("/api/aries/shell/act", json={"kind": "run_automation"})
        check("and a malformed one is refused rather than guessed at",
              r.status_code == 400)


async def test_carrying_out_an_action_takes_the_audited_path():
    """There is no privileged desktop route into ARIES."""
    from agentic_core.security.permissions import permission_for
    check("reading what a phrase means needs only view_data",
          permission_for("POST", "/api/aries/command").value == "view_data")
    check("but carrying it out needs execute — the same as a Run now button",
          permission_for("POST", "/api/aries/shell/act").value == "execute")
    check("and the shell's own configuration is not writable by view_data",
          permission_for("PUT", "/api/aries/shell/config").value == "manage_tools")


async def test_feedback_from_the_shell_is_recorded_like_any_other():
    await reset_db()
    async with await _client() as c:
        r = await c.post("/api/aries/shell/act",
                         json={"kind": "feedback", "text": "only notify me if it is important"})
        check("the shell can pass feedback to ARIES", r.status_code == 200)
        r2 = await c.get("/api/aries/learning/feedback")
        rows = r2.json()["feedback"]
        check("and it lands in the same feedback history as every other route",
              len(rows) == 1)


# ── degraded and absent states ──────────────────────────────────────────────

async def test_a_broken_component_reaches_the_panel_as_degraded():
    """The panel must be able to say ARIES is unwell. The judgement is made here
    so the top bar and the window it opens cannot disagree."""
    await reset_db()
    import aries.runtime.status as runtime

    real = runtime.component_snapshot

    async def broken(db):
        snapshot = await real(db)
        snapshot["database"] = {"ok": False, "detail": "disk I/O error"}
        return snapshot

    runtime.component_snapshot = broken
    try:
        async with async_session() as db:
            out = await status(db)
        check("a failed component makes the state DEGRADED", out["state"] == "DEGRADED")
        check("and raises the severity above ok", out["severity"] != "ok")
        check("with a summary naming how many things are wrong",
              "component" in out["summary"])
    finally:
        runtime.component_snapshot = real


async def test_a_pending_decision_raises_attention_but_not_severity():
    """ARIES waiting for a human is ARIES working correctly. A badge, not an
    alarm — otherwise the one colour that means 'something is wrong' stops
    meaning it."""
    await reset_db()
    from agentic_core.database.models import ActionProposal
    # Compared against the same machine a moment earlier rather than against
    # "ok": under APP_ENV=test the workers are deliberately not started, so ARIES
    # reads as degraded for a reason that has nothing to do with this test. An
    # absolute assertion here would have been testing the harness.
    async with async_session() as db:
        before = await status(db)
        db.add(ActionProposal(kind="test", title="needs you", status="proposed",
                              payload="{}"))
        await db.commit()
        after = await status(db)
    check("the decision is counted", after["decisions"] == before["decisions"] + 1)
    check("and the severity is unchanged by it — waiting for a human is ARIES "
          "working correctly, not a fault", after["severity"] == before["severity"])


# ── the shell's own settings ────────────────────────────────────────────────

async def test_the_shell_takes_nothing_without_being_asked():
    """§11's courtesy, extended to the desktop: installing the extension does
    not switch the shell on, and switching it on does not replace the user's
    wallpaper."""
    from aries.settings import get_def
    check("the shell ships off", get_def("shell.enabled").default is False)
    check("and only a person may switch it on", get_def("shell.enabled").user_only is True)
    check("the wallpaper is left alone by default",
          get_def("shell.wallpaper").default == "system")
    check("and 'system' is an offered choice, not only a default",
          "system" in get_def("shell.wallpaper").choices)


async def test_the_wallpaper_is_borrowed_and_returned():
    """The same discipline as the display timeout in Entry 013: if ARIES changes
    something the user owns, it records what was there first."""
    from aries.settings import get_def
    d = get_def("shell.restore_wallpaper")
    check("there is somewhere to record the previous background", d is not None)
    check("it starts empty, meaning nothing has been taken", d.default == "")
    check("and it is hidden behind Advanced rather than offered as a control",
          d.advanced is True)


async def test_every_shell_setting_lives_in_aries():
    """The extension has no preferences of its own — no second place to
    configure ARIES. Asserted rather than promised."""
    async with await _client() as c:
        body = (await c.get("/api/aries/shell/config")).json()
    for key in ("enabled", "top_bar", "dock", "dock_position", "dock_autohide",
                "command_bar", "command_shortcut", "animations", "wallpaper",
                "file_search", "notifications_in_shell", "status_poll_seconds"):
        check(f"the shell reads '{key}' from ARIES", key in body["settings"])


async def test_the_only_gsettings_key_is_the_one_mutter_insists_on():
    import glob
    base = os.path.join(ROOT, "shell", "aries@aries.local", "schemas")
    schemas = glob.glob(os.path.join(base, "*.gschema.xml"))
    check("there is exactly one schema", len(schemas) == 1)
    with open(schemas[0]) as fh:
        xml = fh.read()
    check("holding exactly one key", xml.count("<key ") == 1)
    check("and that key is the keybinding", 'name="command-bar"' in xml)


# ── the design system ───────────────────────────────────────────────────────

async def test_the_extension_carries_everything_it_references():
    """An extension is copied to a system directory, so every file it names must
    be inside it. The wallpaper pointed at `${extension}/share/backgrounds/`,
    which exists in the repository and not in /usr/local/share — GNOME answers a
    missing wallpaper by drawing the previous one, so the setting "worked", the
    log said so, and the desktop did not change."""
    import re
    base = os.path.join(ROOT, "shell", "aries@aries.local")
    missing = []
    for directory, _dirs, files in os.walk(base):
        for name in sorted(files):
            if not name.endswith(".js"):
                continue
            with open(os.path.join(directory, name)) as fh:
                body = re.sub(r"/\*.*?\*/", "", fh.read(), flags=re.S)
            # Any path built from the extension's own directory.
            for ref in re.findall(r"\$\{(?:base|shell\.path|this\._shell\.path)\}/([\w./-]+)", body):
                if not os.path.exists(os.path.join(base, ref)):
                    missing.append(f"{name}: {ref}")
    check(f"every file the extension references is inside it"
          f"{'' if not missing else ': ' + str(missing)}", missing == [])


async def test_the_shell_stylesheet_matches_the_tokens():
    """Two toolkits, one design language. The stylesheet is generated, so an
    edit to it — or a token changed without regenerating — fails here rather
    than as a shade of grey nobody can place."""
    path = os.path.join(ROOT, "shell", "aries@aries.local", "stylesheet.css")
    check("the generated stylesheet exists", os.path.exists(path))
    with open(path) as fh:
        on_disk = fh.read()
    check("and is exactly what the tokens produce — regenerate with "
          "./scripts/aries-shell generate", on_disk == tokens.shell_stylesheet())


async def test_the_stylesheet_has_no_css_the_shell_cannot_parse():
    """GNOME Shell's CSS is a subset: no variables, no calc(), no nesting. A
    rule it cannot parse is dropped silently, which is the worst failure mode a
    stylesheet has."""
    # Strip the comments first: the header explains which constructs St cannot
    # parse, and scanning the whole file matched the explanation rather than any
    # rule. A checker that reads its own documentation as a violation is not
    # checking anything.
    css = re.sub(r"/\*.*?\*/", "", tokens.shell_stylesheet(), flags=re.S)
    for forbidden in ("var(--", "calc(", "@media", ":root"):
        check(f"no {forbidden} — St would drop the rule without saying so",
              forbidden not in css)

    # 8-digit hex is the one that cost most. St drops the declaration without a
    # word, so a translucent surface renders with no background at all — the
    # dock lost its panel and ARIES Search became fully transparent over the
    # window behind it, while the six-digit colours beside them worked.
    eight_digit = re.findall(r"#[0-9a-fA-F]{8}\b", tokens.shell_stylesheet())
    check(f"no 8-digit #RRGGBBAA hex — St cannot parse it and says nothing"
          f"{'' if not eight_digit else ': ' + str(eight_digit[:4])}", eight_digit == [])
    check("alpha is expressed as rgba(), which St has always supported",
          "rgba(" in tokens.shell_stylesheet())

    # `!important` is allowed in exactly one place. Yaru's dark stylesheet sets
    # `#panel { background-color: #131313 !important }`, and an equally-specific
    # rule without it loses whatever order the sheets load in — overriding a
    # theme that shouts requires shouting back. Everywhere ELSE it would mean a
    # specificity problem we should have fixed instead, so the rule is: only in
    # the session-theme section, and only on selectors that are GNOME's.
    own_widgets = re.sub(r"/\*.*?\*/", "", "\n".join(
        tokens.shell_stylesheet().split("ARIES over the session theme")[0].splitlines()),
        flags=re.S)
    check("ARIES's own widgets never need !important",
          "!important" not in own_widgets)
    theme = tokens.session_theme()
    shouted = [line.strip() for line in theme.splitlines()
               if "!important" in line and not line.strip().startswith("*")]
    check(f"the session-theme section does use it, on GNOME's selectors "
          f"({len(shouted)} rules)", len(shouted) > 0)
    check("every colour is resolved to a literal", "alpha(" not in css)


async def test_both_light_and_dark_are_complete():
    check("the two palettes describe the same things",
          set(tokens.DARK) == set(tokens.LIGHT))
    css = tokens.shell_stylesheet()
    check("and both are written out — St cannot compute one from the other",
          "/* ── dark ─" in css and "/* ── light ─" in css)
    for name in tokens.SEVERITIES:
        check(f"severity '{name}' has a class", f"aries-sev-{name}" in css)


async def test_the_severity_vocabulary_is_the_same_one_everywhere():
    from aries_ui import design
    check("the shell and the Control Centre agree on the severities",
          set(tokens.SEVERITIES) == set(design.SEVERITY_CLASS))


# ── what the extension declares ─────────────────────────────────────────────

async def test_the_extension_declares_what_it_needs_and_nothing_more():
    import json
    base = os.path.join(ROOT, "shell", "aries@aries.local")
    with open(os.path.join(base, "metadata.json")) as fh:
        meta = json.load(fh)
    check("the extension is named for this GNOME", "50" in meta["shell-version"])
    check("with a stable uuid", meta["uuid"] == "aries@aries.local")

    # The one GSettings key that exists, and why.
    schema = os.path.join(base, "schemas",
                          "org.gnome.shell.extensions.aries.gschema.xml")
    with open(schema) as fh:
        xml = fh.read()
    check("the schema holds only the keybinding Mutter insists on",
          xml.count("<key ") == 1 and 'name="command-bar"' in xml)
    check("and says why it is not where the preferences live",
          "GSettings key" in xml)


async def test_no_javascript_file_talks_to_the_database():
    """The architecture, asserted rather than promised: the shell reaches ARIES
    over HTTP and by no other route."""
    offences = _scan_js(("sqlite", "aries.db", "Gda.", "psycopg"))
    check(f"no shell file reaches for a database{'' if not offences else ': ' + str(offences)}",
          offences == [])


async def test_nothing_in_the_shell_blocks_the_compositor():
    """A synchronous HTTP call would freeze the desktop for as long as ARIES took
    to answer, and ARIES answers some questions by running an automation."""
    offences = _scan_js(("send_and_read(", "send_message(", "spawn_command_line_sync",
                         "GLib.usleep"))
    check(f"no synchronous call on the thread that draws the desktop"
          f"{'' if not offences else ': ' + str(offences)}", offences == [])


# ── M13 regressions ─────────────────────────────────────────────────────────
#
# One test per bug found in M13. Where a bug cannot be caught without a real
# display or a real login, the test here pins the *invariant that made it
# possible* and names the end-to-end journey that catches the rest — so the
# reason it is not automated here is written down rather than implied.


async def test_no_launcher_execs_itself():
    """M13-A. `scripts/aries-ui` contained `exec "$HOME/aries/scripts/aries-ui"`
    — itself. An infinite loop, no window, ever, for days, while 1511 assertions
    stayed green. A launcher is not a component, it is the seam between them."""
    import re
    scripts = os.path.join(ROOT, "scripts")
    offences = []
    for name in sorted(os.listdir(scripts)):
        path = os.path.join(scripts, name)
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            continue
        with open(path, errors="replace") as fh:
            body = fh.read()
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("exec "):
                continue
            target = stripped[5:].strip().split()[0].strip('"')
            expanded = os.path.realpath(
                os.path.expandvars(target.replace("$(dirname \"$0\")", scripts)))
            if expanded == os.path.realpath(path):
                offences.append(f"{name} execs itself")
    check(f"no script in scripts/ execs itself"
          f"{'' if not offences else ': ' + str(offences)}", offences == [])


async def test_the_control_centre_launcher_runs_the_control_centre():
    """M13-A, the positive half: it must reach the GTK application, not merely
    exit 0. A launcher test that only checks an exit code is what let this
    through."""
    with open(os.path.join(ROOT, "scripts", "aries-ui")) as fh:
        body = fh.read()
    check("it runs the Control Centre module", "python3 -m aries_ui" in body)
    check("on the system interpreter, where PyGObject lives (ADR-0004)",
          "/usr/bin/python3" in body)
    check("with the repository on PYTHONPATH, or the module cannot be found",
          "PYTHONPATH" in body)
    check("and the module it names actually exists",
          os.path.exists(os.path.join(ROOT, "aries_ui", "__main__.py")))


async def test_the_panel_mark_does_not_depend_on_an_svg_loader():
    """M13-B. The mark used `Gio.FileIcon` on an SVG. This machine has
    `libpixbufloader_svg.so` on disk but not registered in the gdk-pixbuf loader
    cache, so the icon resolved to an empty texture — silently. Drawn now."""
    with open(os.path.join(ROOT, "shell", "aries@aries.local", "lib", "panel.js")) as fh:
        body = fh.read()
    check("the mark is drawn, not loaded from a file",
          "St.DrawingArea" in body and "cr.stroke()" in body)
    check("no file icon is used for it",
          "Gio.icon_new_for_string" not in body)
    check("and it takes its colour from the theme rather than pinning a hue",
          "get_foreground_color" in body)


async def test_the_panel_label_cannot_be_silently_ellipsized():
    """M13-C. The panel gave the label less than its natural width and St
    quietly rendered "ARI…". A four-letter name that does not fit is a name
    nobody reads, and nothing reported it."""
    with open(os.path.join(ROOT, "shell", "aries@aries.local", "lib", "panel.js")) as fh:
        body = fh.read()
    check("ellipsizing is turned off for the mark's label",
          "ellipsize = 0" in body)
    check("and it is kept to one line", "single_line_mode = true" in body)


async def test_section_navigation_is_an_action_not_a_race():
    """M13-D. `--section` set a pending field and called activate(), then applied
    the section again in case the window already existed. Which branch ran
    depended on whether do_activate had cleared the field — so a cold start and
    a second invocation behaved differently, and it landed on Settings.

    The end-to-end proof is `./scripts/aries-e2e`, which drives real windows and
    reads back where each one landed; this pins the mechanism that makes that
    possible."""
    with open(os.path.join(ROOT, "aries_ui", "app.py")) as fh:
        body = fh.read()
    # The name survives only inside the docstring explaining why it is gone, so
    # the docstrings are stripped before looking for it in the code.
    import re
    code = re.sub(r'\"\"\".*?\"\"\"', "", body, flags=re.S)
    check("no pending-section field remains in the code to race with activation",
          "_pending_section" not in code)
    check("navigation is a stateful action",
          'Gio.SimpleAction.new_stateful' in body and '"section"' in body)
    check("whose state is readable, which is what makes the destination testable",
          "def section" in body and "get_state" in body)
    check("and the window reports where it went, however it got there",
          "note_section" in body)


async def test_the_running_build_can_be_compared_to_the_source():
    """M13-E. Three rounds of verification ran against a gnome-shell holding code
    from hours earlier. GJS caches extension modules, so disable/enable reloads
    nothing; only a new shell process does. Nothing could say which revision was
    running, so nothing did."""
    from aries.runtime import version
    src = version.source()
    check("the source reports a commit", bool(src["commit"]) and src["commit"] != "unknown")
    check("and whether the tree is dirty — two dirty trees at one commit are "
          "different software", isinstance(src["dirty"], bool))
    check("the shell has a content-hash build id", len(src["shell_build"]) == 12)

    stamp = os.path.join(ROOT, "shell", "aries@aries.local", "BUILD")
    check("the extension carries that id, so the RUNNING shell can report it",
          os.path.exists(stamp))
    with open(stamp) as fh:
        stamped = fh.read().split("\n")[0].strip()
    check(f"the stamp matches the source it was generated from "
          f"({stamped} vs {src['shell_build']})", stamped == src["shell_build"])

    comparison = version.compare()
    check("installed copies are compared against the source",
          "shell_matches" in comparison)
    check("'not installed' and 'installed but stale' do not share a signal",
          comparison["shell_matches"] is None or isinstance(comparison["shell_matches"], bool))


async def test_a_resolved_command_names_a_destination_that_can_run():
    """M13-F. The router happily returned `navigate → news` for the entire time
    the Control Centre could not open. Resolving is not reaching."""
    from aries.shell import intents
    launcher = os.path.join(ROOT, "scripts", "aries-ui")
    sections = set()
    for intent in intents.INTENTS:
        action = intent.action
        if action.get("kind") == "navigate":
            sections.add(action["section"])
    check("navigate actions name sections", len(sections) > 0)

    from aries_ui.contract import READS  # noqa: F401  (import proves the UI package loads)
    import json as _json
    pages = os.path.join(ROOT, "aries_ui", "pages", "__init__.py")
    with open(pages) as fh:
        page_body = fh.read()
    unknown = [s for s in sections if f'"{s}"' not in page_body]
    check(f"every section a command can name is a real screen"
          f"{'' if not unknown else ': ' + str(unknown)}", unknown == [])
    check("and something exists to open them with", os.access(launcher, os.X_OK))
    del _json


async def test_the_mark_is_defined_once_and_drawn_twice():
    """M13-G. The mark is rendered by Cairo in two languages that cannot share
    code — JavaScript in the panel, Python for the icon files. The first attempt
    shared an SVG instead, and it rendered as nothing in both places, silently.

    So the geometry is data, and this asserts the two renderers agree. Without
    it, the panel mark and the application icon would be free to drift into two
    different logos, and nobody would notice until they were side by side."""
    import re
    from aries.shell import mark

    with open(os.path.join(ROOT, "shell", "aries@aries.local", "lib", "panel.js")) as fh:
        js = fh.read()

    # Every coordinate pair the JavaScript draws, in order.
    drawn = re.findall(r"cr\.(?:moveTo|lineTo|curveTo)\(([^;]*?)\);", js, re.S)
    numbers: list[float] = []
    for call in drawn:
        numbers += [float(v) for v in re.findall(r"x\(([\d.]+)\)|y\(([\d.]+)\)",
                                                call.replace(" ", ""))
                    for v in [v[0] or v[1]] if v]
    expected: list[float] = []
    for segment in mark.PATH:
        expected += [float(v) for v in segment[1:]]

    check(f"the JavaScript draws {len(numbers)} coordinates", len(numbers) > 20)
    check(f"and they are exactly the coordinates in aries/shell/mark.py"
          f"{'' if numbers == expected else f' — js={numbers[:6]}… py={expected[:6]}…'}",
          numbers == expected)
    check("the stroke width matches too", f"{mark.STROKE} * s" in js)


async def test_the_icon_is_shipped_in_a_format_this_machine_can_draw():
    """M13-H. The icon theme resolved `aries` happily and the dock drew a gap:
    the name pointed at an SVG, and this machine has `libpixbufloader_svg.so`
    on disk but not registered, so nothing can rasterise one.

    Worse than merely failing — GTK PREFERS a scalable icon when present, so
    shipping the SVG actively hid the PNGs that would have worked."""
    from aries.shell import mark
    icons = os.path.join(ROOT, "share", "icons", "hicolor")
    missing = [size for size in mark.SIZES
               if not os.path.exists(os.path.join(icons, f"{size}x{size}", "apps", "aries.png"))]
    check(f"a raster icon exists at every declared size"
          f"{'' if not missing else ', missing: ' + str(missing)}", missing == [])
    check("16px is the smallest — below that the horns merge into a blob",
          min(mark.SIZES) == 16)

    with open(os.path.join(ROOT, "scripts", "aries-shell")) as fh:
        installer = fh.read()
    check("the installer asks this machine whether it can rasterise SVG at all",
          "new_from_file_at_size" in installer)
    check("and withholds the scalable icon when it cannot, rather than letting "
          "it hide the PNGs",
          'rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/aries.svg"' in installer)


async def test_an_overlay_sizes_itself_from_its_parts():
    """M13-I. `get_preferred_height()` does not account for a child whose height
    was set explicitly, so the command bar's panel was shorter than its own
    scroll view: results drew outside the surface, on bare wallpaper, over
    whatever window was behind. Deferring the measurement by an idle turn
    changed nothing — the number was not stale, it was measuring the wrong
    thing."""
    import re
    with open(os.path.join(ROOT, "shell", "aries@aries.local", "lib", "commandbar.js")) as fh:
        raw = fh.read()
    # Comments stripped first — the paragraph explaining WHY the preferred
    # height is not used contains the call it forbids. That rule is already in
    # this file for two other scans, and I wrote this one without it anyway.
    body = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    body = re.sub(r"^\s*//.*$", "", body, flags=re.M)
    check("the height is summed from the entry, the scroll and the footer",
          "entryHeight + scrollHeight + footerHeight" in body)
    check("the container's own preferred height is not trusted for it",
          "this._container.get_preferred_height" not in body)
    check("and the chrome comes from the theme node, so changing the padding "
          "in the tokens cannot silently clip the last row",
          "get_padding(St.Side.TOP)" in body)


async def test_the_smoke_test_covers_the_seams():
    """The product-green check must ask about the things component tests skip."""
    with open(os.path.join(ROOT, "scripts", "aries-smoke")) as fh:
        body = fh.read()
    for seam in ("execs ITSELF", "aries-ui is on PATH", "the database answers",
                 "desktop build differs from source", "desktop capabilities unavailable", "navigate action"):
        check(f"the smoke test asks about: {seam}", seam in body)
    check("and exits non-zero when a user-facing path is broken", "exit 1" in body)


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
