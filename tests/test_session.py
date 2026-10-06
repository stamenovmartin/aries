"""The ARIES login session: five files that must be exactly right.

WHY THESE GET THEIR OWN SUITE
-----------------------------
Everything else in ARIES fails safely — a broken automation is skipped, a broken
shell component is guarded out, a stopped runtime leaves a working desktop. A
malformed session definition is the one thing in this project that can fail
*before* the user has a desktop to fix it from.

So the files are parsed and cross-checked here, and `./scripts/test-session.sh`
proves the whole arrangement in a nested GNOME Shell before anything is
installed. Neither test needs root, and neither touches the system.

WHAT IS CROSS-CHECKED
---------------------
Not "is this valid INI" but "do these five files agree with each other". The
session entry names a session; the session file must exist for that name; the
systemd drop-in must start the shell in a mode whose file exists; the mode must
enable the extension whose uuid the shell actually has. Four of those five
agreements are invisible until login fails.
"""
from __future__ import annotations

import configparser
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, run_module

bootstrap("aries-session")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION = os.path.join(ROOT, "session")
UUID = "aries@aries.local"


def _ini(path: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str
    with open(path) as fh:
        parser.read_file(fh)
    return parser


def _desktop() -> configparser.SectionProxy:
    return _ini(os.path.join(SESSION, "aries.desktop"))["Desktop Entry"]


def _mode() -> dict:
    with open(os.path.join(SESSION, "modes", "aries.json")) as fh:
        return json.load(fh)


# ── the login screen entry ──────────────────────────────────────────────────

async def test_the_login_entry_is_a_valid_session():
    entry = _desktop()
    check("it is called ARIES, which is what the login screen shows",
          entry["Name"] == "ARIES")
    check("it is an Application, as a session entry must be",
          entry["Type"] == "Application")
    check("it starts gnome-session, not a compositor of our own",
          entry["Exec"] == "/usr/bin/gnome-session --session=aries")
    check("with a TryExec so the entry hides itself if gnome-session is gone",
          entry["TryExec"] == "/usr/bin/gnome-session")
    check("and it registers with GDM like every other session",
          entry.get("X-GDM-SessionRegisters") == "true")


async def test_the_session_still_says_it_is_ubuntu_underneath():
    """DesktopNames drives OnlyShowIn, Ubuntu-specific settings, and — via
    `Desktop.is('ubuntu')` — GNOME's refusal to load per-user extensions in a
    session mode. Dropping `ubuntu` would bypass that check, which is exactly
    why it stays: the check is right, and working around a security rule to make
    an install easier is how you get a system nobody can reason about."""
    names = _desktop()["DesktopNames"].split(";")
    check("ARIES names itself first", names[0] == "ARIES")
    check("but keeps ubuntu, so Ubuntu-only applications and settings still apply",
          "ubuntu" in names)
    check("and GNOME, so every GNOME application still appears", "GNOME" in names)


# ── the pieces agreeing with each other ─────────────────────────────────────

async def test_the_five_files_agree():
    entry = _desktop()
    session_name = entry["Exec"].split("--session=")[1].strip()
    check("the entry asks for the 'aries' session", session_name == "aries")

    path = os.path.join(SESSION, f"{session_name}.session")
    check(f"and {session_name}.session exists for gnome-session to find",
          os.path.exists(path))
    check("naming itself ARIES", _ini(path)["GNOME Session"]["Name"] == "ARIES")

    dropin = os.path.join(SESSION, f"gnome-session@{session_name}.target.d",
                          f"{session_name}.session.conf")
    check("the systemd drop-in is named for the same session",
          os.path.exists(dropin))
    with open(dropin) as fh:
        conf = fh.read()
    check("it starts the shell in the aries mode",
          f"Requires=org.gnome.Shell@{session_name}.service" in conf)
    check("and a mode file exists for that name",
          os.path.exists(os.path.join(SESSION, "modes", f"{session_name}.json")))
    check("it pulls in ARIES itself", "Wants=aries.target" in conf)
    check("wanting rather than requiring — a session that refuses to start "
          "because the assistant is unwell is the worst way to learn it is unwell",
          "Requires=aries.target" not in conf)


async def test_the_mode_enables_the_extension_that_actually_exists():
    """The uuid is written in two files that cannot see each other."""
    mode = _mode()
    check("the mode enables ARIES", UUID in mode["enabledExtensions"])
    with open(os.path.join(ROOT, "shell", UUID, "metadata.json")) as fh:
        meta = json.load(fh)
    check("and that is the uuid the extension actually declares",
          meta["uuid"] == UUID)


async def test_the_mode_does_not_start_two_docks():
    mode = _mode()
    check("Ubuntu's dock is not in the ARIES session — ARIES has its own",
          "ubuntu-dock@ubuntu.com" not in mode["enabledExtensions"])
    check("but the tray is, because applications depend on it",
          "ubuntu-appindicators@ubuntu.com" in mode["enabledExtensions"])
    check("and snap's security prompting is, because removing it would weaken "
          "the system to make a desktop tidier",
          "snapd-prompting@canonical.com" in mode["enabledExtensions"])


async def test_the_mode_inherits_rather_than_reinvents():
    mode = _mode()
    check("it descends from the standard user mode", mode["parentMode"] == "user")
    check("and keeps the system's own shell stylesheet, so GNOME's widgets look "
          "like the rest of the machine", "stylesheetName" in mode)


# ── what it must not do ─────────────────────────────────────────────────────

async def test_nothing_ubuntu_owns_is_written_to():
    """Every path the installer writes is new. Asserted against the installer
    itself, because 'we only add files' is a claim that rots."""
    with open(os.path.join(ROOT, "scripts", "aries-session")) as fh:
        installer = fh.read()
    targets = [line.split('="')[1].rstrip('"')
               for line in installer.splitlines()
               if line.startswith(("SESSION_ENTRY=", "SESSION_FILE=", "SHELL_MODE=",
                                   "SYS_EXT=", "UNIT_DROPIN="))]
    check("the installer declares five targets", len(targets) == 5)
    for path in targets:
        check(f"{path} is not a file Ubuntu ships",
              "ubuntu" not in os.path.basename(path).lower())
        # $UUID is not expanded in the source text, so the aries-ness of the
        # extension path is in the variable rather than the literal.
        check(f"{path} names ARIES, so it cannot collide with anything else",
              "aries" in path.lower() or "$UUID" in path)

    # Scan for WRITES against an Ubuntu path, not for the string appearing at
    # all: `status` reads /usr/share/wayland-sessions/ubuntu.desktop to report
    # that the fallback is still there, and the header explains where the
    # mechanism was read from. Both mention Ubuntu paths and neither writes one.
    writes = ("rm ", "rm -", "install -", "cp ", "cp -", "ln ", "ln -", "mv ",
              "tee ", "chown ", "chmod ", "truncate ", "sed -i")
    offending = []
    for line in installer.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "ubuntu" not in stripped.lower():
            continue
        if any(verb in stripped for verb in writes) or ">" in stripped.split("#")[0]:
            offending.append(stripped[:90])
    check(f"no line writes to anything Ubuntu owns{'' if not offending else ': ' + str(offending)}",
          offending == [])


async def test_the_installer_handles_the_precedence_trap():
    """`disabled-extensions` overrides a session mode, so a uuid left there makes
    a correct install do nothing at all — silently. Found the hard way."""
    with open(os.path.join(ROOT, "scripts", "aries-session")) as fh:
        installer = fh.read()
    check("the installer clears the uuid from disabled-extensions",
          "disabled-extensions" in installer and "install)" in installer)
    check("and status warns when it is set, rather than reporting success",
          "OVERRIDES the session mode" in installer)


async def test_the_system_extension_is_a_copy_by_default():
    """A symlink from /usr/local/share into a home directory means the code the
    login session runs is writable by that user. Reasonable while developing,
    and not the default."""
    with open(os.path.join(ROOT, "scripts", "aries-session")) as fh:
        installer = fh.read()
    with open(os.path.join(ROOT, "scripts", "aries-session-root")) as fh:
        privileged = fh.read()
    check("the default mode is copy", 'mode="copy"' in installer)
    check("link is chosen only when the flag was given",
          '[ -n "$link" ] && mode="link"' in installer)
    check("and the privileged half copies unless told to link",
          'if [ "$MODE" = "link" ]' in privileged
          and 'cp -rL "$ROOT/shell/$UUID" "$SYS_EXT"' in privileged)
    # Asserted on behaviour, not on an exact line. The first version of this
    # matched the literal `[ "${2:-}" = "--link" ]`, and broke the moment the
    # flags became order-independent — a test failing because correct code was
    # written differently is a test that punishes improvement.
    check("linking is opt-in — the word appears only as a flag to match",
          "--link)" in installer and 'link="yes"' in installer)
    check("and it says what linking costs", "writable by your user account" in installer)


async def test_uninstall_removes_what_install_wrote():
    """Both halves are read, because the privileged work moved into its own
    script: the paths written and the paths removed must still match, and they
    now live in two files that cannot see each other."""
    with open(os.path.join(ROOT, "scripts", "aries-session-root")) as fh:
        writes = fh.read()
    with open(os.path.join(ROOT, "scripts", "aries-session-root-uninstall")) as fh:
        removes = fh.read()
    for literal in ("/usr/share/wayland-sessions/aries.desktop",
                    "/usr/local/share/gnome-session/sessions/aries.session",
                    "/usr/local/share/gnome-shell/modes/aries.json",
                    "/etc/systemd/user/gnome-session@aries.target.d/aries.session.conf"):
        check(f"install writes {literal}", literal in writes)
        check(f"and uninstall removes it", literal in removes)
    check("the system extension is written",
          '/usr/local/share/gnome-shell/extensions/$UUID' in writes)
    check("and removed", '/usr/local/share/gnome-shell/extensions/$UUID' in removes)


async def test_everything_privileged_is_in_one_readable_place():
    """Eight sudo calls spread across a script that also parses arguments and
    prints status is a privileged surface nobody reads. One program, one
    authentication, fifty lines."""
    with open(os.path.join(ROOT, "scripts", "aries-session")) as fh:
        installer = fh.read()
    # The two `sudo "$program"` lines inside as_root() are the point of as_root:
    # one place that escalates, by whichever route this machine can authenticate
    # with. What must not exist is a sudo call somewhere else, running an
    # ad-hoc command.
    body = installer.split("bold() {", 1)[1]
    stray = [line.strip() for line in body.splitlines()
             if line.strip().startswith("sudo ")]
    check(f"nothing outside as_root() escalates"
          f"{'' if not stray else ': ' + str(stray)}", stray == [])
    check("and as_root runs a named program, never a command it assembled",
          'as_root() {\n  local program="$1"; shift' in installer)
    with open(os.path.join(ROOT, "scripts", "aries-session-root")) as fh:
        privileged = fh.read()
    check("the privileged half refuses to run unless it is root",
          '[ "$(id -u)" = "0" ]' in privileged)
    check("it requires an absolute repository path", "must be an absolute path" in privileged)
    check("it validates every input before writing anything",
          privileged.index("does not parse") < privileged.index("install -d"))
    check("and it refuses a mode file that will not parse",
          "json.load" in privileged)
    check("it is short enough to read before running",
          len(privileged.splitlines()) < 90)


async def test_the_fallback_is_never_removed():
    """PRODUCT_IDENTITY.md makes this a standing constraint, not a phase."""
    with open(os.path.join(ROOT, "scripts", "aries-session")) as fh:
        installer = fh.read()
    check("nothing in the installer deletes a session entry that is not ARIES's",
          "rm -f /usr/share/wayland-sessions/ubuntu.desktop" not in installer)
    check("and status reports whether the Ubuntu fallback is still there",
          "Ubuntu fallback" in installer)


# ── the harness must not change the machine ─────────────────────────────────

async def test_the_nested_harnesses_put_the_desktop_back():
    """dconf is per-USER, not per-session: anything the shell writes inside a
    nested run rewrites the keys the real desktop reads. It happened twice — the
    live session lost its dock and desktop icons, and later lost Super+Space —
    so the guard is checked rather than trusted."""
    for name in ("test-shell.sh", "test-session.sh"):
        with open(os.path.join(ROOT, "scripts", name)) as fh:
            body = fh.read()
        check(f"{name} records the settings before anything runs",
              "ARIES_WRITES=(" in body and "SAVED_SETTINGS+=(" in body)
        check(f"{name} restores them on every exit path",
              "trap restore_extensions EXIT INT TERM" in body
              or "trap cleanup EXIT INT TERM" in body)


async def test_the_guard_covers_everything_the_shell_can_write():
    """A guard that silently falls behind the code it guards is worse than none,
    because it reads as protection.

    So the *user desktop* schemas the extension mentions are extracted from the
    extension itself — `org.gnome.desktop.*` and `org.gnome.shell`, which is
    exactly the user's own configuration — and every one must appear in the
    harness guard. The first version of this scan looked for inline
    `schema_id: '...'` literals and found none, because they are all named
    constants; a scan that cannot see the thing it checks passes for free.
    """
    import re
    mentioned = set()
    base = os.path.join(ROOT, "shell", "aries@aries.local")
    for directory, _dirs, files in os.walk(base):
        for name in sorted(files):
            if not name.endswith(".js"):
                continue
            with open(os.path.join(directory, name)) as fh:
                body = re.sub(r"/\*.*?\*/", "", fh.read(), flags=re.S)
            for schema in re.findall(r"'(org\.gnome\.(?:desktop\.[\w.]+|shell))'", body):
                mentioned.add(schema)

    check(f"the scan finds the desktop schemas the shell touches: {sorted(mentioned)}",
          len(mentioned) >= 3)

    with open(os.path.join(ROOT, "scripts", "test-shell.sh")) as fh:
        harness = fh.read()
    missing = sorted(s for s in mentioned if s not in harness)
    check(f"every one is in the harness guard"
          f"{'' if not missing else ', missing: ' + str(missing)}", missing == [])


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
