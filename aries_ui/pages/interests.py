"""Interests — where explicit and learned must never blur.

The requirement is unusually specific here, and it is the right thing to be
specific about:

    AI      Explicit: 0.90    Learned: 0.98

Two numbers, side by side, never merged into one. This screen therefore shows
both bars for every topic that has both, and the bars differ in FORM as well as
colour — solid for what you said, dotted for what ARIES inferred — so the
distinction survives a glance, greyscale, and colour-blindness.

Every topic opens into its evidence: the interval, the trend, what ARIES
believes and why, the history of changes, and any pending reversal.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402
from aries_ui.page import Page  # noqa: E402


class InterestsPage(Page):
    title = "Interests"
    icon = "user-bookmarks-symbolic"
    subtitle = "What matters to you — and what ARIES has inferred"

    def fetch(self, client):
        return {
            "interests": client.get("/api/aries/interests"),
            "reversals": client.get("/api/aries/learning/reversals"),
        }

    def render(self, data):
        interests = (data["interests"] or {}).get("interests") or []
        summary = (data["interests"] or {}).get("summary") or {}
        contested = {c["target"]: c for c in (data["reversals"] or {}).get("contested", [])}
        pending = {r["target"]: r for r in (data["reversals"] or {}).get("reversals", [])
                   if r.get("status") == "pending"}

        box = widgets.page_box()
        box.append(self._legend(summary))

        wanted = [i for i in interests if i["stance"] == "want"]
        avoided = [i for i in interests if i["stance"] == "avoid"]

        if not interests:
            return widgets.empty(
                "No topics yet",
                "Tell ARIES what matters to you and it will use that to decide what is "
                "worth showing.",
                icon="user-bookmarks-symbolic",
                action=("Add a topic", self._add_dialog))

        group = widgets.section("Topics I care about")
        for item in sorted(wanted, key=lambda x: -x["weight"]):
            group.add(self._topic_row(item, contested.get(item["topic"]),
                                      pending.get(item["topic"])))
        box.append(group)

        if avoided:
            group = widgets.section("Topics to ignore",
                                    "an item matching these is never shown, however relevant")
            for item in avoided:
                r = widgets.row(item["topic"], ", ".join(item.get("synonyms") or []))
                r.add_prefix(widgets.status_icon("critical"))
                group.add(r)
            box.append(group)

        add = widgets.section("")
        add_row = widgets.row("Add a topic", "or a topic to ignore", activatable=True)
        add_row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        add_row.connect("activated", lambda *_: self._add_dialog())
        add.add(add_row)
        box.append(add)
        return widgets.scrolled(box)

    # ── the two-number row ──────────────────────────────────────────────────
    def _topic_row(self, item, contested, pending) -> Adw.ExpanderRow:
        explicit = item.get("user_weight")
        learned = (item.get("learned") or {}).get("weight") if item.get("learned") else None
        source = item.get("weight_source", "default")

        exp = Adw.ExpanderRow(title=item["topic"])
        exp.set_subtitle(", ".join(item.get("synonyms") or []) or "no synonyms")

        # The two numbers, never merged.
        numbers = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.MD)
        numbers.set_valign(Gtk.Align.CENTER)
        if explicit is not None:
            numbers.append(self._number("Explicit", explicit, design.EXPLICIT))
        if learned is not None:
            numbers.append(self._number("Learned", learned, design.LEARNED))
        if explicit is None and learned is None:
            numbers.append(self._number("Default", item["weight"], design.DEFAULT))
        exp.add_suffix(numbers)

        if pending:
            exp.add_prefix(widgets.dot("warning"))
        elif contested:
            exp.add_prefix(widgets.dot("notice"))
        else:
            exp.add_prefix(widgets.dot("ok"))

        # ── inside: bars, evidence, why, history ────────────────────────────
        if explicit is not None:
            exp.add_row(self._bar_row("What you set", explicit, design.EXPLICIT,
                                      "this is what applies"))
        if learned is not None:
            note = ("shadowed by yours — clearing yours would use this"
                    if explicit is not None else "this is what applies")
            exp.add_row(self._bar_row("What ARIES inferred", learned, design.LEARNED, note))
            if item["learned"].get("rationale"):
                exp.add_row(widgets.row("Why", item["learned"]["rationale"]))

        eng = item.get("engagement") or {}
        if eng.get("shown"):
            rate = eng.get("rate")
            exp.add_row(widgets.row(
                "Evidence",
                f"{eng.get('engaged', 0)} of {eng.get('shown', 0)} opened"
                + (f" · {rate:.0%}" if rate is not None else " · rate unknown")))

        if pending:
            exp.add_row(self._pending_row(pending))
        elif contested:
            exp.add_row(widgets.row(
                f"Contested — {contested['classification']}",
                contested.get("reason", "")[:200]))

        actions = widgets.row("", "")
        btns = Gtk.Box(spacing=design.SM)
        btns.set_valign(Gtk.Align.CENTER)
        btns.append(widgets.button("Explain", lambda t=item["topic"]: self._explain(t), css="flat"))
        if explicit is not None:
            btns.append(widgets.button("Clear mine",
                                       lambda t=item["topic"]: self._clear(t), css="flat"))
        btns.append(widgets.button("Remove", lambda t=item["topic"]: self._remove(t),
                                   css="flat destructive-action"))
        actions.add_suffix(btns)
        exp.add_row(actions)
        return exp

    def _number(self, label: str, value: float, kind: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_valign(Gtk.Align.CENTER)
        cap = Gtk.Label(label=label, xalign=1)
        cap.add_css_class("aries-quiet")
        cap.add_css_class("caption")
        val = Gtk.Label(label=f"{value:.2f}", xalign=1)
        val.add_css_class("aries-numeric")
        val.add_css_class("heading")
        val.add_css_class(design.PROVENANCE_CLASS.get(kind, ""))
        box.append(cap)
        box.append(val)
        return box

    def _bar_row(self, title: str, value: float, kind: str, note: str) -> Adw.ActionRow:
        r = widgets.row(title, note)
        bar = widgets.weight_bar(value, kind)
        bar.set_size_request(180, -1)
        r.add_suffix(bar)
        r.add_suffix(widgets.provenance_tag(kind))
        return r

    def _pending_row(self, pending) -> Adw.ActionRow:
        r = widgets.row(
            f"Reversal pending — {pending['confirmations']} of "
            f"{pending['required_confirmations']} confirmations",
            pending.get("reason", "")[:200])
        r.add_prefix(widgets.dot("warning"))
        return r

    def _legend(self, summary) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.LG)
        for kind in (design.EXPLICIT, design.LEARNED):
            item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.SM)
            swatch = Gtk.Box()
            swatch.set_size_request(22, 6)
            swatch.add_css_class("aries-bar")
            swatch.add_css_class(design.PROVENANCE_CLASS[kind])
            item.append(swatch)
            lbl = Gtk.Label(label=design.PROVENANCE_LABEL[kind])
            lbl.add_css_class("aries-quiet")
            item.append(lbl)
            box.append(item)
        box.append(Gtk.Box(hexpand=True))
        note = Gtk.Label(label=f"{summary.get('shadowed', 0)} of "
                               f"{summary.get('learned', 0)} inferences overridden by you")
        note.add_css_class("aries-quiet")
        box.append(note)
        return box

    # ── actions ─────────────────────────────────────────────────────────────
    def _explain(self, topic: str):
        from aries_ui.explain import ExplainDialog
        ExplainDialog(self.app, topic).present(self.app.get_active_window() or self.app.window)

    def _clear(self, topic: str):
        self.act(lambda c: c.patch(f"/api/aries/interests/{topic}", {"clear_weight": True}),
                 done=f"Your weight for '{topic}' cleared")

    def _remove(self, topic: str):
        self.act(lambda c: c.delete(f"/api/aries/interests/{topic}"),
                 done=f"'{topic}' removed")

    def _add_dialog(self):
        dialog = Adw.AlertDialog(heading="Add a topic",
                                 body="A topic ARIES should watch for — or one to ignore.")
        page = Adw.PreferencesGroup()
        topic = Adw.EntryRow(title="Topic")
        synonyms = Adw.EntryRow(title="Other ways of saying it (comma separated)")
        stance = Adw.ComboRow(title="Stance")
        stance.set_model(Gtk.StringList.new(["care about", "ignore"]))
        weight = Adw.SpinRow.new_with_range(0.0, 1.0, 0.05)
        weight.set_title("Weight")
        weight.set_value(0.7)
        for w in (topic, synonyms, stance, weight):
            page.add(w)
        dialog.set_extra_child(page)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("add")

        def _response(_d, response):
            if response != "add" or not topic.get_text().strip():
                return
            body = {
                "topic": topic.get_text().strip(),
                "stance": "want" if stance.get_selected() == 0 else "avoid",
                "synonyms": [s.strip() for s in synonyms.get_text().split(",") if s.strip()],
            }
            if stance.get_selected() == 0:
                body["weight"] = round(weight.get_value(), 2)
            self.act(lambda c: c.post("/api/aries/interests", body),
                     done=f"'{body['topic']}' added")

        dialog.connect("response", _response)
        dialog.present(self.app.get_active_window() or self.app.window)
