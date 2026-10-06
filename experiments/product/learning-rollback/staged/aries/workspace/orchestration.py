"""Several goals at once, and a different strategy when one of them cannot.

Today one goal runs at a time. Not because the dispatcher is serial — it already
claims up to `service.MAX_CONCURRENT` rows — but because `service.resources_for`
reserves {desktop, files, local-model, browser} for the whole lifetime of any
`agent_task` goal, and almost every goal is an `agent_task` goal. One reservation
that wide is exclusion by another name, so the measured concurrency is one.

Three things are added here and nothing is rebuilt:

  * **How many** comes from `aries.power.governor`, never from a constant. The
    governor already separates "may this class of work run unattended at all?"
    (settings) from "is the machine in a state to take it now?" (CPU, GPU,
    thermals). A second worker-count setting next to it would be a second policy
    that can disagree with the first. `CEILING` below bounds the arithmetic; it
    is not the limit.
  * **Who goes next** is FIFO with aging. Skipping a blocked goal and taking the
    next one is what keeps the machine busy, and it is also how a goal that wants
    a busy lane is passed over forever. So a goal deferred `AGING_DEFERRALS`
    times reserves the lanes it is waiting for against every *younger* goal.
  * **What to try next** comes from the typed code `agent.error` already
    produces. TRANSIENT/NETWORK_ERROR retries a read after a pause, then tries a
    declared alternative when that mechanism's repeat budget is spent. Mutating
    operations stop on these uncertain failures until their effects are checked;
    CAPABILITY_UNAVAILABLE/PERMISSION_REQUIRED is a different road if one has
    been *declared*; NON_RETRYABLE/AMBIGUOUS/AUTH_REQUIRED/VERIFICATION_FAILED
    stops and says why. There is no open-ended loop: `ATTEMPT_CAP` capability
    invocations, `RETRY_CAP` repeats of one strategy, `ALTERNATIVE_CAP` distinct
    alternatives. Repeats consume the total budget but count as one mechanism.

NEVER A SECOND QUEUE
--------------------
A sub-goal is a `WorkspaceGoal` row, in the one table `aries_workspace_goals`,
claimed by the one compare-and-swap the dispatcher already uses. Sub-goals of one
request are separate rows with separate audit trails and separate evidence, so
one failing cannot corrupt another's record, and a restart resumes them because
the row is the state. The only thing shared between two running goals is the lane
bookkeeping, keyed by goal id.

AN ALTERNATIVE IS NOT A WAY ROUND A GATE
----------------------------------------
`registry.policy` returning False means a person has to decide. That is not a
failure and it is never re-routed — it freezes, exactly as it does in `agent.py`.
`declare()` additionally refuses any alternative that requires more approval than
the capability it stands in for, or that mutates where the original only read, so
"try something else" can never become "try something the user did not authorise".

SQLITE
------
`database is locked` has occurred despite WAL and a 15 s busy timeout. Avoid
holding write transactions across capability I/O. Every persist is open → update → commit → close
(`service.save`), and the read transaction `policy` opens is rolled back before
the capability's executor is called, because in WAL a lingering read holds a
snapshot and blocks checkpointing.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, update

from agentic_core.database.base import async_session
from aries.workspace.agent import error, evidence, transition
from aries.workspace.models import WorkspaceGoal
from aries.workspace.registry import now, policy, registry

# The arithmetic bound on the governor's answer, not the answer. A capacity
# formula that can return anything needs an upper edge; this is it. Raising it is
# a measurement question — 4 concurrent writers against this database were
# measured, 40 were not.
CEILING = 4

# Both halves of a goal's run are bounded, and neither bound is a retry policy.
ATTEMPT_CAP = 4          # capability invocations for one sub-goal, total
RETRY_CAP = 2            # repeats of the SAME strategy, for transient codes only
ALTERNATIVE_CAP = 2      # distinct different strategies
RETRY_BACKOFF_S = (1.0, 3.0)
MAX_SUBGOALS = 4         # fan-out width; concurrency is not a way to do more work

# How many times a goal may be passed over before it reserves what it is waiting
# for. Low enough that a person notices no delay, high enough that a lane freed
# for a moment is not handed straight back to a queue jumper.
AGING_DEFERRALS = 3

# A lane is a thing the machine has one of. `desktop` is the focused window and
# is genuinely a singleton: two goals typing into "the focused window" are one
# goal corrupting another. Files and browser sessions are scoped — a path, a
# session owned by a task id — so they are recorded for inspection but never
# block. Reads take no lane at all, which is what makes a fan-out of questions
# actually parallel.
EXCLUSIVE = frozenset({"desktop", "local-model"})
_FAMILY_LANE = {"browser": "browser", "desktop": "desktop", "screen": "desktop",
                "input": "desktop", "file": "files", "system": "services",
                "network": "network", "display": "display", "notification": "notify",
                "task": "files"}


# ── how many: the governor decides ──────────────────────────────────────────

@dataclass
class Capacity:
    slots: int
    reason: str
    measurement: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    workload_status: str = ""

    def as_dict(self):
        return {"slots": self.slots, "reason": self.reason, "workload_status": self.workload_status,
                "measurement": self.measurement, "limits": self.limits,
                "ceiling": CEILING, "source": "aries.power.governor"}


async def capacity(db) -> Capacity:
    """How many goals may run right now, read out of the resource policy.

    `governor.snapshot` is used rather than `governor.may_run` deliberately:
    `may_run` *records* every refusal, and this is asked on a two-second poll.
    Writing a row per empty pass is the bug that made `automation_logs` 88 %
    noise on 2026-09-29. Nothing here writes; the one row per real refusal is
    still written by the automations runner, where a refusal means something.
    """
    from aries.power import governor
    snapshot = await governor.snapshot(db)
    by_name = {c["name"]: c for c in snapshot["classes"]}
    heavy = by_name.get("heavy_cpu", {"status": "allowed", "why": "no heavy class declared"})
    limits, measured = snapshot["limits"], snapshot["measurement"]

    # Never zero. A queued goal is a person waiting, and the governor's own rule
    # is that light work — a read, a question — is never deferred at all. Zero
    # would make their goal unreachable until the machine cooled; one runs it and
    # says why it is only one.
    if heavy["status"] != "allowed":
        return Capacity(1, f"one goal at a time — {heavy['why']}", measured, limits, heavy["status"])
    load, ceiling = measured.get("cpu_pct"), limits["cpu_pct"]
    if load is None or not ceiling:
        return Capacity(1, "one goal at a time — processor load cannot be measured ("
                        + str(measured.get("cpu_unavailable") or "no limit configured") + ")",
                        measured, limits, heavy["status"])
    free = max(0.0, (ceiling - load) / ceiling)
    slots = max(1, min(CEILING, 1 + int(free * CEILING)))
    return Capacity(slots, f"{slots} goals — the processor is at {load:.0f} % of the "
                    f"{ceiling} % limit, {free * 100:.0f} % of it free",
                    measured, limits, heavy["status"])


# ── who goes next: FIFO, with the aging that stops it starving anyone ────────

_deferred: dict[str, dict] = {}


def lanes_for(name: str) -> frozenset:
    """The lanes one declared capability needs. A read needs none."""
    cap = registry.get(name)
    if cap.effect == "read":
        return frozenset()
    return frozenset({_FAMILY_LANE.get(name.split(".", 1)[0], "desktop")})


def reserved(goal_id: str | None = None) -> frozenset:
    """Lanes held for goals that have been passed over too often.

    Strictly older than the candidate: a goal never reserves against itself, and
    a goal that arrived after the starved one does not get to inherit its claim.
    """
    mine = _deferred.get(goal_id or "", {}).get("first_at")
    out: set[str] = set()
    for other, record in _deferred.items():
        if other == goal_id or record["count"] < AGING_DEFERRALS:
            continue
        if mine is not None and record["first_at"] > mine:
            continue
        out |= record["want"]
    return frozenset(out)


def admit(goal_id: str, want, occupied) -> bool:
    """May this goal be claimed now? Records the refusal so aging can see it."""
    want, occupied = frozenset(want), frozenset(occupied)
    blocked = want & occupied
    if not blocked:
        blocked = want & reserved(goal_id)
    if blocked:
        record = _deferred.setdefault(goal_id, {"first_at": time.monotonic(), "count": 0,
                                                "want": frozenset()})
        record["count"] += 1
        record["want"] = want
        record["lanes"] = sorted(blocked)
        return False
    _deferred.pop(goal_id, None)
    return True


def release(goal_id: str) -> None:
    _deferred.pop(goal_id, None)


def deferrals() -> dict:
    """What has been waiting, and for what — the answer to "why is it not running?"."""
    age = time.monotonic()
    return {goal: {"deferrals": r["count"], "waiting_seconds": round(age - r["first_at"], 1),
                   "wants": sorted(r["want"]), "blocked_on": r.get("lanes", []),
                   "reserving": r["count"] >= AGING_DEFERRALS}
            for goal, r in _deferred.items()}


# ── what to try next: the typed code decides ────────────────────────────────

# One row per code, and the reason is the user-facing sentence. Anything not
# listed stops: an unrecognised failure is not an invitation to improvise.
ROUTE = {
    "TRANSIENT":              ("retry",   "the world was briefly busy; the same route is the right route"),
    "NETWORK_ERROR":          ("retry",   "the network moved under the request; the same route after a pause"),
    "CAPABILITY_UNAVAILABLE": ("reroute", "this mechanism is missing on this machine; a declared alternative may exist"),
    "PERMISSION_REQUIRED":    ("reroute", "this route is closed by policy; a lower-privilege declared route may be open"),
    "TARGET_NOT_FOUND":       ("reroute", "the thing the route needs is not there; only a declared alternative may look elsewhere"),
    "VERIFICATION_FAILED":    ("stop",    "the effect may already have happened; repeating it could happen twice"),
    "AUTH_REQUIRED":          ("stop",    "only a person holds the credential"),
    "AMBIGUOUS":              ("stop",    "two readings of the request; asking is honest, guessing is not"),
    "NON_RETRYABLE":          ("stop",    "the failure says it will not succeed a second time"),
}


@dataclass(frozen=True)
class Alternative:
    capability: str
    argmap: object          # dict -> dict, over the failed capability's own arguments
    why: str
    degraded: bool = False  # reaches a weaker end; can never report `done`


ALTERNATIVES: dict[str, tuple[Alternative, ...]] = {}


def declare(primary: str, capability: str, argmap, why: str, *, degraded: bool = False) -> Alternative:
    """Register one alternative, refusing at import time what is unsafe or unreal.

    Everything checkable is checked here rather than at the moment of failure: the
    capability exists, its arguments validate against its own schema, and it does
    not widen authority. A re-route is only worth having if it cannot surprise.
    """
    original, alternative = registry.get(primary), registry.get(capability)
    if alternative.requires_approval and not original.requires_approval:
        raise ValueError(f"{capability} needs approval that {primary} did not: an alternative "
                         "may not be a way round a gate")
    if original.effect == "read" and alternative.effect != "read":
        raise ValueError(f"{capability} changes the machine where {primary} only read it")
    entry = Alternative(capability, argmap, why, degraded)
    existing = ALTERNATIVES.get(primary, ())
    if any(e.capability == capability for e in existing):
        raise ValueError("Duplicate alternative: " + primary + " -> " + capability)
    ALTERNATIVES[primary] = existing + (entry,)
    return entry


@dataclass
class Decision:
    action: str                     # retry | reroute | stop
    why: str
    capability: str | None = None
    arguments: dict | None = None
    degraded: bool = False

    def as_dict(self):
        return {"action": self.action, "why": self.why, "capability": self.capability,
                "arguments": self.arguments, "degraded": self.degraded}


def route(code: str, capability: str, trail, arguments: dict) -> Decision:
    """Retry, re-route or stop — decided from the code and from what was tried.

    `trail` is the sub-goal's own strategy list, so the caps are read off the
    durable record rather than from a counter that a restart would reset.
    """
    action, why = ROUTE.get(code, ("stop", "unrecognised failure code " + str(code)))
    if len(trail) >= ATTEMPT_CAP:
        return Decision("stop", f"{ATTEMPT_CAP} attempts is the budget for one sub-goal; "
                                f"{code} would have been {action}")
    if action == "retry":
        if registry.get(capability).effect != "read":
            return Decision("stop", f"{code} on {capability}: its effect may already have happened; "
                                    "verification is required before any repeat or alternative")
        same = sum(1 for s in trail if s["capability"] == capability)
        if same <= RETRY_CAP:
            return Decision("retry", why, capability, arguments)
        # Exhausting one mechanism is not exhausting the sub-goal. A declared,
        # untried alternative may still fit inside the total invocation budget.
        why = (f"{capability} failed {same} times; {RETRY_CAP} repeats is the budget; "
               "only a declared untried alternative may continue")
    if action == "stop":
        return Decision("stop", f"{code}: {why}")
    tried = {s["capability"] for s in trail}
    used = len({s["capability"] for s in trail
                if s.get("strategy", {}).get("alternative_of")})
    if used >= ALTERNATIVE_CAP:
        return Decision("stop", f"{ALTERNATIVE_CAP} different approaches have been tried; "
                                f"{code} on {capability} is where it stops")
    for entry in ALTERNATIVES.get(capability, ()):
        if entry.capability in tried:
            continue
        try:
            arguments_for = registry.validate(entry.capability, entry.argmap(arguments))
        except Exception as exc:                                    # noqa: BLE001
            return Decision("stop", f"declared alternative {entry.capability} does not accept the "
                                    f"arguments of {capability}: {type(exc).__name__}")
        return Decision("reroute", f"{code} on {capability}: {why} — {entry.why}",
                        entry.capability, arguments_for, entry.degraded)
    return Decision("stop", f"{code} on {capability}: {why}, and none is declared")


# ── driving one sub-goal through its strategies ─────────────────────────────

async def _persist(goal_id, data, state="running"):
    from aries.workspace.service import save
    await save(goal_id, data, state)


async def _invoke(goal_id, goal, cap, args, data, step):
    """One capability invocation: authorise, execute, verify independently.

    The session is opened for the gate and closed around the effect. `policy`
    only reads, and its read transaction is rolled back before the executor runs
    — a read snapshot held across a 100-second browser navigation is what blocks
    a WAL checkpoint and, eventually, everybody else's writer.
    """
    async with async_session() as db:
        ctx = {"db": db, "goal": goal, "task_id": goal_id, "origin":data.get('origin')}
        try:
            authorized = await policy(db, cap, args, goal, approved=bool(step.get("approved")),origin=data.get('origin'))
        except Exception as exc:                                    # noqa: BLE001
            detail = error(exc)
            row = evidence(data, cap.name, "policy_refusal", detail, verified=False, step_id=step["step_id"])
            return {"state": "failed", "code": detail["code"], "detail": detail,
                    "observation_ref": row["evidence_id"]}
        await db.rollback()
        if not authorized:
            # A person has to decide. Not a failure, and never re-routed.
            return {"state": "needs_approval", "code": "PERMISSION_REQUIRED",
                    "detail": {"message": "This action is frozen for review before anything happens",
                               "retryable": False}}
        step.update(execution_status="executing", started_at=now())
        transition(step, "executing")
        try:
            await _persist(goal_id, data)
            result = await asyncio.wait_for(cap.executor(args, ctx), cap.timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:                                    # noqa: BLE001
            detail = error(exc)
            step.update(execution_status="failed")
            transition(step, "failed")
            row = evidence(data, cap.name, "execution_error", detail, verified=False, step_id=step["step_id"])
            step["observation_ref"] = row["evidence_id"]
            return {"state": "failed", "code": detail["code"], "detail": detail,
                    "observation_ref": row["evidence_id"]}
        step.update(execution_status="observed", execution_result=result)
        transition(step, "observed")
        observed = evidence(data, cap.name, "execution_observation", result, verified=False, step_id=step["step_id"])
        step["observation_ref"] = observed["evidence_id"]
        try:
            verification = await asyncio.wait_for(cap.verifier(args, result, ctx), cap.timeout_seconds)
        except Exception as exc:                                    # noqa: BLE001
            verification = {"met": False, "type": "verification_error", "data": error(exc)}
        met = verification.get("met") is True
        proof = evidence(data, cap.name, verification["type"], verification["data"],
                         verified=met, step_id=step["step_id"])
        step["evidence_refs"] = [*step.get("evidence_refs", []), proof["evidence_id"]]
        step["verification_status"] = "verified" if met else "verification_failed"
        transition(step, step["verification_status"])
        if met:
            return {"state": "verified", "code": None, "detail": verification["data"],
                    "evidence_id": proof["evidence_id"]}
        return {"state": "failed", "code": "VERIFICATION_FAILED",
                "detail": {"message": "Independent verification did not confirm the effect",
                           "retryable": False, "verification": verification["data"]},
                "evidence_id": proof["evidence_id"]}


async def attempt(goal_id, goal, subgoal, data):
    """Drive one sub-goal to a verified end, a frozen proposal, or an honest stop."""
    orchestration = data.setdefault("orchestration", {})
    trail = data.setdefault("steps", [])
    name = subgoal["capability"]
    args = registry.validate(name, subgoal.get("args") or {})
    primary = name
    while True:
        cap = registry.get(name)
        step = {"step_id": uuid.uuid4().hex, "task_id": goal_id, "step_index": len(trail),
                "kind": "capability", "capability": name, "args": args,
                "request": subgoal.get("request") or goal, "approved": bool(subgoal.get("approved")),
                "execution_status": "planned", "verification_status": "pending",
                "started_at": None, "finished_at": None, "evidence_refs": [],
                "strategy": {"index": len(trail) + 1, "of_primary": primary,
                             "alternative_of": None if name == primary else primary,
                             "degraded": bool(subgoal.get("degraded"))}}
        transition(step, "planned")
        trail.append(step)
        # Intent recorded before the effect, so an interrupted process leaves a
        # readable "it was about to do this" rather than a gap.
        await _persist(goal_id, data)
        started = time.monotonic()
        outcome = await _invoke(goal_id, goal, cap, args, data, step)
        step["seconds"] = round(time.monotonic() - started, 3)
        step["finished_at"] = now()
        step["result"] = {"state": "done" if outcome["state"] == "verified" else outcome["state"],
                          "summary": ("Independently verified" if outcome["state"] == "verified"
                                      else str(outcome["detail"].get("message", outcome["state"]))[:400]),
                          "elapsed_seconds": step["seconds"]}
        if outcome["state"] == "failed":
            step["error"] = {**outcome["detail"], "code": outcome["code"]}
        await _persist(goal_id, data)
        if outcome["state"] in ("verified", "needs_approval"):
            break
        decision = route(outcome["code"], name, trail, args)
        step["strategy"]["decision"] = decision.as_dict()
        await _persist(goal_id, data)
        if decision.action == "stop":
            break
        if decision.action == "retry":
            await asyncio.sleep(RETRY_BACKOFF_S[min(len(trail) - 1, len(RETRY_BACKOFF_S) - 1)])
            continue
        name, args = decision.capability, decision.arguments
        subgoal = {**subgoal, "degraded": bool(subgoal.get("degraded")) or decision.degraded}
    verdict = report(primary, trail)
    if verdict['state'] == 'done':
        from aries.workspace import contracts
        contract = contracts.compile_goal(goal, '')
        if contract.get('answer') == 'measurements':
            final = outcome.get('detail') or {}
            if all(contracts.evidence_matches(requirement, {'met': True, 'data': final})
                   for requirement in contract['requirements']):
                verdict['answer'] = contracts.answer(contract, [{'data': final}])
            else:
                verdict.update(state='partial', summary='The requested measurement was unavailable')
    orchestration["outcome"] = verdict
    data.setdefault("cards", []).append(
        {"title": "How it was done", "text": verdict["summary"],
         "evidence": ", ".join(e for s in trail for e in s.get("evidence_refs", [])) or
                     "See each attempt's recorded failure"})
    if verdict["state"] != "done":
        data.setdefault("gaps", []).append(verdict["summary"])
    await _persist(goal_id, data, verdict["state"])
    return verdict


def report(primary: str, trail) -> dict:
    """Say which strategy worked and what it cost — never a clean first attempt.

    A verified end reached through a *degraded* alternative is `partial`, because
    the alternative reaches a weaker end than the one that was asked for and
    saying `done` would be a lie in the one place a person would not check.
    """
    attempts = [s for s in trail if s.get("capability")]
    if not attempts:
        return {"state": "failed", "summary": "Nothing was attempted", "strategies": 0}
    last = attempts[-1]
    tried = [s["capability"] for s in attempts]
    failures = [f"{s['capability']} → {(s.get('error') or {}).get('code', 'unverified')}"
                for s in attempts[:-1]]
    detail = {"strategies": len(attempts), "attempted": tried,
              "alternatives_used": sorted({s["capability"] for s in attempts
                                           if s["strategy"].get("alternative_of")}),
              "route": [s["strategy"].get("decision", {}).get("why") for s in attempts
                        if s["strategy"].get("decision")]}
    if last.get("verification_status") == "verified":
        degraded = last["strategy"].get("degraded")
        where = (f"on strategy {len(attempts)} of {len(attempts)} — {last['capability']}"
                 if len(attempts) > 1 else f"on the first attempt — {last['capability']}")
        after = (" after " + "; ".join(failures)) if failures else ""
        if degraded:
            return {"state": "partial", "summary": f"Partly done {where}{after}. That route reaches a "
                    f"weaker end than the one asked for, so this is not reported as done.", **detail}
        return {"state": "done", "summary": f"Verified {where}{after}.", **detail}
    if last.get("execution_status") == "planned" and not last.get("error"):
        return {"state": "proposed", "summary": f"{last['capability']} is frozen for review before "
                f"anything happens" + (f", after {'; '.join(failures)}" if failures else "") + ".",
                **detail}
    why = last["strategy"].get("decision", {}).get("why") or \
        (last.get("error") or {}).get("message", "no further route")
    return {"state": "failed", "summary": f"Not done after {len(attempts)} "
            f"strateg{'y' if len(attempts) == 1 else 'ies'} ({', '.join(tried)}): {why}", **detail}


# ── fanning out: one request, several durable rows ──────────────────────────

async def fan_out(db, request, subgoals, *, source="default", present=False, check_loop=True):
    """Create a parent row and one child row per sub-goal. Nothing runs yet.

    The loop guard is asked ONCE, for the request the person actually made.
    Children are not re-counted against it — a fan-out is one utterance, and
    charging it four times would trip the guard on legitimate work — so the
    protection is the width cap instead: concurrency may not become a way to do
    more work than was asked for.
    """
    from aries.settings import SettingsService
    from aries.workspace import runaway
    from aries.workspace.service import ACTIVE, audit
    from agentic_core.security import principal
    from agentic_core.security.permissions import Permission
    who = principal.current()
    if who is not None and not who.can(Permission.MANAGE_TOOLS):
        raise ValueError('Submitting executable goals needs manage_tools permission')
    if not request.strip() or len(request) > 2000:
        raise ValueError('A goal needs between 1 and 2000 characters')
    if not await SettingsService(db).get("workspace.enabled"):
        raise ValueError("Goal dashboards are switched off")
    if not subgoals:
        raise ValueError("A fan-out needs at least one sub-goal")
    if len(subgoals) > MAX_SUBGOALS:
        raise ValueError(f"At most {MAX_SUBGOALS} sub-goals in one request")
    if check_loop:
        verdict = runaway.check(request, source)
        if not verdict.allowed:
            raise ValueError(verdict.reason)
    pending = (await db.execute(select(WorkspaceGoal.id).where(WorkspaceGoal.state.in_(ACTIVE)).limit(20))).all()
    if len(pending) + len(subgoals) + 1 > 20:
        raise ValueError("The goal queue is full; finish or cancel a task first")
    for index, subgoal in enumerate(subgoals):
        if registry.get(subgoal['capability']).effect != 'read':
            raise ValueError('Parallel execution currently accepts read-only goals; use sequential goals for changes')
        if subgoal.get('approved'):
            raise ValueError('A submitted sub-goal cannot carry its own approval')
        subgoal["args"] = registry.validate(subgoal["capability"], subgoal.get("args") or {})
        subgoal.setdefault("request", request)
        subgoal["index"] = index
    parent_id = uuid.uuid4().hex
    children = []
    for subgoal in subgoals:
        child = WorkspaceGoal(id=uuid.uuid4().hex, request=subgoal["request"], state="queued",
                              result_json=json.dumps({
                                  "steps": [], "evidence": [], "cards": [], "gaps": [],
                                  "schema_version": 2, "origin": source,
                                  "orchestration": {"role": "child", "parent_id": parent_id,
                                                    "subgoal": subgoal,
                                                    "lanes": sorted(lanes_for(subgoal["capability"]))}}))
        db.add(child)
        children.append(child.id)
    parent = WorkspaceGoal(id=parent_id, request=request, state="running",
                           result_json=json.dumps({
                               "steps": [], "evidence": [], "cards": [], "gaps": [],
                               "present_dashboard": present, "origin": source,
                               "orchestration": {"role": "parent", "children": children,
                                                 "width": len(children),
                                                 "capacity": "set per tick by aries.power.governor"}}))
    db.add(parent)
    await audit(db, "workspace.fanned_out", {"id": parent_id, "children": children})
    await db.commit()
    return {"id": parent_id, "children": children, "width": len(children)}


def combine(states) -> str:
    """Partial the moment one sub-goal is not done. Never `done` on a maybe."""
    states = list(states)
    if not states:
        return "failed"
    if all(s == "done" for s in states):
        return "done"
    if any(s == "proposed" for s in states):
        return "proposed"
    if any(s in ("done", "partial") for s in states):
        return "partial"
    if all(s == "cancelled" for s in states):
        return "cancelled"
    return "failed"


async def roll_up(db, parent_id) -> dict | None:
    """Write the parent's honest outcome once every child has stopped."""
    from aries.workspace.service import ACTIVE, audit
    parent = await db.get(WorkspaceGoal, parent_id, populate_existing=True)
    if parent is None or parent.state not in {'running', 'cancelled'}:
        return None
    data = json.loads(parent.result_json)
    children = data.get("orchestration", {}).get("children", [])
    rows = (await db.execute(select(WorkspaceGoal).where(WorkspaceGoal.id.in_(children)))).scalars().all()
    by_id = {r.id: r for r in rows}
    if parent.state == "cancelled":
        if data.get('orchestration', {}).get('cancellation_applied'):
            return None
        # Stop active executors as well as queued children. Use the existing
        # cancellation path so its durable state and in-memory task agree.
        from aries.workspace.service import cancel
        for child in rows:
            if child.state in ACTIVE | {"proposed"}:
                await cancel(db, child.id)
            release(child.id)
        data['orchestration']['cancellation_applied'] = True
        parent.result_json = json.dumps(data)
        await db.commit()
        return None
    if any(r.state in ACTIVE for r in rows) or len(rows) != len(children):
        return None
    if data['orchestration'].get('dynamic_team'):
        if any(r.state=='proposed' for r in rows):return None
        from aries.workspace.goal_graph import synthesize
        return await synthesize(db,parent,data,[by_id[key] for key in children])
    outcomes = []
    for child_id in children:
        row = by_id.get(child_id)
        child = json.loads(row.result_json) if row else {}
        outcome = child.get("orchestration", {}).get("outcome") or {}
        outcomes.append({"id": child_id, "request": row.request if row else "",
                         "state": row.state if row else "failed",
                         "summary": outcome.get("summary", row.state if row else "missing"),
                         "answer": outcome.get('answer'),
                         "strategies": outcome.get("strategies", 0),
                         "attempted": outcome.get("attempted", [])})
    state = combine(o["state"] for o in outcomes)
    data["orchestration"]["outcomes"] = outcomes
    data["orchestration"]["finished_at"] = now()
    done = sum(1 for o in outcomes if o["state"] == "done")
    rerouted = [o for o in outcomes if o["strategies"] > 1]
    headline = f"{done} of {len(outcomes)} sub-goals verified"
    if rerouted:
        headline += "; " + ", ".join(f"{o['request'][:40]} needed {o['strategies']} strategies "
                                     f"({' → '.join(o['attempted'])})" for o in rerouted)
    data.setdefault("cards", []).insert(0, {"title": "Goal outcome", "text": headline,
                                            "evidence": "Each sub-goal keeps its own row, steps and evidence: "
                                                        + ", ".join(o["id"] for o in outcomes)})
    answers = [o['answer'] for o in outcomes if o.get('answer') and o['state'] == 'done']
    if answers:
        for item in outcomes:
            if item['state'] != 'done':
                from aries.workspace.contracts import compile_goal
                mk = compile_goal(item['request'], '').get('language') == 'mk'
                answers.append(('Не успеав да го проверам: ' if mk else 'I could not verify: ')
                               + item['request'])
        data['cards'].insert(0, {'title': 'Answer', 'text': ' '.join(answers),
                                'evidence': ', '.join(o['id'] for o in outcomes if o.get('answer'))})
    data.setdefault("gaps", []).extend(o["summary"] for o in outcomes if o["state"] != "done")
    parent.result_json = json.dumps(data)
    parent.state = state
    parent.updated_at = datetime.utcnow()
    await audit(db, "workspace.rolled_up", {"id": parent_id, "state": state, "verified": done,
                                            "of": len(outcomes)})
    await db.commit()
    return {"id": parent_id, "state": state, "outcomes": outcomes}


# ── the tick: claim, launch, roll up, then let the existing dispatcher run ──

def _interrupt(data, why):
    """Mark whatever was in flight as interrupted. Never replayed, ever.

    `agent.mark_interrupted` does exactly this for an m14 row and refuses any
    other engine. Rather than forge `engine: 'm14'` to borrow it, the same rule is
    applied here in the open: an effect whose verification never happened is not
    known to have happened or not, and a second attempt could double it.
    """
    for step in data.get("steps", []):
        if step.get("execution_status") != "executing" and step.get("verification_status") != "pending":
            continue
        detail = {"error_type": "InterruptedExecution", "message": why, "retryable": False}
        step["error"] = detail
        step["verification_status"] = "interrupted"
        step["finished_at"] = now()
        transition(step, "interrupted")
        row = evidence(data, step["capability"], "interrupted_execution", detail,
                       verified=False, step_id=step["step_id"])
        step["observation_ref"] = row["evidence_id"]
    data.setdefault("gaps", []).append(why)


async def _drive(goal_id, request, subgoal):
    """Supervise one sub-goal row. Deadline derived from its own capability budget."""
    from aries.workspace import service
    async with async_session() as db:
        row = await db.get(WorkspaceGoal, goal_id, populate_existing=True)
        data = json.loads(row.result_json) if row is not None else _fresh(subgoal)
    if any(s.get("execution_status") == "executing" for s in data.get("steps", [])):
        _interrupt(data, "An execution was interrupted before verification; it will not be replayed")
        await _persist(goal_id, data, "interrupted")
        service._resources.pop(goal_id, None)
        service._supervisors.pop(goal_id, None)
        release(goal_id)
        return
    is_agent=subgoal.get('kind')=='agent'
    if is_agent:
        from aries.workspace.agent import run
        task=asyncio.create_task(run(goal_id,request,data))
    else:
        task = asyncio.create_task(attempt(goal_id, request, subgoal, data))
    service._tasks[goal_id] = task
    try:
        budget = 1800 if is_agent else min(1800, ATTEMPT_CAP * max(30, registry.get(subgoal["capability"]).timeout_seconds) + 60)
        await asyncio.wait_for(asyncio.shield(task), timeout=budget)
    except (Exception, asyncio.CancelledError) as exc:              # noqa: BLE001
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        stopped = isinstance(exc, (asyncio.CancelledError, asyncio.TimeoutError))
        async with async_session() as db:
            row = await db.get(WorkspaceGoal, goal_id, populate_existing=True)
            if row is not None and row.state == "running":
                data = json.loads(row.result_json)
                _interrupt(data, "Interrupted before verification; no effect is replayed"
                           if stopped else str(exc)[:300])
                row.result_json = json.dumps(data)
                row.state = "interrupted" if stopped else "failed"
                row.updated_at = datetime.utcnow()
                await db.commit()
    finally:
        service._tasks.pop(goal_id, None)
        service._resources.pop(goal_id, None)
        service._supervisors.pop(goal_id, None)
        release(goal_id)


def _fresh(subgoal):
    return {"steps": [], "evidence": [], "cards": [], "gaps": [], "schema_version": 2,
            "orchestration": {"role": "child", "subgoal": subgoal}}


async def claim(db, slots) -> list[str]:
    """Claim up to `slots` orchestration children with the dispatcher's own CAS.

    Caller holds `service._lock`, so this never races the ordinary dispatcher's
    claim of the same row.
    """
    from aries.workspace import service
    rows = (await db.execute(select(WorkspaceGoal).where(WorkspaceGoal.state == "queued")
                             .order_by(WorkspaceGoal.created_at).limit(20))).scalars().all()
    occupied = set().union(*service._resources.values()) if service._resources else set()
    launched = []
    for row in rows:
        if len(launched) >= slots:
            break
        data = json.loads(row.result_json)
        orchestration = data.get("orchestration") or {}
        if orchestration.get("role") != "child":
            continue
        parent_id=orchestration.get('parent_id')
        parent=await db.get(WorkspaceGoal,parent_id,populate_existing=True) if parent_id else None
        if parent is None or parent.state!='running':
            data.setdefault('gaps',[]).append('Parent is no longer running')
            await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id==row.id,
                WorkspaceGoal.state=='queued').values(state='cancelled',result_json=json.dumps(data)))
            await db.commit()
            continue
        subgoal = orchestration["subgoal"]
        if subgoal.get('kind')=='agent':
            from aries.workspace.goal_graph import dependencies_ready
            ready,why=await dependencies_ready(db,data)
            if why:
                data.setdefault('gaps',[]).append(why)
                await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id==row.id,
                    WorkspaceGoal.state=='queued').values(state='held',result_json=json.dumps(data)))
                await db.commit()
            if not ready:continue
            want=frozenset(service.resources_for(data))
        else:
            want = lanes_for(subgoal["capability"])
        if not admit(row.id, want, occupied & EXCLUSIVE):
            continue
        # Couple the child's transition to the current durable parent state:
        # an earlier read alone leaves a cancellation race before this update.
        from sqlalchemy.orm import aliased
        parent_row=aliased(WorkspaceGoal)
        live_parent=select(parent_row.id).where(parent_row.id==parent_id,
                                               parent_row.state=='running').exists()
        claimed = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == row.id,
                                                               WorkspaceGoal.state == "queued", live_parent)
                                   .values(state="running", updated_at=datetime.utcnow()))
        if not claimed.rowcount:
            continue
        await db.commit()                    # the claim is durable before any effect
        service._resources[row.id] = set(want)
        occupied |= want
        service._supervisors[row.id] = asyncio.create_task(_drive(row.id, row.request, subgoal))
        launched.append(row.id)
    await db.commit()
    return launched


async def tick(*, wait=False) -> dict:
    """One dispatcher pass: heartbeat parents, roll up, launch children, delegate.

    The ordinary `service.dispatch` still runs, unchanged, for every goal that is
    not an orchestration child. It is called *after* the lock is released,
    because it takes the same lock itself.
    """
    from aries.runtime import maintenance
    from aries.workspace import service
    if maintenance.active():
        return {"launched": 0, "running": len(service._supervisors), "maintenance": True, "idle": True}
    launched, allowed, slots = [], None, 0
    async with service._lock:
        async with async_session() as db:
            parents = (await db.execute(select(WorkspaceGoal)
                                        .where(WorkspaceGoal.state.in_(["running", "cancelled"])))).scalars().all()
            waiting = []
            for parent in parents:
                data = json.loads(parent.result_json)
                if (data.get("orchestration") or {}).get("role") != "parent":
                    continue
                if data['orchestration'].get('cancellation_applied'):
                    continue
                waiting.append(parent.id)
                # Heartbeat: a parent has no task of its own, and the ordinary
                # dispatcher marks any row untouched for five minutes as
                # interrupted. This tick IS its supervisor.
                parent.updated_at = datetime.utcnow()
            await db.commit()
            for parent_id in waiting:
                await roll_up(db, parent_id)
            queued = (await db.execute(select(WorkspaceGoal.id)
                                       .where(WorkspaceGoal.state == "queued").limit(1))).first()
            # Nothing queued means nothing to size, so the machine is not read.
            # An empty pass that measures the GPU and writes a row is the bug the
            # 2 s poll already had once.
            if queued is not None:
                allowed = await capacity(db)
                slots = max(0, allowed.slots - len(service._supervisors))
            if slots:
                launched = await claim(db, slots)
    rest = await service.dispatch(wait=wait, slot_limit=allowed.slots if allowed else None)
    if wait and launched:
        await asyncio.gather(*(service._supervisors[i] for i in launched
                               if i in service._supervisors), return_exceptions=True)
        async with async_session() as db:
            for parent_id in waiting:
                await roll_up(db, parent_id)
    return {"launched": len(launched) + rest.get("launched", 0), "orchestrated": len(launched),
            "running": len(service._supervisors),
            "capacity": allowed.as_dict() if allowed else
                        {"slots": None, "reason": "not measured — nothing is queued"},
            "deferred": deferrals(), "idle": not launched and bool(rest.get("idle")),
            "dispatcher": rest}


# ── the declared alternatives ───────────────────────────────────────────────
# Five, and each one is a different MECHANISM for the same end rather than the
# same mechanism tried again. Anything that would only repeat itself is absent on
# purpose: an alternative that cannot change the outcome is an open-ended retry
# loop wearing a different name.

def _register():
    # "Have this application's window in front of me." Launching and focusing are
    # opposite failures of the same goal: focus fails because nothing is open,
    # launch fails because something already is, or is not installed.
    declare("desktop.focus", "desktop.launch", lambda a: {"app": a["app"]},
            "nothing is open to focus, so open it")
    declare("desktop.launch", "desktop.focus", lambda a: {"app": a["app"]},
            "it may already be running, and focusing an open window is cheaper than a second copy")
    # "Find the file I mean." Substring matching and local relevance are different
    # searches, and a name the user half-remembers defeats only the first.
    declare("file.search", "file.semantic_search",
            lambda a: {k: a[k] for k in ("path", "query", "modified_after", "modified_before")
                       if a.get(k) is not None},
            "filename matching found nothing; bounded local relevance reads content too")
    # "Tell me what is on the screen." OCR is the mechanism that goes missing on a
    # machine without tesseract; the pixels are still there. Degraded: a picture
    # is not the text, and the report says so rather than implying it read it.
    declare("screen.read", "screen.capture", lambda a: {"window_id": a["window_id"]} if a.get("window_id") else {},
            "text recovery is unavailable, so keep the frame itself as evidence", degraded=True)
    # "Get this text into the application." AT-SPI insertion is refused by
    # non-editable and password controls; the clipboard still carries it. Degraded:
    # the text is on the clipboard, not in the control, and that is a weaker end.
    declare("input.type_text", "input.clipboard_write", lambda a: {"text": a["text"]},
            "the control refused insertion; the text is put on the clipboard to paste", degraded=True)


_register()
