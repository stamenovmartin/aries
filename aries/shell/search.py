"""Searching what ARIES knows: settings, automations, and the user's files.

WHY FILE SEARCH BELONGS HERE AND NOT IN THE SHELL
-------------------------------------------------
The shell could walk the filesystem itself — it is a process on the same
machine with the same permissions. It must not, and the reason is a rule the
system already has: `privacy.excluded_paths` says which directories ARIES may
never read, it defaults to `~/.ssh` and `~/.gnupg`, and it is enforced in
`sources/safety.py` with symlinks resolved *before* the check so
`~/docs/link-to-ssh` cannot walk around it.

A shell that indexed files on its own would be a second implementation of that
rule, in another language, that nobody would remember to update when the user
added a directory to the exclusion list. So the shell asks, and the same
`_under()` that guards sources guards this — imported, not reimplemented.

BOUNDED BY CONSTRUCTION
-----------------------
A desktop search box runs on every keystroke, so this walk is bounded three
ways at once: a fixed set of roots, a depth limit, and a hard cap on directory
entries examined. Hitting the cap is reported (`truncated: true`) rather than
hidden, because "no results" and "stopped looking" are different facts — the
same rule the health probes follow about `null` versus `0`.

Hidden files and directories are skipped. Not for safety — `.config` is not
secret — but because a launcher that offers `~/.cache/thumbnails/a3f9.png`
before `~/Documents/thesis.odt` is a launcher nobody uses twice.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from aries.sources.safety import SYSTEM_PATHS, _under

# Where a personal file search is worth looking. Not `/`: a command bar is for
# reaching the things you work on, and everything else is what a file manager
# is for.
DEFAULT_ROOTS = ("~/Desktop", "~/Documents", "~/Downloads", "~/Pictures",
                 "~/Projects", "~/Videos", "~/Music", "~")
MAX_DEPTH = 4
MAX_ENTRIES = 6000
TIME_BUDGET_S = 0.35
SKIP_DIRS = {"node_modules", "__pycache__", ".git", ".venv", "venv", "target",
             "build", "dist", ".cache", "snap"}


@dataclass
class FileHit:
    path: str
    name: str
    is_dir: bool
    score: float

    def as_dict(self) -> dict:
        return {"kind": "file", "id": self.path, "title": self.name,
                "detail": _pretty(os.path.dirname(self.path)),
                "action": {"kind": "open_path", "path": self.path,
                           "is_dir": self.is_dir}}


def _pretty(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def _excluded_roots(excluded: list[str]) -> list[str]:
    out = []
    for pattern in list(excluded or []) + list(SYSTEM_PATHS):
        try:
            resolved = os.path.realpath(os.path.expanduser(os.path.expandvars(str(pattern).strip())))
        except (OSError, ValueError):
            continue
        if resolved and resolved != os.sep:
            out.append(resolved)
    return out


def _match_score(name: str, query: str) -> float:
    """Prefix beats word-start beats substring. Nothing cleverer, on purpose:
    a launcher whose ranking cannot be predicted is a launcher you fight."""
    low = name.lower()
    if low == query:
        return 1.0
    if low.startswith(query):
        return 0.9
    for sep in (" ", "-", "_", "."):
        if f"{sep}{query}" in low:
            return 0.7
    if query in low:
        return 0.5
    return 0.0


def search_files(query: str, *, excluded: list[str], roots: tuple[str, ...] = DEFAULT_ROOTS,
                 limit: int = 8) -> dict:
    """Find files and folders by name. Bounded in depth, count and time."""
    query = (query or "").strip().lower()
    if len(query) < 2:
        return {"results": [], "truncated": False, "scanned": 0,
                "reason": "type at least two characters"}

    blocked = _excluded_roots(excluded)
    seen: set[str] = set()
    hits: list[FileHit] = []
    scanned = 0
    truncated = False
    deadline = time.monotonic() + TIME_BUDGET_S

    def blocked_path(path: str) -> bool:
        return any(_under(path, b) for b in blocked)

    for raw_root in roots:
        root = os.path.realpath(os.path.expanduser(raw_root))
        if not os.path.isdir(root) or root in seen or blocked_path(root):
            continue
        seen.add(root)
        stack = [(root, 0)]
        while stack:
            if scanned >= MAX_ENTRIES or time.monotonic() > deadline:
                truncated = True
                break
            directory, depth = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except (OSError, PermissionError):
                continue
            for entry in entries:
                scanned += 1
                if entry.name.startswith("."):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                full = entry.path
                if is_dir:
                    if entry.name in SKIP_DIRS or blocked_path(os.path.realpath(full)):
                        continue
                    if depth + 1 <= MAX_DEPTH:
                        stack.append((full, depth + 1))
                score = _match_score(entry.name, query)
                if score > 0 and full not in seen:
                    seen.add(full)
                    hits.append(FileHit(full, entry.name, is_dir, score))
        if truncated:
            break

    hits.sort(key=lambda h: (-h.score, len(h.name)))
    return {"results": [h.as_dict() for h in hits[:limit]],
            "truncated": truncated, "scanned": scanned,
            "reason": "stopped early — too many files to scan" if truncated else ""}


def search_settings(query: str, *, limit: int = 6) -> list[dict]:
    """Settings by key, title or description — so "brightness" finds it."""
    from aries.settings import all_defs

    query = (query or "").strip().lower()
    if len(query) < 2:
        return []
    out: list[tuple[float, dict]] = []
    for d in all_defs():
        score = max(_match_score(d.title, query), _match_score(d.key, query))
        if score == 0 and query in (d.description or "").lower():
            score = 0.35
        if score == 0 and query in d.key.lower():
            score = 0.4
        if score > 0:
            out.append((score, {
                "kind": "setting", "id": d.key, "title": d.title,
                "detail": f"{d.section} · {d.description[:90]}",
                "action": {"kind": "navigate", "section": "settings", "anchor": d.key}}))
    out.sort(key=lambda p: -p[0])
    return [r for _, r in out[:limit]]


def search_automations(query: str, *, limit: int = 5) -> list[dict]:
    """Automations by name or purpose, offered as something to RUN.

    An automation found in a command bar is something the user wants to happen,
    not something they want to read about — so the action runs it rather than
    navigating to it. Navigation is one keystroke away in the same list.
    """
    from aries.automations.genome import all_automations

    query = (query or "").strip().lower()
    if len(query) < 2:
        return []
    out: list[tuple[float, dict]] = []
    for spec in all_automations():
        score = max(_match_score(spec.name, query), _match_score(spec.automation_id, query))
        if score == 0 and query in spec.purpose.lower():
            score = 0.35
        if score > 0:
            out.append((score, {
                "kind": "automation", "id": spec.automation_id,
                "title": f"Run {spec.name}", "detail": spec.purpose[:110],
                "action": {"kind": "run_automation", "automation_id": spec.automation_id}}))
    out.sort(key=lambda p: -p[0])
    return [r for _, r in out[:limit]]
