"""Background Mode, against the real machine, over real elapsed time.

Not part of `scripts/test.sh` — it takes minutes and it changes the display
timeout of the machine it runs on (and puts it back). Run it deliberately:

    ./scripts/test-background-mode.sh [minutes]

WHAT THIS CAN AND CANNOT PROVE
------------------------------
It would be easy to write a test that passes for the wrong reason here, so the
limits are stated rather than glossed:

**Proved directly.** That ARIES takes a `sleep`/`block` inhibitor and that
*logind itself* lists it; that the display timeout is applied and exactly
restored; that ARIES keeps running and automations actually fire across the
interval; that the machine did not suspend during it; and that everything is
released when Background Mode is switched off.

**Not proved by waiting.** That the inhibitor *prevented* a suspend. On this
machine `sleep-inactive-ac-type` is `nothing`, so on mains power GNOME was never
going to suspend anyway — waiting an hour and finding the machine awake would
demonstrate nothing about the inhibitor. Asserting otherwise would be a test
passing for the wrong reason.

What stands in for it is the mechanism: logind's documented contract is that a
`block` inhibitor on `sleep` causes a non-interactive suspend request to fail,
and the test asserts that ARIES holds exactly that, as logind reports it. The
suspend itself is deliberately never triggered — suspending the user's machine
to prove a point is not an acceptable test.

**Suspend detection.** Wall-clock and monotonic time advance together while
awake; across a suspend, wall-clock jumps ahead of monotonic. The test compares
them, and also reads the journal for logind's own sleep messages.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor", "agentic-core"))
sys.path.insert(0, os.path.join(ROOT, "vendor"))

os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{ROOT}/var/aries.db")
os.environ.setdefault("DATA_DIR", f"{ROOT}/var")

import asyncio  # noqa: E402

_ok = True


def check(label, condition, detail=""):
    global _ok
    print(("PASS  " if condition else "FAIL  ") + label + (f"   {detail}" if detail else ""),
          flush=True)
    _ok = _ok and bool(condition)


def note(text):
    print(f"      {text}", flush=True)


def api(method, path, body=None):
    import urllib.error
    import urllib.request
    url = f"http://127.0.0.1:8000{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def suspended_since(marker: datetime) -> list[str]:
    """logind's own record of any sleep since the marker."""
    try:
        out = subprocess.run(
            ["journalctl", "--user-unit=aries-core.service", "--since",
             marker.strftime("%Y-%m-%d %H:%M:%S"), "--no-pager"],
            capture_output=True, text=True, timeout=20, check=False).stdout
    except (subprocess.TimeoutExpired, OSError):
        out = ""
    system = ""
    try:
        system = subprocess.run(
            ["journalctl", "--since", marker.strftime("%Y-%m-%d %H:%M:%S"),
             "--no-pager", "-g", "Entering sleep state|Suspending system|PM: suspend"],
            capture_output=True, text=True, timeout=20, check=False).stdout
    except (subprocess.TimeoutExpired, OSError):
        pass
    return [l for l in (out + system).splitlines()
            if "sleep state" in l.lower() or "suspending system" in l.lower()]


def main(minutes: float) -> int:
    print(f"\n=== Background Mode, {minutes:g} minute run ===\n", flush=True)

    # ── 0. ARIES must already be running as a service ───────────────────────
    try:
        runtime = api("GET", "/api/aries/runtime")
    except Exception as e:                                  # noqa: BLE001
        print(f"ARIES is not answering ({e}). Start it first: aries start")
        return 2
    check("ARIES is running before the test begins", runtime["state"] in ("RUNNING", "DEGRADED"),
          runtime["summary"])

    before = api("GET", "/api/aries/power")
    original_idle = before["display"]["off_after_seconds"]
    supplies = []
    try:
        supplies = sorted(os.listdir("/sys/class/power_supply"))
    except OSError:
        pass
    note(f"power supplies: {supplies or 'none — this machine has no battery, so the AC '
                                        'policy is the only one that ever applies'}")
    note(f"display timeout before: {original_idle}s · "
         f"AC policy: {before['suspend_policy'].get('sleep-inactive-ac-type')} / "
         f"{before['suspend_policy'].get('sleep-inactive-ac-timeout')}s · "
         f"battery: {before['suspend_policy'].get('sleep-inactive-battery-type')} / "
         f"{before['suspend_policy'].get('sleep-inactive-battery-timeout')}s")

    # Make an automation fire inside the window, so "ARIES kept working" is
    # evidenced by work rather than by a process being alive. Everything changed
    # here is read first and put back at the end: a test that leaves the user's
    # machine configured differently than it found it is a test that is only
    # honest once.
    borrowed = {}
    for key, value in (("health.interval_minutes", 1),
                       ("health.enabled", True),
                       ("automations.worker_enabled", True)):
        borrowed[key] = api("GET", f"/api/aries/settings/{key}")["value"]
        api("PUT", f"/api/aries/settings/{key}", {"value": value})
    note("borrowed settings: " + ", ".join(f"{k}={v}" for k, v in borrowed.items()))

    runs_before = api("GET", "/api/aries/automations/aries.health/runs")["runs"]
    started_at = datetime.now()
    wall0, mono0 = time.time(), time.monotonic()

    # ── 1. enable Background Mode ───────────────────────────────────────────
    on = api("PUT", "/api/aries/power",
             {"background_mode": True, "display_off_after_minutes": 1,
              "allow_suspend": False})
    check("Background Mode is on", on["background_mode"] is True)
    check("ARIES holds a suspend inhibitor", on["inhibitor"]["active"] is True)
    check("and logind lists it as sleep/block",
          any(r["what"] == "sleep" and r["mode"] == "block"
              for r in on["inhibitor"]["held_by_aries"]),
          str(on["inhibitor"]["held_by_aries"])[:120])

    # ── 2. the display is allowed to blank ──────────────────────────────────
    check("the display is allowed to power off", on["display"]["off_after_seconds"] == 60,
          f"idle-delay now {on['display']['off_after_seconds']}s")
    check("and the previous value was recorded for restoring",
          on["display"]["will_restore_to"] == original_idle,
          f"will restore to {on['display']['will_restore_to']}s")
    check("ARIES does NOT hold an idle inhibitor, which would stop blanking",
          all(r["what"] != "idle" for r in on["inhibitor"]["held_by_aries"]))

    # ── 3. wait, for real ───────────────────────────────────────────────────
    deadline = time.monotonic() + minutes * 60
    print(f"\n      waiting {minutes:g} minutes…", flush=True)
    ticks = 0
    while time.monotonic() < deadline:
        time.sleep(20)
        ticks += 1
        if ticks % 3 == 0:
            try:
                live = api("GET", "/api/aries/power")
                remaining = (deadline - time.monotonic()) / 60
                print(f"      {remaining:4.1f} min left · inhibitor "
                      f"{'held' if live['inhibitor']['active'] else 'LOST'} · display "
                      f"{live['display']['state']}", flush=True)
            except Exception as e:                          # noqa: BLE001
                print(f"      ARIES stopped answering: {e}", flush=True)

    wall_elapsed = time.time() - wall0
    mono_elapsed = time.monotonic() - mono0

    # ── 4. the machine stayed awake ─────────────────────────────────────────
    drift = abs(wall_elapsed - mono_elapsed)
    check("the machine did not suspend (wall clock and monotonic agree)", drift < 5.0,
          f"drift {drift:.1f}s over {wall_elapsed:.0f}s")
    sleeps = suspended_since(started_at)
    check("and the journal records no sleep", not sleeps, "; ".join(sleeps[:2]))

    during = api("GET", "/api/aries/power")
    check("the inhibitor was still held at the end", during["inhibitor"]["active"] is True)
    runtime = api("GET", "/api/aries/runtime")
    check("ARIES is still running", runtime["state"] in ("RUNNING", "DEGRADED"),
          runtime["summary"])

    # ── 5. an automation actually ran during the interval ───────────────────
    runs_after = api("GET", "/api/aries/automations/aries.health/runs")["runs"]
    check("an automation ran while the display was off", len(runs_after) > len(runs_before),
          f"{len(runs_after) - len(runs_before)} new health run(s)")
    if runs_after:
        note(f"last run: {runs_after[0]['status']} · {runs_after[0]['summary'][:70]}")

    # ── 6 & 7. disable, and normal behaviour is restored ────────────────────
    off = api("PUT", "/api/aries/power", {"background_mode": False})
    check("Background Mode is off", off["background_mode"] is False)
    check("the inhibitor is released", off["inhibitor"]["active"] is False)
    check("and logind no longer lists one for ARIES", off["inhibitor"]["held_by_aries"] == [])
    check("the display timeout is restored exactly",
          off["display"]["off_after_seconds"] == original_idle,
          f"back to {off['display']['off_after_seconds']}s")
    check("with nothing left to restore", off["display"]["will_restore_to"] is None)

    # Put back everything the test borrowed.
    for key, value in borrowed.items():
        api("PUT", f"/api/aries/settings/{key}", {"value": value})
    after = api("GET", "/api/aries/power")
    check("and the machine is left exactly as it was found",
          after["display"]["off_after_seconds"] == original_idle
          and all(api("GET", f"/api/aries/settings/{k}")["value"] == v
                  for k, v in borrowed.items()))

    print(f"\n{'ALL PASSED' if _ok else 'FAILURES'}\n", flush=True)
    return 0 if _ok else 1


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 4.0))
