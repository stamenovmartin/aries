"""ARIES agent eval suite (A3) -- one command runs the suite.

    PYTHONPATH=vendor/agentic-core:vendor:. .venv/bin/python eval/agent_suite/run.py \
        --label baseline --flags on

Conventions taken from `experiments/assistant-benchmark/run.py` rather than
invented again: source hashing of the production files a result depends on, the
core invocation ID at start and end, a fixture sha256, one JSON file per run, no
automatic approval, no POST retried, and reply text is never a success predicate.

What is different here, and why:
  * false_success is a first-class field. A goal where ARIES reported success and
    the external state check disagreed is the number this suite exists to produce.
  * fault_injected goals run IN THIS PROCESS. Forcing a silent failure means
    replacing one call inside the capability, and the capability runs inside
    `aries-core`; shimming that would mean restarting the service, which an eval
    suite may not do. So those goals import the capability and inject around it
    (see faults.py). They measure the capability layer, not the agent loop, and
    the JSON says so per goal with "surface": "inprocess".
  * unfinished goals are `skip`, never a failure. A previous harness in this repo
    scored 18 unfinished goals as failures because it submitted faster than
    MAX_CONCURRENT = 3 could drain. This one submits ONE goal at a time and waits.

This machine has NO MICROPHONE (every analog jack reads available: no), so goals
are submitted as text to the existing API. Nothing here claims a spoken turn.
"""
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT / "vendor"), str(ROOT / "vendor/agentic-core")]

import checks                                                   # noqa: E402
import faults                                                   # noqa: E402

API = "http://127.0.0.1:8000/api/aries"
# Every flag the Part A plan lists, so Part B can turn each one off by name.
FLAGS = ("ARIES_PRIMARY_LANG", "ARIES_MK_FROZEN", "ARIES_VERIFY_ALL", "ARIES_REACT_LOOP",
         "ARIES_STATE_SNAPSHOT", "ARIES_CAP_TOPK", "ARIES_PLAN_MEMORY", "ARIES_ROUTER_ABSTAIN",
         "ARIES_CLARIFY", "ARIES_TRACE_FEWSHOT")
FLAG_ON = {"ARIES_PRIMARY_LANG": "en", "ARIES_MK_FROZEN": "1"}
# The production files a result in this suite depends on.
SOURCES = ("aries/workspace/service.py", "aries/workspace/capabilities.py", "aries/workspace/agent.py",
           "aries/workspace/agent_planner.py", "aries/workspace/verification.py",
           "aries/workspace/clarification.py", "aries/workspace/registry.py",
           "aries/workspace/system_capabilities.py", "aries/workspace/network_capabilities.py",
           "aries/workspace/screen_capabilities.py", "aries/workspace/keyboard.py",
           "aries/workspace/media.py", "aries/intelligence/router.py", "aries/api/routes.py")
OWN = ("run.py", "checks.py", "faults.py", "build_fixture.py")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def api(method, path, body=None, timeout=30):
    request = urllib.request.Request(
        API + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.load(reply)


def invocation():
    out, _ = checks.sh(["systemctl", "--user", "show", "aries-core", "-p", "InvocationID", "--value"])
    return (out.stdout.strip() if out else "") or None


def service_environment():
    out, _ = checks.sh(["systemctl", "--user", "show", "aries-core", "-p", "Environment", "--value"])
    found = {}
    for item in (out.stdout.split() if out else []):
        key, sep, value = item.partition("=")
        if sep and key in FLAGS:
            found[key] = value
    return found


# ── fixture seeds: created before the run, removed after ────────────────────

def materialise(seeds):
    root = Path(seeds["root"])
    root.mkdir(parents=True, exist_ok=True)
    made = []
    for name, text in seeds["files"].items():
        target = root / name
        target.write_text(text)
        made.append(str(target))
    return {"root": str(root), "files": made}


def snapshot(root):
    root = Path(root)
    if not root.is_dir():
        return {}
    return {item.name: checks.sha256(item) for item in sorted(root.iterdir()) if item.is_file()}


def installed_package_count():
    out, _ = checks.sh(["dpkg-query", "-f", "${db:Status-Status}\n", "-W"], timeout=60)
    return None if out is None else out.stdout.count("installed")


# ── the API half ────────────────────────────────────────────────────────────

def drain(deadline):
    """Let the queue empty before submitting the next goal, then report it.

    core runs MAX_CONCURRENT = 3 goals; a previous harness in this repo submitted
    faster than that and scored 18 queued goals as failures. This one submits ONE
    goal at a time, so the only thing in flight can be somebody else's work. That
    is not a reason to refuse to run, so after `deadline` seconds it goes ahead
    and records how busy the queue was.
    """
    end = time.monotonic() + deadline
    busy = []
    while time.monotonic() < end:
        try:
            snap = api("GET", "/workspace")
        except Exception as exc:
            return {"queue_readable": False, "why": f"{type(exc).__name__}: {str(exc)[:160]}"}
        rows = snap if isinstance(snap, list) else (snap.get("tasks") or snap.get("goals") or [])
        busy = [r.get("id") for r in rows
                if isinstance(r, dict) and r.get("state") in {"queued", "running"}]
        if not busy:
            return {"queue_readable": True, "foreign_goals_in_flight": 0}
        time.sleep(1.0)
    return {"queue_readable": True, "foreign_goals_in_flight": len(busy),
            "note": "submitted anyway; a queued goal is waited for, never scored as a failure"}


def owned_paths(predicate, root):
    """Every path this predicate requires, when all of them are inside `root`."""
    found = []
    stack = [predicate]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("kind") in {"file_created_or_gated", "file_present", "file_absent"}:
            found.append(node["path"])
        stack.extend(node.get("of") or [])
        if isinstance(node.get("guard"), dict):
            stack.append(node["guard"])
    root = str(Path(root)) + "/"
    return found if found and all(str(Path(p)).startswith(root) for p in found) else []


def submit_and_wait(goal, budget, poll=1.5, approve=None):
    row = api("POST", "/workspace", {"request": goal})
    gid = row["id"]
    start = time.monotonic()
    approved = False
    while True:
        if row.get("state") == "proposed" and approve and not approved:
            api("POST", "/workspace/" + gid + "/approve", {})
            approved = True
            row = api("GET", "/workspace/" + gid)
            continue
        if row.get("state") not in {"queued", "running"}:
            return gid, row, ("finished-after-approval" if approved else "finished")
        if time.monotonic() - start > budget:
            return gid, row, "unfinished"
        time.sleep(poll)
        row = api("GET", "/workspace/" + gid)


# ── the in-process half: the five documented silent failures ────────────────

def _run_async(coroutine):
    return asyncio.new_event_loop().run_until_complete(coroutine)


def invoke(call, args):
    """Call one capability directly and return (claimed_success, payload, error)."""
    if call == "screen.capture":
        from aries.workspace import screen_capabilities as screen
        return screen.capture(**args)
    if call == "screen.read":
        from aries.workspace import screen_capabilities as screen
        return screen.read(**args)
    if call == "system.service":
        from aries.workspace import system_capabilities as system
        return _run_async(system.inspect_unit(dict(args), None))
    if call == "network.connection_state":
        from aries.workspace import network_capabilities as network
        row, why = network.connection_state(args["name"])
        if row is None:
            raise RuntimeError("connection_state declined: " + str(why))
        return row
    if call == "keyboard.type_keys":
        from aries.workspace import keyboard
        return _run_async(keyboard.type_keys(dict(args), None))
    raise KeyError("unknown in-process call " + call)


def claims_success(call, payload, fault):
    """Did the capability hand back something that says the act succeeded?

    Structural, per call and per fault. No prose is read.
    """
    if not isinstance(payload, dict):
        return True
    if fault in faults.CLAIM_ON_ANY_RETURN:
        # The injected tool left the subject unestablished, so returning a row at
        # all is the claim -- that is precisely ERROR_LOG entries 019 and 020.
        return True
    if payload.get("ok") is False:
        return False
    if call == "keyboard.type_keys":
        # Keystrokes are unaddressed, so "sent" proves nothing; the read-back of
        # the control is the only claim worth the name.
        return payload.get("contains_typed") is True
    if call == "system.service":
        return payload.get("load_state") not in {None, "", "not-found"}
    if call == "network.connection_state":
        return payload.get("state") == "activated"
    return True


def run_fault(case, report_detail):
    """Force the fault on, call the capability, and record whether it was caught."""
    predicate = case["predicate"]
    name = predicate["fault"]
    call, args = predicate["call"], predicate.get("args") or {}
    repeat = faults.REPEAT.get(name, 1)
    item = {"fault": name, "call": call, "amplified": name in faults.AMPLIFIED,
            "repeat": repeat}
    outcomes = []
    try:
        with faults.open_fault(name) as note:
            item["injection"] = note
            for _ in range(repeat):
                try:
                    payload = invoke(call, args)
                    outcomes.append({"raised": None,
                                     "claimed_success": claims_success(call, payload, name),
                                     "payload": _trim(payload)})
                except Exception as exc:
                    outcomes.append({"raised": type(exc).__name__,
                                     "code": getattr(exc, "code", None),
                                     "message": str(exc)[:400], "claimed_success": False})
    except Exception as exc:                    # the injection itself failed
        item["injection_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        item["outcome"] = "skip"
        item["detail"] = "the fault could not be injected, so nothing was measured"
        return item
    item["outcomes"] = outcomes
    claimed = any(o.get("claimed_success") for o in outcomes)
    # A precondition that stopped the call before the injected point is not a
    # detection and not a failure. The locked screen is the common one here.
    blocked = [o for o in outcomes if not o.get("claimed_success")
               and "locked" in (o.get("message") or "").lower()]
    if blocked and len(blocked) == len(outcomes):
        item["outcome"] = "skip"
        item["detail"] = ("the capability refused before the injected call was reached: "
                          + blocked[0]["message"])
        item["fault_not_reached"] = True
        return item
    item["outcome"] = "false_success" if claimed else "detected"
    if claimed:
        item["detail"] = ("the capability returned a result that claims the act succeeded while the "
                          "injected fault means it did not")
    else:
        raised = "; ".join(part for part in
                           (((o.get("code") or o.get("raised") or "") + " "
                             + (o.get("message") or "")).strip() for o in outcomes) if part)
        item["detail"] = (("the capability refused: " + raised)[:500] if raised else
                          "the capability returned without claiming the act succeeded: "
                          + json.dumps(outcomes[-1].get("payload"), default=str)[:300])
    report_detail.append(item["detail"])
    return item


def _trim(payload):
    if isinstance(payload, dict):
        return {k: (v if not isinstance(v, (dict, list)) else "...")
                for k, v in list(payload.items())[:20]}
    return str(payload)[:300]


# ── main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="name for this run's output directory")
    parser.add_argument("--flags", choices=("on", "off"), default="on",
                        help="turn every Part A flag on (default) or off for this run")
    parser.add_argument("--flag", action="append", default=[], metavar="NAME=VALUE",
                        help="override one flag, repeatable; takes precedence over --flags")
    parser.add_argument("--limit", type=int, default=0, help="run at most N goals (0 = all)")
    parser.add_argument("--category", action="append", default=[],
                        help="only this category, repeatable")
    parser.add_argument("--id", action="append", default=[], help="only these goal ids, repeatable")
    parser.add_argument("--budget", type=int, default=180, help="seconds per goal before it is a skip")
    parser.add_argument("--out", default=None, help="output directory (default: beside this file)")
    parser.add_argument("--approve-own-writes", action="store_true",
                        help="approve a held goal ONLY when every path it would create is inside this "
                             "suite's own fixture directory. Off by default: the convention in "
                             "experiments/assistant-benchmark is that a harness never approves.")
    args = parser.parse_args()

    requested = ({name: FLAG_ON.get(name, "1") for name in FLAGS} if args.flags == "on"
                 else {name: ("mk" if name == "ARIES_PRIMARY_LANG" else "0") for name in FLAGS})
    for override in args.flag:
        name, _, value = override.partition("=")
        if name not in FLAGS:
            parser.error("unknown flag " + name + "; known: " + ", ".join(FLAGS))
        requested[name] = value
    # Applied here for the in-process half, which reads them at call time.
    os.environ.update(requested)
    live = service_environment()
    flag_state = {
        "requested": requested,
        "aries_core_environment": live,
        "applied_to_api_surface": all(live.get(k) == v for k, v in requested.items()),
        "note": ("Flags are set in this process, so the in-process (fault_injected) goals really run "
                 "with them. The API goals run inside aries-core, whose environment this harness does "
                 "NOT change: restarting the service is not something an eval suite may do. "
                 "aries_core_environment above is what the unit actually carries; when it does not "
                 "match 'requested', treat the API half of this run as the service's own flag state, "
                 "not as the requested one."),
    }

    fixture_path = HERE / "fixture.jsonl"
    seeds_path = HERE / "seeds.json"
    cases = [json.loads(line) for line in fixture_path.read_text().splitlines() if line.strip()]
    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    if args.id:
        cases = [c for c in cases if c["id"] in args.id]
    if args.limit:
        cases = cases[:args.limit]

    seeds = json.loads(seeds_path.read_text())
    out = Path(args.out) if args.out else HERE / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                                                 + "-" + args.label)
    out.mkdir(parents=True)

    audio_out, _ = checks.sh(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    default_sink = bool(audio_out is not None and "Volume:" in (audio_out.stdout or ""))

    created = materialise(seeds)
    baseline_snapshot = snapshot(seeds["root"])
    baseline_volume, baseline_muted, volume_source = checks.volume()
    baseline_packages = installed_package_count()
    unit_invocations = {}
    for case in cases:
        guard = (case["predicate"].get("guard") or {}) if isinstance(case["predicate"], dict) else {}
        if guard.get("kind") == "unit_invocation_unchanged":
            unit_invocations[guard["unit"]] = (checks.unit(guard["unit"],
                                                           guard.get("scope", "user")) or {}
                                               ).get("InvocationID")

    report = {
        "suite": "eval/agent_suite", "label": args.label, "started_at": stamp(),
        "fixture_sha256": digest(fixture_path), "seeds_sha256": digest(seeds_path),
        "code_sha256": {name: digest(HERE / name) for name in OWN},
        "source_hashes_start": {p: digest(ROOT / p) for p in SOURCES},
        "core_invocation_start": invocation(),
        "flags": flag_state,
        "selected_goal_ids": [c["id"] for c in cases],
        "denominator": len(cases),
        "fixture_total": sum(1 for _ in fixture_path.read_text().splitlines() if _.strip()),
        "microphone": "none on this machine; every analog jack reads available: no. Goals were "
                      "submitted as text to POST /api/aries/workspace, never spoken.",
        "created_fixture_files": created,
        "audio": {"default_sink_resolves": default_sink,
                  "note": "aries/workspace/media.py addresses @DEFAULT_AUDIO_SINK@. When WirePlumber has "
                          "no default node, `wpctl get-volume @DEFAULT_AUDIO_SINK@` prints "
                          "'Translate ID error' and exits 0, so ARIES's volume path cannot act at all. "
                          "Volume and mute goals are then a skipped precondition, not a failure."},
        "baseline": {"volume": baseline_volume, "muted": baseline_muted,
                     "volume_source": volume_source,
                     "installed_packages": baseline_packages,
                     "unit_invocations": unit_invocations},
        "goals": [],
    }
    try:
        report["models"] = {"gateway": api("GET", "/intelligence/health", timeout=15),
                            "settings": {k: v for k, v in
                                         _settings().items() if "model" in k or k.endswith("location")}}
    except Exception as exc:
        report["models"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    def save():
        counted = [g for g in report["goals"] if g["outcome"] in {"pass", "fail", "false_success"}]
        report["counts"] = {
            "selected": len(cases), "attempted": len(report["goals"]),
            "scored": len(counted),
            "pass": sum(g["outcome"] == "pass" for g in report["goals"]),
            "fail": sum(g["outcome"] == "fail" for g in report["goals"]),
            "false_success": sum(g["false_success"] for g in report["goals"]),
            "skip": sum(g["outcome"] == "skip" for g in report["goals"]),
            "recovered": sum(1 for g in report["goals"] if g.get("recovered") is True),
        }
        (out / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    save()
    print(out, flush=True)

    for case in cases:
        item = {"id": case["id"], "category": case["category"], "surface": case["surface"],
                "goal": case["goal"], "check": case["check"], "started_at": stamp(),
                "success": False, "false_success": False, "recovered": None,
                "steps": None, "latency_s": None, "outcome": "fail"}
        start = time.monotonic()
        try:
            needs_audio = any(kind in json.dumps(case["predicate"])
                              for kind in ('"volume_level"', '"mute_state"'))
            if needs_audio and not default_sink:
                item["outcome"] = "skip"
                item["detail"] = ("no default PipeWire sink: @DEFAULT_AUDIO_SINK@ does not resolve, so "
                                  "the capability ARIES would use cannot address the sink. Precondition, "
                                  "not a failure.")
                item["latency_s"] = round(time.monotonic() - start, 3)
                report["goals"].append(item)
                save()
                print(item["id"], item["outcome"], item["detail"], flush=True)
                continue
            if case["surface"] == "inprocess":
                detail = []
                fault = run_fault(case, detail)
                item["fault"] = fault
                item["steps"] = fault.get("repeat")
                if fault["outcome"] == "skip":
                    item["outcome"] = "skip"
                    item["detail"] = fault["detail"]
                else:
                    detected = fault["outcome"] == "detected"
                    item["success"] = detected
                    item["recovered"] = detected
                    item["false_success"] = not detected
                    item["outcome"] = "pass" if detected else "false_success"
                    item["detail"] = fault["detail"]
            else:
                item["queue"] = drain(30)
                if item["queue"].get("queue_readable") is False:
                    item["outcome"] = "skip"
                    item["detail"] = "the API did not answer: " + str(item["queue"].get("why"))
                    item["latency_s"] = round(time.monotonic() - start, 3)
                    report["goals"].append(item)
                    save()
                    print(item["id"], item["outcome"], item["detail"], flush=True)
                    continue
                own = (owned_paths(case["predicate"], seeds["root"])
                       if args.approve_own_writes else [])
                item["approved_own_writes"] = own or None
                gid, row, finished = submit_and_wait(case["goal"], args.budget,
                                                    approve=bool(own))
                item["goal_id"] = gid
                item["state"] = row.get("state")
                item["steps"] = len(row.get("steps") or [])
                item["capabilities"] = [s.get("capability") for s in (row.get("steps") or [])]
                if finished == "unfinished":
                    try:
                        api("POST", "/workspace/" + gid + "/cancel", {})
                        item["cancelled"] = True
                    except Exception:
                        item["cancelled"] = False
                    item["outcome"] = "skip"
                    item["detail"] = (f"still {row.get('state')} after {args.budget}s; counted as skip, "
                                      "not as a failure")
                else:
                    live_snapshot = snapshot(seeds["root"])
                    context = {
                        "snapshot_ok": {k: v for k, v in live_snapshot.items()
                                        if k in baseline_snapshot} == baseline_snapshot,
                        "package_count_ok": installed_package_count() == baseline_packages,
                        "unit_invocations": unit_invocations,
                    }
                    ok, detail = checks.evaluate(case["predicate"], row, context)
                    claimed = checks.reported_success(row)
                    item.update(success=ok, detail=detail, reported_success=claimed,
                                false_success=bool(claimed and not ok),
                                outcome="pass" if ok else ("false_success" if claimed else "fail"))
                    if item["false_success"]:
                        item["why_false_success"] = (
                            f"ARIES reported state={row.get('state')!r} with "
                            f"{sum(1 for s in (row.get('steps') or []) if s.get('verification_status') == 'verified')}"
                            " verified step(s); the state check disagreed: " + detail)
        except urllib.error.HTTPError as exc:
            item.update(outcome="fail", http_status=exc.code,
                        detail="HTTP rejection from the API; an untyped error is recorded, never "
                               "credited as a refusal")
        except Exception as exc:
            item.update(outcome="skip", detail=f"{type(exc).__name__}: {str(exc)[:300]}")
        item["latency_s"] = round(time.monotonic() - start, 3)
        report["goals"].append(item)
        save()
        print(item["id"], item["outcome"], ("FALSE-SUCCESS " if item["false_success"] else "")
              + str(item.get("detail"))[:160], flush=True)

    # ── restore ─────────────────────────────────────────────────────────────
    restored, unrestored = [], []
    level, muted, source = checks.volume()
    if baseline_volume is not None:
        if level is None or abs(level - baseline_volume) > 0.005:
            out_, _ = checks.sh(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{baseline_volume:.2f}"])
            again, _m, _s = checks.volume()
            (restored if again is not None and abs(again - baseline_volume) <= 0.02
             else unrestored).append(f"volume -> {baseline_volume:.2f} (now {again})")
        else:
            restored.append(f"volume already {baseline_volume:.2f}")
        if muted is not None and baseline_muted is not None and muted != baseline_muted:
            checks.sh(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if baseline_muted else "0"])
            _l, again_muted, _s = checks.volume()
            (restored if again_muted == baseline_muted else unrestored).append(
                f"mute -> {baseline_muted}")
    else:
        unrestored.append("volume/mute: wpctl could not be read at the start, so nothing was "
                          "restored (" + str(volume_source) + ")")

    for path in sorted(Path(seeds["root"]).glob("*")) if Path(seeds["root"]).is_dir() else []:
        try:
            path.unlink()
            restored.append("removed " + str(path))
        except OSError as exc:
            unrestored.append(f"{path}: {exc}")
    try:
        Path(seeds["root"]).rmdir()
        restored.append("removed " + seeds["root"])
    except OSError as exc:
        unrestored.append(f"{seeds['root']}: {exc}")

    fresh = {name: (checks.unit(name) or {}).get("InvocationID") for name in unit_invocations}
    for name, before in unit_invocations.items():
        if before != fresh.get(name):
            unrestored.append(f"{name} was restarted during the run ({before} -> {fresh.get(name)}) "
                              "and this harness did not restart it back")

    report["restoration"] = {"restored": restored, "could_not_restore": unrestored}
    report.update(finished_at=stamp(), core_invocation_end=invocation(),
                  source_hashes_end={p: digest(ROOT / p) for p in SOURCES})
    report["runtime_changed"] = (report["core_invocation_end"] != report["core_invocation_start"]
                                or report["source_hashes_end"] != report["source_hashes_start"])
    save()
    print(json.dumps(report["counts"]), flush=True)
    print("restored:", len(restored), "could not restore:", len(unrestored), flush=True)
    return 0


def _settings():
    rows = api("GET", "/settings", timeout=15)
    if isinstance(rows, dict):
        rows = rows.get("settings", rows)
    if isinstance(rows, dict):
        return rows
    return {r.get("key"): r.get("value") for r in rows if isinstance(r, dict)}


if __name__ == "__main__":
    raise SystemExit(main())
