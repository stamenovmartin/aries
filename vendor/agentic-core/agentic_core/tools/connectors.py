"""Capability-declaring connectors — the marketing `connectors/` layer,
generalised. Lifted from backend/app/connectors/{base,capabilities,schema,
registry,mock}.py.

A Connector is an adapter to one external system. It DECLARES what it can do
(`capabilities()` read from real config, never assumed), raises NotSupported
for anything else instead of faking success, and every write-type method
defaults to the safe variant (paused/unpublished/dry-run). The registry maps a
target name to a connector; adding a connector is adding one rule.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

from agentic_core.tools.base import NotSupported


@dataclass(frozen=True)
class Capabilities:
    read: bool = False
    write: bool = False
    execute: bool = False
    metrics: bool = False
    listen: bool = False
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ActionRequest:
    """One request to a connector, in the core's vocabulary."""
    target: str
    action: str
    payload: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


@dataclass
class ActionResult:
    success: bool
    external_id: str | None = None
    external_url: str | None = None
    details: str = ""
    skipped: bool = False
    uncertain: bool = False

    @classmethod
    def of(cls, raw: dict) -> "ActionResult":
        return cls(success=bool(raw.get("success")), external_id=raw.get("external_id"),
                   external_url=raw.get("external_url"), details=str(raw.get("details") or ""),
                   skipped=bool(raw.get("skipped")), uncertain=bool(raw.get("uncertain")))

    def as_dict(self) -> dict:
        return asdict(self)


class Connector(ABC):
    name: str = "—"

    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    async def read(self, req: ActionRequest) -> dict:
        raise NotSupported(self.name, "read")

    async def write(self, req: ActionRequest, *, dry_run: bool = True) -> ActionResult:
        raise NotSupported(self.name, "write")

    async def execute(self, req: ActionRequest, *, dry_run: bool = True) -> ActionResult:
        raise NotSupported(self.name, "execute")

    async def fetch_metrics(self, external_id: str) -> list[dict]:
        raise NotSupported(self.name, "metrics")

    async def listen(self) -> list[dict]:
        raise NotSupported(self.name, "listen")


class MockConnector(Connector):
    """Touches nothing — proves the core does not depend on any real system."""
    name = "mock"

    def capabilities(self) -> Capabilities:
        return Capabilities(read=True, write=True, execute=True, metrics=True)

    async def read(self, req):
        return {"target": req.target, "mock": True, "state": "ok"}

    async def write(self, req, *, dry_run=True):
        return ActionResult(success=True, external_id="mock_123", details=("[DRY RUN] " if dry_run else "") + "[MOCK] nothing really happened")

    async def execute(self, req, *, dry_run=True):
        return ActionResult(success=True, external_id="mock_exec", details=("[DRY RUN] " if dry_run else "") + "[MOCK] executed")

    async def fetch_metrics(self, external_id):
        return [{"metric": "latency_ms", "value": 12.0, "entity_id": external_id}]


_RULES: list[tuple[str, type]] = []


def register_connector(match: str, cls: type) -> None:
    """`match` is a lowercase substring of the target name."""
    _RULES.append((match.lower(), cls))


def connector_for(target: str) -> Connector | None:
    n = (target or "").lower()
    for match, cls in _RULES:
        if match in n:
            return cls()
    return None


def all_capabilities() -> list[dict]:
    return [{"match": m, "connector": cls.__name__, "capabilities": cls().capabilities().as_dict()} for m, cls in _RULES]


register_connector("mock", MockConnector)
