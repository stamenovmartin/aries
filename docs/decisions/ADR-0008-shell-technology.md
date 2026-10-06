# ADR-0008 — The ARIES Shell is a GNOME Shell extension, for now

**Status:** accepted · **Date:** 2026-09-13 · **Journal:** Entry 014

## Context

ARIES needs a desktop surface: a top bar, a dock, a command bar bound to a global
shortcut, an application grid, its own quick settings, and its notifications
among the user's. The constraints were explicit — do not replace GNOME, do not
build a compositor, do not touch the bootloader, the display manager or the
login session, and keep an easy fallback to a normal Ubuntu session.

## What was measured, not assumed

On this machine: GNOME Shell **50.1**, session type **wayland**, desktop
**ubuntu:GNOME**, GJS 1.88, `ubuntu-dock`, `ding` and `tiling-assistant` enabled.

The decisive fact: **Mutter does not implement `wlr-layer-shell`**. That protocol
is how a Wayland client anchors a window to a screen edge, reserves space and
sits above ordinary windows — everything a panel or dock must do. `gtk4-layer-shell`
is not installed, and installing it would not help, because the protocol is
absent from the compositor rather than from the client library.

## The options

**A GTK4 window.** What the Control Centre is, and what would have matched the
existing stack. On Wayland it cannot position itself, cannot anchor to an edge,
cannot reserve space and cannot stay above other windows. A "top bar" would be an
ordinary window the user could move and lose behind Firefox. Rejected on
capability, not taste.

**A wlroots compositor** (`wlr-layer-shell` works there). Explicitly out of scope,
and it would mean replacing the session the user logs into before anything had
been proven.

**An X11 session**, where `_NET_WM_STRUT` makes panels possible with plain GTK.
This would mean changing the session type the user logs into — excluded by the
brief, and a step backwards from Wayland for everything else.

**A GNOME Shell extension.** Runs inside `gnome-shell`, so it reaches the panel,
the stage, the overview, the keybinding system and the notification centre
directly. Chosen — it is the only option that satisfies the constraints.

## Decision

The shell is a GNOME Shell extension (`aries@aries.local`) in GJS, talking to the
ARIES runtime over HTTP and by no other route.

**No business logic.** The extension has no settings of its own, no copy of the
command router, no file index and no opinion about ARIES's health. Two tests
enforce this rather than trusting it: one scans every shell source for database
access, one for synchronous calls.

**One GSettings key, and only one.** Mutter accepts a global keybinding only from
a GSettings key, so a schema is unavoidable — but it holds the keybinding and
nothing else, and even its *value* is mirrored from ARIES's
`shell.command_shortcut`. There remains one place a person configures ARIES.

## The consequence that shaped the code

An extension runs in the process that draws the desktop, and on Wayland a shell
that throws during startup cannot be restarted without logging out. There is no
Alt+F2 `r`.

So: every entry point is wrapped in `guard()`, and a component that throws is left
out while the rest runs; there is no synchronous HTTP path anywhere in the
extension; the dock does not reserve struts, because a crash holding struts would
leave every window's work area wrong until logout, while an overlay a maximised
window sits under is merely inconvenient; and `disable()` unwinds in reverse,
tolerating parts that were never built.

Development never touches the live session. `./scripts/test-shell.sh` runs a
**headless GNOME Shell against a virtual monitor on its own D-Bus session** — a
complete isolated GNOME — enables the extension there, and reports whether it
loaded, errored or failed to tear down. Every bug in this milestone was found
that way before a person saw one.

## Consequences

* The shell is tied to GNOME's extension API, which changes between major
  versions. `metadata.json` declares 48–50; a new GNOME needs the extension
  re-verified, and the nested harness makes that a five-minute job rather than a
  gamble with the user's session.
* Some things must be borrowed rather than owned: the notification centre, the
  Wi-Fi credentials dialog, the overview. Where ARIES hands off it does so
  visibly — see `PRODUCT_IDENTITY.md`, which draws the line at the *surface*, not
  at the mechanism.
* The extension cannot be tested by the Python suite at all, so what crosses the
  boundary is declared as data and pinned from the side that can run tests — the
  same contract discipline ADR-0004 established for the Control Centre.

## When to revisit

An ARIES compositor becomes the right answer when ARIES needs window management,
input routing or a session of its own that GNOME will not give it — not before.
The next step toward that is a dedicated ARIES **session** (a `.desktop` session
entry that starts GNOME with the ARIES shell), which changes what the login
screen offers without changing what GNOME is. Ubuntu remains a selectable session
permanently; `PRODUCT_IDENTITY.md` makes that a standing constraint rather than a
transitional one.
