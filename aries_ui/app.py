"""The ARIES Control Centre application.

Compact section icons beside ARIES; content and task tabs use the full window.

Everything the window shows comes from the ARIES API. The application holds one
`Client` and no state of its own beyond which page is visible; a page that needs
something asks for it.
"""
from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from aries_ui import design  # noqa: E402
from aries_ui.client import Client  # noqa: E402

APP_ID = "mk.aries.ControlCentre"


def navigation(app, selected="home"):
    """Compact labelled icon buttons, shared by the centre and response windows."""
    from aries_ui.pages import SECTIONS
    box = Gtk.Box(spacing=2)
    brand = Gtk.Label(label="ARIES")
    brand.add_css_class("heading")
    brand.set_margin_end(10)
    box.append(brand)
    for key, cls in SECTIONS:
        button = Gtk.Button(icon_name=cls.icon)
        button.add_css_class("flat")
        button.set_tooltip_text(cls.title)
        button.update_property([Gtk.AccessibleProperty.LABEL], [cls.title])
        if key == selected:
            button.add_css_class("suggested-action")
        button.connect("clicked", lambda _, k=key: app.go(k))
        box.append(button)
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
    scroll.set_propagate_natural_width(True)
    scroll.set_max_content_width(580)
    scroll.set_min_content_width(120)
    scroll.set_hexpand(True)
    scroll.set_child(box)
    return scroll


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="ARIES", default_width=1320, default_height=860, resizable=True)
        self.app = app
        self.pages: dict[str, object] = {}

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)

        self._build_content()
        self.select("home")
        self._tab_timer = 0
        self.connect("map", self._watch_tabs)
        self.connect("unmap", self._stop_tabs)

    def _watch_tabs(self, *_):
        if not self._tab_timer:
            self._tab_timer = GLib.timeout_add_seconds(5, self._poll_tabs)

    def _stop_tabs(self, *_):
        if self._tab_timer:
            GLib.source_remove(self._tab_timer)
            self._tab_timer = 0

    def _poll_tabs(self):
        if any(key.startswith('goal:') for key in self._tabs):
            def update(data):
                for goal in data['goals']:
                    tab = self._tabs.get('goal:' + goal['id'])
                    if tab:
                        tab.set_title(goal['request'][:48])
                        tab.set_loading(goal['state'] in {'queued','running'})
                        tab.set_tooltip(goal['request'] + ' · ' + goal['state'])
                        tab.set_needs_attention(goal['state'] in {'proposed','partial','failed','interrupted'})
            self.app.client.call(lambda c:c.get('/api/aries/workspace'), on_ok=update, on_error=lambda _:None)
        return GLib.SOURCE_CONTINUE

    def _build_content(self):
        self.content_header = Adw.HeaderBar()
        self.content_title = Adw.WindowTitle(title="", subtitle="")
        self.content_header.set_title_widget(navigation(self.app))
        self.content_header.set_decoration_layout(":minimize,maximize,close")
        search = Gtk.Button(icon_name="system-search-symbolic", tooltip_text="Ask ARIES · Ctrl+Space")
        search.connect("clicked", lambda *_: self.app.open_command_palette())
        self.content_header.pack_end(search)

        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        self.refresh_btn.add_css_class("flat")
        self.refresh_btn.set_tooltip_text("Refresh   Ctrl+R")
        self.refresh_btn.connect("clicked", lambda *_: self.reload_current())
        self.content_header.pack_end(self.refresh_btn)

        # Packed at the END, beside Refresh. Packed at the start it sat to the
        # left of the window title and read as a heading rather than an action.
        self.suffix_slot = Gtk.Box(spacing=design.SM)
        self.content_header.pack_end(self.suffix_slot)

        self.stack = Adw.TabView()
        self.stack.set_vexpand(True)
        self._tabs = {}
        self._syncing = False
        tabbar = Adw.TabBar(view=self.stack, autohide=False)
        self.stack.connect('notify::selected-page', self._tab_changed)
        self.stack.connect('page-detached', self._tab_closed)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(self.content_header)
        tabs_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tabs_content.append(tabbar)
        tabs_content.append(self.stack)
        toolbar.set_content(tabs_content)
        self.toasts.set_child(toolbar)

    # ── navigation ──────────────────────────────────────────────────────────
    def _on_select(self, _list, row):
        if row is not None:
            self.select(row.section_key, from_click=True)

    def select(self, key: str, *, from_click: bool = False) -> None:
        from aries_ui.pages import SECTIONS
        if self._syncing:
            return
        lookup = dict(SECTIONS)
        if key not in lookup:
            return
        if key not in self.pages:
            self._append_tab(key, key, lookup[key](self.app))
        self.stack.set_selected_page(self._tabs[key])
        self._tab_changed()

    def _append_tab(self, key, section, page, title=None):
        page._tab_key = key
        page._section_key = section
        self.pages[key] = page
        tab = self.stack.append(page)
        tab.set_title(title or page.title)
        tab.set_icon(Gio.ThemedIcon.new(page.icon))
        self._tabs[key] = tab
        self.stack.set_selected_page(tab)

    def open_goal(self, goal_id):
        from aries_ui.pages.dashboard import DashboardPage
        key = 'goal:' + goal_id
        if key not in self.pages:
            self._append_tab(key, 'dashboard', DashboardPage(self.app, goal_id=goal_id), 'Task ' + goal_id[:6])
        self.stack.set_selected_page(self._tabs[key])
        self._tab_changed()

    def _tab_changed(self, *_):
        tab = self.stack.get_selected_page()
        if tab is None or self._syncing:
            return
        page = tab.get_child()
        key = page._section_key
        self._syncing = True
        self.content_title.set_title(page.title)
        self.content_title.set_subtitle(page.subtitle)
        self._syncing = False
        child = self.suffix_slot.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.suffix_slot.remove(child)
            child = nxt
        suffix = page.header_suffix()
        if suffix:
            self.suffix_slot.append(suffix)
        if not page._loaded_once:
            page.reload()
        self.app.note_section(key)
        self.app.note_goal(getattr(page, '_selected', None) or '')

    def _tab_closed(self, _view, tab, _position):
        key = tab.get_child()._tab_key
        self._tabs.pop(key, None)
        self.pages.pop(key, None)
        if not self.pages:
            GLib.idle_add(lambda: (self.select('home'), False)[1])

    def reload_current(self):
        tab = self.stack.get_selected_page()
        if tab:
            tab.get_child().reload()

    def toast(self, message: str):
        self.toasts.add_toast(Adw.Toast(title=message, timeout=4))


class ResponseWindow(Adw.ApplicationWindow):
    """One movable desktop surface for one response, without the control sidebar."""
    def __init__(self, app, section, page, goal_id=None, temporary=False):
        super().__init__(application=app, title='ARIES · '+page.title, default_width=940, default_height=820, resizable=True)
        self.app, self.page, self.section, self.goal_id = app, page, section, goal_id
        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.heading = Adw.WindowTitle(title='ARIES', subtitle=page.title)
        header.set_title_widget(navigation(app, section))
        header.set_decoration_layout(":minimize,maximize,close")
        refresh = Gtk.Button(icon_name='view-refresh-symbolic')
        refresh.set_tooltip_text('Refresh this response')
        refresh.connect('clicked', lambda *_:page.reload(quiet=True))
        header.pack_end(refresh)
        command = Gtk.Button(icon_name='system-search-symbolic')
        command.set_tooltip_text('Ask ARIES')
        command.connect('clicked', lambda *_:app.open_command_palette())
        header.pack_end(command)
        suffix = page.header_suffix()
        if suffix: header.pack_end(suffix)
        toolbar.add_top_bar(header)
        toolbar.set_content(page)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)
        self.connect('notify::is-active', self._focused)
        from aries_ui.window_lifecycle import CompletionClose
        self.lifecycle = CompletionClose(temporary=temporary)
        self._close_timer = 0
        self.keep = Gtk.ToggleButton(icon_name='view-pin-symbolic', tooltip_text='Keep this result open')
        self.keep.set_active(not temporary)
        self.keep.connect('toggled', lambda b: self.lifecycle.pin(b.get_active()))
        if goal_id:
            header.pack_end(self.keep)
            self._close_timer = GLib.timeout_add_seconds(1, self._check_completion)
        self.connect('close-request', self._closing)
        page.reload()

    def _check_completion(self):
        if self.lifecycle.update(getattr(self.page, 'goal_state', None)):
            self.close()
            return GLib.SOURCE_REMOVE
        if self.lifecycle.deadline is not None:
            self.keep.set_tooltip_text('Result saved in Monitor · closes shortly unless pinned')
        return GLib.SOURCE_CONTINUE

    def _closing(self, *_):
        if self._close_timer:
            GLib.source_remove(self._close_timer)
            self._close_timer = 0
        return False

    def _focused(self, *_):
        if self.is_active():
            self.app.note_section(self.section)
            self.app.note_goal(self.goal_id or '')

    def reload_current(self):
        self.page.reload(quiet=True)

    def toast(self, message):
        self.toasts.add_toast(Adw.Toast(title=message, timeout=4))


class ControlCentre(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.client = Client(base=os.environ.get("ARIES_API", "http://127.0.0.1:8000"),
                             api_key=os.environ.get("ARIES_API_KEY", ""))
        self.window: Window | None = None
        self.responses = {}
        self.add_main_option("api", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "ARIES API base URL", "URL")
        # The shell opens the Control Centre *on a screen*: a notification about
        # news should land on News, not on Home with the user hunting. Without
        # this the shell would have to drive the UI some other way, and "some
        # other way" is how a second navigation model gets built.
        self.add_main_option("section", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Open on a section (home, brief, news, …)", "SECTION")

        self.add_main_option("goal", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Open a specific goal dashboard", "ID")

    def do_command_line(self, cmdline):
        """Both cases, one path: not running, and already running.

        The first version set `_pending_section` and called `activate()`, then
        tried to apply the section again afterwards in case the window had
        already existed. That is a race dressed as a fallback — which branch ran
        depended on whether `do_activate` had cleared the field yet, and the
        answer differed between a cold start and a second invocation. It landed
        on Settings often enough to be reported and not often enough to be
        obvious.

        Navigation is now a GAction. GTK already has exactly one mechanism for
        "make the running instance go somewhere", every caller uses it, and its
        state is readable from outside — which is what makes the destination
        testable rather than merely intended.
        """
        options = cmdline.get_options_dict().end().unpack()
        if "api" in options:
            self.client.base = options["api"]
        section = options.get("section") or ""
        if options.get("goal"):
            self.activate_action("goal", GLib.Variant("s", options["goal"]))
        elif section:
            self.activate_action("section", GLib.Variant("s", section))
        else:
            self.activate()
        return 0

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_data(design.CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        for name, accel, cb in (
            ("refresh", "<Control>r", lambda *_: self.get_active_window() and self.get_active_window().reload_current()),
            ("command", "<Control>space", lambda *_: self.open_command_palette()),
            ("fullscreen", "F11", lambda *_: self.toggle_fullscreen()),
            ("quit", "<Control>q", lambda *_: self.quit()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)
            self.set_accels_for_action(f"app.{name}", [accel])

        self._goal_action = Gio.SimpleAction.new_stateful("goal", GLib.VariantType.new("s"), GLib.Variant("s", ""))
        self._goal_action.connect("activate", self._on_goal)
        self.add_action(self._goal_action)

        # Navigation, as an action with STATE.
        #
        # Stateful for two reasons. It is how a caller in another process asks a
        # running Control Centre to go somewhere — `Gio.DBusActionGroup` on
        # mk.aries.ControlCentre — so the shell, a notification and the command
        # line all take one path. And the state is readable from outside, which
        # is the only way an end-to-end test can assert where the window
        # actually landed rather than where it was told to go.
        section = Gio.SimpleAction.new_stateful(
            "section", GLib.VariantType.new("s"), GLib.Variant("s", ""))
        section.connect("activate", self._on_section_action)
        self.add_action(section)
        self._section_action = section

    def _on_section_action(self, action, parameter):
        """The one place a section change happens, wherever it came from."""
        section = parameter.get_string() if parameter else ""
        if not section:
            return
        from aries_ui.pages import SECTIONS
        if section not in dict(SECTIONS):
            # An unknown destination is reported, not silently swallowed into
            # whatever page happened to be showing.
            self.toast(f"ARIES has no '{section}' screen")
            return
        self.go(section)
        action.set_state(GLib.Variant("s", section))

    def _on_goal(self, action, parameter):
        import re
        goal_id = parameter.get_string()
        if not re.fullmatch(r"[0-9a-f]{32}", goal_id):
            return
        self.open_goal(goal_id, temporary=True)

    def note_goal(self, goal_id):
        if hasattr(self, "_goal_action"):
            self._goal_action.set_state(GLib.Variant("s", goal_id))

    def note_section(self, section: str) -> None:
        """Record where the window is now, whoever moved it."""
        action = getattr(self, "_section_action", None)
        if action is not None:
            action.set_state(GLib.Variant("s", section))

    @property
    def section(self) -> str:
        """Where the window actually is — read by the end-to-end tests."""
        state = self._section_action.get_state() if hasattr(self, "_section_action") else None
        return state.get_string() if state else ""

    def do_activate(self):
        if self.window is None:
            self.window = Window(self)
        self.window.present()

    def toggle_fullscreen(self):
        window = self.get_active_window()
        if window:
            if window.is_fullscreen():
                window.unfullscreen()
            else:
                window.fullscreen()

    def open_command_palette(self):
        from aries_ui.command import CommandPalette
        parent = self.get_active_window() or self.window
        if parent:
            CommandPalette(self).present(parent)

    def toast(self, message: str):
        parent = self.get_active_window() or self.window
        if parent and hasattr(parent, 'toast'):
            parent.toast(message)

    def open_goal(self, goal_id, temporary=False):
        from aries_ui.pages.dashboard import DashboardPage
        key = 'goal:' + goal_id
        if key not in self.responses:
            self._response(key, 'dashboard', DashboardPage(self, goal_id=goal_id), goal_id, temporary=temporary)
        self.responses[key].present()
        self.note_section('dashboard')

    def _response(self, key, section, page, goal_id=None, temporary=False):
        window = ResponseWindow(self, section, page, goal_id, temporary=temporary)
        self.responses[key] = window
        def closed(*_):
            self.responses.pop(key, None)
            return False
        window.connect('close-request', closed)
        window.present()

    def go(self, section: str):
        from aries_ui.pages import SECTIONS
        cls = dict(SECTIONS).get(section)
        if cls is None:
            return
        key = 'screen:' + section
        if key not in self.responses:
            self._response(key, section, cls(self))
        else:
            self.responses[key].page.reload(quiet=True)
            self.responses[key].present()
        self.note_section(section)



def main(argv=None):
    return ControlCentre().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
