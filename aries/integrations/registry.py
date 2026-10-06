"""What ARIES can connect to — and, honestly, what it cannot yet.

§23 asks for a Connections screen. The requirement attached to it is the
important part: *do not fake integrations that are not implemented*, and
distinguish clearly between CONNECTED, AVAILABLE and NOT IMPLEMENTED.

That distinction is derived, never declared. An integration's status is computed
from things that are actually true:

    NOT IMPLEMENTED   the source type needs a connector and none exists
                      (`SourceType.needs_connector`) — ARIES can describe it and
                      cannot use it
    AVAILABLE         the machinery works and nothing is configured yet
    CONNECTED         at least one enabled source of that kind exists, and its
                      real health is reported

So a screen cannot drift out of step with reality: adding an email connector
makes the Email card change state without this file being touched, and nothing
here can claim a capability that does not exist.

The permissions listed per integration are the ones ARIES actually enforces
today — the read-only reach of a source, not an aspirational list of scopes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

CONNECTED = "connected"
AVAILABLE = "available"
NOT_IMPLEMENTED = "not_implemented"


@dataclass
class Integration:
    """One thing ARIES can (or cannot yet) connect to."""

    id: str
    name: str
    description: str
    category: str                       # information | development | personal | system
    source_type: str | None = None      # the Sources Registry type it maps to, if any
    spec_section: str = ""              # where the specification asks for it
    permissions: list[str] = field(default_factory=list)
    requires_credentials: bool = False
    blocked_by: str = ""                # why it is not implemented, when it is not

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description,
                "category": self.category, "source_type": self.source_type,
                "spec_section": self.spec_section, "permissions": self.permissions,
                "requires_credentials": self.requires_credentials,
                "blocked_by": self.blocked_by or None}


INTEGRATIONS: tuple[Integration, ...] = (
    Integration("rss", "RSS and Atom feeds",
                "Follow publications through their feeds. The News Radar reads these.",
                "information", source_type="rss", spec_section="§24",
                permissions=["read"]),
    Integration("website", "Websites",
                "Read a page when no feed is offered. Slower and more fragile than a feed.",
                "information", source_type="website", spec_section="§24",
                permissions=["read", "search"]),
    Integration("directory", "Local folders",
                "Read a folder on this machine. Never leaves the machine.",
                "personal", source_type="directory", spec_section="§24",
                permissions=["read", "search"]),
    Integration("documents", "Document collections",
                "A curated set of documents — papers, notes, manuals.",
                "personal", source_type="documents", spec_section="§24",
                permissions=["read", "search"]),
    Integration("repository", "Code repositories",
                "Inspect a local checkout: commits, branches, TODOs, test state.",
                "development", source_type="repository", spec_section="§13/05",
                permissions=["read", "search"]),
    Integration("api", "HTTP APIs",
                "Query a JSON endpoint. Usually needs a credential.",
                "information", source_type="api", spec_section="§24",
                permissions=["read", "search"], requires_credentials=True),
    Integration("email", "Email",
                "Read important mail, summarise threads, find action items. Sending is a "
                "separate permission and is never implied by connecting.",
                "personal", source_type="email", spec_section="§21",
                permissions=["read", "search", "draft"], requires_credentials=True),
    Integration("calendar", "Calendar",
                "Read upcoming events and deadlines for the daily plan.",
                "personal", source_type="calendar", spec_section="§22",
                permissions=["read", "availability"], requires_credentials=True),
    Integration("database", "Databases",
                "Query a database read-only.",
                "development", source_type="database", spec_section="§24",
                permissions=["read"], requires_credentials=True),
    Integration("github", "GitHub",
                "Repositories, issues and releases.",
                "development", source_type=None, spec_section="§23",
                permissions=["read"], requires_credentials=True,
                blocked_by="no GitHub connector exists yet; a repository can be followed as a "
                           "local checkout or its releases as an RSS feed in the meantime"),
    Integration("docker", "Docker",
                "Container and image state for the system view.",
                "system", source_type=None, spec_section="§23",
                permissions=["read"],
                blocked_by="no Docker connector exists yet, and Docker is not installed on "
                           "this machine"),
    Integration("ssh", "SSH hosts",
                "Inspect and maintain other machines.",
                "system", source_type=None, spec_section="§23",
                permissions=["read"], requires_credentials=True,
                blocked_by="ARIES only manages this machine; a remote connector is §5 of the "
                           "engine's migration guide and is not built"),
)

_BY_ID = {i.id: i for i in INTEGRATIONS}


def get(integration_id: str) -> Integration | None:
    return _BY_ID.get(integration_id)


async def status(db: AsyncSession) -> list[dict]:
    """Every integration, with a status derived from what is actually true."""
    from aries.connect import base as connectors
    from aries.sources import service as src
    from aries.sources import types as stypes

    rows = await src.list_sources(db)
    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r.type, []).append(r)

    out = []
    for integ in INTEGRATIONS:
        entry = integ.as_dict()
        stype = stypes.get(integ.source_type) if integ.source_type else None

        # `needs_connector` says a type CANNOT work without one; whether one
        # exists is asked of the connector registry, not of the declaration.
        # Deriving it from the static flag meant the screen went on saying
        # "not built yet" about email the day the email connector landed —
        # which is the same kind of lie as claiming a capability that does not
        # exist, told in the other direction.
        missing = bool(stype and stype.needs_connector and not connectors.have(stype.name))
        unreadable = bool(stype and not connectors.have(stype.name))
        if integ.blocked_by or stype is None or missing:
            entry["status"] = NOT_IMPLEMENTED
            entry["detail"] = (integ.blocked_by
                               or (f"the {integ.source_type} source type is declared but has no "
                                   f"connector yet, so ARIES can describe it and not use it"))
            entry["sources"] = []
        else:
            mine = by_type.get(integ.source_type, [])
            enabled = [r for r in mine if r.enabled]
            entry["status"] = CONNECTED if enabled else AVAILABLE
            entry["detail"] = (f"{len(enabled)} connected" if enabled
                               else "nothing connected yet")
            if unreadable:
                # Registerable but not readable: an RSS feed can be added and
                # the News Radar reads it through its own path, not a connector.
                # Saying so is better than implying a connector exists.
                entry["detail"] += " · read by the News Radar, not by a connector"
            entry["readable"] = not unreadable
            entry["capabilities_now"] = (list(connectors.get(stype.name).capabilities())
                                         if connectors.have(stype.name) else [])
            entry["sources"] = [{"source_id": r.source_id, "name": r.name,
                                 "enabled": r.enabled, "health": r.health(),
                                 "last_sync": r.last_sync_at.isoformat() if r.last_sync_at else None,
                                 "last_error": r.last_error,
                                 "location": r.location}
                                for r in mine]
        entry["outbound"] = bool(stype.outbound) if stype else True
        out.append(entry)
    return out


async def summary(db: AsyncSession) -> dict:
    rows = await status(db)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"integrations": rows, "counts": counts,
            "means": {"connected": "configured and in use",
                      "available": "ARIES can do this; nothing is configured yet",
                      "not_implemented": "ARIES cannot do this yet, and says so rather than "
                                         "showing an empty screen"}}
