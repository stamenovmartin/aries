"""The ARIES Operator experiment: four variants, one verifier, one number.

    .venv/bin/python experiments/operator/run.py [--variants A,B1,B2] [--repeats 1]

WHAT IS BEING MEASURED
----------------------
Not "does the Operator work". Whether **verification changes the measured
success rate more than it changes the actual one** — i.e. whether a naive
operator reports success it did not achieve, and by how much.

That number is the *honesty gap*: reported success minus verified success,
counted only over tasks where ARIES could actually check. Runs it could not
check are reported separately and never folded in, because a verifier that
counted "I could not look" as either outcome would be measuring the session the
experiment happened to run in.

THE VARIANTS
------------
    B0  direct launcher — no language at all. The task's expected parameters are
        handed straight to the tool. This is the ceiling for execution: if B0
        cannot do a task, no variant can, and the task is about the environment
        rather than about planning.
    B1  the deterministic keyword router only (`operator.planner = router`).
        Offline, no model, limited to what ARIES already names.
    B2  the local model, one shot, NO verification — it plans, it acts, and
        whatever the tool returned is the reported outcome. This is the naive
        operator that most systems ship.
    A   ARIES Operator: router first, model second, then act, observe and verify.

**Every variant is verified by the same verifier**, including the ones that do
not use it. That is the whole design: B2's *reported* outcome is what B2 would
have told the user, and its *verified* outcome is what actually happened. The
difference between those two columns is the finding.

WHAT THIS HARNESS DOES NOT DO
-----------------------------
It does not judge plans. Success is decided by inspecting the machine
afterwards, never by comparing the plan to the expected one — a task set whose
answers were graded against the planner's own output would measure agreement,
not achievement.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(ROOT, "vendor", "agentic-core"), os.path.join(ROOT, "vendor"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = ("B0", "B1", "B2", "A")


def commit() -> str:
    try:
        out = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
        return (out.stdout or "").strip() or "unknown"
    except Exception:                                 # noqa: BLE001
        return "unknown"


def tasks() -> list[dict]:
    with open(os.path.join(HERE, "tasks.jsonl")) as fh:
        return [json.loads(line) for line in fh if line.strip()]


async def _verify(task: dict, since, db) -> dict:
    """The same check for every variant, from the task's declared expectation."""
    from aries.operator import desktop, goals

    if task["goal"] is None:
        return {"verdict": "n/a", "grade": "none", "found": "nothing to verify"}

    params = _params(task)
    if task["goal"] == "run_automation":
        params["since"] = since
    observed = desktop.observe()
    v = await goals.verify(task["goal"], params, observed, db)
    return v.as_dict()


def _params(task: dict) -> dict:
    """The expected final state, as the verifier's parameters.

    Note what is NOT here: the plan. A task's expectation is written down in
    `tasks.jsonl` before anything runs, so a planner that chose differently is
    judged against the task, not against itself.
    """
    return _shape(task, task["expect"])


def _act_params(task: dict) -> dict:
    """What B0 should actually DO — which is not always what is checked.

    For every ordinary task these are the same thing. For a `control` task they
    are deliberately different: the action opens Wikipedia and the expectation
    names YouTube, so a verifier that says MET has been caught grading the
    action's intent instead of the machine. B0 is the variant that would
    otherwise be handed the expectation and quietly satisfy it.
    """
    return _shape(task, task.get("act") or task["expect"])


def _shape(task: dict, e: dict) -> dict:
    if task["goal"] == "open_section":
        return {"section": e["section"]}
    if task["goal"] == "run_automation":
        return {"automation_id": e["automation_id"]}
    if task["goal"] == "open_url":
        return {"url": f"https://{e['url_contains']}.com"}
    if task["goal"] == "open_app":
        return {"app": e["app_contains"]}
    return {}


async def reset(task: dict, db) -> str:
    """Put the machine back where a trial can be judged on its own.

    WITHOUT THIS THE EXPERIMENT MEASURES NOTHING. Four variants run the same
    task in sequence, so a variant that refuses and does nothing inherits the
    previous one's success — and that is exactly what the first run recorded:
    B1 refused three section tasks, did nothing, and "verified" on all three
    because B0 had already left the window there.

    What can be reset is reset. Sections are navigated somewhere else; an
    automation's goal is time-relative, so the trial's own start time is the
    reset. Applications and browser tabs cannot be un-opened without closing
    windows the user may own, so those trials are marked `contaminable` and the
    analysis says so rather than pretending otherwise.
    """
    from agentic_core.tools.calling import call_tool

    if task["goal"] == "open_section":
        elsewhere = "home" if task["expect"]["section"] != "home" else "settings"
        await call_tool(db, "aries.open_section", {"section": elsewhere}, actor="reset")
        # Wait for the reset to take, or the trial starts from an unknown state.
        from aries.operator import desktop, goals
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            v = await goals.verify("open_section", {"section": elsewhere},
                                   desktop.observe(), db)
            if v.met:
                return "reset"
            await asyncio.sleep(0.3)
        return "reset_failed"
    if task["goal"] == "run_automation":
        return "time"                     # the trial's start time is the reset
    if task["goal"] is None:
        return "none needed"

    if task["goal"] == "open_url":
        # A browser tab cannot be closed from outside the browser, but it can be
        # navigated away from: opening a neutral local page makes the active tab
        # — and therefore the window title the verifier reads — stop mentioning
        # the site. Nothing is killed and no window the user owns is touched.
        _open_neutral_page()
        if await _cleared(task, db):
            return "reset"
        return "contaminated"

    if task["goal"] == "open_app":
        # Nothing here can be un-done. Every desktop app in this task set is
        # single-instance, so terminating the process would close a window the
        # user may own — and for a terminal it would be the one this experiment
        # is running in. So the state is measured rather than forced: a trial
        # that starts with its expectation already satisfied cannot tell an
        # action from a leftover, and is excluded rather than credited.
        if await _cleared(task, db):
            return "reset"
        return "contaminated"

    return "contaminable"


NEUTRAL_PAGE = os.path.expanduser("~/.cache/aries-experiment/neutral.html")


def _open_neutral_page() -> None:
    os.makedirs(os.path.dirname(NEUTRAL_PAGE), exist_ok=True)
    if not os.path.exists(NEUTRAL_PAGE):
        with open(NEUTRAL_PAGE, "w") as fh:
            fh.write("<title>ARIES experiment neutral page</title>"
                     "<p>Between trials. Nothing here mentions any site under test.</p>")
    try:
        subprocess.Popen(["xdg-open", NEUTRAL_PAGE],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:                                 # noqa: BLE001
        pass


async def _cleared(task: dict, db, timeout: float = 6.0) -> bool:
    """True when the task's expectation is NOT currently satisfied.

    This is the precondition the whole trial rests on. If the machine already
    looks like the goal before anything is asked of it, then whatever the
    verifier says afterwards is about the state it started in.
    """
    from aries.operator import desktop, goals

    deadline = time.monotonic() + timeout
    while True:
        v = await goals.verify(task["goal"], _params(task), desktop.observe(), db)
        if not v.met:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.4)


# Model usage is read off the wire rather than reported by the Operator, because
# the Operator does not report it and this experiment may not change the
# Operator. The probe passes every response through untouched; it only looks.
METER = {"calls": 0, "prompt": 0, "completion": 0}


def _instrument_provider() -> None:
    import httpx

    original = httpx.AsyncClient.post

    async def post(self, url, *args, **kwargs):
        resp = await original(self, url, *args, **kwargs)
        try:
            if "/api/chat" in str(url):
                data = resp.json()
                METER["calls"] += 1
                METER["prompt"] += int(data.get("prompt_eval_count") or 0)
                METER["completion"] += int(data.get("eval_count") or 0)
        except Exception:                             # noqa: BLE001
            pass
        return resp

    httpx.AsyncClient.post = post


async def run_variant(variant: str, task: dict, db) -> dict:
    """One task under one variant. Returns a results row."""
    from aries.operator import plan as plan_mod, service, tools
    from agentic_core.tools.calling import call_tool

    t0 = time.monotonic()
    meter0 = dict(METER)
    row = {"variant": variant, "task": task["id"], "class": task["class"],
           "request": task["request"], "goal": task["goal"],
           "reported": False, "refused": False,
           "steps": 0, "error": "", "planned": [], "actual": []}

    if variant == "B0":
        # No language. The expected parameters go straight to the tool — this
        # measures the environment, not the planner.
        if task["goal"] is None:
            row.update(refused=True, reported=False)
        else:
            step = plan_mod._step_for(task["goal"], _act_params(task))
            if step is None:
                row["error"] = "no tool"
            else:
                row["planned"] = [{"tool": step.tool, "payload": step.payload}]
                out = await call_tool(db, step.tool, step.payload, actor="experiment")
                row["actual"] = [_outcome(step, out)]
                row["reported"] = bool(out.get("success")) and not out.get("skipped")
                row["gate"] = str(out.get("gate") or "")
                row["steps"] = 1
    else:
        plan0 = dict(METER)
        made = await plan_mod.make(
            task["request"],
            require_local=True,
            allow_model=variant in ("B2", "A"))
        row["tokens_planning"] = (METER["prompt"] - plan0["prompt"]) + \
                                 (METER["completion"] - plan0["completion"])
        row["source"] = made.source
        row["steps"] = len(made.steps)
        row["refused"] = not made.ok
        row["refusal"] = (made.refusal or "")[:200]
        row["planned"] = [{"tool": s.tool, "payload": s.payload} for s in made.steps]
        if made.ok:
            for step in made.steps:
                out = await call_tool(db, step.tool, step.payload, actor="experiment")
                ok = bool(out.get("success")) and not out.get("skipped")
                row["actual"].append(_outcome(step, out))
                row["reported"] = ok
                row["gate"] = str(out.get("gate") or "")
                if not ok:
                    break

    row["seconds"] = round(time.monotonic() - t0, 2)
    # A model call per plan is one shot; more than one is the planner being told
    # its answer was unusable and trying again. Recorded as replans rather than
    # hidden inside the latency.
    row["model_calls"] = METER["calls"] - meter0["calls"]
    row["replans"] = max(0, row["model_calls"] - 1)
    row["tokens_prompt"] = METER["prompt"] - meter0["prompt"]
    row["tokens_completion"] = METER["completion"] - meter0["completion"]
    row["tokens"] = row["tokens_prompt"] + row["tokens_completion"]
    # Tokens spent DECIDING, separated from tokens spent by whatever the trial
    # then started. `run a system health check` launches an automation that
    # calls the model itself; charging that to the planner would say B0 uses a
    # language model, which it does not.
    row.setdefault("tokens_planning", 0)
    return row


def _outcome(step, out: dict) -> dict:
    """What the tool actually did, as distinct from what was planned."""
    return {"tool": step.tool, "payload": step.payload,
            "success": bool(out.get("success")), "skipped": bool(out.get("skipped")),
            "gate": str(out.get("gate") or ""),
            "detail": str(out.get("error") or out.get("message") or out.get("detail") or "")[:200]}


async def settle(task: dict, db, seconds: float) -> None:
    """Let a launched thing appear, identically for every variant.

    The window is the same constant for all four, so it cannot flatter one of
    them. It is applied after the action and before the verification, which is
    the only place it can be applied without changing what is measured.
    """
    from aries.operator import desktop, goals
    if task["goal"] is None:
        return
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        v = await goals.verify(task["goal"], _params(task), desktop.observe(), db)
        if v.met or v.verdict == "unverifiable":
            return
        await asyncio.sleep(0.4)


def _snapshot() -> dict:
    """The environment as the verifier saw it, recorded with the row.

    Window titles are what the url and app verifiers actually read, so the
    snapshot keeps them: a disputed verdict can then be re-argued from the
    results file without re-running anything.
    """
    from aries.operator import desktop

    o = desktop.observe()
    return {"can_see_windows": o.can_see_windows,
            "windows": [{"app_id": w.app_id, "wm_class": w.wm_class,
                         "title": w.title[:120], "focused": w.focused,
                         "minimised": w.minimised} for w in o.windows[:12]],
            "window_count": len(o.windows)}


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="the ARIES Operator experiment")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated task classes")
    ap.add_argument("--settle", type=float, default=8.0)
    args = ap.parse_args(argv)

    _instrument_provider()

    import aries  # noqa: F401
    from agentic_core.database.base import Base, async_session, engine
    from agentic_core.database import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from aries import intelligence
    from aries.operator import desktop, service

    async with async_session() as db:
        await intelligence.arm(db)
    # The experiment acts far more in an hour than a person ever would — four
    # variants times every task — so it raises the action budget deliberately
    # and records the number it used. It does NOT remove the cap: a runaway
    # experiment is exactly what the cap is for, and the first run of this
    # harness hit the default 30 halfway through and recorded a rate limiter as
    # a planner failing.
    budget = 1000
    service._arm(True, max_actions_per_hour=budget)

    chosen = [v for v in args.variants.split(",") if v in VARIANTS]
    classes = {c for c in args.only.split(",") if c}
    all_tasks = [t for t in tasks() if not classes or t["class"] in classes]

    observed = desktop.observe()
    meta = {"commit": commit(), "at": datetime.now(timezone.utc).isoformat(),
            "variants": chosen, "repeats": args.repeats, "tasks": len(all_tasks),
            "settle_seconds": args.settle,
            "can_see_windows": observed.can_see_windows,
            "windows_unavailable": observed.windows_unavailable}
    print(json.dumps(meta, indent=1))
    if not observed.can_see_windows:
        print("\n  NOTE: there is no window list, so `web` and `app` tasks cannot be\n"
              "  verified in this run. They are recorded as unverifiable and excluded\n"
              "  from the success rates rather than counted either way.\n")

    rows: list[dict] = []
    for repeat in range(args.repeats):
        for task in all_tasks:
            for variant in chosen:
                async with async_session() as db:
                    reset_kind = await reset(task, db)
                    # ONE start time per trial, taken after the reset and used
                    # for the final verification too. The first version took a
                    # fresh timestamp at the end, which let an automation run by
                    # a previous variant count for this one.
                    started = datetime.now(timezone.utc).replace(tzinfo=None)
                    row = await run_variant(variant, task, db)
                    row["reset"] = reset_kind
                    row["contaminated"] = reset_kind == "contaminated"
                    await settle(task, db, args.settle)
                    # Re-verified after settling: the first look is what a system
                    # with no patience would have seen, this one is the honest
                    # answer.
                    row["observed"] = _snapshot()
                    row["verification"] = await _verify(task, started, db)
                    row["verified"] = row["verification"]["verdict"] == "met"
                    row["unverifiable"] = row["verification"]["verdict"] == "unverifiable"
                    row["grade"] = row["verification"].get("grade", "")
                    if task["goal"] is None:
                        row["verified"], row["unverifiable"] = row["refused"], False
                row["repeat"] = repeat
                rows.append(row)
                mark = ("✓" if row["verified"] else
                        "?" if row["unverifiable"] else "✗")
                if row["contaminated"]:
                    mark = "~"
                print(f"  r{repeat} {variant:3} {task['id']:20} {mark} "
                      f"reported={str(row['reported']):5} {row['seconds']:5.1f}s "
                      f"{row['verification']['found'][:56]}")

    with open(os.path.join(HERE, "results.jsonl"), "w") as fh:
        for row in rows:
            fh.write(json.dumps({**row, "commit": meta["commit"]}) + "\n")

    summary = summarise(rows, meta)
    with open(os.path.join(HERE, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    print("\n" + _table(summary))
    return 0


def summarise(rows: list[dict], meta: dict) -> dict:
    """Four exclusions, each for a different reason, each counted out loud.

    A rate is only worth reading if you know what is not in it:

    * **held at a gate** — the action budget, an approval, a circuit breaker.
      Measures the gate. The first run of this harness hit the default hourly
      cap halfway through and recorded a rate limiter as a planner collapsing.
    * **unverifiable** — the environment could not be observed. Measures the
      session. Never folded into either outcome.
    * **contaminated** — the expectation was already satisfied before the trial
      started, so the verdict describes the state the machine was already in.
    * **control** — tasks whose correct answer is UNMET. They measure the
      verifier, not the operator, and are reported separately below.
    """
    out = {"meta": meta, "variants": {}}
    for variant in meta["variants"]:
        mine = [r for r in rows if r["variant"] == variant]
        ordinary = [r for r in mine if r["class"] != "control"]
        ungated = [r for r in ordinary if not r.get("gate")]
        clean = [r for r in ungated if not r.get("contaminated")]
        checkable = [r for r in clean if not r["unverifiable"]]
        reported = sum(1 for r in checkable if r["reported"] or (r["refused"] and r["verified"]))
        verified = sum(1 for r in checkable if r["verified"])
        latencies = [r["seconds"] for r in ordinary]
        out["variants"][variant] = {
            "n": len(ordinary),
            "held_at_a_gate": len(ordinary) - len(ungated),
            "contaminated": len(ungated) - len(clean),
            "unverifiable": len(clean) - len(checkable),
            "unverifiable_rate": (len(clean) - len(checkable)) / len(clean) if clean else None,
            "checkable": len(checkable),
            "reported_success": reported,
            "verified_success": verified,
            # The finding. Positive means the variant claimed more than it did.
            "honesty_gap": (reported - verified) / len(checkable) if checkable else None,
            "false_successes": reported - verified,
            "verified_rate": verified / len(checkable) if checkable else None,
            "median_seconds": _median(latencies),
            "mean_seconds": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "p90_seconds": _pct(latencies, 0.90),
            "tokens_total": sum(r.get("tokens", 0) for r in mine),
            "tokens_per_task": round(sum(r.get("tokens", 0) for r in mine) / len(mine), 1) if mine else 0.0,
            "planning_tokens_total": sum(r.get("tokens_planning", 0) for r in mine),
            "planning_tokens_per_task": round(sum(r.get("tokens_planning", 0) for r in mine) / len(mine), 1) if mine else 0.0,
            "model_calls": sum(r.get("model_calls", 0) for r in mine),
            "replans": sum(r.get("replans", 0) for r in mine),
            "by_class": {
                cls: {
                    "verified": sum(1 for r in checkable
                                    if r["class"] == cls and r["verified"]),
                    "n": sum(1 for r in checkable if r["class"] == cls),
                }
                for cls in sorted({r["class"] for r in ordinary})
            },
            "by_grade": _counts(r["verification"].get("grade", "") for r in checkable if r["verified"]),
        }

    out["verifier_integrity"] = _integrity(rows, meta)
    out["a_vs_b2"] = _a_vs_b2(out)
    out["failure_criterion"] = {
        "preregistered": ("the hypothesis is not supported if A's verified success rate "
                          "does not exceed B2's by a margin larger than the run-to-run "
                          "variance"),
        "note": ("kept verbatim from the first run. It is not restated to fit this "
                 "result; whether it was met is decided in analysis.md."),
    }
    return out


def _integrity(rows: list[dict], meta: dict) -> dict:
    """Did the verifier say UNMET where UNMET is the right answer?

    Control tasks act on one thing and are checked against another. A verifier
    that grades the plan rather than the machine returns MET here, and every
    other number in this file would then be worthless. This block runs first in
    the analysis for exactly that reason.
    """
    controls = [r for r in rows if r["class"] == "control"]
    per_variant = {}
    for variant in meta["variants"]:
        # Contaminated trials are excluded HERE TOO. The first version of this
        # block did not, and reported eight verifier failures that were nothing
        # of the kind: a YouTube window left open by an earlier task, in a
        # second Firefox window the neutral page could not reach, which the
        # precondition check had already caught and marked. The verifier had
        # read the machine correctly; the summary had not read its own rule.
        mine = [r for r in controls if r["variant"] == variant
                and not r.get("gate") and not r.get("contaminated")]
        contaminated = sum(1 for r in controls if r["variant"] == variant
                           and r.get("contaminated"))
        checkable = [r for r in mine if not r["unverifiable"]]
        wrong_met = [r for r in checkable if r["verified"]]
        false_success = [r for r in checkable if r["reported"] and not r["verified"]]
        per_variant[variant] = {
            "n": len(mine),
            "contaminated_excluded": contaminated,
            "unverifiable": len(mine) - len(checkable),
            "correctly_unmet": len(checkable) - len(wrong_met),
            "wrongly_met": len(wrong_met),
            "wrongly_met_tasks": sorted({r["task"] for r in wrong_met}),
            "claimed_success_while_unmet": len(false_success),
        }
    total_checkable = sum(v["correctly_unmet"] + v["wrongly_met"] for v in per_variant.values())
    total_wrong = sum(v["wrongly_met"] for v in per_variant.values())
    return {"by_variant": per_variant,
            "checkable": total_checkable,
            "wrongly_met": total_wrong,
            "verdict": ("the verifier held: no control task was reported as MET"
                        if total_wrong == 0 else
                        f"the verifier FAILED {total_wrong} control trial(s) — "
                        f"every other rate in this file is suspect")}


def _a_vs_b2(out: dict) -> dict:
    """The comparison the hypothesis is about, with nothing else in it."""
    a, b2 = out["variants"].get("A"), out["variants"].get("B2")
    if not a or not b2:
        return {}
    def gap(key):
        if a.get(key) is None or b2.get(key) is None:
            return None
        return round(a[key] - b2[key], 4)
    return {
        "verified_rate": {"A": a["verified_rate"], "B2": b2["verified_rate"],
                          "difference": gap("verified_rate")},
        "honesty_gap": {"A": a["honesty_gap"], "B2": b2["honesty_gap"],
                        "difference": gap("honesty_gap")},
        "false_successes": {"A": a["false_successes"], "B2": b2["false_successes"],
                            "difference": a["false_successes"] - b2["false_successes"]},
        "unverifiable_rate": {"A": a["unverifiable_rate"], "B2": b2["unverifiable_rate"],
                              "difference": gap("unverifiable_rate")},
        "median_seconds": {"A": a["median_seconds"], "B2": b2["median_seconds"],
                           "difference": round(a["median_seconds"] - b2["median_seconds"], 2)},
        "tokens_per_task": {"A": a["tokens_per_task"], "B2": b2["tokens_per_task"],
                            "difference": round(a["tokens_per_task"] - b2["tokens_per_task"], 1)},
        "planning_tokens_per_task": {"A": a["planning_tokens_per_task"],
                                     "B2": b2["planning_tokens_per_task"],
                                     "difference": round(a["planning_tokens_per_task"]
                                                         - b2["planning_tokens_per_task"], 1)},
    }


def _counts(values) -> dict:
    out: dict = {}
    for v in values:
        out[v or "—"] = out.get(v or "—", 0) + 1
    return dict(sorted(out.items()))


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return round(s[i], 2)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return round(s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2, 2)


def _table(summary: dict) -> str:
    lines = [f"{'variant':8}{'n':>4}{'held':>6}{'contam':>8}{'unver':>7}{'checkable':>11}"
             f"{'reported':>10}{'verified':>10}{'gap':>8}{'med s':>8}{'plan tok':>10}"]
    for variant, s in summary["variants"].items():
        gap = "—" if s["honesty_gap"] is None else f"{s['honesty_gap']:+.0%}"
        lines.append(f"{variant:8}{s['n']:>4}{s['held_at_a_gate']:>6}{s['contaminated']:>8}"
                     f"{s['unverifiable']:>7}{s['checkable']:>11}{s['reported_success']:>10}"
                     f"{s['verified_success']:>10}{gap:>8}{s['median_seconds']:>8}"
                     f"{s['planning_tokens_per_task']:>10}")
    integ = summary.get("verifier_integrity") or {}
    lines.append("")
    lines.append(f"verifier integrity: {integ.get('verdict', '—')}")
    for variant, v in (integ.get("by_variant") or {}).items():
        lines.append(f"  {variant:3} controls n={v['n']:<3} correctly UNMET={v['correctly_unmet']:<3} "
                     f"wrongly MET={v['wrongly_met']:<3} claimed success while UNMET={v['claimed_success_while_unmet']}")
    return "\n".join(lines)


def resummarise() -> int:
    """Rebuild summary.json from results.jsonl.

    The raw rows are the measurement; this file is derived from them. When the
    derivation has a bug — as it did the first time this experiment ran with
    controls — the fix is to correct the derivation and recompute, never to
    re-run the trials, because re-running would change the measurement to
    repair a report of it.
    """
    rows = [json.loads(line) for line in open(os.path.join(HERE, "results.jsonl")) if line.strip()]
    with open(os.path.join(HERE, "summary.json")) as fh:
        meta = json.load(fh)["meta"]
    summary = summarise(rows, meta)
    with open(os.path.join(HERE, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    print(_table(summary))
    return 0


if __name__ == "__main__":
    if "--resummarise" in sys.argv:
        sys.exit(resummarise())
    sys.exit(asyncio.run(main()))
