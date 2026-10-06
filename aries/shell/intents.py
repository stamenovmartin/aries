"""What the command bar can actually do — the intent router, moved to the core.

MOVED, NOT COPIED
-----------------
This table used to live in `aries_ui/command.py`, bound to GTK widgets. The
shell needs the same router, and it is a GNOME Shell extension in JavaScript
inside another process, so it cannot import Python. The obvious next step would
have been to write the patterns a second time in JS, and that is exactly the
failure the brief forbids: *do not duplicate business logic in the shell.*

So the router moved here, behind `POST /api/aries/command`, and both surfaces
call it. There is one list of things ARIES can do, one set of patterns, one
ranking. The Control Centre's palette and the shell's command bar cannot drift,
because there is nothing for them to drift from.

WHAT A CLIENT GETS BACK
-----------------------
An `Action` — a description of what to do, not a closure. `{"kind": "navigate",
"section": "news"}` means "open the News screen"; the Control Centre switches
pages, the shell launches the Control Centre on that page. `{"kind":
"run_automation"}` is the same POST either way.

That split is what lets one router serve two very different clients: the core
decides *what the user meant*, and each surface knows only how to carry it out
in its own medium.

WHAT IS NOT HERE
----------------
Launching applications and switching windows. Those are the shell's own
knowledge — `Shell.AppSystem` already has the .desktop index and the window
list, and asking ARIES to maintain a second one would be duplication pointing
the other way. The rule this file follows is: **the core owns what ARIES knows;
the shell contributes only what only the shell knows.**

THE HONESTY RULE, INHERITED
---------------------------
Unmatched input is refused with the nearest real capabilities, never answered
with something plausible. A command bar that responds to everything cannot be
trusted; one that answers half of things and says so can.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Intent:
    """One thing ARIES can do, and how to recognise a request for it."""

    id: str
    patterns: tuple[str, ...]
    title: str
    detail: str
    action: dict                      # what the client should carry out
    example: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)
    # Where a pattern captures a subject (a topic, a belief), the captured text
    # is folded into the action under this key before it is returned.
    subject_key: str | None = None

    def match(self, text: str) -> re.Match | None:
        for p in self.patterns:
            m = re.search(p, text, re.I)
            if m:
                return m
        return None

    def score(self, text: str) -> float:
        low = text.lower()
        if not self.keywords:
            return 0.0
        return sum(1 for k in self.keywords if k in low) / len(self.keywords)

    def resolve(self, m: re.Match | None) -> dict:
        """The action, with any captured subject folded in."""
        action = dict(self.action)
        if self.subject_key and m is not None:
            try:
                subject = (m.group("subject") or "").strip().strip("?'\" ")
            except IndexError:          # this pattern has no subject group
                subject = ""
            if subject:
                action[self.subject_key] = subject
        return action

    def as_dict(self, m: re.Match | None = None) -> dict:
        return {"id": self.id, "title": self.title, "detail": self.detail,
                "kind": "command", "example": self.example,
                "action": self.resolve(m)}


SCREEN_NAMES = {
    'applications':'applications', 'apps':'applications', 'aplikacii':'applications', 'апликации':'applications', 'instalacii':'applications', 'installations':'applications',
    'news':'news', 'vesti':'news', 'вести':'news',
    'system':'system', 'sistem':'system', 'систем':'system',
    'files':'files', 'fajlovi':'files', 'фајлови':'files',
    'monitoring':'monitor', 'monitor':'monitor', 'sledene':'monitor', 'следење':'monitor',
    'evaluacija':'monitor', 'evaluation':'monitor', 'agenti':'monitor', 'agents':'monitor', 'jarvis':'monitor',
    'research':'dashboard', 'istrazuvanje':'dashboard', 'истражување':'dashboard',
    'dashboard':'dashboard', 'dashboards':'dashboard',
    'automations':'automations', 'avtomatizacii':'automations',
}

def screen_for(text):
    match = re.fullmatch(r'(?:open|show|otvori|prikazi|отвори|прикажи)\s+(.+)', text.strip(), re.I)
    return SCREEN_NAMES.get(match[1].casefold()) if match else None


def _nav(section: str) -> dict:
    return {"kind": "navigate", "section": section}


def _run(automation_id: str) -> dict:
    return {"kind": "run_automation", "automation_id": automation_id}


# ORDER IS SIGNIFICANT: first match wins, so ACTIONS come before NAVIGATION.
# Entry 011 found this the hard way — "scan for news" matched the navigate-to-News
# intent because it contains "news", and silently did the more generic, less
# useful thing. In a router with overlapping patterns, order encodes precedence,
# and a verb is more specific than a noun.
INTENTS: tuple[Intent, ...] = (
    Intent("dashboards", (r"^(show |open )?(dashboards?|workspace)$", r"^(прикажи |отвори )?дашборди$", r"^show memories$"),
           "Show dashboards", "Tasks, results and personal context", _nav("dashboard"),
           "show dashboards", ("dashboard", "workspace")),
    # ── actions ─────────────────────────────────────────────────────────────
    Intent("health", (r"\brun\b.*\b(system|health)\b", r"\b(check|scan)\b.*\bmachine\b",
                      r"\bhealth check\b"),
           "Run a system health check", "measures this machine now",
           _run("aries.health"), "run system health",
           ("run", "system", "health", "check", "machine")),
    Intent("scan", (r"\b(scan|fetch|refresh|check)\b.*\bnews\b", r"\brun\b.*\bnews\b",
                    r"\bscan\b"),
           "Scan for news now", "reads every enabled source",
           _run("aries.news"), "scan for news", ("scan", "fetch", "news", "run")),
    Intent("learn", (r"\brun\b.*\blearning\b", r"\blearn(ing)? pass\b"),
           "Run a learning pass", "re-reads the evidence and adjusts what it can",
           _run("aries.learning"), "run a learning pass",
           ("learning", "run", "pass", "adjust")),
    Intent("explain", (r"why (do|does) (you|aries) (think|believe|care about) (?P<subject>.+)",
                       r"why (?P<subject>.+?) matters", r"\bexplain (?P<subject>.+)",
                       r"where do you know (?P<subject>.+) from"),
           "Explain a belief", "what ARIES believes, and the evidence for it",
           {"kind": "explain"}, "why do you think AI matters to me?",
           ("why", "explain", "believe", "because", "know"), subject_key="subject"),
    Intent("shorter", (r"\b(shorter|less detail|too long)\b",), "Make briefs shorter",
           "sends this as feedback — ARIES will ask how far it reaches",
           {"kind": "feedback", "text": "shorter"}, "make my morning brief shorter",
           ("shorter", "brief", "long")),
    Intent("quieter", (r"\b(quieter|too (much|many|noisy)|only.*important)\b",),
           "Notify me less", "only important things reach you",
           {"kind": "feedback", "text": "only notify me if it is important"},
           "only notify me if it is important", ("quiet", "notify", "important", "noise")),
    # AFTER the corrections, not before. "make my morning brief shorter"
    # contains both "make … brief" and "shorter", and the first reading rebuilds
    # the briefing while the user was asking for it to change — the Entry 011
    # precedence lesson, found again by a test rather than by a user.
    Intent("brief_now", (r"\b(make|build|generate|run)\b.*\bbrief\b",),
           "Build the morning brief now", "collects every section again",
           _run("aries.brief"), "build my brief", ("brief", "build", "make", "generate")),
    Intent("avoid", (r"\b(disable|stop|block|ignore|no more)\b\s+(?P<subject>[\w ]+?)"
                     r"(\s+news)?$",),
           "Stop showing a topic", "adds it to the topics ARIES ignores",
           {"kind": "interest_avoid"}, "disable security news",
           ("disable", "stop", "block", "ignore"), subject_key="topic"),
    Intent("background_on", (r"\b(background mode|stay awake|don'?t sleep|keep.*awake)\b",),
           "Background Mode", "keeps the machine awake while the screen is off",
           {"kind": "navigate", "section": "settings", "anchor": "power"},
           "keep the machine awake", ("background", "awake", "sleep", "suspend")),

    # ── navigation ──────────────────────────────────────────────────────────
    Intent("decisions", (r"\b(pending )?decisions?\b", r"\bwaiting for me\b",
                         r"\bapprov\w+\b"),
           "Show pending decisions", "everything ARIES will not do without you",
           _nav("home"), "show pending decisions",
           ("decision", "pending", "waiting", "approve")),
    Intent("brief", (r"\b(brief|briefing|morning)\b",), "Show the morning brief",
           "one page: what needs you, and what happened", _nav("brief"),
           "show my brief", ("brief", "morning", "summary")),
    Intent("news", (r"\b(news|articles|what.*read)\b",), "Show news",
           "what ARIES collected, and what it held back", _nav("news"),
           "show today's important news", ("news", "article", "read", "today")),
    Intent("interests", (r"\b(interests?|topics?)\b",), "Show interests",
           "explicit and learned, side by side", _nav("interests"),
           "show my interests", ("interest", "topic", "weight")),
    Intent("memory", (r"\b(memory|remember|what do you know)\b",),
           "Inspect what ARIES knows", "beliefs, evidence, and where each came from",
           _nav("learning"), "what do you remember about me",
           ("memory", "remember", "know", "belief")),
    Intent("automations", (r"\bautomations?\b", r"\bwhat.*running\b"), "Show automations",
           "what ARIES does on its own", _nav("automations"),
           "show automations", ("automation", "schedule", "running")),
    Intent("settings", (r"\bsettings?\b", r"\bconfigure\b", r"\bpreferences?\b"),
           "Open settings", "everything, without editing a file", _nav("settings"),
           "open settings", ("settings", "configure", "preference")),
    Intent("sources", (r"\bsources?\b", r"\bfeeds?\b", r"\bwhere.*news.*from\b"),
           "Manage news sources", "browse the catalogue or add a feed", _nav("news"),
           "where does my news come from", ("source", "feed", "catalogue", "rss")),
    Intent("connections", (r"\b(connections?|integrations?|connect)\b",),
           "Show connections", "what ARIES can reach, and what it cannot yet",
           _nav("connections"), "show connections", ("connect", "integration", "email")),
    Intent("system", (r"\b(system|cpu|memory|disk|temperature|machine)\b",),
           "Show this machine", "the last health measurement", _nav("system"),
           "show system health", ("system", "cpu", "memory", "disk", "machine")),
)

SUGGESTIONS = ("show pending decisions", "run system health", "scan for news",
               "show my brief", "why do you think AI matters to me?")


def resolve(text: str, *, limit: int = 8) -> dict:
    """Match text against everything ARIES can do.

    Exact pattern matches first, in declaration order. When nothing matches, the
    nearest capabilities by keyword — and if not even those, an honest refusal
    with real examples rather than a plausible nothing.
    """
    text = (text or "").strip()
    if not text:
        return {"query": "", "results": [i.as_dict() for i in INTENTS[:limit]],
                "matched": False, "exact": False, "suggestions": list(SUGGESTIONS)}

    screen = screen_for(text)
    if screen:
        return {"query":text, "results":[{"id":"screen:"+screen, "kind":"command", "title":"Open "+screen.title(), "detail":"ARIES screen", "action":_nav(screen)}], "matched":True, "exact":True, "suggestions":[]}
    exact = [(i, i.match(text)) for i in INTENTS]
    exact = [(i, m) for i, m in exact if m is not None]
    if exact:
        return {"query": text, "results": [i.as_dict(m) for i, m in exact[:limit]],
                "matched": True, "exact": True, "suggestions": []}

    scored = sorted(((i.score(text), i) for i in INTENTS), key=lambda p: -p[0])
    near = [i for s, i in scored if s > 0][:5]
    if near:
        return {"query": text, "results": [i.as_dict() for i in near],
                "matched": True, "exact": False, "suggestions": []}

    return {"query": text, "results": [], "matched": False, "exact": False,
            "unmatched_reason":
                f'ARIES cannot do "{text}" yet. This is a command bar over the capabilities '
                f"that exist, not a chat — so it says so rather than guessing.",
            "suggestions": list(SUGGESTIONS)}
