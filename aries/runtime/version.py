"""Which revision is actually running — as opposed to which one is checked out.

WHY THIS EXISTS
---------------
Entry 016 was verified three times against a `gnome-shell` running code from
hours earlier. Every check passed, the reports were confident, and the desktop
had none of the changes: GJS caches extension modules, so disabling and
re-enabling an extension re-runs `disable()`/`enable()` on the object loaded at
login and imports nothing new. There was no way to notice, because nothing in
the system could say what revision it was.

So every component now carries a build identity, and `aries version` prints all
of them side by side. The question it answers is not "what version is ARIES" —
it is **"is the thing running the thing I just changed?"**, which is a different
question and the one that was missing.

WHAT COUNTS AS IDENTITY
-----------------------
A git commit alone is not enough: during development the working tree is dirty
more often than not, and two dirty trees at the same commit are different
software. So the identity is the commit, whether the tree is dirty, and — for
the parts that are copied elsewhere to run — a content hash of the files that
were actually copied. A hash difference between source and installed is the
exact signal that was missing.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EXTENSION_UUID = "aries@aries.local"


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL, timeout=5).strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def _tree_hash(path: Path, suffixes: tuple[str, ...] = (".js", ".css", ".json", ".xml")) -> str:
    """A stable hash of the files that actually run.

    Sorted, path-relative, content only — so the same files copied to a
    different directory hash the same, which is the whole point: it compares
    what is installed against what it was installed from.
    """
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file() and p.suffix in suffixes):
        digest.update(str(file.relative_to(path)).encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()[:12]


def source() -> dict:
    """What the working tree says."""
    dirty = bool(_git("status", "--porcelain"))
    return {
        "commit": _git("rev-parse", "--short", "HEAD") or "unknown",
        "dirty": dirty,
        "described": _git("describe", "--always", "--dirty") or "unknown",
        "shell_build": _tree_hash(ROOT / "shell" / EXTENSION_UUID),
        "control_centre_build": _tree_hash(ROOT / "aries_ui", (".py",)),
    }


def installed() -> dict:
    """What is on disk where the desktop actually loads it from."""
    candidates = [
        Path(os.path.expanduser("~/.local/share/gnome-shell/extensions")) / EXTENSION_UUID,
        Path("/usr/local/share/gnome-shell/extensions") / EXTENSION_UUID,
        Path("/usr/share/gnome-shell/extensions") / EXTENSION_UUID,
    ]
    found = {}
    for path in candidates:
        if path.exists():
            found[str(path)] = _tree_hash(path)
    return found


def compare() -> dict:
    """Is what is installed what it was built from?"""
    src = source()
    inst = installed()
    system = {p: h for p, h in inst.items() if not p.startswith(os.path.expanduser("~"))}
    matches = [h == src["shell_build"] for h in system.values()]
    return {
        "source": src,
        "installed": inst,
        # `None` rather than False when nothing is installed: "not installed" and
        # "installed and stale" are different facts and must not share a signal.
        "shell_matches": (all(matches) if matches else None),
    }


def describe() -> dict:
    """Everything, for `aries version` and for the smoke test."""
    from aries import __version__

    return {"aries": __version__, **compare()}
