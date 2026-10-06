"""Reading a folder on this machine — the first connector, and the safe one.

WHY LOCAL FILES COME FIRST
--------------------------
No credential, no network, nothing leaves the machine, and every failure is
visible immediately. It is the connector on which the whole boundary can be
proved before anything with a password uses it — and it is the one that makes
`directory`, `documents` and `repository` sources stop being descriptions of
things ARIES cannot do.

WHAT IT REFUSES, AND WHY THAT IS THE INTERESTING PART
-----------------------------------------------------
The privacy rules are not this file's invention: `privacy.excluded_paths` and
`SYSTEM_PATHS` already govern file search, and reusing them is the point. Two
sets of rules about which folders ARIES may read would disagree eventually, and
the one that disagreed quietly would be this one.

**Symlinks are resolved before any check.** A source pointing at `~/notes` that
is a link to `~/.ssh` is a source pointing at `~/.ssh`, and checking the name
before resolving it is how that gets missed.

**Hidden files and directories are skipped**, which is why the privacy test for
file search had to put its probe somewhere visible — a guard that cannot be
shown to fire is not a guard.

**Binary files are not read.** A JPEG's bytes as "content" is noise that costs
the working set and the model nothing but tokens.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from aries.connect.base import Health, Item, register
from aries.connect.untrusted import Untrusted
from aries.shell.search import SKIP_DIRS, _excluded_roots
from aries.sources.safety import SYSTEM_PATHS

logger = __import__("logging").getLogger(__name__)

# Bounds, so one enormous folder cannot become one enormous working set.
MAX_FILES = 200
MAX_BYTES = 200_000            # per file
MAX_DEPTH = 6

# Extensions ARIES will read as text. An allowlist rather than a binary sniff:
# the failure of a sniff is reading something it should not have, and the
# failure of an allowlist is a file type someone has to ask for.
TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".org", ".tex",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".h", ".cpp", ".hpp",
    ".rs", ".go", ".rb", ".sh", ".bash", ".zsh", ".sql", ".r", ".jl", ".lua",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env.example",
    ".csv", ".tsv", ".html", ".htm", ".xml", ".css", ".scss",
}


@dataclass
class FilesConnector:
    """Read-only access to a folder. Local, so `outbound` is False and stays so."""

    source_type: str = "directory"
    outbound: bool = False

    def capabilities(self) -> tuple[str, ...]:
        return ("read", "search")

    async def check(self, source) -> Health:
        """Is the folder there, readable, and allowed? Measured now."""
        now = datetime.now(timezone.utc)
        path = os.path.realpath(os.path.expanduser(source.location))
        if not os.path.exists(path):
            return Health(False, f"{_pretty(path)} does not exist", checked_at=now)
        if not os.path.isdir(path):
            return Health(False, f"{_pretty(path)} is not a folder", checked_at=now)
        if not os.access(path, os.R_OK | os.X_OK):
            return Health(False, f"{_pretty(path)} is not readable by this user",
                          checked_at=now)
        blocked = await _blocked_roots()
        for root in blocked:
            if _under(path, root):
                return Health(False,
                              f"{_pretty(path)} is inside {_pretty(root)}, which ARIES "
                              f"is not allowed to read", checked_at=now)
        return Health(True, f"{_pretty(path)} is readable", checked_at=now)

    async def read(self, source, *, since: datetime | None = None,
                   limit: int = MAX_FILES) -> list[Item]:
        """Every readable text file, newest first — optionally only what changed.

        `since` is what makes this cheap to run often: a folder of a thousand
        files that has not been touched returns nothing rather than everything.
        """
        return await self._walk(source, limit=limit, since=since)

    async def search(self, source, query: str, *, limit: int = 25) -> list[Item]:
        """Files whose NAME or CONTENT contains the query.

        Content is searched, not just names, because "the file about the thesis
        deadline" is a thing a person asks for and a filename search cannot
        answer. The bound is the same; a search that read more than a read does
        would be a way around the limit.
        """
        needle = (query or "").strip().lower()
        if not needle:
            return []
        hits = await self._walk(source, limit=MAX_FILES, since=None)
        scored = []
        for item in hits:
            name = os.path.basename(item.item_id).lower()
            body = item.body.text.lower()
            if needle in name:
                scored.append((2.0, item))
            elif needle in body:
                scored.append((1.0, item))
        scored.sort(key=lambda pair: -pair[0])
        return [item for _, item in scored[:limit]]

    async def _walk(self, source, *, limit: int, since: datetime | None) -> list[Item]:
        root = os.path.realpath(os.path.expanduser(source.location))
        blocked = await _blocked_roots()
        cutoff = since.timestamp() if since else None
        found: list[tuple[float, Item]] = []

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            depth = dirpath[len(root):].count(os.sep)
            if depth >= MAX_DEPTH:
                dirnames[:] = []
                continue
            # Pruned in place, so a skipped directory is never descended into
            # rather than walked and then discarded.
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d not in SKIP_DIRS
                           and not _blocked(os.path.join(dirpath, d), blocked)]
            for name in filenames:
                if name.startswith(".") or len(found) >= limit * 4:
                    continue
                full = os.path.join(dirpath, name)
                if os.path.splitext(name)[1].lower() not in TEXT_SUFFIXES:
                    continue
                real = os.path.realpath(full)
                if _blocked(real, blocked):
                    continue
                try:
                    stat = os.stat(real)
                except OSError:
                    continue
                if cutoff is not None and stat.st_mtime <= cutoff:
                    continue
                text = _read_text(real)
                if text is None:
                    continue
                at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                found.append((stat.st_mtime, Item(
                    item_id=real, title=name, at=at,
                    link=f"file://{real}",
                    body=Untrusted(text=text, source=f"file:{_pretty(real)}", label=name),
                    meta={"bytes": stat.st_size, "folder": _pretty(os.path.dirname(real))})))

        found.sort(key=lambda pair: -pair[0])
        return [item for _, item in found[:limit]]


def _read_text(path: str) -> str | None:
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_BYTES)
    except OSError:
        return None
    if b"\0" in raw[:1024]:
        return None                       # a binary file with a text suffix
    return raw.decode("utf-8", "replace")


def _pretty(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _blocked(path: str, blocked: list[str]) -> bool:
    real = os.path.realpath(path)
    return any(_under(real, root) for root in blocked)


async def _blocked_roots() -> list[str]:
    """The folders ARIES may not read — the SAME list file search uses.

    Read through `aries.shell.search`'s helper rather than reimplemented. Two
    sets of privacy rules would disagree eventually, and the one that disagreed
    quietly would be the newer one.

    IT FAILS CLOSED. The first version answered `[]` when the settings read
    raised — so a database hiccup would have quietly removed every exclusion and
    ARIES would have walked into `~/.ssh` with nothing in any log to say why.
    A privacy guard that degrades to "allow everything" under failure is worse
    than no guard, because it looks like one.

    The fallback is the SCHEMA's own default, which is known without a database,
    plus the system paths, which are constants.
    """
    from agentic_core.database.base import async_session

    from aries.settings import SettingsService
    from aries.settings.schema import get_def

    excluded: list = []
    try:
        async with async_session() as db:
            excluded = list(await SettingsService(db).get("privacy.excluded_paths") or [])
    except Exception:                                 # noqa: BLE001
        definition = get_def("privacy.excluded_paths")
        excluded = list(definition.default or []) if definition else []
        logger.warning(
            "could not read privacy.excluded_paths; falling back to the declared "
            "default %s rather than excluding nothing", excluded)
    return _excluded_roots(excluded + list(SYSTEM_PATHS))


# `documents` and `repository` are the same reading with different intent — a
# curated set and a checkout — and they are registered separately so the
# Connections screen can describe each honestly rather than lumping them.
FILES = register(FilesConnector())
DOCUMENTS = register(FilesConnector(source_type="documents"))
REPOSITORY = register(FilesConnector(source_type="repository"))
