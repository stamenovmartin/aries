"""Data — what ARIES is holding, and what it is about to forget.

WHY THIS SCREEN EXISTS
----------------------
A cleaner that deletes a person's data from a place they cannot see is not a
feature, it is a liability. Every other guarantee in the lifecycle — the
rehearsal, the refused window, the audit line — is only worth something if there
is somewhere to look. This is that somewhere.

It leads with the working set rather than with retention, deliberately. The
retention windows are the boring half; the interesting half is "what is ARIES
reading right now, and where did it come from?", which is the question a person
actually has once ARIES can open their mail. Labels and sources are shown — never
content, because the content never leaves the machine's working set at all.

Nothing here deletes by accident. The screen only ever reads; the two buttons
that write say what they will do and go through the same service the automation
uses, rehearsal included.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402
from aries_ui.page import Page  # noqa: E402

# Which classes read as reassuring and which read as a warning. Rows past their
# window are not an error — they are the system working — so they are "notice".
CLASS_SEVERITY = {
    "working": "notice", "operational": "info", "memory": "ok",
    "provenance": "info", "audit": "ok",
}


def _bytes(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    return f"{n / 1024:.0f} kB"


class DataPage(Page):
    title = "Data"
    icon = "drive-harddisk-symbolic"
    subtitle = "What ARIES keeps, for how long, and what it is reading now"

    def fetch(self, client):
        return {"status": client.get("/api/aries/data"),
                "working": client.get("/api/aries/data/working-set")}

    def render(self, data):
        status, working = data["status"], data["working"]
        box = widgets.page_box()
        box.append(self._summary(status))
        box.append(self._working_set(status, working))

        by_kind: dict[str, list] = {}
        for line in status.get("tables") or []:
            by_kind.setdefault(line["kind"], []).append(line)

        for cls in status.get("classes") or []:
            lines = [t for t in by_kind.get(cls["kind"], []) if t["table"] != "aries_working_set"]
            if not lines:
                continue
            group = widgets.section(cls["title"], cls["meaning"])
            for line in sorted(lines, key=lambda r: (-r["would_remove"], -r["present"])):
                group.add(self._table_row(line))
            box.append(group)

        box.append(self._actions(status))
        return widgets.scrolled(box)

    # ── the three things worth knowing at a glance ──────────────────────────
    def _summary(self, status) -> Gtk.Widget:
        held = status.get("working_set") or {}
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.LG)
        for severity, text in (
                ("info", f"{_bytes(status.get('database_bytes', 0))} on disk"),
                ("notice" if status.get("would_remove") else "ok",
                 f"{status.get('would_remove', 0)} rows past their window"),
                ("notice" if held.get("held") else "ok",
                 f"{held.get('held', 0)} items held for live work")):
            item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.SM)
            item.append(widgets.dot(severity))
            label = Gtk.Label(label=text)
            label.add_css_class("aries-quiet")
            item.append(label)
            row.append(item)
        return row

    def _working_set(self, status, working) -> Gtk.Widget:
        held = status.get("working_set") or {}
        items = working.get("items") or []
        group = widgets.section(
            "Being read now",
            "Context borrowed for one task. Released when the task ends, whatever the "
            "outcome — the way a page is gone once the tab closes. Contents are never "
            "shown here, or sent anywhere.")

        if not items:
            r = widgets.row("Nothing held",
                            "No task is reading anything at the moment")
            r.add_prefix(widgets.dot("ok"))
            group.add(r)
            return group

        for item in items[:40]:
            r = widgets.row(item.get("label") or "(unlabelled)",
                            f"{item.get('source') or 'unknown source'} · "
                            f"{_bytes(item.get('bytes', 0))} · "
                            f"task {item.get('task_id')} · "
                            f"since {widgets.when(item.get('created_at'))}")
            r.add_prefix(widgets.dot("notice"))
            if item.get("sensitive"):
                # The one label that has to be visible: material marked sensitive
                # may not be sent to a model that is not on this machine.
                r.add_suffix(widgets.tag("stays local", design.SEVERITY_CLASS.get("ok", "")))
            group.add(r)

        if held.get("tasks"):
            group.add(widgets.row(
                "Held for", f"{len(held['tasks'])} task(s): {', '.join(held['tasks'][:6])}"))
        return group

    def _table_row(self, line) -> Adw.ExpanderRow:
        n = line["would_remove"]
        exp = Adw.ExpanderRow(title=line["table"].replace("aries_", "").replace("_", " "))
        exp.set_subtitle(f"{line['present']} rows · {line['why']}")
        exp.add_prefix(widgets.dot(CLASS_SEVERITY.get(line["kind"], "info")))
        if n:
            exp.add_suffix(widgets.tag(f"{n} past window",
                                       design.SEVERITY_CLASS.get("notice", "")))

        exp.add_row(widgets.row("Why this long", line.get("reason") or line["why"]))
        if line.get("dependants"):
            exp.add_row(widgets.row(
                "What reads it", ", ".join(line["dependants"])
                + " — the window cannot go below what these need"))
        if line.get("days"):
            r = widgets.row("Window", f"{line['days']} days", activatable=True)
            r.add_prefix(Gtk.Image.new_from_icon_name("document-edit-symbolic"))
            r.connect("activated", lambda *_: self.app.go("settings"))
            exp.add_row(r)
        return exp

    def _actions(self, status) -> Gtk.Widget:
        group = widgets.section(
            "Cleaning",
            "The first pass records what it would remove and acts only on the next one. "
            "Every deletion is written to the audit log, which is itself never cleaned.")

        stale = status.get("would_remove", 0)
        clean = widgets.row(
            "Remove what is past its window",
            f"{stale} row(s) would go" if stale else "Nothing is past its window")
        clean.add_suffix(widgets.button(
            "Clean now",
            lambda: self.act(lambda c: c.post("/api/aries/data/clean", {"vacuum": True}),
                             done="Cleaning pass finished"),
            css="destructive-action" if stale else ""))
        if not stale:
            clean.set_sensitive(False)
        group.add(clean)

        sweep = widgets.row(
            "Collect abandoned working sets",
            "Context left behind by a task that stopped mid-flight")
        sweep.add_suffix(widgets.button(
            "Sweep",
            lambda: self.act(lambda c: c.post("/api/aries/data/sweep"),
                             done="Swept")))
        group.add(sweep)

        windows = widgets.row("Change how long things are kept",
                              "Every window is a setting you own", activatable=True)
        windows.add_prefix(Gtk.Image.new_from_icon_name("preferences-system-symbolic"))
        windows.connect("activated", lambda *_: self.app.go("settings"))
        group.add(windows)
        return group
