"""News — configuring the News Radar without knowing a single URL.

Two halves. **Sources**: browse the catalogue by category, add a feed, and see
each source's real health — including the error when there is one. **Articles**:
what ARIES chose to show, what it held back, and why, with feedback on each item
that goes to the same endpoints the CLI uses.

Article feedback is the interesting part. "Useful" and "not useful" are counted
against the item, its source and its topics — evidence for the medium loop —
while "follow this topic" and "block this source" are the user speaking, and
land at layers the loop can never reach.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets, hud  # noqa: E402
from aries_ui.page import Page  # noqa: E402

DISPOSITION = {
    "delivered": ("shown", "ok"),
    "held": ("held for the brief", "notice"),
    "below_threshold": ("below your bar", "info"),
    "excluded": ("excluded", "critical"),
    "duplicate": ("duplicate", "info"),
}


class NewsPage(Page):
    title = "News"
    icon = "application-rss+xml-symbolic"
    subtitle = "Where news comes from, and what reached you"

    def __init__(self, app):
        super().__init__(app)
        self._tab = "articles"

    def fetch(self, client):
        return {
            "sources": client.get("/api/aries/sources", type="rss"),
            "catalogue": client.get("/api/aries/sources/catalogue"),
            "items": client.get("/api/aries/news", limit=25),
            "settings": client.get("/api/aries/settings", section="news"),
        }

    def render(self, data):
        stack = Adw.ViewStack()
        stack.add_titled_with_icon(widgets.scrolled(self._sources(data)), "sources",
                                   "Sources", "application-rss+xml-symbolic")
        stack.add_titled_with_icon(widgets.scrolled(self._articles(data)), "articles",
                                   "Articles", "view-list-symbolic")
        stack.add_titled_with_icon(widgets.scrolled(self._tuning(data)), "tuning",
                                   "Tuning", "preferences-system-symbolic")
        stack.set_visible_child_name(self._tab)
        stack.connect("notify::visible-child-name",
                      lambda s, _p: setattr(self, "_tab", s.get_visible_child_name()))

        switcher = Adw.ViewSwitcherBar(stack=stack, reveal=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(stack)
        box.append(switcher)
        return box

    # ── sources ─────────────────────────────────────────────────────────────
    def _sources(self, data) -> Gtk.Widget:
        box = widgets.page_box()
        mine = (data["sources"] or {}).get("sources") or []
        catalogue = data["catalogue"] or {}

        group = widgets.section("Your sources", f"{len(mine)} feed(s)")
        if not mine:
            r = widgets.row("Nothing yet",
                            "Pick from the catalogue below, or add a feed by URL")
            r.add_prefix(widgets.dot("info"))
            group.add(r)
        for s in mine:
            group.add(self._source_row(s))
        box.append(group)

        add = widgets.section("")
        add_row = widgets.row("Add a feed by URL", "if you already know the address",
                              activatable=True)
        add_row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        add_row.connect("activated", lambda *_: self._add_dialog())
        add.add(add_row)
        box.append(add)

        have = {s.get("metadata", {}).get("catalogue_id") for s in mine}
        by_category: dict[str, list] = {}
        for entry in catalogue.get("entries", []):
            by_category.setdefault(entry["category"], []).append(entry)

        titles = {c["id"]: c["title"] for c in catalogue.get("categories", [])}
        for category, entries in by_category.items():
            group = widgets.section(titles.get(category, category))
            for e in entries:
                r = widgets.row(e["name"], e["description"])
                if e.get("language") != "en":
                    r.add_suffix(widgets.tag(e["language"], "aries-quiet"))
                if e["id"] in have or e.get("already_added"):
                    r.add_suffix(widgets.tag("added", "aries-ok"))
                else:
                    r.add_suffix(widgets.button(
                        "Add", lambda i=e["id"]: self._add_from_catalogue(i), css="pill flat"))
                group.add(r)
            box.append(group)

        unavailable = catalogue.get("unavailable") or []
        if unavailable:
            group = widgets.section("Checked and not working",
                                    "verified when the catalogue was built")
            for u in unavailable:
                r = widgets.row(u["name"], u["why"])
                r.add_prefix(widgets.dot("notice"))
                group.add(r)
            box.append(group)
        return box

    def _source_row(self, s) -> Adw.ExpanderRow:
        health = s.get("health") or {}
        perf = s.get("performance") or {}
        exp = Adw.ExpanderRow(title=s["name"])
        exp.set_subtitle(f"{health.get('state', '')}"
                         + (f" · {health['reason']}" if health.get("reason") else ""))
        exp.add_prefix(widgets.dot(health.get("state", "info")))

        toggle = Gtk.Switch()
        toggle.set_active(bool(s.get("enabled")))
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.connect("state-set", self._on_enable, s["source_id"])
        exp.add_suffix(toggle)

        exp.add_row(widgets.row("Address", s.get("location_original") or s["location"]))
        exp.add_row(widgets.row("Last read", widgets.when(s.get("last_sync"))))
        if s.get("last_error"):
            r = widgets.row("Last error", s["last_error"][:200])
            r.add_prefix(widgets.dot("critical"))
            exp.add_row(r)
        useful = perf.get("useful_rate")
        exp.add_row(widgets.row(
            "Usefulness",
            f"{perf.get('items_useful', 0)} of {perf.get('items_seen', 0)} reached you"
            + (f" · {useful:.0%}" if useful is not None else " · unknown — not read yet")))
        exp.add_row(self._priority_row(s))
        exp.add_row(self._trust_row(s))
        exp.add_row(widgets.row("Topics", ", ".join(s.get("topics") or []) or "any"))

        remove = widgets.row("Remove this source", "", activatable=True)
        remove.add_prefix(Gtk.Image.new_from_icon_name("user-trash-symbolic"))
        remove.connect("activated", lambda _w, i=s["source_id"]: self._remove(i))
        exp.add_row(remove)
        return exp

    def _priority_row(self, s) -> Adw.ComboRow:
        row = Adw.ComboRow(title="Priority", subtitle="your ranking always beats what ARIES learns")
        options = ["low", "normal", "high"]
        row.set_model(Gtk.StringList.new(options))
        row.set_selected(options.index(s.get("priority", "normal")))
        row.connect("notify::selected", lambda w, _p: self._patch(
            s["source_id"], {"priority": options[w.get_selected()]}, "Priority updated"))
        return row

    def _trust_row(self, s) -> Adw.ComboRow:
        row = Adw.ComboRow(title="Trust")
        options = ["blocked", "untrusted", "normal", "trusted"]
        row.set_model(Gtk.StringList.new(options))
        row.set_selected(options.index(s.get("trust", "normal")))
        row.connect("notify::selected", lambda w, _p: self._patch(
            s["source_id"], {"trust": options[w.get_selected()]}, "Trust updated"))
        return row

    # ── articles ────────────────────────────────────────────────────────────
    def _articles(self, data) -> Gtk.Widget:
        box = widgets.page_box()
        items = (data["items"] or {}).get("items") or []
        if not items:
            return widgets.empty(
                "No articles yet",
                "Add a source and run the News Radar; what it finds appears here — "
                "including what it decided not to show you.",
                icon="application-rss+xml-symbolic",
                action=("Run News Radar", self._run))

        box.append(hud.hero('ARIES / INTELLIGENCE', 'News radar',
                            f'{len(items)} recent articles · Real sources, ranked for your interests', self.icon))
        stories = hud.grid(2)
        for item in [i for i in items if not i.get('excluded_by') and i.get('disposition') not in {'excluded','duplicate'}][:6]:
            story = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            story.add_css_class('hud-story')
            story.append(hud.label(item.get('source_id','SOURCE'), 'hud-kicker'))
            headline = hud.label(item['title'], 'hud-story-title')
            headline.set_max_width_chars(28)
            story.append(headline)
            description = hud.label((item.get('summary') or item.get('explanation') or 'Collected from a configured news source.')[:240], 'hud-muted')
            description.set_max_width_chars(38)
            story.append(description)
            url = item.get('link')
            if url:
                button = Gtk.Button(label='Read with ARIES ↗')
                button.connect('clicked', lambda _, u=url: self.act(lambda c: c.post('/api/aries/workspace', {'capability':'read_article','args':{'url':u}}), on_ok=lambda r:self.app.open_goal(r['id'], temporary=True), then_reload=False))
                story.append(button)
            stories.append(story)
        box.append(stories)
        group = widgets.section("What ARIES saw",
                                "including the items it chose not to show you")
        for item in items:
            group.add(self._article_row(item))
        box.append(group)
        return box

    def _article_row(self, item) -> Adw.ExpanderRow:
        label, severity = DISPOSITION.get(item.get("disposition", ""),
                                          (item.get("disposition", ""), "info"))
        exp = Adw.ExpanderRow(title=item["title"])
        exp.set_subtitle(f"{item['source_id']} · {label} · relevance {item['relevance']}")
        exp.add_prefix(widgets.dot(severity))

        if item.get("explanation"):
            exp.add_row(widgets.row("Why", item["explanation"]))
        if item.get("excluded_by"):
            r = widgets.row("Excluded by", item["excluded_by"])
            r.add_prefix(widgets.dot("critical"))
            exp.add_row(r)
        if item.get("link"):
            link = widgets.row("Link", item["link"])
            exp.add_row(link)

        actions = widgets.row("Was this useful?", "")
        buttons = Gtk.Box(spacing=design.SM)
        buttons.set_valign(Gtk.Align.CENTER)
        buttons.append(widgets.button(
            "Useful", lambda i=item["item_id"]: self._feedback(i, engaged=True),
            css="flat", icon="thumbs-up-symbolic"))
        buttons.append(widgets.button(
            "Not useful", lambda i=item["item_id"]: self._feedback(i, dismissed=True),
            css="flat", icon="thumbs-down-symbolic"))
        actions.add_suffix(buttons)
        exp.add_row(actions)

        for topic in item.get("topics") or []:
            r = widgets.row(f"More like '{topic}'", "raises this topic — your setting, not a guess",
                            activatable=True)
            r.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
            r.connect("activated", lambda _w, t=topic: self._follow(t))
            exp.add_row(r)

        block = widgets.row(f"Block {item['source_id']}",
                            "nothing from this source will be shown again", activatable=True)
        block.add_prefix(Gtk.Image.new_from_icon_name("action-unavailable-symbolic"))
        block.connect("activated", lambda _w, s=item["source_id"]: self._block(s))
        exp.add_row(block)
        return exp

    # ── tuning ──────────────────────────────────────────────────────────────
    def _tuning(self, data) -> Gtk.Widget:
        from aries_ui.pages.settings import settings_group
        box = widgets.page_box()
        settings = (data["settings"] or {}).get("settings") or []
        box.append(settings_group(self, "News Radar", settings))
        return box

    # ── actions ─────────────────────────────────────────────────────────────
    def _on_enable(self, _switch, state, source_id):
        self._patch(source_id, {"enabled": bool(state)},
                    f"Source {'enabled' if state else 'disabled'}")
        return False

    def _patch(self, source_id, body, done):
        self.act(lambda c: c.patch(f"/api/aries/sources/{source_id}", body), done=done)

    def _remove(self, source_id):
        self.act(lambda c: c.delete(f"/api/aries/sources/{source_id}"), done="Source removed")

    def _add_from_catalogue(self, entry_id):
        self.act(lambda c: c.post("/api/aries/sources/from-catalogue", {"entry_id": entry_id}),
                 done="Source added")

    def _feedback(self, item_id, *, engaged=False, dismissed=False):
        self.act(lambda c: c.post(f"/api/aries/news/{item_id}/feedback",
                                  {"engaged": engaged, "dismissed": dismissed}),
                 done="Thanks — that counts as evidence", then_reload=False)

    def _follow(self, topic):
        self.act(lambda c: c.post("/api/aries/interests",
                                  {"topic": topic, "weight": 0.8}),
                 done=f"Following '{topic}'", then_reload=False)

    def _block(self, source_id):
        self.act(lambda c: c.patch(f"/api/aries/sources/{source_id}", {"trust": "blocked"}),
                 done=f"{source_id} blocked")

    def _run(self):
        self.act(lambda c: c.post("/api/aries/automations/aries.news/run", {"force": True}),
                 done="News Radar finished")

    def header_suffix(self):
        return widgets.button("Scan now", self._run, css="flat")

    def _add_dialog(self):
        dialog = Adw.AlertDialog(heading="Add a source",
                                 body="A feed URL, or a folder on this machine.")
        group = Adw.PreferencesGroup()
        name = Adw.EntryRow(title="Name")
        location = Adw.EntryRow(title="Address (https://… or a folder path)")
        kind = Adw.ComboRow(title="Type")
        types = ["rss", "website", "directory", "documents", "repository"]
        kind.set_model(Gtk.StringList.new(types))
        topics = Adw.EntryRow(title="Topics (comma separated, optional)")
        for w in (name, location, kind, topics):
            group.add(w)
        dialog.set_extra_child(group)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        def _response(_d, response):
            if response != "add":
                return
            body = {"name": name.get_text().strip(),
                    "type": types[kind.get_selected()],
                    "location": location.get_text().strip(),
                    "topics": [t.strip() for t in topics.get_text().split(",") if t.strip()]}
            if not body["name"] or not body["location"]:
                self.app.toast("A name and an address are needed")
                return
            # ARIES validates the location; a refusal is shown as ARIES worded it.
            self.act(lambda c: c.post("/api/aries/sources", body), done="Source added")

        dialog.connect("response", _response)
        dialog.present(self.app.get_active_window() or self.app.window)
