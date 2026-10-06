"""Connections — §23's hub, and an honest one.

Three states, and the third is the point: **not implemented** is shown as such,
with the reason, rather than as an empty card implying it would work if only you
configured it. The status is derived by ARIES from what actually exists — a
source type with no connector cannot be "available" — so this screen cannot
drift into claiming a capability the system does not have.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402
from aries_ui.page import Page  # noqa: E402

STATE = {
    "connected": ("Connected", "ok"),
    "available": ("Available", "notice"),
    "not_implemented": ("Not built yet", "info"),
}
CATEGORY_TITLES = {
    "information": "Information", "personal": "Personal",
    "development": "Development", "system": "System",
}


class ConnectionsPage(Page):
    title = "Connections"
    icon = "network-server-symbolic"
    subtitle = "What ARIES can reach — and what it cannot yet"

    def fetch(self, client):
        return {"connections": client.get("/api/aries/connections"),
                "connect": client.get("/api/aries/connect"),
                "attention": client.get("/api/aries/attention")}

    def render(self, bundle):
        data = bundle["connections"]
        box = widgets.page_box()
        box.append(self._summary(data))
        box.append(self._attention(bundle["attention"]))
        box.append(self._connected(bundle["connect"]))

        by_category: dict[str, list] = {}
        for i in data.get("integrations") or []:
            by_category.setdefault(i["category"], []).append(i)

        # Connected and available first; what is not built is grouped at the end,
        # so the screen leads with what the user can actually do.
        for category in ("information", "personal", "development", "system"):
            entries = [i for i in by_category.get(category, [])
                       if i["status"] != "not_implemented"]
            if entries:
                group = widgets.section(CATEGORY_TITLES.get(category, category))
                for i in entries:
                    group.add(self._row(i))
                box.append(group)

        missing = [i for i in (data.get("integrations") or [])
                   if i["status"] == "not_implemented"]
        if missing:
            group = widgets.section(
                "Not built yet",
                "ARIES says so rather than showing a screen that would never work")
            for i in missing:
                group.add(self._row(i))
            box.append(group)
        return widgets.scrolled(box)

    def _attention(self, attention) -> Gtk.Widget:
        """What the last pass found — and what tried to instruct ARIES.

        The injection attempts are shown, never hidden. Content that tried to
        give ARIES orders is evidence, and a person wants to see that someone
        tried far more than they want a tidy screen.
        """
        needs = attention.get("needs_you") or []
        group = widgets.section(
            "What needs you",
            attention.get("summary") or "The Attention Pass has not run yet. It reads what "
            "you have connected, understands each item on the local model, and never acts "
            "on any of it.")

        run = widgets.row("Read my sources now",
                          "Reports only — it never replies, forwards, deletes or marks "
                          "anything as read")
        run.add_suffix(widgets.button(
            "Run",
            lambda: self.act(lambda c: c.post("/api/aries/attention/run"),
                             done="Attention Pass finished")))
        group.add(run)

        if not attention.get("ran"):
            return group

        for item in needs[:10]:
            severity = "critical" if item.get("suspicious") else "notice"
            exp = Adw.ExpanderRow(title=item.get("title") or "(untitled)")
            exp.set_subtitle(str(item.get("summary") or "")[:160])
            exp.add_prefix(widgets.dot(severity))
            exp.add_suffix(widgets.tag(item.get("urgency") or "",
                                       design.SEVERITY_CLASS.get(severity, "")))
            exp.add_row(widgets.row("What it is",
                                    f"{item.get('category')} · from {item.get('source_id')}"))
            if item.get("author"):
                exp.add_row(widgets.row("From", item["author"]))
            for attempt in item.get("injection_attempts") or []:
                r = widgets.row("This content tried to instruct ARIES",
                                f"{attempt['why']} — “{attempt['excerpt']}”")
                r.add_prefix(widgets.dot("critical"))
                exp.add_row(r)
            group.add(exp)

        if attention.get("can_wait"):
            group.add(widgets.row(f"{len(attention['can_wait'])} more can wait",
                                  "understood, and not worth interrupting you for"))
        if attention.get("not_understood"):
            r = widgets.row(f"{attention['not_understood']} not understood",
                            "the local model did not answer for these — an unread inbox is "
                            "not an empty one")
            r.add_prefix(widgets.dot("warning"))
            group.add(r)
        for failure in attention.get("failures") or []:
            r = widgets.row(failure.get("source_id") or "a source", failure.get("why") or "")
            r.add_prefix(widgets.dot("warning"))
            group.add(r)
        return group

    def _connected(self, connect) -> Gtk.Widget:
        """The sources ARIES can actually read, and where their secrets live."""
        keyring = connect.get("keyring") or {}
        group = widgets.section(
            "Connected and readable",
            "Credentials live in the OS keyring. ARIES stores a reference — meaningless "
            "without the keyring — and never the secret itself.")

        r = widgets.row(
            "Keyring" if keyring.get("available") else "No keyring",
            f"credentials are stored in {keyring.get('backend')}" if keyring.get("available")
            else "ARIES will refuse to store a credential rather than write it to a file")
        r.add_prefix(widgets.dot("ok" if keyring.get("available") else "warning"))
        group.add(r)

        r = widgets.row(
            "Reading connected sources" if connect.get("enabled") else "Reading is switched off",
            "ARIES may read the folders and mailboxes below" if connect.get("enabled")
            else "sources can be registered and checked; nothing is read")
        r.add_prefix(widgets.dot("ok" if connect.get("enabled") else "info"))
        group.add(r)

        r = widgets.row(
            "Understanding happens on this machine" if connect.get("understand_locally")
            else "Understanding may leave this machine",
            "summaries and categories are produced by the local model only"
            if connect.get("understand_locally")
            else "content may be sent to whichever model provider is configured")
        r.add_prefix(widgets.dot("ok" if connect.get("understand_locally") else "warning"))
        group.add(r)

        for source in connect.get("sources") or []:
            exp = Adw.ExpanderRow(title=source["name"])
            exp.set_subtitle(f"{source['type']} · {source['location'][:70]}")
            exp.add_prefix(widgets.dot("ok" if source["enabled"] else "info"))
            exp.add_row(widgets.row("Can do", ", ".join(source["capabilities"])))
            exp.add_row(widgets.row("Leaves this machine",
                                    "yes" if source["outbound"] else "no — stays local"))
            cred = source.get("credential") or {}
            if cred.get("reference"):
                exp.add_row(widgets.row(
                    "Credential",
                    f"{'stored' if cred.get('stored') else 'MISSING'} in {cred.get('where')}"))
            if source.get("last_error"):
                r = widgets.row("Last error", source["last_error"][:160])
                r.add_prefix(widgets.dot("warning"))
                exp.add_row(r)
            exp.add_row(widgets.row("Last read", widgets.when(source.get("last_sync"))))
            group.add(exp)

        if not connect.get("sources"):
            group.add(widgets.row(
                "Nothing connected yet",
                "aries connect add directory Notes ~/Documents/notes"))
        return group

    def _summary(self, data) -> Gtk.Widget:
        counts = data.get("counts") or {}
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.LG)
        for key in ("connected", "available", "not_implemented"):
            label, severity = STATE[key]
            item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.SM)
            item.append(widgets.dot(severity))
            text = Gtk.Label(label=f"{counts.get(key, 0)} {label.lower()}")
            text.add_css_class("aries-quiet")
            item.append(text)
            box.append(item)
        return box

    def _row(self, integration) -> Adw.ExpanderRow:
        label, severity = STATE.get(integration["status"], (integration["status"], "info"))
        exp = Adw.ExpanderRow(title=integration["name"])
        exp.set_subtitle(integration.get("detail") or label)
        exp.add_prefix(widgets.dot(severity))
        exp.add_suffix(widgets.tag(label, design.SEVERITY_CLASS.get(severity, "")))

        exp.add_row(widgets.row("What it does", integration["description"]))
        exp.add_row(widgets.row("Permissions ARIES would use",
                                ", ".join(integration.get("permissions") or []) or "none"))
        exp.add_row(widgets.row("Leaves this machine",
                                "yes" if integration.get("outbound") else
                                "no — stays local"))
        if integration.get("requires_credentials"):
            r = widgets.row("Needs a credential",
                            "stored in the OS keyring, never in settings or memory")
            r.add_prefix(widgets.dot("notice"))
            exp.add_row(r)
        if integration.get("spec_section"):
            exp.add_row(widgets.row("Specification", integration["spec_section"]))

        for s in integration.get("sources") or []:
            health = s.get("health") or {}
            r = widgets.row(s["name"], f"{health.get('state', '')} · "
                                       f"last read {widgets.when(s.get('last_sync'))}")
            r.add_prefix(widgets.dot(health.get("state", "info")))
            exp.add_row(r)

        if integration["status"] == "available":
            r = widgets.row("Connect one", "adds a source of this kind", activatable=True)
            r.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
            r.connect("activated", lambda *_: self.app.go("news"))
            exp.add_row(r)
        return exp
