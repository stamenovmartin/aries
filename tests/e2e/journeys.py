"""End-to-end journeys: does a person get what they asked for?

WHAT MAKES THESE DIFFERENT FROM THE SUITE
-----------------------------------------
Every assertion here is made about **observable state after crossing a process
boundary** — a window that exists, an application that is running, a section
that is actually showing. Nothing is mocked; in particular the launcher is never
mocked, because the launcher is what broke.

`test.sh` had 1511 green assertions while the Control Centre could not open at
all. That is not a gap in coverage, it is a gap in *kind*: component tests
verify components, and the product is the seams.

HOW THE DESTINATION IS VERIFIED
-------------------------------
Not by the exit code of the launcher, and not by the shell reporting that it
asked. The Control Centre exports its current section as the state of a GAction,
so a separate process reads back where the window actually is over D-Bus. Asking
the thing itself is the only answer that cannot be wrong.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The name the ARIES shell uses — `CONTROL_CENTRE` in extension.js. Bare, so it
# is resolved through PATH, which is the invocation that broke.
LAUNCHER_NAME = "aries-ui"
BUS_NAME = "mk.aries.ControlCentre"
OBJECT_PATH = "/mk/aries/ControlCentre"
# Read from the Control Centre itself rather than listed here. A hard-coded
# checklist stops growing with the code — the nested shell harness asserted a
# fixed list of surfaces and passed while a new one was missing (Entry 016), and
# this list had the same shape. Adding a screen now adds a journey.
sys.path.insert(0, ROOT)
from aries_ui.pages import SECTIONS as _SECTIONS  # noqa: E402

SECTIONS = tuple(key for key, _ in _SECTIONS)

_passed = 0
_failed = 0
_owned_control_centre = None


def control_centre_owner() -> str | None:
    try:
        return _bus().call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "GetNameOwner",
            GLib.Variant("(s)", (BUS_NAME,)), GLib.VariantType.new("(s)"),
            Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
    except GLib.Error:
        return None


def check(label: str, condition: bool, detail: str = "") -> bool:
    global _passed, _failed
    mark = "\033[32mPASS\033[0m" if condition else "\033[31mFAIL\033[0m"
    print(f"  {mark}  {label}" + (f"   \033[2m{detail}\033[0m" if detail else ""), flush=True)
    if condition:
        _passed += 1
    else:
        _failed += 1
    return condition


def note(text: str) -> None:
    print(f"        \033[2m{text}\033[0m", flush=True)


def heading(text: str) -> None:
    print(f"\n\033[1m{text}\033[0m", flush=True)


# ── talking to the running Control Centre ───────────────────────────────────

def _bus() -> Gio.DBusConnection:
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def control_centre_running() -> bool:
    try:
        names = _bus().call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "ListNames", None, GLib.VariantType.new("(as)"),
            Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        return BUS_NAME in names
    except GLib.Error:
        return False


def current_section(timeout_s: float = 8.0) -> str | None:
    """Where the window actually is, asked of the window.

    Read from the `section` action's STATE rather than inferred from what we
    told it to do — the difference between verifying and hoping.

    Called with a synchronous `org.gtk.Actions.Describe` rather than
    `Gio.DBusActionGroup`, which populates asynchronously and needs a running
    main loop to receive its replies. This script has no main loop, so the
    convenience wrapper returned `None` for every section and eleven journeys
    "failed" against a harness that was never going to hear an answer. Asking
    the bus directly is both simpler and synchronous.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            reply = _bus().call_sync(
                BUS_NAME, OBJECT_PATH, "org.gtk.Actions", "Describe",
                GLib.Variant("(s)", ("section",)),
                GLib.VariantType.new("((bgav))"),
                Gio.DBusCallFlags.NONE, 3000, None)
            _enabled, _signature, state = reply.unpack()[0]
            if state and isinstance(state[0], str) and state[0]:
                return state[0]
        except GLib.Error:
            pass
        time.sleep(0.3)
    return None


def open_section(section: str) -> None:
    """Exactly what the shell does — by NAME, through PATH, with an argument.

    Not the repository path. The shell's `CONTROL_CENTRE = 'aries-ui'` is a bare
    name, and the name on PATH is a symlink into the repository — so a launcher
    that computes its location from `$0` resolves somewhere else entirely when
    invoked this way, and works perfectly when invoked by its real path. That is
    exactly what happened: `PYTHONPATH` became `~/.local` and every launch died
    with `No module named aries_ui`, while this suite called the repository path
    and passed. Invoke it the way the product does, or the product is untested.
    """
    global _owned_control_centre
    before = control_centre_owner()
    child = subprocess.Popen(
        [LAUNCHER_NAME, "--section", section],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    if before is None and wait_for_control_centre():
        owner = control_centre_owner()
        if owner:
            try:
                pid = _bus().call_sync(
                    "org.freedesktop.DBus", "/org/freedesktop/DBus",
                    "org.freedesktop.DBus", "GetConnectionUnixProcessID",
                    GLib.Variant("(s)", (owner,)), GLib.VariantType.new("(u)"),
                    Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                if pid == child.pid:
                    _owned_control_centre = owner
            except GLib.Error:
                pass


def quit_control_centre() -> None:
    global _owned_control_centre
    owner = control_centre_owner()
    if not owner or owner != _owned_control_centre:
        return
    try:
        # Address the unique connection we launched, never a replacement owner.
        _bus().call_sync(
            owner, OBJECT_PATH, "org.gtk.Actions", "Activate",
            GLib.Variant("(sava{sv})", ("quit", [], {})), None,
            Gio.DBusCallFlags.NONE, 3000, None)
    except GLib.Error:
        return
    for _ in range(20):
        if control_centre_owner() != owner:
            _owned_control_centre = None
            return
        time.sleep(0.3)


def wait_for_control_centre(timeout_s: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if control_centre_running():
            return True
        time.sleep(0.4)
    return False


# ── the journeys ────────────────────────────────────────────────────────────

def _launcher_chain(start: str, limit: int = 8) -> list[str]:
    """Follow a launcher from PATH to whatever finally runs.

    A symlink is followed by resolution; a wrapper script is followed by reading
    its `exec` line. Stops at anything that is not a shell script, and stops on
    a repeat — a repeat IS the self-exec bug, and returning the chain lets the
    caller say so rather than hanging.
    """
    chain: list[str] = []
    current = os.path.realpath(start) if os.path.exists(start) else ""
    while current and len(chain) < limit:
        if current in chain:
            chain.append(current)              # the loop, made visible
            break
        chain.append(current)
        try:
            with open(current) as fh:
                head = fh.read(4096)
        except OSError:
            break
        if not head.startswith("#!"):
            break
        target = ""
        for line in head.splitlines():
            if line.strip().startswith("exec "):
                target = line.strip()[5:].strip().split()[0].strip('"')
                break
        if not target or target.startswith("/usr/bin/python"):
            break
        current = os.path.realpath(os.path.expandvars(target))
    return chain


def journey_launcher_is_sane() -> None:
    """The M13 regression, permanently. A launcher that execs itself passes any
    check that only looks at an exit code."""
    heading("The launcher")
    launcher = os.path.join(ROOT, "scripts", "aries-ui")
    check("the launcher exists and is executable", os.access(launcher, os.X_OK))

    with open(launcher) as fh:
        body = fh.read()
    target = ""
    for line in body.splitlines():
        if line.strip().startswith("exec "):
            target = line.strip()[5:].strip()
            break
    expanded = os.path.realpath(os.path.expandvars(target.strip('"').split()[0])) if target else ""
    check("it does not exec itself — the M13 infinite loop",
          expanded != os.path.realpath(launcher),
          f"execs: {target[:60]}" if target else "")
    check("it runs the Control Centre module", "python3 -m aries_ui" in body)

    # The check that would have caught it: not what the file says, but what
    # happens when it is run the way the shell runs it. `--help` exits without
    # opening a window, so this is cheap and still crosses the whole seam —
    # PATH lookup, symlink resolution, PYTHONPATH, the module import.
    on_path = shutil.which(LAUNCHER_NAME)
    check(f"'{LAUNCHER_NAME}' is on PATH", bool(on_path), on_path or "")
    if on_path:
        out = subprocess.run([LAUNCHER_NAME, "--help"], capture_output=True,
                             text=True, timeout=30)
        text = (out.stdout or "") + (out.stderr or "")
        check("running it BY NAME finds the Control Centre module",
              "No module named" not in text, text.strip().splitlines()[0][:90] if text else "")
        check("and it accepts --section", "--section" in text)
    check("on the system interpreter, where GTK lives (ADR-0004)",
          "/usr/bin/python3" in body)

    # And the whole chain from PATH, which may be a symlink OR a wrapper script.
    #
    # The invariant is not "the shim is a wrapper whose exec line names the
    # launcher" — that assumption made this check parse the REAL launcher's exec
    # line and report /usr/bin/python3.14 as a fault. The invariant is: following
    # the chain from PATH terminates, reaches the launcher, and no step execs
    # itself. Stated that way it holds for a symlink and for a wrapper.
    chain = _launcher_chain(os.path.expanduser("~/.local/bin/aries-ui"))
    if chain:
        check("following aries-ui from PATH terminates — no self-exec anywhere",
              len(chain) == len(set(chain)), " → ".join(os.path.basename(c) for c in chain))
        check("and the chain ends at the real launcher",
              os.path.realpath(chain[-1]) == os.path.realpath(launcher),
              chain[-1])

    importable = subprocess.run(
        ["/usr/bin/python3", "-c", f"import sys; sys.path.insert(0, {ROOT!r}); import aries_ui"],
        capture_output=True)
    check("the Control Centre module imports on that interpreter",
          importable.returncode == 0,
          importable.stderr.decode()[:80] if importable.returncode else "")


def journey_cold_start_lands_on_the_requested_section() -> None:
    """Case A: the Control Centre is NOT running."""
    heading("Cold start — the Control Centre is not running")
    if control_centre_running():
        note("cold start skipped: preserving the existing Control Centre")
        return
    check("nothing is running to begin with", not control_centre_running())

    open_section("news")
    started = wait_for_control_centre()
    check("asking for a section starts the Control Centre", started)
    if not started:
        return
    where = current_section()
    check("and it lands on the section that was asked for", where == "news",
          f"landed on: {where}")


def journey_warm_start_navigates_the_existing_window() -> None:
    """Case B: it is already running — the case that was broken.

    The old code set a pending field and called activate(), then tried to apply
    the section again in case the window already existed. Which branch ran
    depended on whether do_activate had cleared the field yet, and the answer
    differed between a cold start and a second invocation.
    """
    heading("Warm start — the Control Centre is already running")
    if not control_centre_running():
        open_section("home")
        if not wait_for_control_centre():
            check("the Control Centre could be started for this journey", False)
            return
    check("it is already running", control_centre_running())

    for section in ("system", "brief", "learning", "news"):
        open_section(section)
        time.sleep(1.4)
        where = current_section()
        check(f"asking for '{section}' navigates the existing window",
              where == section, f"landed on: {where}")


def journey_every_section_is_reachable() -> None:
    """All nine, deterministically — the brief asks for every one."""
    heading("Every section, deterministically")
    if not control_centre_running():
        open_section("home")
        wait_for_control_centre()
    wrong = []
    for section in SECTIONS:
        open_section(section)
        time.sleep(1.2)
        where = current_section()
        if where != section:
            wrong.append(f"{section}→{where}")
    check(f"all {len(SECTIONS)} sections land where asked"
          + ("" if not wrong else f": {', '.join(wrong)}"), not wrong)


def journey_an_unknown_section_is_refused_not_swallowed() -> None:
    heading("An unknown destination")
    if not control_centre_running():
        open_section("home")
        wait_for_control_centre()
    open_section("news")
    time.sleep(1.2)
    open_section("nonsense-section")
    time.sleep(1.2)
    where = current_section()
    check("a section ARIES does not have leaves the window where it was, "
          "rather than silently landing somewhere", where == "news",
          f"still on: {where}")


def journey_command_router_reaches_a_real_destination() -> None:
    """The bug class: a result exists, and its action cannot execute.

    The router happily returned `navigate → news` the whole time the launcher
    was broken. Resolving is not reaching.
    """
    heading("Typing 'news' reaches the news screen")
    import urllib.request
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/aries/command",
            data=json.dumps({"text": "show news"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=8) as reply:
            results = json.loads(reply.read())["results"]
    except Exception as error:                          # noqa: BLE001
        check(f"ARIES resolved the request ({error})", False)
        return

    navigate = next((r for r in results
                     if r["action"]["kind"] == "navigate"), None)
    check("the router resolves it to a navigate action", navigate is not None)
    if not navigate:
        return
    section = navigate["action"].get("section")
    note(f"router says: navigate → {section}")

    quit_control_centre()
    open_section(section)
    started = wait_for_control_centre()
    check("carrying that action out actually opens the Control Centre", started)
    if started:
        where = current_section()
        check("on the section the router named", where == section,
              f"landed on: {where}")


def journey_an_application_actually_launches() -> None:
    """ARIES Search offers applications; launching one must launch one."""
    heading("Launching an application")
    app_id = None
    for candidate in ("org.gnome.Calculator.desktop", "gnome-calculator.desktop",
                      "org.gnome.TextEditor.desktop"):
        found = Gio.DesktopAppInfo.new(candidate)
        if found is not None:
            app_id = candidate
            break
    if app_id is None:
        note("no suitable test application installed — skipped")
        return

    info = Gio.DesktopAppInfo.new(app_id)
    # A single-instance application can reuse its process. Observe the actual
    # mapped application window instead of counting pgrep matches.
    def app_windows():
        from aries.operator.desktop import read_windows
        windows, _, _ = read_windows()
        return [w for w in (windows or [])
                if w.app_id.removesuffix(".desktop") == app_id.removesuffix(".desktop")]
    try:
        info.launch([], None)
    except GLib.Error as error:
        check(f"the application launched ({error.message})", False)
        return
    deadline = time.monotonic() + 10
    windows = app_windows()
    while not windows and time.monotonic() < deadline:
        time.sleep(0.3)
        windows = app_windows()
    check(f"{app_id} has an observed application window", bool(windows))
    note("application retained; no process-name cleanup of user applications")


def journey_reopen_after_close() -> None:
    heading("Closing it, then asking again")
    if control_centre_owner() != _owned_control_centre or not _owned_control_centre:
        note("close/reopen skipped: the Control Centre is not owned by this run")
        return
    quit_control_centre()
    check("it closed", not control_centre_running())
    open_section("interests")
    started = wait_for_control_centre()
    check("asking again reopens it", started)
    if started:
        where = current_section()
        check("on the requested section", where == "interests", f"landed on: {where}")


def journey_degraded_when_aries_is_absent() -> None:
    """The shell must stay usable, and say so, when ARIES is not answering.

    Read from the shell itself rather than simulated: if the ARIES service is
    running the check is about the healthy path, and the unavailable path is
    covered by `test-shell-api.sh` against a server that refuses connections.
    """
    heading("When ARIES is not answering")
    ping = subprocess.run(
        ["gdbus", "call", "--session", "--dest", "org.aries.Shell",
         "--object-path", "/org/aries/Shell", "--method", "org.aries.Shell.Ping"],
        capture_output=True, text=True)
    if ping.returncode != 0:
        note("the ARIES shell is not running — are you in the ARIES session?")
        return
    check("the shell answers and reports its own state", "built" in ping.stdout)
    check("and reports no component failures", '"failures":[]' in ping.stdout)
    note("the unavailable/timeout/malformed paths are covered by "
         "./scripts/test-shell-api.sh, which can produce them on demand")


def journey_running_code_is_the_source_code() -> None:
    """The staleness check, as a journey: is the desktop running what I changed?"""
    heading("Is the running shell the source revision?")
    ping = subprocess.run(
        ["gdbus", "call", "--session", "--dest", "org.aries.Shell",
         "--object-path", "/org/aries/Shell", "--method", "org.aries.Shell.Ping"],
        capture_output=True, text=True)
    if ping.returncode != 0:
        note("the ARIES shell is not running — skipped")
        return
    running = ""
    marker = '"build":"'
    if marker in ping.stdout:
        running = ping.stdout.split(marker)[1].split('"')[0]

    source = subprocess.run(
        [os.path.join(ROOT, ".venv", "bin", "python"), "-c",
         "from aries.runtime.version import source; print(source()['shell_build'])"],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH":
             f"{ROOT}/vendor/agentic-core:{ROOT}/vendor:{ROOT}"}).stdout.strip()

    if not running:
        check("the running shell reports a build id", False,
              "install and log in again to stamp it")
        return
    check("the running shell reports a build id", True, running)
    check("and it matches the source", running == source,
          f"running {running} · source {source}"
          if running != source else running)


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    print("\n\033[1mARIES end-to-end journeys\033[0m")
    print("\033[2mReal processes, real windows, on the installed system.\033[0m")

    initial_owner = control_centre_owner()
    initial_section = current_section() if initial_owner else None

    if only == "section-check":
        journey_cold_start_lands_on_the_requested_section()
        journey_warm_start_navigates_the_existing_window()
    else:
        journey_launcher_is_sane()
        journey_cold_start_lands_on_the_requested_section()
        journey_warm_start_navigates_the_existing_window()
        journey_every_section_is_reachable()
        journey_an_unknown_section_is_refused_not_swallowed()
        journey_command_router_reaches_a_real_destination()
        journey_reopen_after_close()
        journey_an_application_actually_launches()
        journey_degraded_when_aries_is_absent()
        journey_running_code_is_the_source_code()

    quit_control_centre()
    if initial_owner and control_centre_owner() == initial_owner and initial_section:
        open_section(initial_section)
        check("original Control Centre section restored", current_section() == initial_section)
    print(f"\n{_passed} passed, {_failed} failed\n")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
