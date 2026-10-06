"""What kinds of source exist — specification §24.

A source is a place ARIES may get information from: an RSS feed, a website, an
API, a folder of documents, a repository, a mailbox. §24's requirement is that
"agents should query the Sources Registry instead of hard-coding external
websites", so the registry has to be general enough that adding a kind of source
is data rather than a new branch in every agent.

Each type is declared once, here, and from that declaration we get:

  * how its `location` is shaped and validated  (`location_kind`, `scheme`)
  * whether using it sends anything off the machine (`outbound`)
  * whether it needs a credential                (`requires_credentials`)
  * a sensible default polling interval          (`default_poll_minutes`)
  * what a consumer can do with it               (`capabilities`)
  * the sentence the Settings UI shows           (`description`)

CONCEPT — why `outbound` is a field and not a comment. Whether a source reaches
off this machine is the single most consequential fact about it, and it changes
what ARIES is allowed to do: §32 demands least privilege for anything external,
§21 forbids sending without explicit permission, and privacy mode (§20) exists to
keep work local. Making it a declared property means a consumer can ask "is this
source local?" instead of pattern-matching a URL and getting it wrong. A
`directory` source is not outbound; a `website` source is; and no agent has to
decide that for itself.

CONCEPT — declaration, not inheritance. The obvious design is a base class per
source type with a `fetch()` method. That couples the *description* of a source
to the *code that reads it*, which is wrong here: the registry needs to describe
sources long before anything can read them, and a user must be able to add an RSS
feed whether or not the News Radar exists yet. Reading a source is a separate
concern (the engine's `Connector` pattern), and it can arrive per type, later,
without the registry changing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Trust(IntEnum):
    """How much a source's content is believed. §20's trusted/blocked lists.

    BLOCKED is a value rather than a deletion on purpose: "I never want this
    source" is information worth keeping, and a blocked source that is merely
    deleted comes back the next time something suggests it.
    """

    BLOCKED = 0
    UNTRUSTED = 1
    NORMAL = 2
    TRUSTED = 3

    @property
    def label(self) -> str:
        return self.name.lower()


class Priority(IntEnum):
    """How strongly the user wants this source consulted. Higher wins."""

    LOW = 0
    NORMAL = 1
    HIGH = 2

    @property
    def label(self) -> str:
        return self.name.lower()


TRUST_BY_NAME = {t.label: t for t in Trust}
PRIORITY_BY_NAME = {p.label: p for p in Priority}


@dataclass(frozen=True)
class SourceType:
    """One kind of source."""

    name: str
    title: str
    description: str
    location_kind: str                       # "url" | "path" | "connector"
    outbound: bool                           # does using it leave this machine?
    schemes: tuple[str, ...] = ()            # permitted URL schemes, for location_kind="url"
    default_poll_minutes: int = 120
    requires_credentials: bool = False
    capabilities: tuple[str, ...] = ("read",)   # read · listen · search
    # A source of this type cannot be used until a connector for it exists. The
    # registry still stores it, and says so, rather than pretending it works.
    needs_connector: bool = False
    example: str = ""

    def describe(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description,
                "location_kind": self.location_kind, "outbound": self.outbound,
                "schemes": list(self.schemes), "default_poll_minutes": self.default_poll_minutes,
                "requires_credentials": self.requires_credentials,
                "capabilities": list(self.capabilities), "needs_connector": self.needs_connector,
                "example": self.example}


_TYPES: dict[str, SourceType] = {}


def define(t: SourceType, *, replace: bool = False) -> SourceType:
    if t.name in _TYPES and not replace:
        raise ValueError(f"source type '{t.name}' is already defined")
    _TYPES[t.name] = t
    return t


def get(name: str) -> SourceType | None:
    return _TYPES.get(name)


def require(name: str) -> SourceType:
    t = _TYPES.get(name)
    if t is None:
        raise ValueError(f"unknown source type '{name}' (known: {', '.join(sorted(_TYPES))})")
    return t


def all_types() -> list[SourceType]:
    return [_TYPES[k] for k in sorted(_TYPES)]


def names() -> list[str]:
    return sorted(_TYPES)


# ── the types ARIES ships with (§24's list) ─────────────────────────────────
HTTP = ("http", "https")

define(SourceType(
    "rss", "RSS / Atom feed",
    "A syndication feed. The cheapest and most predictable way to follow a publication.",
    "url", outbound=True, schemes=HTTP, default_poll_minutes=120,
    capabilities=("read",), example="https://example.com/feed.xml"))

define(SourceType(
    "website", "Website",
    "A page or site ARIES may read when a feed is not offered. Slower and more fragile "
    "than a feed, so prefer RSS where both exist.",
    "url", outbound=True, schemes=HTTP, default_poll_minutes=360,
    capabilities=("read", "search"), example="https://example.com/news"))

define(SourceType(
    "api", "HTTP API",
    "A JSON endpoint ARIES may query. Usually needs a credential.",
    "url", outbound=True, schemes=HTTP, default_poll_minutes=60,
    requires_credentials=True, capabilities=("read", "search"),
    example="https://api.example.com/v1/items"))

define(SourceType(
    "directory", "Local folder",
    "A folder on this machine that ARIES may read. Never leaves the machine.",
    "path", outbound=False, default_poll_minutes=30,
    capabilities=("read", "search"), example="~/Documents/research"))

define(SourceType(
    "documents", "Document collection",
    "A curated set of documents to draw on — papers, notes, manuals. Local.",
    "path", outbound=False, default_poll_minutes=720,
    capabilities=("read", "search"), example="~/Zotero/storage"))

define(SourceType(
    "repository", "Code repository",
    "A local checkout ARIES may inspect: commits, branches, TODOs, test state.",
    "path", outbound=False, default_poll_minutes=60,
    capabilities=("read", "search"), example="~/projects/aries"))

define(SourceType(
    "database", "Database",
    "A database ARIES may query read-only.",
    "connector", outbound=True, requires_credentials=True,
    default_poll_minutes=360, capabilities=("read", "search"),
    needs_connector=True, example="postgres://host/db"))

define(SourceType(
    "email", "Email account",
    "A mailbox, once connected through the Integrations screen (§21). Reading is "
    "separate from sending, and sending is never implied by adding the source.",
    "connector", outbound=True, requires_credentials=True,
    default_poll_minutes=15, capabilities=("read", "search", "listen"),
    needs_connector=True, example="gmail:me@example.com"))

define(SourceType(
    "calendar", "Calendar",
    "A calendar ARIES may read for deadlines and availability (§22).",
    "connector", outbound=True, requires_credentials=True,
    default_poll_minutes=30, capabilities=("read",),
    needs_connector=True, example="google:primary"))
