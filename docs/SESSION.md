# ARIES — The login session

**ARIES as a choice on the login screen**, beside Ubuntu.

```
POWER → ARIES → ARIES Login → ARIES Desktop
```

with Ubuntu underneath providing kernel, drivers, packages and systemd — and
still offered at the login screen, permanently, as the recovery path.

```bash
./scripts/aries-session plan        # exactly what would be written — no sudo
./scripts/aries-session verify      # prove it works, before installing — no sudo
./scripts/aries-session install     # write it (asks first, then sudo)
./scripts/aries-session status      # what is installed, and what would break it
./scripts/aries-session uninstall   # remove exactly what install wrote
```

---

## What an ARIES session actually is

Not a compositor, and not a fork of GNOME. It is a GNOME session started in an
ARIES **session mode** — the same mechanism Ubuntu uses for its own session. That
was read out of `/usr/share/gnome-shell/modes/ubuntu.json` and the units around
it rather than guessed at:

```
/usr/share/wayland-sessions/aries.desktop        the entry GDM offers
        └─ Exec=gnome-session --session=aries
             └─ …/gnome-session/sessions/aries.session          the session
                  └─ /etc/systemd/user/gnome-session@aries.target.d/…
                       └─ Requires=org.gnome.Shell@aries.service
                            └─ gnome-shell --mode=aries
                                 └─ …/gnome-shell/modes/aries.json
                                      └─ enabledExtensions: [aries@aries.local, …]
```

The mode names the extensions the session loads, so **logging into ARIES gives
you the ARIES desktop without switching anything on.** That is the whole point of
a session rather than an extension you enable.

## Five files, all new

| file | what it is |
|---|---|
| `/usr/share/wayland-sessions/aries.desktop` | the entry the login screen offers |
| `/usr/local/share/gnome-session/sessions/aries.session` | the gnome-session definition |
| `/usr/local/share/gnome-shell/modes/aries.json` | which extensions the session loads |
| `/usr/local/share/gnome-shell/extensions/aries@aries.local/` | the ARIES shell, system-wide |
| `/etc/systemd/user/gnome-session@aries.target.d/aries.session.conf` | starts `gnome-shell --mode=aries`; wants ARIES |

**No file belonging to any package is modified.** Ubuntu's session files are
untouched and Ubuntu stays on the login screen. A test asserts that no line in
the installer writes to anything Ubuntu owns — "we only add files" is a claim
that rots, so it is checked rather than promised.

`/usr/share` for the session entry because GDM's own binary names that path;
`/usr/local/share` for the rest because gnome-session and gnome-shell both walk
`XDG_DATA_DIRS`, and `/usr/local` is where local additions belong.

## Why the extension must be installed system-wide

The finding that shaped the installer. GNOME refuses to load a **per-user**
extension as part of a session mode:

```
Found user extension aries@aries.local, but not loading from
/home/…/.local/share/gnome-shell/extensions/… as part of session mode.
```

Which is right. A session mode is system configuration, and it must not be able
to auto-load code out of somebody's home directory. So the ARIES session installs
the extension into a system data directory.

`install --link` symlinks it back to the repository instead, which is convenient
while developing — and means the code your login session runs is writable by your
user account. `install` copies by default for that reason, and says so.

The per-user copy from `./scripts/aries-shell install` can stay: when both exist
the shell loads the system one and logs that it skipped the other. `aries-session
verify` asserts *which copy won*, because with both present the obvious check
(does the skip message appear?) tests nothing.

## The trap that makes a correct install do nothing

`disabled-extensions` **takes precedence over a session mode.** A uuid left in
that key — because you once ran `gnome-extensions disable aries@aries.local` —
makes the ARIES session start silently without ARIES, looking exactly like a
session that did not work.

So `install` removes it, `status` warns when it is set, and `verify` clears it
for the duration of its run. This was found by an installed-and-correct session
doing nothing at all.

## How it asks for administrator rights

`sudo` needs a controlling terminal, which a script run from an editor, an agent
or a desktop shortcut does not have — it fails with *"sudo: A terminal is
required to authenticate"*. So everything privileged moved into **one** script,
`scripts/aries-session-root`, and `as_root` picks the route this machine can
actually authenticate with:

| route | when |
|---|---|
| `sudo -n` | the machine is set up for passwordless sudo |
| `pkexec` | there is a graphical session — the desktop's own PolicyKit agent draws the password dialog |
| `sudo` | a real terminal |
| *none* | it prints the exact command to run yourself rather than dying with a shell error |

Splitting it that way is worth more than the convenience. One authentication
instead of eight, and a privileged surface of about fifty lines that you can read
in one sitting before deciding to run it — rather than root spread through a
script that also parses arguments and prints status. It validates every input,
refuses a mode file that will not parse, and refuses to run at all unless it is
root.

## Proving it before installing it

```bash
./scripts/aries-session verify                    # before installing
./scripts/test-session.sh 20 --installed          # what is actually on disk
```

Those are different assurances. The first says *this would work if installed*;
the second says *what got installed works*, and only the second is about the
machine you will log into.

This is the important one. Writing a session entry means that getting it wrong
produces a login screen offering a session that does not start — the only failure
in this project a user cannot recover from *inside* the system.

So the session is proved first, with **nothing installed**. `gnome-shell` finds
modes by walking `XDG_DATA_DIRS`, so pointing that at a staging directory loads
the real mode file in a real GNOME Shell, started exactly as the session starts
it — `gnome-shell --mode=aries` — in a nested headless session.

It asserts that the mode loads, that the ARIES extension becomes **ACTIVE
because the session says so** (nobody ran `gnome-extensions enable`), that the
copy which won was the system one, that every ARIES surface came up inside the
session, and that Ubuntu's own mode is present and unmodified.

```
PASS  gnome-shell started with --mode=aries
PASS  the ARIES extension is ACTIVE because the SESSION says so
PASS  it loaded the SYSTEM copy, which is the only kind a session mode accepts
PASS  every ARIES surface was built inside the session
PASS  with nothing reporting a failure
PASS  Ubuntu's own session mode is present and unmodified
```

## What the ARIES session loads, and what it leaves out

| extension | in the ARIES session | why |
|---|---|---|
| `aries@aries.local` | ✓ | the point |
| `ubuntu-appindicators` | ✓ | applications put tray icons there |
| `tiling-assistant` | ✓ | window management the user already relies on |
| `snapd-prompting` | ✓ | a security prompt; removing it to tidy a desktop would weaken the system |
| `snapd-search-provider`, `web-search-provider` | ✓ | overview search |
| `ding` (desktop icons) | ✓ | the user's existing desktop; ARIES does not take it away |
| `ubuntu-dock` | ✗ | ARIES has its own dock, and two docks is not one environment |

The mode sets `parentMode: user` and keeps the system's shell stylesheet, so
GNOME's own widgets look like the rest of the machine. ARIES restyles its own
surfaces and leaves everything else alone.

## Fallback and recovery

In order of increasing severity. None needs a rescue disk.

| situation | what to do |
|---|---|
| you want Ubuntu back for one login | pick **Ubuntu** from the session menu on the login screen (the gear beside the password box) |
| the ARIES session starts but ARIES is missing | `./scripts/aries-session status` — almost always the `disabled-extensions` trap |
| the ARIES session does not start | pick Ubuntu, then `./scripts/aries-session uninstall` |
| you cannot reach a graphical login at all | `Ctrl+Alt+F3` for a TTY, log in, `~/aries/scripts/aries-session uninstall` |
| remove every trace | `./scripts/aries-session uninstall` then `./scripts/aries-shell uninstall` |

**The Ubuntu session is never removed.** `PRODUCT_IDENTITY.md` makes that a
standing constraint rather than a transitional phase: it is the recovery
environment, and `aries-session status` reports whether it is still there.

## What this is not, yet

* **Not a display manager change.** GDM still runs, still draws the login screen,
  still lists both sessions. An ARIES login *screen* would mean replacing or
  theming GDM, which is a separate decision with a worse failure mode.
* **Not a boot change.** The bootloader, initramfs and `default.target` are
  untouched. `POWER → ARIES` is true from the login screen onward; below that it
  is still Ubuntu booting, which is the point of the foundation.
* **Not a compositor.** Still GNOME Shell, still Mutter. ADR-0008 records when
  that would be worth revisiting, and it is not yet.
