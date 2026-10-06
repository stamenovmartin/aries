"""How ARIES acts on this desktop — four tools, every one gated.

WHY THESE ARE ENGINE TOOLS AND NOT FUNCTIONS
--------------------------------------------
`agentic_core.tools.calling.call_tool` already implements the eight things that
have to be true before software opens something on a person's machine:
permission, schema, dry run, a live-tool allowlist, policy, approval,
at-most-once, and a journal line. Writing `subprocess.run` here instead would
mean reimplementing all eight badly, or — far more likely — skipping them and
discovering later which one mattered.

So the Operator's hands are `ToolSpec`s, and the Operator has no other way to
touch the machine. Everything it does is therefore already audited, already
refusable, and already replay-safe before any of the Operator's own logic runs.

THE LIVE GATE IS THE SWITCH, AND IT IS OFF
------------------------------------------
The engine holds every side-effecting tool unless it is named in `live_tools`.
ARIES drives that from its own setting (`operator.enabled`, default off) rather
than from an environment variable a user would never find — same rule as
everywhere else: the switch a person can see is the switch that decides.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
Closing windows, killing processes, deleting anything, typing into another
application. v0.1 opens things. Every tool here is something a person could undo
by closing a window, which is the property that makes "let it try and check
afterwards" a reasonable design at all. An Operator that can destroy has to
argue its way past a much higher bar, and it has not earned that yet.
"""
from __future__ import annotations

import logging
import asyncio
import os
import shutil
import subprocess
from urllib.parse import urlsplit

from agentic_core.security.permissions import Permission
from agentic_core.tools.base import ToolSpec
from agentic_core.tools.registry import register

logger = logging.getLogger(__name__)

# Opening a thing should be near-instant; anything slower is a launcher that is
# never going to return, and the Operator needs the turn back to say so.
LAUNCH_TIMEOUT_S = 20.0

# Schemes a browser may be pointed at. NOT `file:`, `data:` or `javascript:`:
# those would turn "open a URL" into "read this machine's files" or "run this",
# which is a different capability with a different bar, and a natural-language
# front door is exactly where that substitution would be attempted.
WEB_SCHEMES = ("http", "https")


class LaunchFailed(RuntimeError):
    pass


def _detach(argv: list[str]) -> tuple[bool, str]:
    """Start something that may BECOME the application, and do not wait for it.

    `aries-ui --section news` returns immediately when the Control Centre is
    already up — it sends a D-Bus message — and never returns when it is not,
    because it *is* the Control Centre from then on. Waiting on that blocked the
    Operator for the full launch timeout and then reported failure for something
    that had worked perfectly.

    The cost is that the launcher's own report becomes nearly worthless: "it
    started" says almost nothing. That is acceptable precisely because the
    verifier is what decides, and it is the reason a verifier exists rather than
    a return code.
    """
    if not shutil.which(argv[0]):
        return False, f"{argv[0]} is not installed"
    if os.environ.get("INVOCATION_ID") and shutil.which("systemd-run"):
        # A GUI application belongs to the desktop, outside the core service's
        # lifetime and NoNewPrivileges/PrivateTmp sandbox (notably for Snap).
        return _run(["systemd-run", "--user", "--collect", "--quiet",
                     "--service-type=exec", "--property=ExitType=cgroup", "--", *argv])
    try:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return False, f"{argv[0]} could not be started: {exc}"
    return True, f"{argv[0]} started; whether it worked is for the verifier to say"


def _run(argv: list[str], *, timeout: float = LAUNCH_TIMEOUT_S) -> tuple[bool, str]:
    """Run a launcher and report honestly.

    The session environment is inherited: ARIES runs as a systemd --user
    service, which has WAYLAND_DISPLAY and DBUS_SESSION_BUS_ADDRESS imported
    from the session, so a launched application finds a display. If that ever
    stops being true the failure is loud here rather than silent later.
    """
    if not shutil.which(argv[0]):
        return False, f"{argv[0]} is not installed"
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Timed out AFTER starting: the application may well be coming up. This
        # is the engine's `uncertain`, and the verifier is what settles it.
        return False, f"{argv[0]} did not return within {timeout:g}s"
    except OSError as exc:
        return False, f"{argv[0]} could not be run: {exc}"
    if out.returncode != 0:
        return False, (out.stderr or out.stdout or f"{argv[0]} exited {out.returncode}").strip()[:300]
    return True, (out.stdout or "").strip()[:300]


# ── opening a URL ───────────────────────────────────────────────────────────

async def open_url(payload: dict, ctx: dict) -> dict:
    url = str(payload.get("url") or "").strip()
    parts = urlsplit(url)
    if parts.scheme.lower() not in WEB_SCHEMES:
        return {"success": False,
                "details": f"ARIES opens {' and '.join(WEB_SCHEMES)} addresses; "
                           f"'{parts.scheme or url[:20]}' is not one of them"}
    if not parts.hostname:
        return {"success": False, "details": f"'{url}' has no host"}

    # Existing Firefox windows may be minimised; opening a background tab then
    # reporting success leaves the requested page invisible. Respect the default
    # browser, but request a real new window when that default is Firefox.
    ok, browser = _run(["xdg-settings", "get", "default-web-browser"])
    if ok and "firefox" in browser.lower() and shutil.which("firefox"):
        started, detail = _detach(["firefox", "--new-window", url])
        if started:
            return {"success": True, "opened": url, "via": "firefox --new-window", "details": detail}

    # `xdg-open` first: it is the freedesktop way, it respects the user's chosen
    # default browser, and it exists on every desktop. `gio open` is the GNOME
    # fallback for a system where xdg-utils is not installed.
    for argv in (["xdg-open", url], ["gio", "open", url]):
        ok, detail = _run(argv)
        if ok:
            return {"success": True, "opened": url, "via": argv[0], "details": detail}
        last = f"{argv[0]}: {detail}"
    return {"success": False, "details": last}


# ── opening an application ──────────────────────────────────────────────────

def _desktop_file(app: str) -> str | None:
    """Find the .desktop file for a name like 'firefox' or 'org.gnome.Nautilus'.

    Looked up rather than guessed: an id that does not exist would otherwise be
    "launched" successfully by a launcher that silently does nothing, which is
    the failure mode this whole milestone is about.
    """
    candidates = [app, f"{app}.desktop"]
    if "." not in app:
        candidates += [f"org.gnome.{app.capitalize()}.desktop"]
    dirs = [os.path.join(d, "applications") for d in (
        os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
        *(os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"))]

    for d in dirs:
        for name in candidates:
            if not name.endswith(".desktop"):
                continue
            path = os.path.join(d, name)
            if os.path.exists(path):
                return name
    # Nothing exact: fall back to a case-insensitive scan, which is how a person
    # saying "firefox" reaches `firefox_firefox.desktop` on a snap system.
    low = app.lower()
    for d in dirs:
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            continue
        for name in entries:
            if name.endswith(".desktop") and low in name.lower():
                return name
    return None


async def open_app(payload: dict, ctx: dict) -> dict:
    app = str(payload.get("app") or "").strip()
    if app.casefold() in {"vs code", "vscode", "visual studio code"}:
        app = "code"
    if not app:
        return {"success": False, "details": "an application is required"}

    desktop_id = _desktop_file(app)
    if desktop_id is None:
        return {"success": False,
                "details": f"no application called '{app}' is installed — ARIES looked "
                           f"through the .desktop files and found nothing matching"}

    from aries.operator import desktop
    windows, why, _ = await asyncio.to_thread(desktop.read_windows)
    matches = [w for w in (windows or []) if w.app_id == os.path.basename(desktop_id)]
    if matches:
        # Titles are arbitrary application content, never app identity. Prefer
        # the already focused window, then a visible window, then stable ID.
        target = sorted(matches, key=lambda w: (not w.focused, w.minimised, w.id))[0]
        if target.focused and not target.minimised:
            ok, detail = True, 'The requested application window is already focused'
        else:
            ok, detail = await asyncio.to_thread(desktop.focus_window, target)
        return {'success':ok, 'reused_window':target.id, 'via':'existing window',
                'details':detail + '; no additional window was launched'}
    if windows is None:
        return {'success':False, 'details':'Cannot determine whether this app is already open: ' + why}

    if "firefox" in desktop_id.lower() and shutil.which("firefox"):
        ok, detail = _detach(["firefox", "--new-window", "about:blank"])
        if ok:
            return {"success": True, "launched": desktop_id, "via": "firefox --new-window", "details": detail}
    ok, detail = _detach(["gtk-launch", desktop_id.removesuffix(".desktop")])
    if ok:
        return {"success": True, "launched": desktop_id, "via": "gtk-launch", "details": detail}
    ok, detail2 = _run(["gio", "launch", desktop_id])
    if ok:
        return {"success": True, "launched": desktop_id, "via": "gio launch", "details": detail2}
    return {"success": False, "details": f"gtk-launch: {detail}; gio launch: {detail2}"}


# ── ARIES's own surfaces ────────────────────────────────────────────────────

async def open_section(payload: dict, ctx: dict) -> dict:
    """Open the Control Centre on a section.

    Launched BY NAME, exactly as the shell launches it, rather than by the
    repository path. The two are not equivalent: the name is a symlink, and a
    launcher that resolves its own location from `$0` lands somewhere else
    entirely when invoked through it. Calling the path here would make the
    Operator work while the desktop stayed broken.
    """
    section = str(payload.get("section") or "").strip()
    argv = ["aries-ui", "--section", section]
    if payload.get("goal_id"):
        import re
        if not re.fullmatch(r"[0-9a-f]{32}", str(payload["goal_id"])):
            return {"success": False, "details": "Invalid dashboard id"}
        argv += ["--goal", payload["goal_id"]]
    ok, detail = _detach(argv)
    return ({"success": True, "section": section, "details": detail} if ok
            else {"success": False, "details": detail})


async def run_automation(payload: dict, ctx: dict) -> dict:
    """Run one ARIES automation, through the same path as the CLI.

    `ran` is NOT success. It means the automation was reached — the gates let it
    through and the body executed — and an automation whose body failed has
    `ran: True, status: "failed"`. The first version reported `ran` as success,
    so a News Radar pass that died on a database error was reported to the
    Operator as having worked. The verifier caught it, which is the point, but a
    tool that lies to its own verifier is making that verifier do avoidable
    work and would be believed anywhere the verifier is not.
    """
    from aries.automations.runner import run_automation as _run_automation

    automation_id = str(payload.get("automation_id") or "").strip()
    out = await _run_automation(automation_id, trigger="operator", force=True)
    status = out.get("status")
    succeeded = bool(out.get("ran")) and status in ("ok", "degraded")

    # An automation refused BEFORE it ran was not attempted — its circuit
    # breaker is open, the resource policy said no, or a pass is already in
    # flight. Reported as a gate, like every other refusal, so that "a rule
    # stopped this" is never counted as "the Operator could not do it".
    gate = ""
    if not out.get("ran"):
        gate = {"circuit_breaker_open": "circuit_breaker",
                "already running": "overlap",
                "disabled": "disabled"}.get(str(out.get("reason") or ""), "")
        if not gate and str(out.get("reason") or "").startswith("resource_policy"):
            gate = "resource_policy"

    return {"success": succeeded, "skipped": bool(gate), "gate": gate, "result": out,
            "details": (out.get("summary") or out.get("reason")
                        or (f"the run finished {status}" if status else ""))}


# ── registration ────────────────────────────────────────────────────────────

SPECS = (
    ToolSpec(
        name="desktop.open_url", run=open_url,
        description="Open a web address in the user's default browser.",
        input_schema={"url": {"type": str, "required": True}},
        permission=Permission.MANAGE_TOOLS,
        # `idempotent=False` in the engine's vocabulary means "every call is new
        # work", which is what opening something is. With it True the
        # at-most-once register recognised the second "open the news screen" as
        # a replay of the first and returned the recorded result without doing
        # anything — correct behaviour for sending an email, exactly wrong for
        # opening a window, and invisible because the replayed result said
        # success.
        risk="low", side_effect=True, idempotent=False, timeout_s=LAUNCH_TIMEOUT_S + 5,
        tags=["desktop", "operator"]),
    ToolSpec(
        name="desktop.open_app", run=open_app,
        description="Launch an installed application by name or .desktop id.",
        input_schema={"app": {"type": str, "required": True}},
        permission=Permission.MANAGE_TOOLS,
        risk="low", side_effect=True, idempotent=False, timeout_s=LAUNCH_TIMEOUT_S + 5,
        tags=["desktop", "operator"]),
    ToolSpec(
        name="aries.open_section", run=open_section,
        description="Open the ARIES Control Centre on one of its sections.",
        input_schema={"section": {"type": str, "required": True}, "goal_id": {"type": str}},
        permission=Permission.MANAGE_TOOLS,
        risk="low", side_effect=True, idempotent=False, timeout_s=LAUNCH_TIMEOUT_S + 5,
        tags=["aries", "operator"]),
    ToolSpec(
        name="aries.run_automation", run=run_automation,
        description="Run one ARIES automation now.",
        input_schema={"automation_id": {"type": str, "required": True}},
        permission=Permission.MANAGE_TOOLS,
        # Not idempotent: running an automation twice is two runs, and the
        # at-most-once register must treat the second as new work rather than
        # replay the first one's result.
        risk="medium", side_effect=True, idempotent=False,
        tags=["aries", "operator"]),
)

for _spec in SPECS:
    register(_spec, replace=True)

TOOL_NAMES = tuple(s.name for s in SPECS)
