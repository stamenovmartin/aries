"""Live system instrument panels, alongside the last judged health pass."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets, hud  # noqa: E402
from aries_ui.page import Page  # noqa: E402

PROBE_TITLES = {
    "cpu": "Processor", "memory": "Memory", "disk": "Storage", "thermal": "Temperature",
    "gpu": "Graphics", "services": "Services", "uptime": "Uptime",
}


class SystemPage(hud.LivePage):
    title = "System"
    icon = "computer-symbolic"
    subtitle = "This machine, as ARIES last measured it"

    def fetch(self, client):
        return {**client.get("/api/aries/health/latest"), "live":client.get("/api/aries/workspace/telemetry")}

    def render(self, data):
        box = widgets.page_box()
        live = data.get('live', {})
        box.append(hud.hero('ARIES / TELEMETRY', 'System observatory',
                            'Live sensors · sampled ' + widgets.when(live.get('measured_at')) + ' · refreshes every 5 seconds', self.icon))
        box.append(hud.readings_grid(live.get('probes', [])))
        if not data.get("ran"):
            box.append(widgets.absent(
                "No health check has run",
                "ARIES measures this machine only when the System Health automation runs. "
                "Enable it in Automations, or run it once now."))
            return widgets.scrolled(box)

        findings = data.get("findings") or []
        problems = [f for f in findings if f.get("severity") != "ok"]
        healthy = [f for f in findings if f.get("severity") == "ok"]

        box.append(self._headline(data, problems))
        if problems:
            group = widgets.section("Needs attention")
            for f in problems:
                r = widgets.row(f.get("summary", ""), f.get("advice") or f.get("suppressed") or "")
                r.add_prefix(widgets.dot(f.get("severity", "notice")))
                group.add(r)
            box.append(group)

        box.append(self._readings(healthy))
        box.append(self._probes(data.get("probes") or []))
        return widgets.scrolled(box)

    def _headline(self, data, problems) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.MD)
        box.append(widgets.status_icon("warning" if problems else "ok"))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(
            label=("Everything healthy" if not problems
                   else f"{len(problems)} thing{'s' if len(problems) != 1 else ''} to look at"),
            xalign=0)
        title.add_css_class("title-2")
        sub = Gtk.Label(label=f"measured {widgets.when(data.get('started_at'))} · "
                              f"{data.get('duration_ms', 0)} ms", xalign=0)
        sub.add_css_class("aries-quiet")
        text.append(title)
        text.append(sub)
        box.append(text)
        box.append(Gtk.Box(hexpand=True))
        box.append(widgets.button("Check now", self._run, css="pill", icon="view-refresh-symbolic"))
        return box

    def _readings(self, healthy) -> Gtk.Widget:
        """Healthy readings, behind a disclosure. Present, not shouting."""
        group = widgets.section("Readings")
        expander = Adw.ExpanderRow(
            title=f"{len(healthy)} healthy readings",
            subtitle="everything within its normal range")
        expander.add_prefix(widgets.dot("ok"))
        for f in healthy:
            r = widgets.row(f.get("summary", ""), "")
            baseline = f.get("baseline")
            if baseline and baseline.get("trusted"):
                r.set_subtitle(f"normally up to {baseline.get('p95')} here "
                               f"({baseline.get('n')} samples)")
            expander.add_row(r)
        group.add(expander)
        return group

    def _probes(self, probes) -> Gtk.Widget:
        group = widgets.section("Probes", "what ARIES was able to measure")
        for p in probes:
            name = PROBE_TITLES.get(p.get("probe", ""), p.get("probe", ""))
            if p.get("unavailable"):
                r = widgets.row(name, p["unavailable"])
                r.add_prefix(widgets.dot("notice"))
            else:
                readings = [x for x in p.get("readings", []) if x.get("value") is not None]
                r = widgets.row(name, f"{len(readings)} readings · {p.get('duration_ms', 0)} ms")
                r.add_prefix(widgets.dot("ok"))
            group.add(r)
        return group

    def _run(self):
        self.act(lambda c: c.post("/api/aries/automations/aries.health/run", {"force": True}),
                 done="System checked")
