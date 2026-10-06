"""ARIES Shell — the desktop surface, and the core that serves it.

The shell itself is a GNOME Shell extension in JavaScript (`shell/aries@aries.local`),
because on a GNOME Wayland session that is the only way to reach the panel, the
dock layer and the overview: Mutter does not implement `wlr-layer-shell`, so a
GTK window cannot anchor itself to a screen edge, and replacing the compositor
was explicitly out of scope (ADR-0008).

This package is everything the shell is NOT allowed to decide for itself:

    intents.py   what a typed command means — one router, two front ends
    search.py    settings, automations and files, with privacy enforced
    status.py    one cheap call for the panel indicator, severity included
    settings.py  the shell's preferences, in ARIES's settings service
    tokens.py    the design language, generating both stylesheets
"""
from __future__ import annotations

from aries.shell import intents, search, status, tokens, watchdog  # noqa: F401  watchdog registers a worker
from aries.shell import settings as _settings  # noqa: F401  registers the settings

__all__ = ["intents", "search", "status", "tokens"]
