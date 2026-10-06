"""Settings — the graphical system, built from the schema.

Not a hand-written form per setting. The Settings Service already declares
everything a control needs — type, title, description, control kind, choices,
bounds, whether it is advanced, whether a machine may write it — so the screen is
**generated** from `GET /api/aries/settings`. Adding a setting to ARIES makes it
appear here, correctly rendered, with no UI change at all.

Two things are shown that a settings screen usually hides, because ARIES's whole
design depends on them being visible:

* where a value came from — yours, inferred, or the shipped default;
* what a stronger layer is currently overriding, so a value you set which is
  being outranked by a security policy does not silently appear to be in force.

Advanced settings are behind a disclosure per section (progressive disclosure),
and nothing here requires editing YAML.
"""
from __future__ import annotations

from dataclasses import replace
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402
from aries_ui.page import Page  # noqa: E402

SECTION_TITLES = {
    "general": "General", "autonomy": "Autonomy", "ai": "AI & model parameters", "news": "News",
    "interests": "Interests", "notifications": "Notifications", "privacy": "Privacy",
    "learning": "Learning", "automations": "Automations", "briefing": "Briefing",
    "health": "System health", "sources": "Sources", "power": "Power & Background",
    "intelligence": "Intelligence & routing", "workspace": "Tasks & memory",
    "operator": "Actions & permissions", "shell": "Desktop", "connect": "Connections",
}
SECTION_ORDER = ["ai", "intelligence", "workspace", "general", "autonomy", "power",
                 "privacy", "notifications", "briefing", "news", "interests", "learning",
                 "automations", "health", "sources"]

# Written by ARIES to remember what it must put back; shown in the status panel as
# "will restore to" rather than as an editable control, because editing it would
# lose the value the machine has to be returned to.
HIDDEN = {"power.restore_idle_delay"}


def changed_from_default(setting):
    # The list endpoint supplies value/default but currently omits provenance.
    # Missing `source` must not turn every setting into an explicit override.
    if 'default' in setting and 'value' in setting:
        return setting['value'] != setting['default']
    return setting.get('source') not in (None, 'default')


def matching_settings(settings, query="", section="", changed_only=False):
    """Filter schema rows without losing new sections or advanced model controls."""
    terms = query.casefold().split()
    return [s for s in settings if s['key'] not in HIDDEN
            and (not section or s.get('section') == section)
            and (not changed_only or changed_from_default(s))
            and all(term in ' '.join(str(s.get(field) or '') for field in
                    ('key', 'title', 'description', 'section')).casefold() for term in terms)]


def control_for(page, setting: dict) -> Gtk.Widget:
    """Build the right control from the setting's own declaration."""
    key = setting["key"]
    value = setting.get("value")
    title = setting.get("title") or key
    description = setting.get("description") or ""

    def write(new_value):
        page.act(lambda c: c.put(f"/api/aries/settings/{key}", {"value": new_value}),
                 done=f"{title} updated")

    control = setting.get("control")

    if control == "toggle" or setting["type"] == "bool":
        return widgets.switch_row(title, description, bool(value), write)

    if control == "select" and setting.get("choices"):
        choices = [str(c) for c in setting["choices"]]
        row = Adw.ComboRow(title=title, subtitle=description or None)
        row.set_model(Gtk.StringList.new(choices))
        if str(value) in choices:
            row.set_selected(choices.index(str(value)))
        guard = {"quiet": True}

        def _changed(widget, _param):
            if guard["quiet"]:
                return
            write(choices[widget.get_selected()])

        row.connect("notify::selected", _changed)
        guard["quiet"] = False
        return row

    if control in ("slider", "number") and setting["type"] in ("int", "float"):
        low = setting.get("minimum")
        high = setting.get("maximum")
        step = 1 if setting["type"] == "int" else 0.05
        row = Adw.SpinRow.new_with_range(
            float(low if low is not None else 0),
            float(high if high is not None else 10_000), step)
        row.set_title(title)
        row.set_subtitle((description + (f"  ({setting['unit']})" if setting.get("unit") else "")))
        row.set_digits(0 if setting["type"] == "int" else 2)
        row.set_value(float(value if value is not None else 0))
        guard = {"quiet": True}

        def _spin(widget, _param):
            if guard["quiet"]:
                return
            raw = widget.get_value()
            write(int(raw) if setting["type"] == "int" else round(raw, 3))

        row.connect("notify::value", _spin)
        guard["quiet"] = False
        return row

    if setting["type"] == "list":
        current = ", ".join(str(v) for v in (value or []))
        row = Adw.EntryRow(title=title)
        row.set_text(current)
        row.set_show_apply_button(True)
        row.connect("apply", lambda w: write(
            [s.strip() for s in w.get_text().split(",") if s.strip()]))
        return row

    row = Adw.EntryRow(title=title)
    row.set_text("" if value is None else str(value))
    row.set_show_apply_button(True)
    row.connect("apply", lambda w: write(w.get_text()))
    return row


def annotate(row: Gtk.Widget, setting: dict) -> Gtk.Widget:
    """Attach provenance, and any stronger layer that is overriding this."""
    source = setting.get("source", "default")
    if source in ("user", "restriction", "security", "instruction", "project"):
        kind = design.EXPLICIT
    elif source in ("learned", "historical"):
        kind = design.LEARNED
    else:
        kind = design.DEFAULT
    if kind != design.DEFAULT and hasattr(row, "add_suffix"):
        row.add_suffix(widgets.provenance_tag(kind))
    if setting.get("user_only"):
        row.add_css_class("aries-explicit")
    return row


def settings_group(page, title: str, settings: list[dict],
                   description: str = "", *, expand_advanced=False) -> Gtk.Widget:
    """One section: plain settings first, advanced behind a disclosure."""
    settings = [s for s in settings if s["key"] not in HIDDEN]
    plain = [s for s in settings if not s.get("advanced")]
    advanced = [s for s in settings if s.get("advanced")]

    group = widgets.section(title, description)
    for s in plain:
        group.add(annotate(control_for(page, s), s))
    if advanced:
        exp = Adw.ExpanderRow(title="Advanced",
                              subtitle=f"{len(advanced)} setting(s) most people never change")
        built = False

        def populate(*_):
            nonlocal built
            if built or not exp.get_expanded():
                return
            built = True
            for s in advanced:
                exp.add_row(annotate(control_for(page, s), s))

        exp.connect('notify::expanded', populate)
        exp.set_expanded(expand_advanced)
        group.add(exp)
    return group


def power_status(power: dict) -> Gtk.Widget:
    """The five runtime lines — measured now, not remembered.

    Every line here is read from the machine at request time: the inhibitor from
    `systemd-inhibit --list` (what logind would actually act on, not what ARIES
    believes it took), the display from the session, the timeout from gsettings.
    A settings screen that reported its own intentions back would be worse than
    useless for a feature whose whole job is to still be true an hour later.
    """
    group = widgets.section(
        "Power & Background",
        "What the machine is doing right now. Read from logind and the session, "
        "not from the settings below.")

    if power.get("unavailable"):
        group.add(widgets.row("Status unavailable", power["unavailable"]))
        return group

    inhibitor = power.get("inhibitor") or {}
    display = power.get("display") or {}
    system = power.get("system") or {}

    on = bool(power.get("background_mode"))
    group.add(_status_row("Background Mode", "on" if on else "off",
                          "ok" if on else "info",
                          "held back from suspending" if on else "normal power behaviour"))

    active = bool(inhibitor.get("active"))
    if not inhibitor.get("available", True):
        state_text, sev = "unavailable", "warning"
        detail = inhibitor.get("unavailable_reason") or ""
    else:
        state_text = "active" if active else "inactive"
        sev = "ok" if active else "info"
        detail = f"{inhibitor.get('what', 'sleep')}/{inhibitor.get('mode', 'block')}"
        if active and inhibitor.get("held_by_aries"):
            detail += f" · pid {inhibitor['held_by_aries'][0].get('pid', '?')}"
        elif on and not active:
            detail += " · Background Mode is on but nothing is held"
            sev = "warning"
    group.add(_status_row("Suspend inhibitor", state_text, sev, detail))

    shown = {"on": "on", "off": "off"}.get(display.get("state", ""), "unknown")
    group.add(_status_row("Display", shown,
                          "info" if shown != "unknown" else "notice",
                          display.get("detail", "")))

    after = display.get("off_after_seconds")
    if after == 0:
        after_text = "never"
    elif after is None:
        after_text = "unknown"
    else:
        after_text = f"{after // 60} min" if after >= 60 else f"{after} s"
    restore = display.get("will_restore_to")
    group.add(widgets.row("Display off after", after_text + (
        f" · will restore to {restore}s when Background Mode is switched off"
        if restore is not None else "")))

    session = system.get("session") or {}
    if session.get("available"):
        where = f"session {session.get('id', '?')} · {session.get('state', 'unknown')}"
        if session.get("type"):
            where += f" · {session['type']}"
    else:
        where = "no logind session is visible"
    group.add(_status_row("System", "awake", "ok", where))

    # Reaching this screen at all is the proof: the numbers above were answered
    # by the running service, not assembled by the UI.
    group.add(_status_row("ARIES", "running", "ok",
                          "these readings were answered by the service just now"))

    group.add(widgets.row("What this means", power.get("effect", "")))

    others = inhibitor.get("other_sleep_blockers") or []
    if others:
        exp = Adw.ExpanderRow(
            title="Other programs blocking sleep",
            subtitle=f"{len(others)} — the machine would not suspend even with "
                     f"Background Mode off")
        for line in others:
            exp.add_row(widgets.row(line))
        group.add(exp)

    if power.get("allow_gpu_jobs"):
        group.add(widgets.row("Heavy GPU jobs", power.get("gpu_jobs_note", "")))
    return group


def resource_status(res: dict) -> Gtk.Widget:
    """What the machine may do right now, and why.

    Background Mode's second half. The first panel says the machine will stay
    awake; this one says what it is allowed to do while it is — because those
    are different promises and a user who only saw the first would reasonably
    assume ARIES would start anything at any temperature.

    Every class is listed, including the ones nothing declares yet. A gate you
    cannot see is a gate you cannot trust, and "no automation is heavy today" is
    information rather than a reason to hide the rule.
    """
    group = widgets.section(
        "Resource policy",
        "What ARIES may run while the display is off — measured now, from the "
        "processor, the GPU and the thermal sensors.")

    if not res:
        group.add(widgets.row("Unavailable",
                              "ARIES did not report the resource policy"))
        return group

    m = res.get("measurement") or {}
    lim = res.get("limits") or {}

    def reading(title, value, unit, unavailable, limit, subject=None):
        if value is None:
            # Never a zero standing in for a sensor that could not be read.
            row = widgets.row(title, unavailable or "could not be measured")
            row.add_prefix(widgets.dot("notice"))
            row.add_suffix(_value_label("unknown"))
            return row
        over = limit is not None and value >= limit
        detail = f"limit {limit}{unit}" if limit is not None else ""
        if subject:
            detail += f" · {subject}"
        row = widgets.row(title, detail)
        row.add_prefix(widgets.dot("warning" if over else "ok"))
        row.add_suffix(_value_label(f"{value:g}{unit}"))
        return row

    group.add(reading("CPU", m.get("cpu_pct"), " %", m.get("cpu_unavailable"),
                      lim.get("cpu_pct")))
    group.add(reading("GPU", m.get("gpu_pct"), " %", m.get("gpu_unavailable"),
                      lim.get("gpu_pct"), m.get("gpu_subject")))
    group.add(reading("Temperature", m.get("temperature_celsius"), " °C",
                      m.get("temperature_unavailable"), lim.get("temperature_celsius"),
                      m.get("temperature_subject")))

    for cls in res.get("classes") or []:
        severity = {"allowed": "ok", "blocked": "notice",
                    "deferred": "warning", "held": "warning"}.get(cls["status"], "info")
        row = widgets.row(cls["title"], cls["why"])
        row.add_prefix(widgets.dot(severity))
        row.add_suffix(_value_label(cls["status"]))
        group.add(row)

    for job in res.get("running_heavy") or []:
        minutes = job["elapsed_seconds"] / 60
        row = widgets.row(f"Running: {job['automation_id']}",
                          f"{minutes:.0f} min of a {lim.get('heavy_job_max_minutes')} min budget"
                          + (" · asked to stop at its next checkpoint"
                             if job.get("stop_requested") else ""))
        row.add_prefix(widgets.dot("warning" if job.get("stop_requested") else "info"))
        group.add(row)

    events = res.get("events") or []
    if events:
        exp = Adw.ExpanderRow(title="Recent decisions",
                              subtitle=f"{len(events)} recorded — also in the audit log")
        for e in events:
            when = (e.get("at") or "")[:16].replace("T", " ")
            exp.add_row(widgets.row(f"{e['kind']} · {e['workload']}",
                                    f"{when} — {e['reason']}"))
        group.add(exp)
    return group


def _value_label(text: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    lbl.add_css_class("aries-numeric")
    lbl.set_valign(Gtk.Align.CENTER)
    return lbl


def _status_row(title: str, value: str, severity: str, detail: str = "") -> Adw.ActionRow:
    r = widgets.row(title, detail)
    r.add_prefix(widgets.dot(severity))
    r.add_suffix(_value_label(value))
    return r


class SettingsPage(Page):
    title = "Settings"
    icon = "preferences-system-symbolic"
    subtitle = "Configure ARIES without editing a file"

    def fetch(self, client):
        return client.get("/api/aries/settings")

    def reload(self, *, quiet=False):
        self._power_key = f'settings-power:{id(self)}'
        self._power_generation = self.client.bump(self._power_key)
        self._power_requested_generation = None
        self._power_data = None
        super().reload(quiet=quiet)

    def _paint_power(self):
        slot = getattr(self, '_power_slot', None)
        if slot is None:
            return
        while slot.get_first_child() is not None:
            slot.remove(slot.get_first_child())
        power = getattr(self, '_power_data', None)
        if power is None:
            slot.append(Gtk.Label(label='Reading power status…', xalign=0))
        else:
            slot.append(power_status(power))
            if not power.get('unavailable'):
                slot.append(resource_status(power.get('resources') or {}))

    def _load_power(self):
        generation = getattr(self, '_power_generation', None)
        if generation is None or self._power_requested_generation == generation:
            return
        self._power_requested_generation = generation

        def received(power):
            self._power_data = power
            self._paint_power()

        # Optional hardware probes must neither hold the form's loading state
        # nor replace an editor containing unsaved text when they arrive.
        self.client.call(lambda client: replace(client, timeout=min(client.timeout, 3)).get('/api/aries/power'),
                         on_ok=received, on_error=lambda exc: received({'unavailable': str(exc)}),
                         key=self._power_key, generation=generation)

    def render(self, data):
        settings = data.get("settings") or []
        box = widgets.page_box()
        title = Gtk.Label(label="Your ARIES, your controls", xalign=0)
        title.add_css_class("title-1")
        box.append(title)
        description = Gtk.Label(label="Models, memory, permissions and the way your desktop works.",
                                xalign=0, wrap=True)
        description.add_css_class("aries-quiet")
        box.append(description)
        box.append(self._legend(settings))

        search = Gtk.SearchEntry(placeholder_text="Search settings, temperature, memory…")
        search.add_css_class('aries-settings-search')
        search.set_hexpand(True)
        search.set_text(getattr(self, '_settings_query', ''))
        self._settings_search = search
        box.append(search)

        available = {s['section'] for s in settings if s['key'] not in HIDDEN}
        ordered = [s for s in SECTION_ORDER if s in available]
        ordered += sorted(available - set(ordered))
        sections = [''] + ordered
        labels = ['All sections'] + [SECTION_TITLES.get(s, s.replace('_', ' ').title()) for s in ordered]
        selector = Gtk.DropDown.new_from_strings(labels)
        selector.add_css_class('aries-settings-section')
        selector.set_hexpand(True)
        selector.set_tooltip_text("Choose a settings section")
        default_section = 'general' if 'general' in available else (ordered[0] if ordered else '')
        selected = getattr(self, '_settings_section', default_section)
        selector.set_selected(sections.index(selected) if selected in sections else 0)
        self._settings_selector = selector
        changed = Gtk.CheckButton(label="Changed only")
        changed.set_active(getattr(self, '_settings_changed', False))
        self._settings_changed_button = changed
        filters = Gtk.Box(spacing=design.MD)
        filters.append(selector)
        filters.append(changed)
        box.append(filters)
        count = Gtk.Label(xalign=0)
        count.add_css_class("aries-quiet")
        box.append(count)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=design.LG)
        box.append(content)

        def refresh(*_):
            self._power_slot = None
            self._settings_query = search.get_text()
            self._settings_section = sections[selector.get_selected()]
            self._settings_changed = changed.get_active()
            visible = matching_settings(settings, self._settings_query,
                                        self._settings_section, self._settings_changed)
            self._visible_settings = visible
            child = content.get_first_child()
            while child is not None:
                following = child.get_next_sibling()
                content.remove(child)
                child = following
            count.set_label(f"{len(visible)} controls · {len({s['section'] for s in visible})} sections")
            if not visible:
                content.append(widgets.empty("No matching settings",
                    "Try another search or choose All sections.", icon="system-search-symbolic"))
                return
            for name in ordered:
                rows = [s for s in visible if s['section'] == name]
                if not rows:
                    continue
                if name == 'power' and not self._settings_query and not self._settings_changed:
                    self._power_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=design.LG)
                    content.append(self._power_slot)
                    if data.get('power') is not None:
                        self._power_data = data['power']
                    self._paint_power()
                    self._load_power()
                content.append(settings_group(self, SECTION_TITLES.get(name, name.title()), rows,
                    expand_advanced=bool(self._settings_query)))

        def searched(*_):
            # A fresh search is global; the user can then narrow it explicitly.
            if search.get_text() and search.get_text() != getattr(self, '_settings_query', ''):
                selector.set_selected(0)
            refresh()

        search.connect('search-changed', searched)
        selector.connect('notify::selected', refresh)
        changed.connect('toggled', refresh)
        refresh()
        return widgets.scrolled(box)

    def _legend(self, settings) -> Gtk.Widget:
        changed = [s for s in settings if changed_from_default(s)]
        learned = [s for s in changed if s.get("source") == "learned"]
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=design.MD)
        label = Gtk.Label(
            label=f"{len(changed)} of {len(settings)} settings changed from their defaults"
                  + (f" · {len(learned)} inferred by ARIES" if learned else ""),
            xalign=0)
        label.add_css_class("aries-quiet")
        box.append(label)
        return box
