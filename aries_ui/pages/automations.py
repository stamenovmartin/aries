"""Automations — §27's Control Centre.

Everything the specification asks a Control Centre to show, with the advanced
half (genome, metrics, evolution) behind a disclosure: a user who wants to know
whether the brief ran this morning should not have to read a permissions list
to find out.

Edit, Duplicate and Rollback are deliberately absent, exactly as they are absent
from the API. They operate on a versioned genome, which is §18's controlled
evolution — a button that mutated a spec in place would look like that feature
while providing none of its safety. What the genome already records
(`parent_version`, `evolution_history`, `rollback_version`) is shown, so the
data those controls will need is visible now.
"""
from __future__ import annotations

import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402
from aries_ui.page import Page  # noqa: E402


class AutomationsPage(Page):
    title = "Automations"
    icon = "media-playback-start-symbolic"
    subtitle = "What ARIES does on its own"

    def fetch(self, client):
        return client.get("/api/aries/automations")

    def render(self, data):
        box = widgets.page_box()
        box.append(self._dispatcher(data.get("worker") or {}))
        group = widgets.section("Automations")
        for a in data.get("automations") or []:
            group.add(self._row(a))
        box.append(group)
        return widgets.scrolled(box)

    def _dispatcher(self, worker) -> Gtk.Widget:
        group = widgets.section(
            "Background dispatcher",
            "when this is off, automations run only when you ask")
        row = widgets.switch_row(
            "Run automations on their own schedule",
            f"{worker.get('means', '')}",
            bool(worker.get("switch_on")),
            lambda value: self._set_worker(value))
        alive = worker.get("state") == "running" and worker.get("alive")
        row.add_prefix(widgets.dot("ok" if alive else
                                   ("notice" if worker.get("switch_on") else "info")))
        group.add(row)
        if worker.get("switch_on") and not alive:
            r = widgets.row("The dispatcher is switched on but not running in this process",
                            "It starts with the ARIES API. Restart it to pick this up.")
            r.add_prefix(widgets.dot("warning"))
            group.add(r)
        return group

    def _row(self, a) -> Adw.ExpanderRow:
        health = a.get("health") or {}
        rate = health.get("success_rate")
        last = a.get("last_run") or {}

        exp = Adw.ExpanderRow(title=a["name"])
        subtitle = []
        if a.get("enabled"):
            subtitle.append("enabled")
            if a.get("next_run"):
                subtitle.append(f"next {widgets.when(a['next_run'])}")
        else:
            subtitle.append("disabled")
        if last:
            subtitle.append(f"last {widgets.when(last.get('started_at'))}")
        exp.set_subtitle(" · ".join(subtitle))

        severity = "info"
        if a.get("enabled"):
            severity = {"ok": "ok", "degraded": "notice", "failed": "critical",
                        "skipped": "notice"}.get(last.get("status"), "ok")
        exp.add_prefix(widgets.dot(severity))

        controls = Gtk.Box(spacing=design.SM)
        controls.set_valign(Gtk.Align.CENTER)
        controls.append(widgets.button(
            "Run now", lambda i=a["automation_id"]: self._run(i), css="pill"))
        toggle = Gtk.Switch()
        toggle.set_active(bool(a.get("enabled")))
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.connect("state-set", self._on_toggle, a["automation_id"])
        controls.append(toggle)
        exp.add_suffix(controls)

        # ── plain facts ─────────────────────────────────────────────────────
        exp.add_row(widgets.row("What it does", a.get("purpose", "")))
        if last:
            r = widgets.row("Last result", last.get("summary") or last.get("status", ""))
            r.add_prefix(widgets.dot(severity))
            exp.add_row(r)
        exp.add_row(widgets.row(
            "Reliability",
            f"{rate:.0%} over {health.get('runs', 0)} runs in {health.get('window_days', 7)} days"
            if rate is not None else (health.get("reason") or "no runs yet")))
        exp.add_row(widgets.row("Schedule",
                                f"every {a.get('interval_minutes')} min"
                                if a.get("trigger") == "schedule" else a.get("trigger", "")))
        if a.get("due_reason"):
            exp.add_row(widgets.row("Due", a["due_reason"]))

        # ── advanced, behind a second disclosure ────────────────────────────
        advanced = Adw.ExpanderRow(title="Advanced", subtitle="version, permissions, genome")
        advanced.add_row(widgets.row("Version", a.get("version", "")))
        advanced.add_row(widgets.row("Risk", a.get("risk", "")))
        advanced.add_row(widgets.row("Permissions", ", ".join(a.get("permissions") or []) or "none"))
        advanced.add_row(widgets.row("Agents", ", ".join(a.get("agents") or [])
                                     or "none — this automation uses no model"))
        advanced.add_row(widgets.row("Tools", ", ".join(a.get("tools") or []) or "none"))
        evolution = a.get("evolution_history") or []
        advanced.add_row(widgets.row(
            "Evolution",
            f"{len(evolution)} recorded · rollback to {a.get('rollback_version') or 'nothing yet'}"))
        history = widgets.row("History", "recent runs", activatable=True)
        history.add_prefix(Gtk.Image.new_from_icon_name("document-open-recent-symbolic"))
        history.connect("activated", lambda _w, i=a["automation_id"]: self._history(i))
        advanced.add_row(history)
        genome = widgets.row("Genome", "the full declaration", activatable=True)
        genome.add_prefix(Gtk.Image.new_from_icon_name("view-list-symbolic"))
        genome.connect("activated", lambda _w, i=a["automation_id"]: self._genome(i))
        advanced.add_row(genome)
        exp.add_row(advanced)
        return exp

    # ── actions ─────────────────────────────────────────────────────────────
    def _on_toggle(self, switch, state, automation_id):
        self.act(lambda c: c.post(f"/api/aries/automations/{automation_id}/enabled",
                                  {"enabled": bool(state)}),
                 done=f"{automation_id} {'enabled' if state else 'disabled'}")
        return False

    def _set_worker(self, value: bool):
        self.act(lambda c: c.put("/api/aries/settings/automations.worker_enabled",
                                 {"value": value}),
                 done=f"Dispatcher {'on' if value else 'off'}")

    def _run(self, automation_id):
        self.act(lambda c: c.post(f"/api/aries/automations/{automation_id}/run",
                                  {"force": True}),
                 done=f"{automation_id} finished")

    def _history(self, automation_id):
        _JsonDialog(self.app, f"History — {automation_id}",
                    f"/api/aries/automations/{automation_id}/runs").present(self.app.get_active_window() or self.app.window)

    def _genome(self, automation_id):
        _JsonDialog(self.app, f"Genome — {automation_id}",
                    f"/api/aries/automations/{automation_id}").present(self.app.get_active_window() or self.app.window)


class _JsonDialog(Adw.Dialog):
    """Raw ARIES state, for when the summary is not enough.

    Progressive disclosure's last step: the technical truth, unedited, rather
    than a prettier version of it that might disagree with the API.
    """

    def __init__(self, app, title, path):
        super().__init__(title=title, content_width=760, content_height=620)
        self._slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(self._slot)
        self.set_child(toolbar)
        self._slot.append(widgets.Loading())
        app.client.call(lambda c: c.get(path), on_ok=self._render,
                        on_error=lambda e: self._set(widgets.error_state(e)))

    def _set(self, widget):
        child = self._slot.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._slot.remove(child)
            child = nxt
        widget.set_vexpand(True)
        self._slot.append(widget)

    def _render(self, data):
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(json.dumps(data, indent=2, ensure_ascii=False))
        view.set_margin_top(design.MD)
        view.set_margin_bottom(design.MD)
        view.set_margin_start(design.MD)
        view.set_margin_end(design.MD)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(view)
        self._set(sw)
