"""The components every screen is built from.

Three of these exist because the brief asks for states most interfaces treat as
afterthoughts, and ARIES has spent ten entries insisting on exactly this
distinction in its data:

    Loading    work is in flight and the window stays interactive
    Empty      nothing here, and that is fine
    Absent     nothing here BECAUSE something is missing or not built

`Empty` and `Absent` look different and say different things. "No failed
services" and "the health automation has never run" are not the same fact, and a
UI that renders both as blankness is lying by omission — the same rule that
makes ARIES report `null` with a reason instead of `0`.
"""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

from aries_ui import design  # noqa: E402


# ── status ──────────────────────────────────────────────────────────────────

def dot(severity: str) -> Gtk.Widget:
    """An 8px status dot in the severity vocabulary."""
    d = Gtk.Box()
    d.add_css_class("aries-dot")
    d.add_css_class(design.SEVERITY_CLASS.get(design.severity_of(severity), "aries-ok"))
    d.set_valign(Gtk.Align.CENTER)
    return d


def status_icon(severity: str) -> Gtk.Image:
    sev = design.severity_of(severity)
    img = Gtk.Image.new_from_icon_name(design.SEVERITY_ICON.get(sev, "emblem-ok-symbolic"))
    img.add_css_class(design.SEVERITY_CLASS.get(sev, "aries-ok"))
    return img


def tag(text: str, css: str = "") -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    lbl.add_css_class("aries-provenance-tag")
    if css:
        lbl.add_css_class(css)
    lbl.set_valign(Gtk.Align.CENTER)
    lbl.set_max_width_chars(28)
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    lbl.set_tooltip_text(str(text))
    return lbl


def provenance_tag(kind: str) -> Gtk.Label:
    """`explicit` / `learned` / `default`, never blurred together."""
    return tag(design.PROVENANCE_LABEL.get(kind, kind), design.PROVENANCE_CLASS.get(kind, ""))


def weight_bar(value: float, kind: str) -> Gtk.ProgressBar:
    bar = Gtk.ProgressBar()
    bar.set_fraction(max(0.0, min(1.0, float(value or 0.0))))
    bar.add_css_class("aries-bar")
    bar.add_css_class("explicit" if kind == design.EXPLICIT else "learned")
    bar.set_valign(Gtk.Align.CENTER)
    bar.set_hexpand(True)
    return bar


# ── states ──────────────────────────────────────────────────────────────────

class Loading(Gtk.Box):
    """Work is in flight. The window stays interactive throughout."""

    def __init__(self, message: str = "Loading…"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=design.MD)
        self.set_valign(Gtk.Align.CENTER)
        self.set_vexpand(True)
        spinner = Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True)
        spinner.set_size_request(32, 32)
        spinner.set_halign(Gtk.Align.CENTER)
        label = Gtk.Label(label=message)
        label.add_css_class("aries-quiet")
        self.append(spinner)
        self.append(label)


def empty(title: str, description: str = "", icon: str = "checkbox-checked-symbolic",
          action: tuple[str, Callable] | None = None) -> Adw.StatusPage:
    """Nothing here, and that is fine."""
    page = Adw.StatusPage(title=title, description=description or None, icon_name=icon)
    page.add_css_class("compact")
    if action:
        label, cb = action
        btn = Gtk.Button(label=label)
        btn.add_css_class("pill")
        btn.add_css_class("suggested-action")
        btn.set_halign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda *_: cb())
        page.set_child(btn)
    return page


def absent(title: str, reason: str, command: str = "") -> Adw.StatusPage:
    """Nothing here BECAUSE something is missing — a different fact from empty."""
    page = Adw.StatusPage(title=title, description=reason,
                          icon_name="dialog-question-symbolic")
    page.add_css_class("compact")
    if command:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=design.SM)
        box.set_halign(Gtk.Align.CENTER)
        code = Gtk.Label(label=command, selectable=True)
        code.add_css_class("aries-mono")
        code.add_css_class("aries-quiet")
        box.append(code)
        page.set_child(box)
    return page


def error_state(exc: Exception, retry: Callable | None = None) -> Gtk.Widget:
    """A failure, in plain words, with the command that fixes it when there is one."""
    from aries_ui.client import describe
    title, explanation, command = describe(exc)
    page = Adw.StatusPage(title=title, description=explanation,
                          icon_name="network-offline-symbolic")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=design.MD)
    box.set_halign(Gtk.Align.CENTER)
    if command:
        code = Gtk.Label(label=command, selectable=True)
        code.add_css_class("aries-mono")
        code.add_css_class("aries-quiet")
        box.append(code)
    if retry:
        btn = Gtk.Button(label="Try again")
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda *_: retry())
        box.append(btn)
    page.set_child(box)
    return page


# ── layout ──────────────────────────────────────────────────────────────────

def page_box(spacing: int = design.LG) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.set_margin_top(design.XL)
    box.set_margin_bottom(design.XXL)
    box.set_margin_start(design.XL)
    box.set_margin_end(design.XL)
    return box


def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_vexpand(True)
    clamp = Adw.Clamp(maximum_size=1180, tightening_threshold=880)
    clamp.set_child(child)
    sw.set_child(clamp)
    return sw


def section(title: str, description: str = "") -> Adw.PreferencesGroup:
    """A titled group. The title is Pango markup, so it is escaped.

    `row()` had escaped its title since the first screen; this one did not, and
    nothing noticed until a section was called "Power & Background" and the bare
    ampersand made Pango reject the whole string — leaving the group untitled,
    with the reason only in a warning on stderr. Text that reaches a markup
    parser is escaped at every door, not at most of them.
    """
    return Adw.PreferencesGroup(title=GLib.markup_escape_text(title),
                                description=GLib.markup_escape_text(description)
                                if description else None)


def row(title: str, subtitle: str = "", *, activatable: bool = False) -> Adw.ActionRow:
    r = Adw.ActionRow(title=GLib.markup_escape_text(title))
    if subtitle:
        r.set_subtitle(GLib.markup_escape_text(subtitle))
    r.set_activatable(activatable)
    return r


def switch_row(title: str, subtitle: str, active: bool,
               on_change: Callable[[bool], None]) -> Adw.SwitchRow:
    """A toggle that reports the user's intent once, not the programmatic reset.

    Setting `active` from code emits `notify::active` too, and without the guard
    every refresh would write the value back to ARIES — a UI that argues with
    itself and floods the audit log.
    """
    r = Adw.SwitchRow(title=title, subtitle=subtitle or None)
    r.set_active(active)
    guard = {"quiet": False}

    def _changed(widget, _param):
        if guard["quiet"]:
            return
        on_change(widget.get_active())

    r.connect("notify::active", _changed)

    def set_quiet(value: bool):
        guard["quiet"] = True
        r.set_active(value)
        guard["quiet"] = False

    r.set_quiet = set_quiet          # type: ignore[attr-defined]
    return r


def button(label: str, on_click: Callable, *, css: str = "", icon: str = "") -> Gtk.Button:
    if icon:
        btn = Gtk.Button()
        content = Adw.ButtonContent(icon_name=icon, label=label)
        btn.set_child(content)
    else:
        btn = Gtk.Button(label=label)
    if css:
        for c in css.split():
            btn.add_css_class(c)
    btn.set_valign(Gtk.Align.CENTER)
    btn.connect("clicked", lambda *_: on_click())
    return btn


def key_value(key: str, value: str, *, mono: bool = False) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.MD)
    k = Gtk.Label(label=key, xalign=0)
    k.add_css_class("aries-quiet")
    k.set_size_request(150, -1)
    v = Gtk.Label(label=value, xalign=0, wrap=True, selectable=True)
    v.add_css_class("aries-numeric")
    if mono:
        v.add_css_class("aries-mono")
    v.set_hexpand(True)
    box.append(k)
    box.append(v)
    return box


def when(iso: str | None, *, fallback: str = "never") -> str:
    """A timestamp a person can read. ARIES stores UTC; people live locally.

    The two-clocks bug from Entries 003 and 009, arriving for a third time in a
    third subsystem — and this time the convention from ERROR_LOG.md was already
    written down: database timestamps are UTC, and conversion happens at the
    point of display. This is that point.
    """
    if not iso:
        return fallback
    from datetime import datetime, timezone
    try:
        raw = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:16].replace("T", " ")
    if raw.tzinfo is None:
        raw = raw.replace(tzinfo=timezone.utc)
    local = raw.astimezone()
    delta = datetime.now(timezone.utc) - raw
    seconds = delta.total_seconds()
    if seconds < 0:
        mins = int(-seconds // 60)
        if mins < 60:
            return f"in {mins} min" if mins else "in a moment"
        if mins < 60 * 24:
            return f"in {mins // 60}h"
        return local.strftime("%a %d %b, %H:%M")
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 86400 * 7:
        return f"{int(seconds // 86400)}d ago"
    return local.strftime("%d %b, %H:%M")
