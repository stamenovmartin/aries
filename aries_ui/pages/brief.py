"""The Morning Brief, read rather than generated.

The brief is already rendered as text by ARIES, in three lengths, from stored
sections. This screen shows the structured form — sections, severities, items —
and lets the length be changed without collecting again, which is exactly what
the stored sections exist for.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402
from aries_ui.page import Page  # noqa: E402


class BriefPage(Page):
    title = "Brief"
    icon = "view-paged-symbolic"
    subtitle = "One page, once a morning"

    def fetch(self, client):
        return client.get("/api/aries/brief")

    def render(self, data):
        if not data.get("exists"):
            return widgets.empty(
                "No brief yet",
                "ARIES gathers what needs you, what the machine is doing and what is worth "
                "reading, once a morning.",
                icon="view-paged-symbolic",
                action=("Generate one now", self._generate))

        box = widgets.page_box()
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.MD)
        head.append(widgets.status_icon(data.get("severity", "info")))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=data.get("headline") or "Brief", xalign=0, wrap=True)
        title.add_css_class("title-2")
        sub = Gtk.Label(label=f"{data.get('item_count', 0)} items · "
                              f"{widgets.when(data.get('created_at'))}", xalign=0)
        sub.add_css_class("aries-quiet")
        text.append(title)
        text.append(sub)
        head.append(text)
        box.append(head)

        for section in data.get("sections") or []:
            group = widgets.section(section["title"], section.get("summary") or "")
            if section.get("unavailable"):
                r = widgets.row("Not available", section["unavailable"])
                r.add_prefix(widgets.dot("info"))
                group.add(r)
            elif not section.get("items"):
                r = widgets.row(section.get("summary") or "Nothing", "")
                r.add_prefix(widgets.dot("ok"))
                group.add(r)
            for item in section.get("items") or []:
                r = widgets.row(item["text"], item.get("detail") or "")
                r.add_prefix(widgets.dot(item.get("severity", "info")))
                group.add(r)
            box.append(group)
        return widgets.scrolled(box)

    def header_suffix(self):
        return widgets.button("Generate", self._generate, css="flat")

    def _generate(self):
        self.act(lambda c: c.post("/api/aries/automations/aries.brief/run", {"force": True}),
                 done="Brief generated")
