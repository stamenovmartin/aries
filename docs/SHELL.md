# ARIES Shell v0.1

**The desktop surface of ARIES.** Status in the top bar, a dock, ARIES Search on
`Super+Space`, an application grid, ARIES's own quick settings, and ARIES's
decisions arriving in the same place as every other notification.

```bash
./scripts/aries-shell install     # link it in and generate the stylesheet
./scripts/aries-shell identity    # application entry, icon, backgrounds
./scripts/aries-shell test        # run it in a HEADLESS nested GNOME Shell
./scripts/aries-shell enable      # switch it on in the live session
./scripts/aries-shell disable     # the fallback — works from a TTY
```

GNOME reads the extension list when the session starts, so after the first
`install` you must log out and back in before `enable` finds it.

---

## Architecture

```
   ARIES Shell  ── a GNOME Shell extension, inside gnome-shell
        │
        │   HTTP, asynchronous, 127.0.0.1:8000 — and nothing else
        ▼
   typed ARIES APIs      /api/aries/shell/{status,config,act} · /api/aries/command
        ▼
   ARIES runtime         aries-core.service
```

The shell holds no state ARIES could hold instead and decides nothing ARIES
could decide. It has no settings of its own, no second copy of the command
router, no private file index, and no opinion about whether ARIES is healthy. It
draws what the runtime says and sends back what the user did.

Two tests enforce that rather than trusting it: one scans every shell source for
database access, and one for synchronous calls.

## Component tree

```
extension.js                     lifecycle, wiring, and the action dispatcher
├── lib/log.js                   guard() — a broken component is left out, the session survives
├── lib/api.js                   async Soup 3; every reply is data, never an exception
├── lib/topbar.js                ARIES status · workspace pills · the menu
│    ├── AriesIndicator          severity dot, decisions badge, what ARIES is about to do
│    └── WorkspacePills          which workspace, as shape rather than a number
├── lib/quicksettings.js         ARIES Quick Settings — Wi-Fi, audio, Bluetooth,
│                                brightness, Background Mode, privacy, autonomy
├── lib/commandbar.js            ARIES Search (Super+Space)
├── lib/launcher.js              the application grid, search-first
├── lib/dock.js                  pinned + running apps, focus indicator
├── lib/notifications.js         ARIES decisions into the desktop's notification centre
├── lib/overview.js              ARIES as a search provider in the workspace overview
├── lib/wallpaper.js             the ARIES background, borrowed and returned
├── lib/dbus.js                  org.aries.Shell — Search(), Launcher(), Close(), Ping()
├── stylesheet.css               GENERATED from aries/shell/tokens.py
└── schemas/                     one key: the keybinding Mutter insists on
```

On the ARIES side, `aries/shell/`:

| file | what it owns |
|---|---|
| `intents.py` | what a typed phrase means — **one router, two front ends** |
| `search.py` | settings, automations and files, with `privacy.excluded_paths` enforced |
| `status.py` | the one cheap call the panel polls, severity already judged |
| `settings.py` | the shell's preferences, in ARIES's settings service |
| `tokens.py` | the design language, generating both stylesheets |

## Why an extension, and not a window

On a GNOME Wayland session, a top bar, a dock and overlays must anchor to screen
edges and sit above ordinary windows. That needs `wlr-layer-shell`, and **Mutter
does not implement it** — verified on this machine, GNOME Shell 50.1, with
`gtk4-layer-shell` not installed and no way for a GTK window to reserve an edge.
Writing a compositor was explicitly out of scope.

Inside `gnome-shell` is therefore the only place this can be built on the session
the user already has. [ADR-0008](decisions/ADR-0008-shell-technology.md) records
what was considered and what would have to change to revisit it.

## What ARIES owns, and what it borrows

Per [PRODUCT_IDENTITY.md](PRODUCT_IDENTITY.md): ARIES owns the **surface**; Linux
provides the **mechanism**. The user should not have to know which is which.

| surface | ARIES owns | implemented over |
|---|---|---|
| top bar | the ARIES status, the workspace pills, the menu | GNOME's panel |
| ARIES Search | the whole thing | `Shell.AppSystem` for apps; ARIES for everything else |
| quick settings | the panel, its language, its ordering | NetworkManager, Gvc, gsd-power, gsd-rfkill |
| notifications | the identity, grouping and priority | the desktop's notification centre |
| dock | the whole thing | `Shell.AppSystem` |
| overview search | the ARIES results in it | GNOME's overview and its provider API |
| background | the artwork and the choice | `org.gnome.desktop.background` |
| power | the whole thing | logind (Entry 013) |

Two places hand off visibly rather than pretending:

* **Joining a Wi-Fi network** opens the system picker. WPA-Enterprise, captive
  portals and secret agents are a large surface, and ARIES failing at them would
  be worse than ARIES not claiming them.
* **Another dock.** If `ubuntu-dock` or `dash-to-dock` is enabled, the ARIES dock
  is not drawn and says so in the log. Two docks is not a coherent environment.

## ARIES Search

`Super+Space`. One surface for what used to be three programs — an application
launcher, a file search and a command prompt.

```
typing ──┬─→ applications        local, drawn on the keystroke
         └─→ POST /api/aries/command   debounced 90 ms, merged when it lands
                  ├── commands      "scan for news" → run the News Radar
                  ├── automations   found by name, offered as something to RUN
                  ├── settings      found by title, key or description
                  └── files         name search, privacy-enforced, bounded
```

**Typing never waits for the network.** Applications are computed locally and
drawn immediately; the ARIES request is debounced and merges in. With ARIES
stopped the bar still launches applications and says the rest is unavailable.

**One router, two front ends.** The patterns that recognise "scan for news" exist
once, in `aries/shell/intents.py`, behind `POST /api/aries/command`. The Control
Centre's palette calls the same endpoint. They cannot drift because there is
nothing to drift from.

**Results are actions, not closures.** `{"kind": "navigate", "section": "news"}`
means "open News": the Control Centre switches page, the shell launches it on
that page. The core decides what the user meant; each surface knows how to carry
it out in its own medium.

**Applications and windows are the shell's contribution**, because they are the
only things the shell knows that ARIES does not. Files are *not* — 
`privacy.excluded_paths` is ARIES policy, and a shell that walked the filesystem
itself would be a second implementation of a privacy rule.

## The workspace overview

GNOME's overview is already a mission-control view — live thumbnails, a workspace
strip, drag-between-workspaces, touchpad gestures. Rebuilding it would produce
something worse and call it coherence.

What it was missing is ARIES. So ARIES registers as a **search provider** —
`Main.overview.searchController.addProvider()`, a public API in GNOME 50 — and
typing in the overview reaches everything ARIES knows:

![ARIES in the overview](screenshots/shell-overview.png)

Typing `brief` now surfaces an **ARIES** section with *Show the morning brief*,
*Run Morning Brief*, and the three settings that control briefing length and
reach — beside GNOME's own results, not instead of them.

It calls `POST /api/aries/command`, the same endpoint as ARIES Search and the
Control Centre's palette. **One router, three front ends.** A capability added to
`aries/shell/intents.py` appears in all three without any of them changing.

Applications and files are deliberately excluded from the provider's request:
GNOME already provides both, and asking for them again would show every result
twice. Cancellation is honoured — GNOME cancels a search on the next keystroke,
and a provider that keeps working afterwards is why overview search feels heavy.

The ARIES dock steps aside while the overview is open, because the overview
brings its own dash and two docks is not one environment.

## The background

`shell.wallpaper` defaults to **`system`**: switching the shell on does not
replace the wallpaper you chose. When you do pick an ARIES background, the same
discipline as Entry 013's display timeout applies — the previous value is
recorded in `shell.restore_wallpaper` **before** anything is written, in ARIES's
settings service rather than in the extension's memory, so a crash does not lose
it and choosing `system` again puts back exactly what was there.

`aries` sets both the light and dark keys so the background follows your own
light/dark preference; `aries-light` and `aries-dark` pin one.

Disabling the extension deliberately does **not** revert the background. A
teardown with an opinion about what your desktop should look like is worse than
one that leaves it alone.

## Keyboard

Every surface is reachable and operable without a pointer.

| key | does |
|---|---|
| `Super+Space` | ARIES Search |
| `↑` `↓` `Tab` | move through results |
| `Enter` | run the selected result |
| `Esc` | close |
| `←` `→` `↑` `↓` | move through the application grid |

Focus is never invisible: one 2 px ring, defined once in the tokens, applied to
every focusable thing in both toolkits.

## Performance

Measured on this machine (GNOME Shell 50.1, RTX 3060, 12 cores):

| | |
|---|---|
| status poll | one request every 8 s (configurable), ~400 bytes of JSON |
| notification poll | one request every 16 s |
| typing in ARIES Search | applications drawn locally on the keystroke; the ARIES request is debounced 90 ms |
| dock rebuild | coalesced to at most one per 120 ms — a launching application used to trigger five |
| blocking calls | none. There is no synchronous HTTP path in the extension, and a test enforces it |
| extension startup | components are built with defaults immediately; configuration is folded in when it arrives, so the shell draws with ARIES stopped |

The deliberate omission: no animation lasts longer than 240 ms, and the system's
own reduce-motion preference always wins over ARIES's `shell.animations`.

## When ARIES is not there

The first requirement, ahead of every feature. Tested by stopping the service:

* the indicator's dot goes red and its menu says *"ARIES is not running — the
  desktop keeps working without it. Start it with: aries start"*;
* ARIES Search still opens, still launches applications, and says the rest is
  unavailable rather than hanging;
* the dock, the top bar and quick settings' system half keep working — they read
  the machine, not ARIES;
* nothing retries in a tight loop, and nothing blocks.

`{ok: false, reason}` is data every component renders. ARIES being down is a
state to show, not an exception to crash on.

## Safety

The constraint that shaped the code: an extension runs inside `gnome-shell`, and
on Wayland a shell that throws during startup **cannot be restarted without
logging out** — there is no Alt+F2 `r`. So:

* every entry point goes through `guard()`; a component that throws is logged,
  left out, and the rest of the shell runs;
* the dock does **not** reserve struts. A crash with struts held would leave
  every window's work area wrong until logout. An overlay a maximised window
  sits under is recoverable; a wrong work area is not;
* `disable()` removes everything in reverse and tolerates parts that were never
  built;
* nothing is tested by trying it in the live session — see below.

Not done, and deliberately: GNOME is not replaced, no compositor is written, the
bootloader and display manager are untouched, and the login session is unchanged.

## Is it actually working right now?

```bash
./scripts/aries-smoke      # five seconds: can I use ARIES?
aries version              # is the running shell the source revision?
```

`aries-smoke` checks the things component tests skip: the service, the API, the
database, the launcher chain, the installed extension, the running shell's
surfaces, whether the running build matches the source, and whether typing
`news` resolves to something that can actually run. It exits non-zero if a
user-facing path is broken.

`aries version` answers the question that went unanswered for three rounds of
M13 verification: **is the thing running the thing I just changed?** Source,
installed and running are compared by content hash, because during development a
commit is not an identity — the tree is dirty more often than not, and two dirty
trees at one commit are different software.

## Testing

```bash
./scripts/test.sh              # everything, including the two below
./scripts/test-shell-api.sh    # the HTTP layer, in plain gjs
./scripts/test-shell.sh        # the extension, in a nested GNOME Shell
```

**Three levels, because the shell has three kinds of code.**

`test_shell.py` (106 assertions) covers what the shell *asks for*: the router,
the search, the status, the settings, the tokens, and the architecture itself —
no shell file reaches a database, none makes a synchronous call.

`test-shell-api.sh` (28 assertions) runs `lib/api.js` in **plain gjs** against a
deliberately badly-behaved ARIES. `api.js` imports nothing from `gnome-shell`, so
it loads outside a compositor — which is the only way to produce timeout,
truncation, refusal and cancellation on demand:

| the fake ARIES does | the shell must |
|---|---|
| never answer | give up on its own timeout and say *"ARIES did not answer in time"* |
| refuse the connection | report *"ARIES is not running"* as a **state**, flagged offline |
| return HTML with a 200 | refuse it as an unreadable reply rather than parse hopefully |
| return truncated JSON | the same — never half-use a partial body |
| return an empty body | succeed with `null` data, which is different from broken |
| return 404 with a detail | prefer ARIES's own words to a status number |
| return 500 with a plain-text body | still say *"ARIES answered 500"* — the status is the news |
| answer after `destroy()` | drop it as stale rather than deliver it to a dead widget |

`test-shell.sh` runs the extension in a **headless GNOME Shell on its own D-Bus
session** and now asserts more than "it loaded" — which said almost nothing,
because every component is guarded and the extension reaches ENABLED whether six
surfaces came up or one. It checks that **every named surface was built**, that
none reported a failure, that ARIES Search and the launcher respond to being
driven over D-Bus, and that the extension **enables cleanly a second time** after
being disabled. That last one is the real teardown test: a leak — a keybinding
still bound, a panel role still taken, a D-Bus name still owned — fails on the
second enable, not the first.

`test-shell.sh` starts a **headless GNOME Shell against a virtual monitor on its
own D-Bus session** — a complete, isolated GNOME, with real Mutter and real
extension loading — enables the extension there, and checks that it reached
ENABLED, logged no component failure, threw no JavaScript exception, and tore
itself down cleanly on disable. The user's session is never involved.

That harness found every bug in this milestone before a person saw one:
`affectsInputRegion` no longer being a valid parameter, a `St.ScrollView` given a
child that is not scrollable, `AppSystem.get_installed()` returning
`Gio.DesktopAppInfo` where `Shell.App` was assumed, and overlays that the
LayoutManager forced visible because they had opted into `trackFullscreen`.

The Python side additionally asserts the architecture rather than promising it:
no shell file reaches a database, no shell file makes a synchronous call, the
generated stylesheet matches the tokens exactly, and the severity vocabulary is
the same one the Control Centre uses.

## Fallback procedure

In order of increasing severity. Every one of them is reversible and none needs
`sudo`.

| situation | what to do |
|---|---|
| the shell misbehaves | `./scripts/aries-shell disable` |
| the desktop is unusable | `Ctrl+Alt+F3` to a TTY, then `gnome-extensions disable aries@aries.local`, then `Ctrl+Alt+F2` back |
| the session will not start | log in choosing **Ubuntu** at the session picker — ARIES has changed nothing about it ([SESSION.md](SESSION.md)) |
| remove it entirely | `./scripts/aries-shell uninstall` — unlinks the extension, the application entry, the icon, the backgrounds, and resets the wallpaper |

ARIES writes nothing outside `~/.local/share` and `~/aries`, installs no system
files, modifies no boot or login configuration, and replaces no part of GNOME.
Disabling the extension returns a plain Ubuntu GNOME session immediately.

## Changing the shell, and seeing the change

**Disabling and re-enabling the extension does not reload its code.** GJS caches
the module, so `gnome-extensions disable` followed by `enable` calls `disable()`
and `enable()` on the object loaded at login — new files are never imported and
a new stylesheet is never read. On Wayland `gnome-shell` cannot be restarted
either.

So the loop is:

```bash
./scripts/aries-shell generate       # regenerate the stylesheet from the tokens
./scripts/test-shell.sh              # prove it in a FRESH nested shell
./scripts/aries-session install      # copy it system-wide
# log out and back in — the only way new shell code runs
```

The nested harness matters precisely because it is the only fast way to load new
code: it starts a new `gnome-shell`, which is what your session will do at the
next login.

## What ARIES changes about the look

| | stock Ubuntu | ARIES |
|---|---|---|
| panel ground | Yaru `#131313`, bold text | ARIES surface with an accent underline, normal weight |
| panel buttons | pill (999px radius) | ARIES radius — square-ish, the most visible single difference |
| far left | Activities dots only | the **ARIES ram mark**, a button that opens ARIES Search |
| menus, notifications, dialogs, OSD | Yaru radii and greys | one ARIES radius and surface across all of them |
| overview search field | Yaru | ARIES surface, accent focus ring |
| dock | Ubuntu Dock | ARIES dock |
| background | Ubuntu aubergine | ARIES background, light/dark following your theme |

`!important` appears in exactly one section of the generated stylesheet, and a
test enforces that. Yaru sets `#panel { background-color: #131313 !important }`,
and an equally-specific rule without it loses whatever order the sheets load in
— overriding a theme that shouts requires shouting back. In ARIES's own widgets
it would mean a specificity problem to fix instead.

### The mark

Aries is the ram, and the zodiac glyph ♈ is a pair of horns — so the mark is the
name drawn rather than a metaphor added. It is one SVG path using `currentColor`,
so it follows the panel's foreground and stays legible in a light theme; horns
only, because a face becomes a smudge at 16 px. Drawn rather than taken from the
web: a downloaded illustration would be someone else's copyright shipped as this
system's identity, and a raster one would blur at every size the shell asks for.

## Screenshots

Captured from the nested session, so they are the real shell rather than a mockup.

| | |
|---|---|
| ![the desktop](screenshots/shell-desktop.png) | workspace pills, ARIES status, the dock |
| ![ARIES Search](screenshots/shell-search.png) | one router, real results |
| ![the launcher](screenshots/shell-launcher.png) | the application grid |
| ![quick settings](screenshots/shell-quicksettings.png) | one panel: the machine and ARIES |
| ![ARIES status](screenshots/shell-status.png) | what ARIES is doing and about to do |
| ![the overview](screenshots/shell-overview.png) | ARIES results in GNOME's own search |

Note what the quick settings panel says on this machine: *"no backlight"* and
*"Bluetooth · no adapter"*. Those are the honest-absence rule showing through —
a desktop with no backlight control gets told so, rather than a 0 % slider.

## What is not built yet

Stated plainly rather than implied by omission:

* **Dock auto-hide** is a setting (`shell.dock_autohide`) that nothing reads yet.
* **An ARIES-native overview.** ARIES appears *in* GNOME's overview as a search
  provider, which is integration rather than ownership. Replacing the overview
  needs to be better than what it replaces, not merely different.
* **The notification centre** is the desktop's, with ARIES as a source in it.
  An ARIES-native view grouping decisions, automation results and agent activity
  belongs with **ARIES Activity**, which is a later milestone.
* **The ARIES login session** is built — see [SESSION.md](SESSION.md). It adds
  ARIES to the login screen beside Ubuntu, loading the shell through a GNOME
  session mode rather than an extension you switch on.
