"""Home — only what is worth the first glance.

The brief says to avoid dashboard clutter, and the ordering here is the whole
design: **decisions first**, because they are the only thing on the screen the
user is BLOCKED on. Everything else is information; that is a queue. It is the
same judgement the Morning Brief makes, and the two agree on purpose.

A healthy section collapses to one calm line rather than a card full of green
ticks. Nothing needing attention should look like nothing happening.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402
from aries_ui.page import Page  # noqa: E402


class HomePage(Page):
    title = "Home"
    icon = "go-home-symbolic"
    subtitle = "What needs you, and what ARIES is doing"

    def fetch(self, client):
        # The runtime state comes from ARIES itself, which means this page can
        # only show it when ARIES answers. When it does not, the error state
        # already says "ARIES is not running" and gives the command — which is
        # the honest version of a status indicator that would otherwise have to
        # guess.
        return {"home": client.get("/api/aries/home"),
                "runtime": client.get("/api/aries/runtime")}

    def render(self, data):
        home = data["home"]
        runtime = data.get("runtime") or {}
        box = widgets.page_box()
        box.append(self._status(home, runtime))
        if runtime.get("state") == "DEGRADED":
            box.append(self._degraded(runtime))
        data = home

        decisions = data.get("decisions") or []
        if decisions:
            box.append(self._decisions(decisions))

        box.append(self._brief(data.get("brief")))
        box.append(self._health(data.get("health") or {}))

        notes = data.get("notifications") or []
        if notes:
            box.append(self._notifications(notes))

        box.append(self._next_automation(data))
        box.append(self._learned(data.get("learned") or []))
        return widgets.scrolled(box)

    # ── sections ────────────────────────────────────────────────────────────
    def _degraded(self, runtime) -> Gtk.Widget:
        """Something inside ARIES is not working — said plainly, not buried."""
        group = widgets.section("ARIES itself", runtime.get("summary", ""))
        for c in runtime.get("problems") or []:
            r = widgets.row(c["name"], c.get("detail") or "")
            r.add_prefix(widgets.dot(c.get("severity", "warning")))
            r.add_suffix(widgets.tag(c.get("kind", ""), "aries-quiet"))
            group.add(r)
        return group

    def _status(self, data, runtime=None) -> Gtk.Widget:
        runtime = runtime or {}
        st = data.get("status") or {}
        decisions = len(data.get("decisions") or [])
        healthy = st.get("healthy", True)

        if decisions:
            headline = f"{decisions} decision{'s' if decisions != 1 else ''} waiting for you"
            severity = "critical"
        elif not healthy:
            headline = "Something on this machine needs attention"
            severity = "warning"
        else:
            headline = "Nothing needs you"
            severity = "ok"

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.MD)
        box.append(widgets.status_icon(severity))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=headline, xalign=0)
        title.add_css_class("title-2")
        runtime_state = runtime.get("state")
        detail = (f"{st.get('automations_enabled', 0)} of "
                  f"{st.get('automations_total', 0)} automations enabled")
        if runtime_state:
            detail = f"ARIES {runtime_state.lower()} · " + detail
        sub = Gtk.Label(label=detail, xalign=0)
        sub.add_css_class("aries-quiet")
        text.append(title)
        text.append(sub)
        box.append(text)
        box.append(Gtk.Box(hexpand=True))
        if runtime_state:
            chip = widgets.tag(
                runtime_state,
                {"RUNNING": "aries-ok", "DEGRADED": "aries-warning",
                 "STARTING": "aries-notice", "STOPPED": "aries-critical"}.get(runtime_state, ""))
            chip.set_tooltip_text(runtime.get("means", ""))
            box.append(chip)
        return box

    def _decisions(self, decisions) -> Gtk.Widget:
        group = widgets.section("Waiting for you",
                                "ARIES will not act on these without you")
        for d in decisions:
            r = widgets.row(d.get("title") or d.get("kind", ""),
                            (d.get("rationale") or "")[:160])
            r.add_prefix(widgets.dot("critical" if d.get("risk") == "high" else "warning"))
            r.add_suffix(widgets.tag(d.get("kind", ""), "aries-mono"))
            group.add(r)
        return group

    def _brief(self, brief) -> Gtk.Widget:
        group = widgets.section("Morning brief")
        if not brief:
            r = widgets.row("No brief yet",
                            "Enable it in Settings → General, or generate one now")
            r.add_suffix(widgets.button("Generate", self._generate_brief, css="pill"))
            group.add(r)
            return group
        r = widgets.row(brief.get("headline") or "Brief ready",
                        f"{brief.get('item_count', 0)} items · {widgets.when(brief.get('at'))}")
        r.add_prefix(widgets.dot(brief.get("severity", "info")))
        if not brief.get("seen"):
            r.add_suffix(widgets.tag("unread", "aries-notice"))
        r.add_suffix(widgets.button("Open", lambda: self.app.go("brief"), css="flat"))
        group.add(r)
        return group

    def _health(self, health) -> Gtk.Widget:
        group = widgets.section("System")
        if not health.get("ran"):
            r = widgets.row("The health check has not run yet",
                            "Enable System Health in Automations to see this machine's state")
            r.add_prefix(widgets.dot("notice"))
            group.add(r)
            return group
        findings = health.get("findings") or []
        if not findings:
            r = widgets.row("Everything healthy",
                            f"{health.get('probes', 0)} checks · {widgets.when(health.get('at'))}")
            r.add_prefix(widgets.dot("ok"))
            group.add(r)
            return group
        for f in findings:
            r = widgets.row(f.get("summary", ""), f.get("advice", ""))
            r.add_prefix(widgets.dot(f.get("severity", "notice")))
            group.add(r)
        return group

    def _notifications(self, notes) -> Gtk.Widget:
        group = widgets.section("Recently told you")
        for n in notes:
            r = widgets.row(n.get("title", ""),
                            f"{n.get('source', '')} · {widgets.when(n.get('created_at'))}")
            r.add_prefix(widgets.dot(n.get("severity", "info")))
            group.add(r)
        return group

    def _next_automation(self, data) -> Gtk.Widget:
        group = widgets.section("Next")
        nxt = data.get("next_automation")
        if not nxt:
            r = widgets.row("Nothing scheduled",
                            "No automation is enabled, so ARIES is doing nothing on its own")
            r.add_prefix(widgets.dot("info"))
            r.add_suffix(widgets.button("Automations", lambda: self.app.go("automations"),
                                        css="flat"))
            group.add(r)
            return group
        r = widgets.row(nxt.get("name", ""), f"next {widgets.when(nxt.get('next_run'))}")
        r.add_prefix(widgets.dot(nxt.get("last_status") or "info"))
        r.add_suffix(widgets.button("Run now",
                                    lambda a=nxt["automation_id"]: self._run(a), css="pill"))
        group.add(r)
        return group

    def _learned(self, learned) -> Gtk.Widget:
        group = widgets.section("What ARIES recently learned")
        if not learned:
            r = widgets.row("Nothing learned yet",
                            "ARIES adjusts what it shows you once it has enough evidence")
            r.add_prefix(widgets.dot("info"))
            group.add(r)
            return group
        for item in learned:
            shadowed = item.get("user") is not None
            subtitle = (item.get("rationale") or "")[:150]
            if shadowed:
                subtitle = f"your {item['user']:.2f} still applies · {subtitle}"
            r = widgets.row(f"{item['topic']} — ARIES would weight it "
                            f"{(item.get('learned') or 0):.2f}", subtitle)
            r.add_prefix(widgets.dot("notice"))
            r.add_suffix(widgets.provenance_tag(design.LEARNED))
            group.add(r)
        return group

    # ── actions ─────────────────────────────────────────────────────────────
    def _run(self, automation_id: str):
        self.act(lambda c: c.post(f"/api/aries/automations/{automation_id}/run",
                                  {"force": True}),
                 done=f"{automation_id} finished")

    def _generate_brief(self):
        self.act(lambda c: c.post("/api/aries/automations/aries.brief/run", {"force": True}),
                 done="Brief generated")
