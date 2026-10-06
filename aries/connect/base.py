"""What a connector is — the boundary between ARIES and everything outside it.

ONE BOUNDARY, SO THERE IS ONE PLACE TO BE CAREFUL
-------------------------------------------------
`aries/sources/` already declares *what kinds of source exist* and refuses to
pretend one works when nothing can read it (`needs_connector`). This is the
other half: the thing that actually reads one.

The separation is deliberate and predates this file — a user can register an
RSS feed whether or not the News Radar exists, and the registry describes
sources long before anything can read them. A connector arrives per type,
later, without the registry changing.

WHAT EVERY CONNECTOR OWES
-------------------------
    capabilities()   what it can do, honestly — a connector that cannot search
                     says so rather than searching badly
    check()          can it reach the source RIGHT NOW, measured, with the
                     reason when it cannot
    read()           items since a point in time
    search()         items matching a query, when capable

And one rule that is not a method: **everything a connector returns carries
`Untrusted` content**. Not a string. The type is the reminder, and a test
enforces it — a connector that returned plain text would let a mail body reach
somewhere that treats text as instructions.

WHAT A CONNECTOR MAY NOT DO
---------------------------
Write anything, anywhere, to the source. v0.1 is read-only across every
connector, and that is enforced by the protocol having no write method rather
than by everyone remembering. Sending mail, creating events and pushing commits
are a separate capability with a separate approval path, and none of them is
implied by connecting a source — §21, and the source registry already says so
in the email type's own description.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from aries.connect.untrusted import Untrusted


@dataclass(frozen=True)
class Item:
    """One thing read from a source.

    `body` is `Untrusted`, always. That is the whole point of the type: a
    function that takes a `str` will happily accept a mail body, and a function
    that takes `Untrusted` has said in its signature that it knows what it is
    holding.
    """

    item_id: str
    title: str
    body: Untrusted
    at: datetime | None = None
    author: str = ""
    link: str = ""
    meta: dict = field(default_factory=dict)

    def as_dict(self, *, include_body: bool = False) -> dict:
        return {"item_id": self.item_id, "title": self.title, "author": self.author,
                "link": self.link, "at": self.at.isoformat() if self.at else None,
                "meta": self.meta, **self.body.as_dict(include_text=include_body)}


@dataclass(frozen=True)
class Health:
    """Can ARIES reach this source, and if not, why not — in a sentence a person
    can act on. `"authentication failed"` and `"no network"` need different
    things from the user, so they must not arrive as one `False`."""

    reachable: bool
    detail: str
    needs_credential: bool = False
    checked_at: datetime | None = None

    def as_dict(self) -> dict:
        return {"reachable": self.reachable, "detail": self.detail,
                "needs_credential": self.needs_credential,
                "checked_at": self.checked_at.isoformat() if self.checked_at else None}


@runtime_checkable
class Connector(Protocol):
    """Read-only access to one kind of source. No write method, by design."""

    source_type: str
    outbound: bool

    def capabilities(self) -> tuple[str, ...]: ...

    async def check(self, source) -> Health: ...

    async def read(self, source, *, since: datetime | None = None,
                   limit: int = 50) -> list[Item]: ...

    async def search(self, source, query: str, *, limit: int = 25) -> list[Item]: ...


_CONNECTORS: dict[str, Connector] = {}


def register(connector: Connector, *, replace: bool = False) -> Connector:
    """Make a source type usable. This is the only thing that flips a type from
    'not built yet' to available on the Connections screen, which is why that
    screen cannot lie about what exists."""
    name = connector.source_type
    if name in _CONNECTORS and not replace:
        raise ValueError(f"a connector for '{name}' is already registered")
    _CONNECTORS[name] = connector
    return connector


def get(source_type: str) -> Connector | None:
    return _CONNECTORS.get(source_type)


def all_connectors() -> dict[str, Connector]:
    return dict(_CONNECTORS)


def have(source_type: str) -> bool:
    return source_type in _CONNECTORS


def describe_all() -> list[dict]:
    return [{"source_type": name, "outbound": c.outbound,
             "capabilities": list(c.capabilities())}
            for name, c in sorted(_CONNECTORS.items())]
