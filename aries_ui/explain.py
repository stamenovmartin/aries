"""«Why does ARIES believe this?» — as a dialog.

The CLI answers this with `aries learning explain`. This is the same answer, from
the same endpoint, laid out so it can be read rather than parsed: what is
believed now, why, from which evidence, at what scope, how sure, and — set apart
visually — whether it came from the user or from inference.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402


class ExplainDialog(Adw.Dialog):
    def __init__(self, app, subject: str):
        super().__init__(title="Why ARIES believes this", content_width=620, content_height=560)
        self.app = app
        self.subject = subject

        self._slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._slot.set_vexpand(True)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(self._slot)
        self.set_child(toolbar)

        self._show(widgets.Loading("Asking ARIES…"))
        app.client.call(lambda c: c.get(f"/api/aries/learning/explain/{subject}"),
                        on_ok=self._render, on_error=self._failed)

    def _show(self, widget):
        child = self._slot.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._slot.remove(child)
            child = nxt
        widget.set_vexpand(True)
        self._slot.append(widget)

    def _failed(self, exc):
        self._show(widgets.error_state(exc))

    def _render(self, data):
        box = widgets.page_box()

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=design.XS)
        subject = Gtk.Label(label=str(data.get("subject", self.subject)), xalign=0)
        subject.add_css_class("title-2")
        value = Gtk.Label(label=_pretty(data.get("value")), xalign=0, selectable=True)
        value.add_css_class("title-1")
        value.add_css_class("aries-numeric")
        kind = design.EXPLICIT if data.get("explicit") else (
            design.LEARNED if data.get("source") == "learned" else design.DEFAULT)
        value.add_css_class(design.PROVENANCE_CLASS[kind])
        head.append(subject)
        head.append(value)
        tags = Gtk.Box(spacing=design.SM)
        tags.append(widgets.provenance_tag(kind))
        tags.append(widgets.tag(data.get("source_label", ""), "aries-quiet"))
        head.append(tags)
        box.append(head)

        group = widgets.section("Because")
        group.add(widgets.row(data.get("because", "") or "no reason recorded", ""))
        group.add(widgets.row("Scope", data.get("scope") or "everywhere"))
        if data.get("confidence") is not None:
            group.add(widgets.row("Confidence", f"{data['confidence']:.0%}"))
        box.append(group)

        ev = data.get("evidence") or {}
        overall = ev.get("overall")
        if overall:
            group = widgets.section("Evidence")
            group.add(widgets.row(
                f"{overall.get('engaged', 0)} of {overall.get('shown', 0)} opened",
                f"interval [{overall.get('lower')}, {overall.get('upper')}] over "
                f"{ev.get('window_days')} days · trend {ev.get('trend')}"))
            best, worst = ev.get("best_source"), ev.get("worst_source")
            if best and worst:
                group.add(widgets.row(
                    "By source",
                    f"{best['label']}: {best['engaged']}/{best['shown']} · "
                    f"{worst['label']}: {worst['engaged']}/{worst['shown']}"))
            box.append(group)
        elif ev.get("note"):
            group = widgets.section("Evidence")
            group.add(widgets.row("None yet", ev["note"]))
            box.append(group)

        alternatives = [a for a in (data.get("alternatives") or [])
                        if a.get("layer") != data.get("source")]
        if alternatives:
            group = widgets.section("Also held", "kept, not overwritten — so nothing is lost")
            for a in alternatives:
                r = widgets.row(str(a.get("layer", "?")), _pretty(a.get("value")))
                if a.get("rationale"):
                    r.set_subtitle(str(a["rationale"])[:180])
                group.add(r)
            box.append(group)

        history = data.get("history") or []
        if history:
            group = widgets.section("Changed")
            for h in history[:8]:
                if "from" in h:
                    r = widgets.row(f"{h['from']} → {h['to']}",
                                    f"{widgets.when(h.get('at'))} · "
                                    f"{h.get('classification') or 'ordinary'} · "
                                    f"{h.get('policy_version', '')}")
                    r.add_prefix(widgets.dot("warning" if h.get("reversal") else "info"))
                else:
                    r = widgets.row(f"Reversal {h.get('status')}",
                                    f"{widgets.when(h.get('first_seen'))} · "
                                    f"{h.get('classification', '')}")
                    r.add_prefix(widgets.dot("warning"))
                group.add(r)
            box.append(group)

        said = data.get("feedback") or []
        if said:
            group = widgets.section("You said")
            for f in said[:6]:
                r = widgets.row(f'"{f.get("text", "")}"',
                                f"{f.get('classification')} · {f.get('scope')} · "
                                f"{widgets.when(f.get('at'))}")
                group.add(r)
            box.append(group)

        self._show(widgets.scrolled(box))


def _pretty(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "—"
    return str(value)
