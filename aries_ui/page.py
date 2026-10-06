"""The contract every screen implements.

One base class so all eight screens handle the three states identically —
loading, loaded, failed — and so none of them has to think about threads. A page
declares what to fetch and how to render it; everything else is here.

The staleness guard matters more than it looks. Switching Home → News → Home
starts three requests that can land in any order, and a late reply from the
first would repaint the screen with older data. Each page bumps a generation
counter every time it reloads, and a reply from a superseded generation never
reaches a widget.
"""
from __future__ import annotations

from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402


class Page(Gtk.Box):
    """A screen: fetches on the main loop, renders on the main loop, never blocks it."""

    title = "Page"
    icon = "application-x-executable-symbolic"
    subtitle = ""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.client = app.client
        self._slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._slot.set_vexpand(True)
        self.append(self._slot)
        self._loaded_once = False

    # ── subclasses implement these two ──────────────────────────────────────
    def fetch(self, client) -> Any:
        """Runs on a WORKER THREAD. No widget may be touched here."""
        raise NotImplementedError

    def render(self, data: Any) -> Gtk.Widget:
        """Runs on the MAIN LOOP. Returns the widget to show."""
        raise NotImplementedError

    # ── the machinery ───────────────────────────────────────────────────────
    def reload(self, *, quiet: bool = False) -> None:
        key = f"page:{self.__class__.__name__}:{id(self)}"
        generation = self.client.bump(key)
        if not quiet or not self._loaded_once:
            self._show(widgets.Loading(f"Loading {self.title.lower()}…"))

        self.client.call(
            self.fetch,
            on_ok=self._on_ok,
            on_error=self._on_error,
            key=key, generation=generation)

    def _on_ok(self, data):
        self._loaded_once = True
        try:
            self._show(self.render(data))
        except Exception as exc:                          # noqa: BLE001
            # A rendering bug must not leave a blank window with no explanation.
            import traceback
            traceback.print_exc()
            self._show(widgets.error_state(exc, retry=self.reload))

    def _on_error(self, exc):
        self._show(widgets.error_state(exc, retry=self.reload))

    def _show(self, widget: Gtk.Widget) -> None:
        child = self._slot.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._slot.remove(child)
            child = nxt
        widget.set_vexpand(True)
        self._slot.append(widget)

    # ── helpers for subclasses ──────────────────────────────────────────────
    def act(self, work: Callable, *, done: str = "", then_reload: bool = True,
            on_ok: Callable[[Any], None] | None = None) -> None:
        """Perform a write. Confirms with a toast; reloads; never blocks.

        Writes are never optimistic. The UI shows what ARIES says happened, not
        what it hoped would happen — a setting refused by validation or by the
        permission model must not appear to have been applied.
        """
        def _ok(result):
            if on_ok:
                on_ok(result)
            if done:
                self.app.toast(done)
            if then_reload:
                self.reload(quiet=True)

        def _err(exc):
            from aries_ui.client import describe
            title, explanation, _ = describe(exc)
            self.app.toast(f"{title}: {explanation}"[:160])

        self.client.call(work, on_ok=_ok, on_error=_err)

    def header_suffix(self) -> Gtk.Widget | None:
        """Optional widget for the window header while this page is showing."""
        return None
