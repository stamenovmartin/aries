"""The universal command interface, v0.1.

The brief is emphatic: **not a fake AI chat box**. So this is a deterministic
intent router over the capabilities ARIES actually has. It matches what it
recognises, runs it through the real API, and — when it does not recognise
something — says so plainly instead of producing a plausible-sounding nothing.

That last property is the whole design. A command bar that answers everything
with "I'll look into that" is worse than one that answers half of things and is
honest about the other half, because the first cannot be trusted and the second
can. Unmatched input offers the closest real capabilities rather than pretending.

Intents are patterns, and each carries the ARIES call it makes. Adding one means
adding a row here — and it is only addable if the capability already exists,
which keeps the command bar from outrunning the system.

`Super+Space` belongs to the desktop shell, not to an application, so the
in-application binding is `Ctrl+Space`. Binding the global shortcut is a GNOME
setting and is offered in the documentation rather than taken.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402


@dataclass
class Intent:
    """One thing the command bar can actually do."""

    id: str
    patterns: tuple[str, ...]
    title: str
    detail: str
    run: Callable                       # (app, match) -> None
    example: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def match(self, text: str):
        for p in self.patterns:
            m = re.search(p, text, re.I)
            if m:
                return m
        return None

    def score(self, text: str) -> float:
        """How well this intent fits, for ranking when nothing matches exactly."""
        low = text.lower()
        hits = sum(1 for k in self.keywords if k in low)
        return hits / max(1, len(self.keywords))


# ── the intents ─────────────────────────────────────────────────────────────

def _go(section):
    return lambda app, m: app.go(section)


def _run_automation(automation_id, label):
    def _do(app, m):
        app.go("automations")
        app.client.call(
            lambda c: c.post(f"/api/aries/automations/{automation_id}/run", {"force": True}),
            on_ok=lambda r: app.toast(f"{label}: {r.get('summary') or r.get('verdict', 'done')}"),
            on_error=lambda e: app.toast(_error(e)))
        app.toast(f"Running {label}…")
    return _do


def _explain(app, m):
    subject = (m.group("subject") or "").strip().strip("?'\" ")
    if not subject:
        app.go("learning")
        return
    from aries_ui.explain import ExplainDialog
    ExplainDialog(app, subject).present(app.window)


def _feedback(text):
    def _do(app, m):
        app.client.call(
            lambda c: c.post("/api/aries/learning/feedback", {"text": text}),
            on_ok=lambda r: (app.go("learning"),
                             app.toast(r.get("question") if r.get("ambiguous")
                                       else f"Heard: {r.get('classification', '').replace('_', ' ')}")),
            on_error=lambda e: app.toast(_error(e)))
    return _do


def _avoid_topic(app, m):
    topic = (m.group("subject") or "").strip()
    if not topic:
        return
    app.client.call(
        lambda c: c.post("/api/aries/interests", {"topic": topic, "stance": "avoid"}),
        on_ok=lambda r: (app.go("interests"), app.toast(f"'{topic}' will be ignored")),
        on_error=lambda e: app.toast(_error(e)))


def _error(exc) -> str:
    from aries_ui.client import describe
    title, explanation, _ = describe(exc)
    return f"{title}: {explanation}"[:160]


# ORDER IS SIGNIFICANT: first match wins, so ACTIONS come before NAVIGATION.
#
# Declared the other way round, "scan for news" matched the navigate-to-News
# intent (it contains "news") and "make my morning brief shorter" matched
# navigate-to-Brief (it contains "brief") — both silently doing the more generic,
# less useful thing. A router whose patterns overlap must try the specific
# interpretation first, and a verb is more specific than a noun.
INTENTS: tuple[Intent, ...] = (
    # ── actions: the user wants something DONE ──────────────────────────────
    Intent("health", (r"\brun\b.*\b(system|health)\b", r"\b(check|scan)\b.*\bmachine\b",
                      r"\bhealth check\b"),
           "Run a system health check", "measures this machine now",
           _run_automation("aries.health", "System health"),
           "run system health", ("run", "system", "health", "check", "machine")),
    Intent("scan", (r"\b(scan|fetch|refresh|check)\b.*\bnews\b", r"\brun\b.*\bnews\b",
                    r"\bscan\b"),
           "Scan for news now", "reads every enabled source",
           _run_automation("aries.news", "News Radar"),
           "scan for news", ("scan", "fetch", "news", "run")),
    Intent("learn", (r"\brun\b.*\blearning\b", r"\blearn(ing)? pass\b"),
           "Run a learning pass", "re-reads the evidence and adjusts what it can",
           _run_automation("aries.learning", "Learning"),
           "run a learning pass", ("learning", "run", "pass", "adjust")),
    Intent("explain", (r"why (do|does) (you|aries) (think|believe|care about) (?P<subject>.+)",
                       r"why (?P<subject>.+?) matters", r"\bexplain (?P<subject>.+)"),
           "Explain a belief", "what ARIES believes, and the evidence for it",
           _explain, "why do you think AI matters to me?",
           ("why", "explain", "believe", "because")),
    Intent("shorter", (r"\b(shorter|less detail|too long)\b",), "Make briefs shorter",
           "sends this as feedback — ARIES will ask how far it reaches",
           _feedback("shorter"), "make my morning brief shorter",
           ("shorter", "brief", "long")),
    Intent("quieter", (r"\b(quieter|too (much|many|noisy)|only.*important)\b",),
           "Notify me less", "only important things reach you",
           _feedback("only notify me if it is important"),
           "only notify me if it is important", ("quiet", "notify", "important", "noise")),
    Intent("avoid", (r"\b(disable|stop|block|ignore|no more)\b\s+(?P<subject>[\w ]+?)"
                     r"(\s+news)?$",),
           "Stop showing a topic", "adds it to the topics ARIES ignores",
           _avoid_topic, "disable security news", ("disable", "stop", "block", "ignore")),

    # ── navigation: the user wants to SEE something ─────────────────────────
    Intent("decisions", (r"\b(pending )?decisions?\b", r"\bwaiting for me\b",
                         r"\bapprov\w+\b"),
           "Show pending decisions", "everything ARIES will not do without you",
           _go("home"), "show pending decisions", ("decision", "pending", "waiting", "approve")),
    Intent("brief", (r"\b(brief|briefing|morning)\b",), "Show the morning brief",
           "one page: what needs you, and what happened", _go("brief"),
           "show my brief", ("brief", "morning", "summary")),
    Intent("news", (r"\b(news|articles|what.*read)\b",), "Show news",
           "what ARIES collected, and what it held back", _go("news"),
           "show today's important news", ("news", "article", "read", "today")),
    Intent("interests", (r"\b(interests?|topics?)\b",), "Show interests",
           "explicit and learned, side by side", _go("interests"),
           "show my interests", ("interest", "topic", "weight")),
    Intent("automations", (r"\bautomations?\b", r"\bwhat.*running\b"), "Show automations",
           "what ARIES does on its own", _go("automations"),
           "show automations", ("automation", "schedule", "running")),
    Intent("settings", (r"\bsettings?\b", r"\bconfigure\b", r"\bpreferences?\b"),
           "Open settings", "everything, without editing a file", _go("settings"),
           "open settings", ("settings", "configure", "preference")),
    Intent("sources", (r"\bsources?\b", r"\bfeeds?\b", r"\bwhere.*news.*from\b"),
           "Manage news sources", "browse the catalogue or add a feed", _go("news"),
           "where does my news come from", ("source", "feed", "catalogue", "rss")),
    Intent("connections", (r"\b(connections?|integrations?|connect)\b",),
           "Show connections", "what ARIES can reach, and what it cannot yet",
           _go("connections"), "show connections", ("connect", "integration", "email")),
    Intent("system", (r"\b(system|cpu|memory|disk|temperature|machine)\b",),
           "Show this machine", "the last health measurement", _go("system"),
           "show system health", ("system", "cpu", "memory", "disk", "machine")),
)


class CommandPalette(Adw.Dialog):
    def __init__(self, app):
        super().__init__(title="Command", content_width=620, content_height=480)
        self.app = app
        self.set_presentation_mode(Adw.DialogPresentationMode.FLOATING)

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("What would you like ARIES to do?")
        self.entry.add_css_class("aries-command-entry")
        self.entry.connect("search-changed", lambda *_: self._update())
        self.entry.connect("activate", lambda *_: self._activate_first())

        self.list = Gtk.ListBox()
        self.list.add_css_class("boxed-list")
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", self._on_activated)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.list)

        self.hint = Gtk.Label(xalign=0)
        self.hint.add_css_class("aries-command-hint")
        self.hint.set_wrap(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=design.MD)
        box.set_margin_top(design.LG)
        box.set_margin_bottom(design.LG)
        box.set_margin_start(design.LG)
        box.set_margin_end(design.LG)
        box.append(self.entry)
        box.append(scroller)
        box.append(self.hint)
        self.set_child(box)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)
        self._update()
        GLib.idle_add(self.entry.grab_focus)

    def _on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _matches(self, text: str) -> list[Intent]:
        text = text.strip()
        if not text:
            return list(INTENTS)[:8]
        exact = [i for i in INTENTS if i.match(text)]
        if exact:
            return exact
        scored = sorted(INTENTS, key=lambda i: -i.score(text))
        return [i for i in scored if i.score(text) > 0][:5]

    def _update(self):
        text = self.entry.get_text()
        key = "command-palette"
        generation = self.app.client.bump(key)
        self.app.client.call(
            lambda c: c.post("/api/aries/command", {"text": text, "limit": 8}),
            on_ok=self._render_results,
            on_error=lambda e: self.hint.set_text(_error(e)), key=key, generation=generation)

    def _render_results(self, data):
        child = self.list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.list.remove(child)
            child = nxt
        self.hint.set_text(data.get("unmatched_reason") or "Enter to run · Esc to close")
        for result in data.get("results", []):
            row = widgets.row(result["title"], result.get("detail", ""), activatable=True)
            row.action = result["action"]
            self.list.append(row)
        first = self.list.get_first_child()
        if first:
            self.list.select_row(first)

    def _activate_first(self):
        row = self.list.get_selected_row() or self.list.get_first_child()
        if row is not None and hasattr(row, "action"):
            self._run_action(row.action)

    def _on_activated(self, _list, row):
        if hasattr(row, "action"):
            self._run_action(row.action)

    def _run_action(self, action):
        self.close()
        kind = action.get("kind")
        if kind == "navigate":
            self.app.go(action["section"])
            return
        if kind == "explain":
            from aries_ui.explain import ExplainDialog
            ExplainDialog(self.app, action.get("subject", "")).present(self.app.get_active_window() or self.app.window)
            return
        if kind == "open_path":
            work = lambda c: c.post("/api/aries/workspace", {"capability": "open_path", "args": {"path": action["path"]}})
        else:
            work = lambda c: c.post("/api/aries/shell/act", action)
        def done(result):
            if kind in {"workspace", "open_path"} or result.get("section") == "dashboard":
                goal = result.get("result", result)
                if goal.get("id"):
                    self.app.open_goal(goal["id"], temporary=True)
            self.app.toast(result.get("message") or "Task submitted")
        self.app.client.call(work, on_ok=done, on_error=lambda e: self.app.toast(_error(e)))
