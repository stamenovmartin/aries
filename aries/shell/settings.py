"""The shell's own settings — declared in ARIES, not in the extension.

A GNOME Shell extension would normally keep its preferences in its own GSettings
schema, which means compiling a schema, a `prefs.js`, and a second place the
user has to go to configure ARIES. The brief is explicit that complexity is
hidden behind one coherent system, and §20 already gives ARIES a typed settings
service with provenance, precedence and an audit trail.

So the shell has no settings of its own. It reads these over the same API as
everything else, and they appear in the same Settings screen next to the rest —
which is also what makes "learned behaviour must never override an explicit user
preference" (§30) apply to the desktop as much as to the briefing.
"""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

S = "shell"

define(SettingDef("shell.enabled", bool, False, "ARIES Shell",
                  "Whether the ARIES desktop shell is active. Installing the extension does "
                  "not switch it on; this does. Turning it off leaves a plain GNOME session.",
                  S, control="toggle", user_only=True))

define(SettingDef("shell.top_bar", bool, True, "Top bar",
                  "Show ARIES status, workspace and quick access in the GNOME panel.",
                  S, control="toggle"))

define(SettingDef("shell.dock", bool, True, "Dock",
                  "Show the ARIES dock with pinned and running applications.",
                  S, control="toggle"))

define(SettingDef("shell.dock_position", str, "top", "Application icons position",
                  "Application icons appear in the top panel beside ARIES.",
                  S, control="select", choices=("top", "bottom", "left", "right")))

define(SettingDef("shell.dock_autohide", bool, False, "Hide the dock automatically",
                  "Slide the dock away until the pointer reaches its edge.",
                  S, control="toggle"))

define(SettingDef("shell.dock_icon_size", int, 44, "Dock icon size",
                  "How large dock icons are drawn.",
                  S, control="slider", minimum=28, maximum=64, unit="px"))

define(SettingDef("shell.pinned_apps", list,
                  ["org.gnome.Nautilus.desktop", "firefox_firefox.desktop",
                   "org.gnome.Terminal.desktop", "aries-control-centre.desktop"],
                  "Pinned applications",
                  "Desktop file ids kept in the dock whether or not they are running.",
                  S, control="list"))

define(SettingDef("shell.command_bar", bool, True, "Command bar",
                  "Super+Space opens the ARIES command bar.",
                  S, control="toggle"))

define(SettingDef("shell.command_shortcut", str, "<Super>space", "Command bar shortcut",
                  "The key combination that opens the command bar, in GTK accelerator form.",
                  S, control="text", advanced=True))

# Written by ARIES: the keybindings Super+Space was taken from, so it can be
# given back. Same borrow-and-return discipline as the wallpaper and the display
# timeout — if ARIES takes something the user owns, it records what was there.
define(SettingDef("shell.restore_shortcut", str, "", "Previous shortcut owners",
                  "Internal: which desktop shortcuts the command bar's key was taken from, "
                  "so switching the shell off puts them back exactly.",
                  S, control="text", advanced=True))

# Written by ARIES: which dock extension was enabled before ARIES took over, and
# where it sat in the list, so `aries-shell dock ubuntu` restores it exactly.
define(SettingDef("shell.restore_dock", str, "", "Previous dock",
                  "Internal: the dock extension ARIES stood down, and its position in your "
                  "enabled list, so switching back restores it exactly where it was.",
                  S, control="text", advanced=True))

define(SettingDef("shell.animations", str, "full", "Animations",
                  "How much motion the shell uses. 'reduced' keeps only what communicates "
                  "state; 'none' removes it entirely and is also what the system's own "
                  "reduce-motion setting forces.",
                  S, control="select", choices=("full", "reduced", "none")))

define(SettingDef("shell.status_poll_seconds", int, 8, "Status refresh",
                  "How often the top bar asks ARIES how it is. Lower is more current and "
                  "costs more; the panel never blocks on the answer either way.",
                  S, control="number", minimum=2, maximum=120, unit="seconds", advanced=True))

define(SettingDef("shell.notifications_in_shell", bool, True, "ARIES notifications in the shell",
                  "Deliver ARIES decisions and automation results through the desktop's own "
                  "notification system, so they sit with everything else rather than in a "
                  "place you have to remember to look.",
                  S, control="toggle"))

# Defaults to `system`: ARIES does not replace the user's wallpaper because an
# extension was switched on. §11's "nothing is enabled by default" is about
# automations, but the same courtesy applies to anything that changes something
# the user chose — and a wallpaper is the most personal setting on a desktop.
define(SettingDef("shell.wallpaper", str, "system", "Background",
                  "Which ARIES background to use. 'system' leaves your own wallpaper alone. "
                  "'aries' follows your light/dark preference; the other two pin one of them. "
                  "Whatever was set before is recorded and put back if you choose 'system'.",
                  S, control="select",
                  choices=("system", "aries", "aries-dark", "aries-light")))

# Written by ARIES, not by the user: the wallpaper found before ARIES changed it.
# The same borrow-and-return discipline as `power.restore_idle_delay` (Entry 013)
# — if ARIES touches something the user owns, it records what was there first.
define(SettingDef("shell.restore_wallpaper", str, "", "Previous background",
                  "Internal: the wallpaper ARIES found before it changed anything, so choosing "
                  "'system' puts it back exactly.",
                  S, control="text", advanced=True))

define(SettingDef("shell.file_search", bool, True, "Search files from the command bar",
                  "Look through your own folders for files by name. Anything in "
                  "privacy.excluded_paths is never read.",
                  S, control="toggle"))
