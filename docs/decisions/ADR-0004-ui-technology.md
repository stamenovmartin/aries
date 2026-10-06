# ADR-0004 — GTK4 + libadwaita, in a separate process, over the HTTP API

**Status:** accepted · **Date:** 2026-09-12 · **Journal:** Entry 011

## Context

ARIES needs its first graphical interface: a Control Centre through which a non-technical user
can understand, configure and control everything built in Entries 001–010. The requirement is
explicit that this is not a visual shell over a rewrite — the UI must consume the existing
services, must not become a second implementation of ARIES logic, and must never touch the
database directly.

Two facts about this machine decided most of it, and both were measured rather than assumed.

**The desktop is GNOME on Wayland**, and GTK4 4.22 with libadwaita 1.9 and PyGObject 3.56 are
**already installed**. A GTK4 window presents natively on `GdkWaylandDisplay` with no
configuration and nothing to install.

**Those bindings belong to the system interpreter.** ARIES runs in a `uv`-managed Python 3.12
virtual environment (ADR-0002); PyGObject lives on system Python 3.14. Importing `gi` from the
ARIES venv would mean building PyGObject from source, which needs `-dev` packages, a compiler
toolchain and `sudo` — and would then pin a second copy of the bindings to a Python version the
distribution does not ship them for.

## Options

**A. GTK4 + libadwaita via PyGObject.** Native on this desktop, already present, Wayland-native,
accessible through AT-SPI by default, and the toolkit the ARIES specification itself names for
the eventual shell (§3). Adwaita provides the interaction patterns — `NavigationSplitView`,
`PreferencesPage`, `StatusPage`, `Toast` — that the calm, progressively-disclosed UI the
requirement asks for is built from, without inventing a design language.

**B. Qt via PySide6.** `pip`-installable into the venv, so one interpreter and one process.
Excellent widgets and genuinely good Wayland support now. But it bundles ~150 MB of Qt, looks
foreign on GNOME (its own theming, not the system's), and points away from the specification's
stated GTK4/libadwaita direction. Choosing it to avoid a process boundary would be choosing the
easier build over the better fit.

**C. Electron, Tauri, or a local web UI.** Rejected on the requirement's own terms, and on the
merits: a browser engine to render a settings window on a machine ARIES is also monitoring is a
poor trade in memory, startup time and attack surface. Tauri is lighter but adds Rust and a
webview to a Python project for no benefit the native toolkit does not already give.

**D. A TUI (Textual).** Fast to build and genuinely nice, but the requirement asks for a desktop
application a non-technical user can operate, and a terminal is not that.

## Decision

**Option A — and the interpreter split is turned from an obstacle into the architecture.**

```
aries_ui  (system Python 3.14, GTK4 + libadwaita, stdlib only)
    │  HTTP, loopback
    ▼
ARIES API (venv Python 3.12, FastAPI)  →  permissions → audit → services → database
```

The Control Centre is a **separate process** that speaks to ARIES only over the HTTP API. It
does not import `aries`, and cannot: `aries` is not on its interpreter's path.

This is not a workaround. It is the requirement's own rule — *UI → typed service boundary →
ARIES core, never UI → database* — made **structural rather than disciplinary**. A future
contributor cannot accidentally reach into the database from the UI, because there is nothing
there to reach with. Every action the UI takes goes through the same authenticated, audited path
as the CLI, because it is the same path.

Consequences that follow, all of them acceptable:

* the UI needs ARIES running (`scripts/start.sh`); it says so plainly and offers the command
  when the API is unreachable, rather than showing an empty window;
* the UI uses **stdlib only** (`urllib.request`, `json`, `threading`) — nothing is installed
  into the system interpreter, which is PEP 668 externally-managed;
* concurrency is background threads marshalled back with `GLib.idle_add`, the standard GTK
  pattern, rather than an asyncio loop fighting the GTK main loop.

## Consequences

**Positive.** Native look and behaviour on the user's actual desktop; Wayland-native; keyboard
navigation and screen-reader support inherited from GTK rather than reimplemented; zero
installation; a hard architectural boundary; and the toolkit the long-term ARIES Shell will use,
so this is practice for it rather than a detour.

**Negative.** Two interpreters, which must be explained (this ADR, and `docs/UI.md`). The UI
cannot be unit-tested by importing ARIES objects — so its tests exercise the **HTTP contract**
instead, which is the thing that actually needs pinning. GTK's own rendering is not tested
headlessly; screenshots are produced by rendering widgets to a texture offscreen, which works
without any compositor permission (the GNOME Shell screenshot D-Bus API refuses unprivileged
callers).

**Revisit when** ARIES needs to run its UI on a machine without GNOME, or when the shell (§5)
subsumes the Control Centre. Neither changes the process boundary, which is the part worth
keeping.
