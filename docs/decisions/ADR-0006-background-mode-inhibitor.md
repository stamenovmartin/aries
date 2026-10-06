# ADR-0006 — Background Mode holds a logind `sleep`/`block` inhibitor, not a simulated user

**Status:** accepted · **Date:** 2026-09-12 · **Journal:** Entry 013

## Context

ARIES is meant to keep working while the machine sits with its screen dark. Left alone, GNOME
eventually suspends the machine, and everything ARIES does stops until someone touches a key:
the scheduler, the News Radar, the Morning Brief, the learning loop.

The requirement named the mechanism as well as the goal: *use the proper systemd/logind inhibitor
mechanism; do not simulate activity with mouse/keyboard events.* It also constrained the blast
radius: *the implementation must not permanently change global GNOME power settings if a scoped
inhibitor is sufficient.*

## The options

**Simulated input** — `xdotool`, `ydotool`, or moving the pointer a pixel every few minutes. It is
what most "keep awake" scripts do, and it is wrong in several ways at once: it defeats the screen
lock, it defeats the screensaver, it makes the session permanently non-idle so *nothing* that
depends on idleness works again, it needs input-injection permission that Wayland does not grant
casually, and it lies to every other program on the machine about whether a human is present.
Rejected before it was tried, and the brief rejected it too.

**Changing the GNOME suspend settings** — set `sleep-inactive-ac-type` to `nothing` while ARIES
runs. It works, but it is a global, persistent change to the user's desktop configuration made by a
background program, and if ARIES dies it stays changed. The machine would silently never suspend
again, and nothing on screen would explain why.

**A logind inhibitor** — ask `systemd-logind` for a lock and let it arbitrate, which is the
mechanism the platform provides for exactly this. Chosen.

## Decision

ARIES takes exactly one inhibitor, `what=sleep`, `mode=block`, `who=ARIES`, for as long as
Background Mode is on.

**`sleep`, not `idle`.** This is the choice the whole feature turns on. An `idle` inhibitor tells
the session a user is present — it stops the screen blanking and stops the lock, which is the
opposite of the use case. `sleep` holds back suspend and hibernate only, so the display powers down
exactly as before. ARIES asserts on screen that it holds no `idle` lock, so a future regression
would be visible rather than mysterious.

**`block`, not `delay`.** `delay` buys a few seconds and then the suspend proceeds; it exists for
programs that need to flush state first. `block` makes a non-interactive suspend request fail,
which is what the requirement asks for. An interactive `systemctl suspend` still works — the user
is never locked out of their own machine.

**Held as an open file descriptor, not as a record.** logind's lock lives exactly as long as the fd
returned by `Inhibit()` stays open. ARIES holds it by running `systemd-inhibit … /bin/sh -c
'read -r _ <&0'` with a pipe on stdin: closing the pipe releases the lock, and so does the process
dying by any means, because the kernel closes the fds of dead processes. This is the property that
made the option acceptable — **a lock ARIES holds cannot outlive ARIES**, in a crash, an OOM kill,
a `SIGKILL`, or a power cut. Nothing needs a cleanup path, because there is nothing to clean up.

**One exception, borrowed and returned.** "Display off after" has no scoped equivalent — it is the
global `org.gnome.desktop.session idle-delay`. ARIES records the existing value in
`power.restore_idle_delay` *before* writing, and writes it back exactly when Background Mode is
switched off. The record lives in the database rather than in memory, so a crash does not lose it.
This is the only GNOME setting ARIES touches, and setting "Display off after" to the value the
desktop already has means nothing is written at all.

**`user_only`.** Background Mode, "allow normal suspend" and "allow heavy GPU jobs" may never be
inferred by the learning loop (§30). Keeping a machine awake spends the user's electricity and
their battery; it is not a preference to be guessed from behaviour.

## Consequences

* A machine in Background Mode does not suspend, and therefore uses power continuously. Stated
  plainly in `POWER.md` rather than buried.
* If ARIES is restarted, the lock is briefly absent (`RestartSec=5`) and is retaken by startup
  reconcile. A suspend inside that window is possible and is the correct trade against a lock
  nobody could find.
* The status panel reads `systemd-inhibit --list` rather than ARIES's own memory, so the screen
  cannot claim a lock that is no longer held.
* On a machine already configured never to suspend — including the one this was built on — the
  inhibitor changes nothing observable. ARIES says so instead of taking the credit.

## Not decided here

Linger stays **off**. Background Mode keeps the machine awake while the user is logged in; it is
not a way to run ARIES headless, and the requirement was explicit that linger was not to be enabled
yet.
