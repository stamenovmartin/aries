"""ARIES as part of the environment: status, lifecycle, and honest degradation.

The status derivation is what these mostly test, because it is the part that
must work when everything else does not — `aries status` is asked most urgently
when ARIES is broken, so it cannot depend on ARIES being healthy.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-runtime")

import httpx  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.runtime import status as rt  # noqa: E402
from aries.runtime import systemd  # noqa: E402
from aries.settings import SettingsService  # noqa: E402

from aries.api.app import app  # noqa: E402


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class _Unit(systemd.UnitState):
    pass


def _unit(**kw) -> systemd.UnitState:
    base = dict(name="aries-core.service", loaded=True, active="active", sub="running",
                enabled="enabled", since="", pid=123, restarts=0, result="success")
    base.update(kw)
    return systemd.UnitState(**base)


def _patch(monkey: dict):
    """Swap systemd's view for a constructed one. Restored by the caller."""
    original = {k: getattr(systemd, k) for k in monkey}
    for k, v in monkey.items():
        setattr(systemd, k, v)
    return original


def _restore(original):
    for k, v in original.items():
        setattr(systemd, k, v)


# ── the four states ─────────────────────────────────────────────────────────

async def test_stopped_when_not_installed():
    orig = _patch({
        "state": lambda: systemd.Systemd(available=True, units={}),
        "installed": lambda: False,
    })
    try:
        s = rt.describe(probe_api=False)
        check("not installed reads as STOPPED", s.state == rt.STOPPED)
        check("and says how to install it", "aries-service install" in s.summary)
        check("and reports itself as not installed", s.installed is False)
    finally:
        _restore(orig)


async def test_stopped_when_the_unit_is_inactive():
    orig = _patch({
        "state": lambda: systemd.Systemd(available=True, units={
            systemd.CORE: _unit(active="inactive", sub="dead"),
            systemd.TARGET: _unit(name=systemd.TARGET, active="inactive", sub="dead")}),
        "installed": lambda: True,
    })
    try:
        s = rt.describe(probe_api=False)
        check("an inactive unit is STOPPED", s.state == rt.STOPPED)
        check("and the meaning says no automation will fire",
              "no automation will fire" in rt.MEANING[s.state])
    finally:
        _restore(orig)


async def test_a_failed_unit_explains_itself():
    orig = _patch({
        "state": lambda: systemd.Systemd(available=True, units={
            systemd.CORE: _unit(active="failed", sub="failed", result="start-limit-hit"),
            systemd.TARGET: _unit(name=systemd.TARGET)}),
        "installed": lambda: True,
    })
    try:
        s = rt.describe(probe_api=False)
        check("a failed unit is STOPPED", s.state == rt.STOPPED)
        check("and start-limit-hit is explained in words, not jargon",
              "failed repeatedly" in s.summary)
        check("pointing at the logs", "--logs" in s.summary)
    finally:
        _restore(orig)


async def test_starting_while_coming_up():
    orig = _patch({
        "state": lambda: systemd.Systemd(available=True, units={
            systemd.CORE: _unit(active="activating", sub="start"),
            systemd.TARGET: _unit(name=systemd.TARGET)}),
        "installed": lambda: True,
    })
    try:
        s = rt.describe(base="http://127.0.0.1:1", timeout=0.2)
        check("a unit coming up is STARTING", s.state == rt.STARTING)
        check("and the api is reported as not answering",
              any(c.name == "api" and not c.ok for c in s.components))
    finally:
        _restore(orig)


async def test_alive_but_wedged_is_degraded_not_starting():
    """A unit up for a while that still will not answer must not sit in STARTING
    forever — that would make STARTING a place ARIES can live."""
    orig = _patch({
        "state": lambda: systemd.Systemd(available=True, units={
            systemd.CORE: _unit(since="Sat 2020-01-01 00:00:00 CET"),
            systemd.TARGET: _unit(name=systemd.TARGET)}),
        "installed": lambda: True,
    })
    try:
        s = rt.describe(base="http://127.0.0.1:1", timeout=0.2)
        check("an old unit that will not answer is DEGRADED", s.state == rt.DEGRADED)
        check("and says the process is alive but not answering",
              "alive" in s.summary and "not answering" in s.summary)
    finally:
        _restore(orig)


async def test_running_when_everything_is_alive():
    snapshot = {
        "database": {"ok": True, "detail": "answering"},
        "workers": [{"name": "scheduler", "alive": True, "enabled": True, "state": "running"},
                    {"name": "triggers", "alive": True, "enabled": True, "state": "running"}],
        "automations": [{"automation_id": "aries.health", "name": "System Health",
                         "last_summary": "healthy",
                         "breaker": {"state": "closed", "means": "running normally"}}],
    }
    orig = _patch({
        "state": lambda: systemd.Systemd(available=True, units={
            systemd.CORE: _unit(), systemd.TARGET: _unit(name=systemd.TARGET)}),
        "installed": lambda: True,
    })
    real_probe = rt._api_snapshot
    rt._api_snapshot = lambda base, timeout: snapshot
    try:
        s = rt.describe()
        check("everything alive reads as RUNNING", s.state == rt.RUNNING)
        check("and the summary counts what is running", "2 workers alive" in s.summary)
        check("with a component per worker, automation and the database",
              len(s.components) == 5)
        check("and no problems", s.problems == [])
    finally:
        rt._api_snapshot = real_probe
        _restore(orig)


async def test_degraded_when_a_worker_is_dead():
    snapshot = {
        "database": {"ok": True, "detail": "answering"},
        "workers": [{"name": "scheduler", "alive": True, "enabled": True, "state": "running"},
                    {"name": "aries.automations", "alive": False, "enabled": True,
                     "state": "crashed", "error": "RuntimeError: boom"}],
        "automations": [],
    }
    orig = _patch({
        "state": lambda: systemd.Systemd(available=True, units={
            systemd.CORE: _unit(), systemd.TARGET: _unit(name=systemd.TARGET)}),
        "installed": lambda: True,
    })
    real = rt._api_snapshot
    rt._api_snapshot = lambda base, timeout: snapshot
    try:
        s = rt.describe()
        check("a dead worker makes ARIES DEGRADED, not RUNNING", s.state == rt.DEGRADED)
        check("the failing component is named", "aries.automations" in s.summary)
        check("and its error is carried", any("boom" in c.detail for c in s.problems))
    finally:
        rt._api_snapshot = real
        _restore(orig)


async def test_degraded_when_an_automation_breaker_is_open():
    snapshot = {
        "database": {"ok": True, "detail": "answering"},
        "workers": [{"name": "scheduler", "alive": True, "enabled": True, "state": "running"}],
        "automations": [{"automation_id": "aries.news", "name": "News Radar",
                         "breaker": {"state": "open", "means": "paused after repeated failures"}}],
    }
    orig = _patch({
        "state": lambda: systemd.Systemd(available=True, units={
            systemd.CORE: _unit(), systemd.TARGET: _unit(name=systemd.TARGET)}),
        "installed": lambda: True,
    })
    real = rt._api_snapshot
    rt._api_snapshot = lambda base, timeout: snapshot
    try:
        s = rt.describe()
        check("a paused automation makes ARIES DEGRADED", s.state == rt.DEGRADED)
        check("because a process that cannot do its work is not 'running'",
              any(c.kind == "automation" and not c.ok for c in s.components))
    finally:
        rt._api_snapshot = real
        _restore(orig)


async def test_a_switched_off_worker_is_not_a_fault():
    snapshot = {
        "database": {"ok": True, "detail": "answering"},
        "workers": [{"name": "autopilot", "alive": False, "enabled": False, "state": "running"}],
        "automations": [],
    }
    orig = _patch({
        "state": lambda: systemd.Systemd(available=True, units={
            systemd.CORE: _unit(), systemd.TARGET: _unit(name=systemd.TARGET)}),
        "installed": lambda: True,
    })
    real = rt._api_snapshot
    rt._api_snapshot = lambda base, timeout: snapshot
    try:
        s = rt.describe()
        check("a worker the user switched off is not a failure", s.state == rt.RUNNING)
        check("and says so rather than looking broken",
              any("switched off" in c.detail for c in s.components))
    finally:
        rt._api_snapshot = real
        _restore(orig)


async def test_status_works_without_a_systemd_session():
    """In a container or over bare SSH there is no user manager. The answer must
    still be an answer."""
    orig = _patch({
        "state": lambda: systemd.Systemd(available=False, reason="no XDG_RUNTIME_DIR"),
        "installed": lambda: False,
    })
    try:
        s = rt.describe(probe_api=False)
        check("no session still produces a state", s.state == rt.STOPPED)
        check("with the reason", "XDG_RUNTIME_DIR" in s.summary)
    finally:
        _restore(orig)


async def test_running_without_systemd_when_the_api_answers():
    """Started by hand rather than by systemd is still running."""
    snapshot = {"database": {"ok": True, "detail": "answering"},
                "workers": [{"name": "scheduler", "alive": True, "enabled": True,
                             "state": "running"}],
                "automations": []}
    orig = _patch({
        "state": lambda: systemd.Systemd(available=False, reason="no user session"),
        "installed": lambda: False,
    })
    real = rt._api_snapshot
    rt._api_snapshot = lambda base, timeout: snapshot
    try:
        s = rt.describe()
        check("an ARIES started by hand reads as RUNNING", s.state == rt.RUNNING)
        check("and says it is not managed by systemd", "not managed by systemd" in s.summary)
    finally:
        rt._api_snapshot = real
        _restore(orig)


# ── the API surface the status and the UI both use ──────────────────────────

async def test_the_components_endpoint_reports_everything():
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set("health.enabled", True, set_by="user")
    async with await _client() as c:
        r = await c.get("/api/aries/runtime/components")
    body = r.json()
    check("the components endpoint answers", r.status_code == 200)
    check("it reports the database", body["database"]["ok"] is True)
    check("it reports workers", isinstance(body["workers"], list))
    check("it reports the process id", isinstance(body["pid"], int))
    check("and when the process started", bool(body["started_at"]))
    check("enabled automations carry their breaker state",
          all("breaker" in a for a in body["automations"]))


async def test_the_runtime_endpoint_agrees_with_the_cli():
    """One derivation, two surfaces — or they drift, which is the engine's rule."""
    await reset_db()
    async with await _client() as c:
        r = await c.get("/api/aries/runtime")
    body = r.json()
    check("the runtime endpoint answers", r.status_code == 200)
    check("with one of the four states", body["state"] in
          (rt.RUNNING, rt.DEGRADED, rt.STOPPED, rt.STARTING))
    check("and what that state means", bool(body["means"]))
    check("it never claims to be unreachable from inside itself",
          body["api_reachable"] is True)
    check("and carries the same component shape the CLI renders",
          all({"name", "kind", "ok", "detail", "severity"} <= set(c)
              for c in body["components"]))


async def test_the_units_are_shipped_and_coherent():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(root, "systemd", "aries.target")
    core = os.path.join(root, "systemd", "aries-core.service")
    check("aries.target ships", os.path.exists(target))
    check("aries-core.service ships", os.path.exists(core))

    target_text = open(target).read()
    core_text = open(core).read()
    check("the target is wanted by the login session", "WantedBy=default.target" in target_text)
    check("the service is pulled in by the target", "WantedBy=aries.target" in core_text)
    check("stopping the target stops the service", "PartOf=aries.target" in core_text)
    check("a crash is restarted", "Restart=on-failure" in core_text)
    check("but never in a loop", "StartLimitBurst" in core_text
          and "StartLimitIntervalSec" in core_text)
    check("the start limit is in [Unit], where systemd reads it",
          core_text.index("StartLimitBurst") < core_text.index("[Service]"))
    check("shutdown is graceful", "KillSignal=SIGINT" in core_text)
    check("paths are absolute, since a service has no cwd assumptions",
          "%h/aries/.venv/bin/python" in core_text)
    check("it does not wait for the network, which ARIES tolerates losing",
          "network-online.target" not in core_text)
    check("PATH is pinned, so aries-ui resolves even before the session imports its own",
          "Environment=PATH=%h/.local/bin:" in core_text)


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
