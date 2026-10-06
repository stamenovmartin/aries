"""What the user wants to be TRUE afterwards — and how ARIES checks it.

THE DISTINCTION THIS FILE IS BUILT ON
-------------------------------------
An action is something ARIES does. A goal is something that is true when it
worked. `xdg-open https://youtube.com` exiting 0 is an action succeeding; a
browser window showing YouTube is the goal being met. They are not the same
event and they fail independently — the command can succeed with no browser
installed, and the browser can end up on YouTube after the command timed out.

Every goal here therefore carries its own verification: not "did the tool
return", but "look at the machine and decide".

THE EVIDENCE LADDER, WHICH IS THE HONEST PART
---------------------------------------------
Not all verification is equally strong, and a system that pretends otherwise is
lying about the part that matters. Four grades, and every result says which it
earned:

    proof          ARIES read the fact from a system of record it owns or from
                   the application itself. An automation run row; the Control
                   Centre stating its own section over D-Bus. This cannot be
                   coincidence.
    strong         two independent observations agree — a process of the right
                   name AND a mapped window belonging to that process.
    circumstantial one observation consistent with the goal but explainable
                   otherwise. A window title containing "YouTube" is this: the
                   title comes from the page, and it is still a title. There is
                   no way to read a browser's active tab URL from outside the
                   browser, so this is the ceiling for web goals, and saying so
                   is better than inventing a stronger claim.
    none           the observation needed was not available at all — no window
                   list outside the ARIES session, for instance.

`none` produces **unverifiable**, which is a third verdict beside met and
unmet. It is not a failure and it is certainly not a success: it is ARIES
saying "I did the thing and I cannot confirm it", which is the truth and is
what the user needs to hear. The engine already has this shape — `uncertain` is
a first-class outcome there for the same reason.

WHY THE VOCABULARY IS DATA
--------------------------
Same argument as `shell/intents.py`: one table, inspectable, testable, and
referenced by the experiment's task set by id. A goal that exists only inside a
planner's prompt cannot be evaluated, and an evaluation is what this milestone
owes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse

from aries.operator.desktop import Desktop

# ── the evidence ladder ─────────────────────────────────────────────────────

PROOF = "proof"
STRONG = "strong"
CIRCUMSTANTIAL = "circumstantial"
NONE = "none"

GRADE_RANK = {NONE: 0, CIRCUMSTANTIAL: 1, STRONG: 2, PROOF: 3}

GRADES: tuple[dict, ...] = (
    {"grade": PROOF, "meaning": "read from a system of record, or from the application itself"},
    {"grade": STRONG, "meaning": "two independent observations agree"},
    {"grade": CIRCUMSTANTIAL, "meaning": "consistent with the goal, and explainable otherwise"},
    {"grade": NONE, "meaning": "the observation needed was not available"},
)

MET = "met"
UNMET = "unmet"
UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class Verification:
    """The answer to "did it actually happen?", with its working shown."""

    verdict: str                  # met | unmet | unverifiable
    grade: str                    # how strong the evidence is
    checked: str                  # what was inspected, in a sentence
    found: str                    # what was there
    evidence: dict = field(default_factory=dict)

    @property
    def met(self) -> bool:
        return self.verdict == MET

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "grade": self.grade, "checked": self.checked,
                "found": self.found, "evidence": self.evidence}


def met(grade: str, checked: str, found: str, **evidence) -> Verification:
    return Verification(MET, grade, checked, found, evidence)


def unmet(grade: str, checked: str, found: str, **evidence) -> Verification:
    return Verification(UNMET, grade, checked, found, evidence)


def unverifiable(checked: str, why: str, **evidence) -> Verification:
    return Verification(UNVERIFIABLE, NONE, checked, why, evidence)


# ── what a browser is ───────────────────────────────────────────────────────
# Matched on the process name and the window class, because neither alone is
# reliable: a Firefox started from a wrapper has the wrapper's name, and a
# Chromium-based application has a browser's class without being one.
BROWSERS: tuple[str, ...] = ("firefox", "chrome", "chromium", "epiphany", "brave",
                             "vivaldi", "opera", "edge", "librewolf", "zen")


def _looks_like_a_browser(text: str) -> bool:
    low = text.lower()
    return any(b in low for b in BROWSERS)


def site_words(url: str) -> list[str]:
    """The words a page's title would plausibly contain for this URL.

    `https://www.youtube.com/results?search_query=x` → `["youtube"]`. The host's
    registrable part only: "www" and the TLD appear in no title, and including
    them would make every check fail.
    """
    host = (urlparse(url).hostname or url).lower()
    host = re.sub(r"^(www|m|mobile)\.", "", host)
    parts = [p for p in host.split(".") if p not in ("com", "org", "net", "io", "co", "uk", "mk")]
    return parts[:1] or [host]


# ── the goal vocabulary ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Goal:
    """One thing ARIES can be asked to make true."""

    kind: str
    describe: Callable[[dict], str]           # params → a sentence a person reads
    ceiling: str                              # the best grade this goal can ever earn
    why_ceiling: str                          # and why it cannot do better
    params: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"kind": self.kind, "ceiling": self.ceiling, "why_ceiling": self.why_ceiling,
                "params": list(self.params)}


GOALS: tuple[Goal, ...] = (
    Goal("open_url", lambda p: f"a browser showing {p.get('url', '?')}",
         CIRCUMSTANTIAL,
         "a browser's active tab URL cannot be read from outside the browser, so the "
         "strongest available evidence is a browser window whose title matches the site",
         ("url",)),
    Goal("open_app", lambda p: f"{p.get('app', '?')} running with a window",
         STRONG,
         "a process and a window belonging to it are two independent observations; "
         "nothing further is available without the application cooperating",
         ("app",)),
    Goal("run_automation", lambda p: f"the {p.get('automation_id', '?')} automation has run",
         PROOF,
         "the run is a row in ARIES's own database, written by the run itself",
         ("automation_id",)),
    Goal("open_section", lambda p: f"the Control Centre showing {p.get('section', '?')}",
         PROOF,
         "the Control Centre is asked over D-Bus which section it is on, and answers "
         "for itself",
         ("section",)),
)

BY_KIND: dict[str, Goal] = {g.kind: g for g in GOALS}


def get(kind: str) -> Goal | None:
    return BY_KIND.get(kind)


# ── verification ────────────────────────────────────────────────────────────

async def verify(kind: str, params: dict, desktop: Desktop, db=None) -> Verification:
    """Look at the machine and decide whether the goal is met.

    Never consults what the Operator *did* — only what is true now. A verifier
    that reads the action's own report is not a verifier, it is a second copy of
    the claim it was meant to check.
    """
    fn = _VERIFIERS.get(kind)
    if fn is None:
        return unverifiable(f"the goal '{kind}'",
                            f"ARIES has no way to check a '{kind}' goal")
    if kind in ("run_automation",):
        return await fn(params, desktop, db)
    return fn(params, desktop)


def _verify_open_url(params: dict, desktop: Desktop) -> Verification:
    url = params.get("url") or ""
    words = site_words(url)
    checked = f"browser windows, for a title mentioning {' '.join(words)!r}"

    if not desktop.can_see_windows:
        # A browser process proves a browser is open and says nothing about
        # where it is. Reporting that as success would be exactly the dishonesty
        # this milestone exists to measure.
        browsers = [p for p in desktop.processes if _looks_like_a_browser(p.name)]
        return unverifiable(
            checked,
            f"{desktop.windows_unavailable}. "
            + (f"{len(browsers)} browser process(es) are running, which says a browser "
               f"is open and nothing about what it is showing."
               if browsers else "No browser process is running either."),
            browser_processes=len(browsers))

    hits = [w for w in desktop.windows
            if not w.minimised and any(word in w.title.lower() for word in words)
            and (_looks_like_a_browser(w.wm_class) or _looks_like_a_browser(w.app_id))]
    if hits:
        return met(CIRCUMSTANTIAL, checked,
                   f"{hits[0].wm_class or 'a browser'} has a window titled {hits[0].title!r}",
                   windows=[w.as_dict() for w in hits[:3]])

    any_browser = [w for w in desktop.windows if _looks_like_a_browser(w.wm_class)]
    return unmet(CIRCUMSTANTIAL if any_browser else STRONG, checked,
                 (f"{len(any_browser)} browser window(s) are open and none mentions "
                  f"{words[0]!r}" if any_browser else "no browser window is open at all"),
                 browser_windows=[w.title for w in any_browser[:5]])


def _verify_open_app(params: dict, desktop: Desktop) -> Verification:
    app = (params.get("app") or "").strip()
    if app.casefold() in {'vs code', 'vscode', 'visual studio code'}:
        app = 'code'
    # ".desktop" ids and paths both arrive here; what matches a process name and
    # a window class is the bare token.
    token = re.sub(r"\.desktop$", "", app).split(".")[-1].split("/")[-1].lower()
    checked = f"processes and windows named {token!r}"

    procs = desktop.processes_named(token)
    if not desktop.can_see_windows:
        if procs:
            return unverifiable(
                checked,
                f"{len(procs)} {token!r} process(es) are running, but "
                f"{desktop.windows_unavailable.lower()} — so ARIES cannot tell whether "
                f"it has a window on screen or is a background process",
                processes=[p.as_dict() for p in procs[:3]])
        return unmet(CIRCUMSTANTIAL, checked,
                     f"no {token!r} process is running "
                     f"({desktop.windows_unavailable.lower()})")

    # Resolve through the same installed application catalogue as the launcher.
    # Snap Firefox maps as firefox_firefox.desktop, not firefox.desktop.
    # Keep identity exact; a title containing the requested name is not proof.
    from aries.operator.tools import _desktop_file
    installed_id = _desktop_file(app)
    windows = [w for w in desktop.windows or []
               if (installed_id and w.app_id == installed_id) or w.wm_class.casefold() == token or
               w.app_id.removesuffix('.desktop').split('.')[-1].casefold() == token]
    if windows and not any(w.focused and not w.minimised for w in windows):
        return unmet(STRONG, checked,
                     'The application has a window, but it is not focused and visible',
                     windows=[w.as_dict() for w in windows[:3]])
    windows = [w for w in windows if w.focused and not w.minimised]
    if windows and procs:
        return met(STRONG, checked,
                   f"{len(procs)} process(es) and the window {windows[0].title!r}",
                   windows=[w.as_dict() for w in windows[:3]],
                   processes=[p.as_dict() for p in procs[:3]])
    if windows:
        return met(CIRCUMSTANTIAL, checked,
                   f"a window titled {windows[0].title!r}, but no process of that name "
                   f"— it may be owned by a differently-named process",
                   windows=[w.as_dict() for w in windows[:3]])
    if procs:
        return unmet(STRONG, checked,
                     f"{len(procs)} process(es) are running but none has a window — it "
                     f"started and did not map anything, or it is still starting",
                     processes=[p.as_dict() for p in procs[:3]])
    return unmet(STRONG, checked, f"nothing named {token!r} is running")


async def _verify_run_automation(params: dict, desktop: Desktop, db) -> Verification:
    """Read the run out of ARIES's own database — the only goal here that can be
    proved rather than observed.

    In its OWN session, deliberately. The automation runs in sessions of its own
    and commits there; a caller's session opened before that commit holds a
    snapshot from before it, and SQLite will happily keep answering from it. The
    first version read through the caller's session and concluded that a health
    pass which had just succeeded was "a run from before this task began" — a
    verifier reporting a stale read as a negative result, which is worse than no
    verifier at all.
    """
    from agentic_core.database.base import async_session

    from aries.automations.genome import last_run

    automation_id = params.get("automation_id") or ""
    since = params.get("since")
    checked = f"the run history of {automation_id}"

    async with async_session() as fresh:
        row = await last_run(fresh, automation_id)
        if row is None:
            return unmet(PROOF, checked, f"{automation_id} has never run")
        started = getattr(row, "started_at", None)
        status = getattr(row, "status", "") or ""
        summary = (getattr(row, "summary", "") or "")[:160]

    # `started_at` is stored to whole seconds while `since` carries microseconds,
    # so a run that began in the SAME second as the task looked older than it.
    # The verifier then reported a health pass that had just succeeded as "a run
    # from before this task" — a false negative from a unit mismatch, which is
    # the most embarrassing kind for a component whose whole job is deciding
    # what is true. Compare at the resolution the column actually has.
    if since is not None and started is not None and started < since.replace(microsecond=0):
        return unmet(PROOF, checked,
                     f"the most recent run of {automation_id} started at {started} — "
                     f"before this task began, so it is not this task's run",
                     started_at=str(started), task_started=str(since))
    if status in ("ok", "degraded"):
        return met(PROOF, checked, f"a run finished {status}: {summary}",
                   status=status, started_at=str(started), summary=summary)
    return unmet(PROOF, checked, f"the run finished {status or 'with no status'}: {summary}",
                 status=status, summary=summary)


def _verify_open_section(params: dict, desktop: Desktop) -> Verification:
    """Ask the Control Centre where it is. It answers for itself, which is why
    this is proof rather than an inference from a window title."""
    import subprocess

    section = params.get("section") or ""
    checked = f"the Control Centre's own 'section' action, for {section!r}"
    try:
        out = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "mk.aries.ControlCentre",
             "--object-path", "/mk/aries/ControlCentre",
             "--method", "org.gtk.Actions.Describe", "section"],
            capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return unverifiable(checked, f"the Control Centre did not answer: {exc}")

    if out.returncode != 0:
        return unmet(PROOF, checked, "the Control Centre is not running")

    # gdbus prints the GVariant: ((true, signature 's', [<'learning'>]),)
    # The section is the only quoted value inside the angle brackets, which is
    # the part of the shape that will not change if GTK adds a field.
    match = re.search(r"<'([^']*)'>", out.stdout or "")
    current = match.group(1) if match else None
    if current is None:
        return unverifiable(checked, f"could not read the section from {out.stdout.strip()[:120]!r}")
    if current == section:
        return met(PROOF, checked, f"it says it is on {current!r}", section=current)
    return unmet(PROOF, checked, f"it says it is on {current!r}, not {section!r}",
                 section=current)


_VERIFIERS = {
    "open_url": _verify_open_url,
    "open_app": _verify_open_app,
    "run_automation": _verify_run_automation,
    "open_section": _verify_open_section,
}
