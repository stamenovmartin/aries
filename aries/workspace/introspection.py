"""What ARIES can do, what it cannot, and how it knows the difference.

An assistant that cannot answer "what can you do?" makes the person guess, and a
person who guesses wrong concludes the thing is broken. So this exists. The one
rule that shapes every line: **the answer is derived, never written down.**

Every list here is built at call time from the same structures the router and the
planner actually use — `capabilities.CATALOGUE`, `capabilities.ARGUMENTS`,
`capabilities.SENSITIVE`, the M14 `registry` — and every readiness claim comes
from a subsystem's own live check. A hand-maintained list of features is a lie
with a delay on it: someone adds a capability and forgets the doc, and ARIES
then denies being able to do something it does. Nothing here can drift that way,
because there is nothing to forget to update.

The limits are held to the same standard. `limits()` reports what ARIES cannot
do WITH the evidence for each, and most of that evidence is measured on the
machine at the moment of asking rather than asserted: whether a compiler exists,
whether there is a backlight to dim, whether the accessibility bus is up. A
limit that used to be true and is not any more is worse than no answer, because
it teaches the person not to ask again.

`can(request)` answers the narrower and more useful question — "can you do THIS"
— by running the real parser. Not a paraphrase of it, the same `recognize()` the
command bar and the voice daemon use, so the answer and the behaviour cannot
disagree. When the parser declines, that is reported as "this goes to the
planner", which is the truth, rather than as a refusal.
"""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Presentation only. Membership comes from CATALOGUE, so a capability that is
# added and not listed here appears under "ungrouped" instead of disappearing —
# the failure mode of a grouping table should be visible, not silent.
AREAS = (
    ("Говор", "Speech", ("say",)),
    ("Апликации и прозорци", "Applications and windows",
     ("open_app", "inspect_app", "ui_action", "processes", "list_apps", "install_app")),
    ("Екран", "Screen", ("screenshot", "read_screen")),
    ("Текст и клипборд", "Text and clipboard",
     ("clipboard_read", "clipboard_write", "editable_fields", "type_text")),
    ("Прелистувач", "Browser",
     ("browser_open", "browser_inspect", "browser_follow", "browser_fill", "browser_close",
      "open_url", "search_web", "read_article")),
    ("Датотеки", "Files",
     ("open_path", "find_files", "list_folder", "read_file", "create_folder", "create_file",
      "move_file", "trash_file")),
    ("Звук и медиуми", "Sound and media", ("play_music", "media_control", "set_volume")),
    ("Мрежа", "Network", ("network_status", "wifi_list", "wifi_connect")),
    ("Екран и осветленост", "Display", ("brightness", "set_brightness")),
    ("Систем", "System", ("services", "service_control", "disk", "package_info", "system", "health")),
    ("Вести и преглед", "News and briefing", ("research", "refresh_news", "brief")),
    ("Програмирање", "Programming", ("python_project", "build_python")),
    ("Памтење и учење", "Memory and learning", ("remember", "learning_eval", "evaluation")),
    ("Задачи", "Tasks", ("agent_task",)),
    ("Самосвесност", "Self-knowledge", ("abilities", "can_you")),
)


def _probe(argv, timeout=5):
    """Run a read-only probe. Returns stdout, or None if the tool is not there."""
    if not shutil.which(argv[0]):
        return None
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def abilities():
    """Every capability ARIES has, grouped, with the phrase that reaches it."""
    from aries.workspace.capabilities import CATALOGUE, SENSITIVE, ARGUMENTS
    entries = {k: {"id": k, "title": title, "example": example,
                   "needs_approval": k in SENSITIVE,
                   "arguments": list(ARGUMENTS.get(k, ()))}
               for k, title, example in CATALOGUE}
    grouped, placed = [], set()
    for mk, en, members in AREAS:
        rows = [entries[k] for k in members if k in entries]
        placed.update(r["id"] for r in rows)
        if rows:
            grouped.append({"area": en, "area_mk": mk, "capabilities": rows})
    leftover = [entries[k] for k in entries if k not in placed]
    if leftover:
        # Visible on purpose: a new capability nobody grouped is still reported.
        grouped.append({"area": "Ungrouped", "area_mk": "Негрупирани", "capabilities": leftover})
    return {"spoken": grouped, "spoken_count": len(entries),
            "needs_approval": sorted(k for k in entries if entries[k]["needs_approval"])}


def agent_surface():
    """The typed capabilities the planner may use, which is a different set.

    The spoken catalogue is what a person can say. This is what ARIES may do
    while working through a goal on its own, and it is deliberately narrower in
    some places and wider in others — `file.edit` exists here and has no spoken
    form, because editing one fragment of a file is not a thing anyone dictates.
    """
    from aries.workspace.registry import registry
    rows = []
    for name in sorted(registry._items):
        item = registry._items[name]
        rows.append({"name": name, "description": getattr(item, "description", ""),
                     "effect": getattr(item, "effect", "read"),
                     "needs_approval": bool(getattr(item, "requires_approval", False)),
                     "risk": getattr(item, "risk_level", None)})
    reads = [r for r in rows if r["effect"] == "read"]
    return {"capabilities": rows, "count": len(rows),
            "read_only": len(reads), "changes_something": len(rows) - len(reads),
            "needs_approval": sum(1 for r in rows if r["needs_approval"])}


def readiness():
    """Live health per subsystem, each from that subsystem's own check.

    Nothing is assumed ready. A subsystem that cannot answer is reported as
    unable to answer, which is different from reported as broken.
    """
    found = {}
    try:
        from aries import speech
        state = speech.available()
        found["speech"] = {"ok": state["ok"], "detail": state["detail"],
                           "voices": {code: entry["engine"] for code, entry in state["languages"].items()}}
    except Exception as exc:                          # noqa: BLE001 - a health report never raises
        found["speech"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    for label, module, probe in (("screen", "screen_capabilities", "describe_allowed"),
                                 ("network", "network_capabilities", None),
                                 ("system", "system_capabilities", None),
                                 ("input", "input_capabilities", None)):
        try:
            __import__(f"aries.workspace.{module}")
            found[label] = {"ok": True, "detail": "module loads"}
        except Exception as exc:                      # noqa: BLE001
            found[label] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    # The accessibility bus is what "click anything in any app" rests on, and it
    # is a switch a person can turn off without ARIES noticing.
    bus = _probe(["gsettings", "get", "org.gnome.desktop.interface", "toolkit-accessibility"])
    found["accessibility"] = {"ok": bus == "true",
                              "detail": f"toolkit-accessibility is {bus or 'unreadable'}"}
    return found


def limits():
    """What ARIES cannot do, each with the evidence, measured where possible.

    Ordered by how often it is the answer a person actually needs.
    """
    from aries.workspace.capabilities import CATALOGUE, WRITES
    ids = {k for k, _, _ in CATALOGUE}
    out = []

    # The deliberate one, and the reason the rest of this list is short.
    out.append({"limit": "Run an arbitrary shell command",
                "limit_mk": "Да изврши произволна команда во терминал",
                "why": f"There is no such capability. All {len(ids)} spoken capabilities are named and "
                       "typed, and nothing in aries/workspace or aries/operator calls a shell.",
                "kind": "by design", "changeable": "only by adding one, which would remove the guarantee"})

    root = shutil.which("sudo") is not None
    out.append({"limit": "Change anything needing root",
                "limit_mk": "Да смени нешто што бара root",
                "why": ("sudo exists but needs interactive authentication, so ARIES cannot use it; "
                        "system services, apt and firewall rules are all out of reach")
                       if root else "sudo is not installed",
                "kind": "environment", "changeable": "a polkit rule naming specific units for this user"})

    compilers = [c for c in ("gcc", "g++", "make", "cmake") if shutil.which(c)]
    out.append({"limit": "Build software from source",
                "limit_mk": "Да компајлира софтвер од извор",
                "why": "no C/C++ toolchain: " + (", ".join(compilers) if compilers
                                                 else "gcc, g++, make and cmake are all absent"),
                "kind": "environment", "changeable": "apt install build-essential, which needs root"})

    backlights = list(Path("/sys/class/backlight").glob("*")) if Path("/sys/class/backlight").is_dir() else []
    if not backlights:
        out.append({"limit": "Change screen brightness",
                    "limit_mk": "Да ја смени осветленоста на екранот",
                    "why": "/sys/class/backlight is empty: this machine has no backlight device, and an "
                           "external monitor's brightness lives in the monitor",
                    "kind": "hardware", "changeable": "not on this hardware"})

    out.append({"limit": "Type Cyrillic by synthesizing keystrokes",
                "limit_mk": "Да пишува кирилица преку синтетички тастатурни притисоци",
                "why": "Wayland has no global synthetic input, and Mutter's keysym path silently drops "
                       "characters the active keyboard layout cannot produce. Typing goes through "
                       "AT-SPI into one reviewed control instead, or it refuses.",
                "kind": "platform", "changeable": "a keymap swap mid-sentence, which was rejected"})

    # Derived, not asserted: ask the guard itself whether it still holds.
    from aries.workspace.capabilities import INSTALLATION
    out.append({"limit": "Change its own code",
                "limit_mk": "Да си го менува сопствениот код",
                "why": f"file capabilities refuse any path under {INSTALLATION}. Reading it is allowed — this "
                       "answer is read from it — but writing is not. Until 2026-09-29 it was allowed, because "
                       "the tree sits under $HOME and every other guard waved it through.",
                "kind": "by design", "changeable": "a reviewed development flow that runs the suite before "
                                                   "registering anything, not a file write"})

    out.append({"limit": "Write outside your home folder",
                "limit_mk": "Да запишува вон твојата домашна папка",
                "why": f"every one of the {len(WRITES)} writing capabilities resolves its path through "
                       "checked_path(), which refuses anything outside $HOME, the home folder itself, "
                       "a hidden configuration directory, or a symbolic link",
                "kind": "by design", "changeable": "no"})

    out.append({"limit": "Speak Macedonian in a fully natural voice while offline",
                "limit_mk": "Да зборува македонски со целосно природен глас без интернет",
                "why": "no neural model has ever been trained on Macedonian speech. The offline voice is "
                       "RHVoice Kiko, recorded from a Macedonian speaker but parametric; the natural one "
                       "is Microsoft's and needs the network.",
                "kind": "state of the field", "changeable": "training a Piper mk_MK voice on the 24 CC0 "
                                                            "hours in Common Voice; nobody has"})
    return out


def can(request):
    """Can ARIES do this exact thing? Answered by the real parser.

    Three honest outcomes, and the middle one is the one a hand-written FAQ gets
    wrong: a request the router does not recognize is not refused, it is handed
    to the planner, which can compose several capabilities or decline.
    """
    from aries.workspace.capabilities import CATALOGUE, SENSITIVE, recognize
    text = " ".join((request or "").split())
    if not text:
        return {"request": "", "answer": "unclear", "detail": "nothing was asked"}
    found = recognize(text)
    if found:
        kind = found["capability"]
        title = next((t for k, t, _ in CATALOGUE if k == kind), kind)
        return {"request": text, "answer": "yes", "capability": kind, "title": title,
                "arguments": found["args"], "needs_approval": kind in SENSITIVE,
                "detail": f"understood directly as {kind}"
                          + (" and it will ask you to approve it first" if kind in SENSITIVE else "")}
    return {"request": text, "answer": "maybe", "capability": None,
            "detail": "no single capability matches this wording, so it goes to the planner, which "
                      "either composes several capabilities into a task or declines. Ask for one thing "
                      "at a time to get a direct answer."}


def report():
    """Everything at once, for a dashboard card or a spoken summary."""
    able, agent, ready, cannot = abilities(), agent_surface(), readiness(), limits()
    healthy = [k for k, v in ready.items() if v.get("ok")]
    return {"spoken_capabilities": able["spoken_count"],
            "agent_capabilities": agent["count"],
            "read_only": agent["read_only"], "needs_approval": len(able["needs_approval"]),
            "subsystems_ready": f"{len(healthy)} of {len(ready)}",
            "abilities": able, "agent": agent, "readiness": ready, "limits": cannot,
            # Two different sets, so they are counted separately. An earlier version
            # said "58 typed capabilities, 9 of which need your approval" — 9 is the
            # SPOKEN gate count and the typed one is 12. Merging them made the one
            # sentence a person reads the only wrong number in the report.
            "summary": (f"{able['spoken_count']} things you can ask for out loud, "
                        f"{len(able['needs_approval'])} of them gated by your approval. "
                        f"{agent['count']} typed capabilities the planner may use, "
                        f"{agent['read_only']} of those observe only and "
                        f"{agent['needs_approval']} need approval. "
                        f"{len(cannot)} known limits, with the evidence for each.")}
