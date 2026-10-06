"""The one question: is ARIES running?

Four answers, and each is DERIVED rather than declared:

    STOPPED    the service is not running
    STARTING   the service is coming up, or is up but not answering yet
    RUNNING    the service is up, answering, and every enabled component is alive
    DEGRADED   it is up and something inside it is not working

DEGRADED is the one that earns its place. A process that is alive while its news
dispatcher has crashed, or while an automation's circuit breaker is open, is not
"running" in any sense the user cares about — and reporting it as running is the
same dishonesty as reporting `0` for "unknown". Everything that can make ARIES
partly useless is folded in: a dead worker, an open breaker, a database that does
not answer, a source that has failed repeatedly.

WHY THIS MUST WORK WITH ARIES STOPPED
-------------------------------------
`aries status` is asked most urgently when something is wrong, so it cannot need
the thing it is reporting on. Status is assembled in layers, each optional:

    systemd      always available on a user session; works when nothing runs
    the API      adds component health; absent means "not answering", which is
                 itself an answer
    the database not touched here — the running service owns it

So the command answers when the service is dead, when it is starting, when it is
wedged, and when it is fine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from aries.runtime import systemd

RUNNING, DEGRADED, STOPPED, STARTING = "RUNNING", "DEGRADED", "STOPPED", "STARTING"

MEANING = {
    RUNNING: "ARIES is running and everything inside it is working",
    DEGRADED: "ARIES is running, but something inside it is not working",
    STOPPED: "ARIES is not running — no automation will fire",
    STARTING: "ARIES is coming up",
}


@dataclass
class Component:
    """One thing inside ARIES that can be working or not."""

    name: str
    kind: str                         # worker | automation | storage | service
    ok: bool
    detail: str = ""
    severity: str = "ok"              # ok | notice | warning | critical

    def as_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "ok": self.ok,
                "detail": self.detail, "severity": self.severity}


@dataclass
class Status:
    state: str
    summary: str
    components: list[Component] = field(default_factory=list)
    systemd: dict = field(default_factory=dict)
    api_reachable: bool = False
    installed: bool = False
    enabled: bool = False
    checked_at: str = ""

    @property
    def problems(self) -> list[Component]:
        return [c for c in self.components if not c.ok]

    def as_dict(self) -> dict:
        return {"state": self.state, "means": MEANING.get(self.state, ""),
                "summary": self.summary, "installed": self.installed,
                "enabled": self.enabled, "api_reachable": self.api_reachable,
                "components": [c.as_dict() for c in self.components],
                "problems": [c.as_dict() for c in self.problems],
                "systemd": self.systemd, "checked_at": self.checked_at}


def _api_snapshot(base: str, timeout: float) -> dict | None:
    """Ask the running ARIES about itself. None when it is not answering."""
    import json
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/api/aries/runtime/components",
                                    timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def describe(*, base: str = "http://127.0.0.1:8000", timeout: float = 3.0,
             probe_api: bool = True) -> Status:
    """The global status, assembled from whatever is available."""
    sd = systemd.state()
    now = datetime.now().isoformat(timespec="seconds")
    components: list[Component] = []

    core = sd.units.get(systemd.CORE)
    target = sd.units.get(systemd.TARGET)
    is_installed = systemd.installed()
    is_enabled = bool(target and target.enabled == "enabled")

    if not sd.available:
        # No user session to ask. Fall back to whether the API answers: ARIES may
        # well be running, just not under systemd.
        snapshot = _api_snapshot(base, timeout) if probe_api else None
        if snapshot:
            components = _components_from(snapshot)
            state = DEGRADED if any(not c.ok for c in components) else RUNNING
            return Status(state=state,
                          summary=f"answering on {base}, but not managed by systemd "
                                  f"({sd.reason})",
                          components=components, systemd=sd.as_dict(), api_reachable=True,
                          installed=is_installed, enabled=is_enabled, checked_at=now)
        return Status(state=STOPPED, summary=sd.reason or "no systemd user session",
                      systemd=sd.as_dict(), installed=is_installed, enabled=is_enabled,
                      checked_at=now)

    if core is not None:
        components.append(Component(
            "aries-core.service", "service", core.running,
            detail=(f"{core.active}/{core.sub}"
                    + (f" since {core.since}" if core.since else "")
                    + (f" · {core.restarts} restart(s)" if core.restarts else "")
                    + (f" · last result {core.result}" if core.result not in ("", "success") else "")),
            severity="ok" if core.running else ("critical" if core.failed else "notice")))

    if not is_installed:
        return Status(state=STOPPED,
                      summary="ARIES is not installed as a service — "
                              "run ./scripts/aries-service install",
                      components=components, systemd=sd.as_dict(),
                      installed=False, enabled=False, checked_at=now)

    if core is None or core.failed:
        raw = (core.result or "unknown reason") if core else "unit not found"
        detail = {
            "start-limit-hit": ("it failed repeatedly and systemd stopped trying — "
                                "`aries start` will clear that and try again, but check "
                                "`aries status --logs 30` first"),
            "exit-code": "it exited with an error — see `aries status --logs 30`",
            "timeout": "it did not start within the timeout",
            "signal": "it was killed by a signal",
        }.get(raw, raw)
        return Status(state=STOPPED, summary=f"aries-core failed: {detail}",
                      components=components, systemd=sd.as_dict(),
                      installed=True, enabled=is_enabled, checked_at=now)

    if not core.running and not core.starting:
        return Status(state=STOPPED, summary="ARIES is not running",
                      components=components, systemd=sd.as_dict(),
                      installed=True, enabled=is_enabled, checked_at=now)

    snapshot = _api_snapshot(base, timeout) if probe_api else None
    if snapshot is None:
        # Alive but not answering: starting, or wedged. A unit that has been up a
        # while and still will not answer is DEGRADED, not STARTING — otherwise
        # "starting" becomes a state ARIES can sit in indefinitely.
        state = STARTING if core.starting or _young(core) else DEGRADED
        components.append(Component("api", "service", False,
                                    detail=f"not answering on {base}",
                                    severity="notice" if state == STARTING else "critical"))
        return Status(state=state,
                      summary=("coming up" if state == STARTING
                               else f"the process is alive but is not answering on {base}"),
                      components=components, systemd=sd.as_dict(),
                      installed=True, enabled=is_enabled, checked_at=now)

    components.extend(_components_from(snapshot))
    problems = [c for c in components if not c.ok]
    if problems:
        worst = sorted(problems, key=lambda c: {"critical": 0, "warning": 1}.get(c.severity, 2))[0]
        return Status(state=DEGRADED,
                      summary=f"{len(problems)} component(s) not working — {worst.name}: "
                              f"{worst.detail}",
                      components=components, systemd=sd.as_dict(), api_reachable=True,
                      installed=True, enabled=is_enabled, checked_at=now)

    workers = sum(1 for c in components if c.kind == "worker")
    autos = sum(1 for c in components if c.kind == "automation")
    return Status(state=RUNNING,
                  summary=f"{workers} workers alive, {autos} automation(s) enabled",
                  components=components, systemd=sd.as_dict(), api_reachable=True,
                  installed=True, enabled=is_enabled, checked_at=now)


def _young(core: systemd.UnitState, seconds: int = 40) -> bool:
    """Has the unit only just come up? Used to tell STARTING from wedged."""
    if not core.since:
        return True
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S"):
        try:
            started = datetime.strptime(core.since.strip(), fmt)
            return (datetime.now() - started.replace(tzinfo=None)).total_seconds() < seconds
        except ValueError:
            continue
    return True


def _components_from(snapshot: dict) -> list[Component]:
    """Turn the API's own report into components."""
    out: list[Component] = []
    db = snapshot.get("database") or {}
    out.append(Component("database", "storage", bool(db.get("ok")),
                         detail=db.get("detail", ""),
                         severity="ok" if db.get("ok") else "critical"))
    for w in snapshot.get("workers") or []:
        alive = bool(w.get("alive"))
        enabled = bool(w.get("enabled", True))
        out.append(Component(
            w.get("name", "worker"), "worker",
            ok=alive or not enabled,
            detail=(w.get("state", "")
                    + ("" if enabled else " (switched off)")
                    + (f" · {w['error']}" if w.get("error") else "")),
            severity="ok" if (alive or not enabled) else "critical"))
    for a in snapshot.get("automations") or []:
        breaker = a.get("breaker") or {}
        paused = breaker.get("state") in ("open", "half_open")
        out.append(Component(
            a.get("name", a.get("automation_id", "automation")), "automation",
            ok=not paused,
            detail=(breaker.get("means", "") if paused
                    else (a.get("last_summary") or "enabled")),
            severity="warning" if paused else "ok"))
    return out


async def component_snapshot(db) -> dict:
    """What is alive inside this process: workers, enabled automations, database.

    Lived in the `/runtime/components` route until the shell needed it too.
    Moved rather than called over HTTP, because the panel indicator asking the
    API to ask itself is a deadlock on a single-worker server — and moved rather
    than copied, because two answers to "is ARIES healthy?" is exactly the
    divergence the runtime state was built to prevent.

    Deliberately cheap: one database round trip, worker state from memory, and
    it never runs an automation. The question is asked most urgently when
    something is already wrong.
    """
    from sqlalchemy import text

    from agentic_core.scheduler import registry as workers

    from aries.automations import genome
    from aries.automations.breaker import state as breaker_state
    from aries.settings import SettingsService

    try:
        await db.execute(text("SELECT 1"))
        database = {"ok": True, "detail": "answering"}
    except Exception as e:                                  # noqa: BLE001
        database = {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    settings = SettingsService(db)
    automations = []
    for spec in genome.all_automations():
        if not await genome.is_enabled(spec, settings):
            continue
        last = await genome.last_run(db, spec.automation_id)
        automations.append({
            "automation_id": spec.automation_id, "name": spec.name,
            "last_status": last.status if last else None,
            "last_summary": last.summary if last else None,
            "breaker": (await breaker_state(db, spec.automation_id)).as_dict(),
        })

    return {"workers": workers.status(), "automations": automations,
            "database": database}
