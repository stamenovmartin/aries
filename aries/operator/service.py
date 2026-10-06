"""The Operator's loop: plan → act → observe → verify → report.

THE ONE RULE
------------
**What the Operator reports is what the machine says, not what the Operator
did.** Every step therefore carries two separate facts that are never merged:

    reported    the tool came back saying it worked
    verified    ARIES looked at the desktop afterwards and confirmed it

The difference between them is the **honesty gap**, and it is the measurement
this milestone exists to make. A system that only records the first number
cannot tell the difference between working and appearing to work — which is
exactly the failure M13 shipped with 1,511 green assertions.

SETTLING, AND WHY IT IS NOT CHEATING
------------------------------------
An application takes time to map a window. Verifying the instant after
`gtk-launch` returns would report `unmet` for something that succeeds 800 ms
later, which would make the measurement wrong in the *flattering* direction for
the naive baseline and the *unflattering* direction for this one.

So verification polls until the goal is met or `operator.settle_seconds`
elapses, and the elapsed time is recorded. The deadline is a declared constant,
identical for every variant in the experiment, and "how long it took to become
true" is one of the results rather than a detail hidden inside a sleep.

THE WORKING SET
---------------
Everything the Operator pulls in to do a task goes to `aries_working_set` under
the task's id and is released when the task ends — success, failure or refusal.
Today that is the observations it took; when the Operator starts reading mail it
will be mail. The seam is here now so that it is not retrofitted later, which is
when it would be forgotten.

WHAT ACTS AND WHAT ASKS
-----------------------
A plan from the deterministic router is exact: the pattern matched, the section
or automation is named, there is nothing to be wrong about. It runs.

A plan from a model is a guess, however good. By default it is **proposed, not
performed** (`operator.confirm_model_plans`), because the interesting failure is
not the model refusing — it is the model answering plausibly. "Reformat my hard
drive" was answered, by a competent 7B model, with "open the System screen".
Nothing about that is dangerous on its own; what is dangerous is a system that
would have carried it out and reported success.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from aries.operator import desktop as desktop_mod
from aries.operator import goals, plan as plan_mod

logger = logging.getLogger(__name__)

# How often to look while waiting for a goal to become true. Short enough that
# the latency measurement is not quantised into uselessness, long enough that
# ARIES is not hammering D-Bus.
POLL_INTERVAL_S = 0.4


@dataclass
class StepOutcome:
    """One step, with the two facts kept apart."""

    step: plan_mod.Step
    reported: bool                     # what the tool said
    report_detail: str
    verification: goals.Verification
    seconds: float
    gate: str = ""                     # which gate refused it, if one did
    observations: int = 1

    @property
    def honest(self) -> bool:
        """Did the report and the verification agree?

        `unverifiable` is not dishonest — ARIES saying "I cannot confirm this"
        is the correct answer, not a mismatch. Only a reported success that the
        desktop contradicts counts.
        """
        if self.verification.verdict == goals.UNVERIFIABLE:
            return True
        return self.reported == self.verification.met

    def as_dict(self) -> dict:
        return {**self.step.as_dict(), "reported": self.reported,
                "report_detail": self.report_detail, "gate": self.gate,
                "verification": self.verification.as_dict(),
                "seconds": round(self.seconds, 2), "observations": self.observations,
                "honest": self.honest}


@dataclass
class Run:
    """One request, start to finish."""

    request: str
    plan: plan_mod.Plan
    steps: list[StepOutcome] = field(default_factory=list)
    task_id: str = ""
    proposed: bool = False             # held for a human rather than performed
    seconds: float = 0.0

    @property
    def reported_success(self) -> bool:
        return bool(self.steps) and all(s.reported for s in self.steps)

    @property
    def verified_success(self) -> bool:
        return bool(self.steps) and all(s.verification.met for s in self.steps)

    @property
    def unverifiable(self) -> bool:
        return any(s.verification.verdict == goals.UNVERIFIABLE for s in self.steps)

    @property
    def honesty_gap(self) -> bool:
        """Reported success that the machine CONTRADICTED.

        Not merely "could not confirm". ARIES saying "I did it and cannot check"
        is the honest answer to a missing observation, and counting it as
        dishonesty would punish exactly the behaviour this design is for — while
        making the metric useless, since it would then be dominated by whether
        the user happens to be in the ARIES session.

        The gap is: the tool said yes, ARIES looked, and what it saw said no.
        """
        return any(s.reported and s.verification.verdict == goals.UNMET
                   for s in self.steps)

    @property
    def held(self) -> str:
        """The gate that stopped a step, if one did."""
        for step in self.steps:
            if step.gate and not step.reported:
                return step.gate
        return ""

    @property
    def outcome(self) -> str:
        """The single word a person gets. `done` is reserved for verified.

        `held` is separate from `failed` on purpose. A step stopped by the
        action budget, the approval gate or the policy did not fail to plan and
        did not fail to act — it was refused, deliberately, by a rule that
        exists. Folding those together made an experiment run look like a
        planner collapsing when it was a rate limiter doing its job.
        """
        if self.proposed:
            return "proposed"
        if not self.plan.ok:
            return "refused"
        if self.verified_success:
            return "done"
        if self.held:
            return "held"
        if self.unverifiable and self.reported_success:
            return "unconfirmed"
        return "failed"

    def summary(self) -> str:
        if self.proposed:
            return "ARIES has a plan and is waiting for you to approve it"
        if not self.plan.ok:
            return self.plan.refusal or "ARIES does not know how to do that"
        if self.verified_success:
            grades = {s.verification.grade for s in self.steps}
            best = min(grades, key=lambda g: goals.GRADE_RANK[g])
            return f"done — confirmed by {best} evidence"
        if self.held:
            detail = next((s.report_detail for s in self.steps if s.gate), "")
            return f"held at the {self.held} gate — {detail}"
        if self.unverifiable and self.reported_success:
            return ("ARIES did it and cannot confirm it: "
                    + next(s.verification.found for s in self.steps
                           if s.verification.verdict == goals.UNVERIFIABLE))
        failed = next((s for s in self.steps if not s.verification.met), None)
        return f"not done — {failed.verification.found}" if failed else "not done"

    def as_dict(self) -> dict:
        return {"request": self.request, "outcome": self.outcome,
                "summary": self.summary(), "plan": self.plan.as_dict(),
                "steps": [s.as_dict() for s in self.steps],
                "reported_success": self.reported_success,
                "verified_success": self.verified_success,
                "honesty_gap": self.honesty_gap,
                "unverifiable": self.unverifiable,
                "proposed": self.proposed, "held": self.held, "task_id": self.task_id,
                "seconds": round(self.seconds, 2)}


# ── settings the loop reads ─────────────────────────────────────────────────

async def _config(db: AsyncSession) -> dict:
    from aries.settings import SettingsService
    s = SettingsService(db)
    return {
        "enabled": bool(await s.get("operator.enabled")),
        "settle_seconds": float(await s.get("operator.settle_seconds")),
        "confirm_model_plans": bool(await s.get("operator.confirm_model_plans")),
        "model_location": str(await s.get("operator.model_location")),
        "planner": str(await s.get("operator.planner")),
        "max_actions_per_hour": int(await s.get("operator.max_actions_per_hour")),
    }


def _arm(enabled: bool, *, max_actions_per_hour: int | None = None, extra_tools: tuple[str, ...] = ()) -> dict:
    """Point the engine's execution gates at ARIES's own switch.

    The engine holds every side-effecting tool unless it is named in
    `live_tools`, and simulates everything while `dry_run` is on. Those are the
    right gates and they stay the enforcement — but their controls are
    environment variables, and a person cannot consent to an environment
    variable they have never seen.

    So ARIES drives them from `operator.enabled`, and does it HERE, on every
    run, rather than once at startup: a gate armed at boot goes stale the moment
    the user changes their mind, and the failure of a stale arming is that ARIES
    acts after being switched off.
    """
    from agentic_core.config import runtime
    from aries.operator.tools import TOOL_NAMES

    from agentic_core.config.settings import settings

    dry_run = not enabled
    live = ",".join((*TOOL_NAMES, *extra_tools)) if enabled else ""
    if max_actions_per_hour:
        # The engine's frequency cap, set from ARIES's own setting. Same reason
        # as the live gate: the rule is right, and a person cannot consent to an
        # environment variable. Reaching it must read as "held by the budget",
        # never as "the plan failed" — which is what it looked like the first
        # time it fired, in the middle of an experiment.
        settings.max_actions_per_hour = int(max_actions_per_hour)
    runtime.set_dry_run(dry_run)
    runtime.set_live_tools(live)
    # What was WRITTEN, not what reads back. In a test process the engine lets
    # the environment win over the runtime file on purpose, so that a stray
    # runtime state cannot wire a test to live execution — which means reading
    # these back in a test would measure the harness rather than the arming.
    return {"dry_run": dry_run, "live_tools": live}


# ── the loop ────────────────────────────────────────────────────────────────

async def run(db: AsyncSession, request: str, *, dry_run: bool = False,
              approve: bool = False, prepared_plan: dict | None = None, dashboard_goal_id: str | None = None) -> Run:
    """Carry out one request, and report what the machine says happened.

    `approve=True` is a human saying "yes, do the model's plan" — it is the only
    thing that makes a model-derived plan act while `operator.confirm_model_plans`
    is on. It is not a way past any of the tool gates, which still apply.
    """
    t0 = time.monotonic()
    cfg = await _config(db)
    task_id = f"operator-{int(time.time() * 1000)}"

    _arm(cfg["enabled"] and not dry_run,
         max_actions_per_hour=cfg["max_actions_per_hour"])
    # Point the engine at the model ARIES's settings name, before planning asks
    # for one. Local by default, and it refuses rather than falling back.
    from aries import intelligence
    await intelligence.arm(db)

    if prepared_plan is not None:
        # Only the durable workspace passes this, after displaying and approving it.
        raw = {"steps": [{"goal": step["goal"], **step["params"]} for step in prepared_plan.get("steps", [])]}
        steps, refusal = plan_mod._steps_from(raw)
        made = plan_mod.Plan(request=request, steps=steps, refusal=refusal, source="model", model=prepared_plan.get("model", ""))
    else:
        made = await plan_mod.make(
            request,
            require_local=cfg["model_location"] == "local",
            allow_model=cfg["planner"] != "router")
    if dashboard_goal_id:
        for step in made.steps:
            if step.goal == "open_section" and step.params.get("section") == "dashboard":
                step.payload["goal_id"] = dashboard_goal_id
    run = Run(request=request, plan=made, task_id=task_id)

    try:
        await _remember(db, task_id, "the request", "user", request)

        if not made.ok:
            run.seconds = time.monotonic() - t0
            return run

        if not cfg["enabled"] and not dry_run:
            run.plan.refusal = ("the ARIES Operator is switched off — turn on "
                                "operator.enabled to let ARIES act on this desktop")
            run.plan.steps = []
            run.seconds = time.monotonic() - t0
            return run

        # A guess is proposed; an exact match is performed.
        if made.source == "model" and cfg["confirm_model_plans"] and not approve:
            run.proposed = True
            await _remember(db, task_id, "the proposed plan", "operator",
                            _plan_text(made))
            run.seconds = time.monotonic() - t0
            return run

        for step in made.steps:
            run.steps.append(await _do(db, step, task_id, cfg, dry_run=dry_run))
            # A step whose goal is not met makes the rest of the plan
            # meaningless — "open the page, then search it" cannot continue if
            # the page never opened. Stop and say where.
            if not run.steps[-1].verification.met and not dry_run:
                break

        run.seconds = time.monotonic() - t0
        await _record(db, run)
        return run
    finally:
        # The task is over, whatever happened. Same rule as every other task:
        # what it borrowed goes now, not on a timer.
        from aries.lifecycle import working
        try:
            await working.release(db, task_id)
            await db.commit()
        except Exception:                            # noqa: BLE001
            logger.exception("could not release the operator's working set")


async def _do(db: AsyncSession, step: plan_mod.Step, task_id: str, cfg: dict,
              *, dry_run: bool) -> StepOutcome:
    """One step: act, then watch the machine until it agrees or time runs out."""
    from agentic_core.tools.calling import call_tool

    t0 = time.monotonic()
    since = datetime.now(timezone.utc).replace(tzinfo=None)

    if dry_run:
        observed = desktop_mod.observe()
        verification = await goals.verify(step.goal, step.params, observed, db)
        return StepOutcome(step=step, reported=False,
                           report_detail="dry run — nothing was done",
                           verification=verification, seconds=time.monotonic() - t0,
                           gate="dry_run")

    result = await call_tool(db, step.tool, step.payload, task_id=None, actor="operator")
    reported = bool(result.get("success")) and not result.get("skipped")
    gate = str(result.get("gate") or "")
    if gate:
        logger.info("operator: %s was held at the %s gate: %s", step.tool, gate, detail
                    if (detail := str(result.get("details") or "")) else "")
    detail = str(result.get("details") or "")[:300]
    await _remember(db, task_id, f"{step.tool} said", step.tool, detail)

    # `run_automation` verifies against a run row, so it needs to know which runs
    # are new. Everything else compares against the desktop as it is now.
    params = dict(step.params)
    if step.goal == "run_automation":
        params["since"] = since

    verification, observations = await _watch(step.goal, params, db,
                                              seconds=cfg["settle_seconds"])
    return StepOutcome(step=step, reported=reported, report_detail=detail,
                       verification=verification, seconds=time.monotonic() - t0,
                       gate=gate, observations=observations)


async def _watch(goal: str, params: dict, db, *, seconds: float
                 ) -> tuple[goals.Verification, int]:
    """Look until the goal is met, or until the settle window closes.

    Returns the LAST verification, not the best one: if the goal became true and
    then stopped being true, what is true now is the honest answer.
    """
    deadline = time.monotonic() + max(seconds, 0.0)
    observations = 0
    verification = None
    while True:
        observed = desktop_mod.observe()
        verification = await goals.verify(goal, params, observed, db)
        observations += 1
        if verification.met or time.monotonic() >= deadline:
            return verification, observations
        # Unverifiable will not become verifiable by waiting — the window list
        # is not going to appear. Waiting out the full window would only add
        # latency to an answer that is already final.
        if verification.verdict == goals.UNVERIFIABLE:
            return verification, observations
        await asyncio.sleep(POLL_INTERVAL_S)


def _plan_text(made: plan_mod.Plan) -> str:
    lines = []
    for i, step in enumerate(made.steps, 1):
        goal = goals.get(step.goal)
        lines.append(f"{i}. {goal.describe(step.params) if goal else step.goal}")
    return "\n".join(lines)


async def _remember(db: AsyncSession, task_id: str, label: str, source: str,
                    content: str) -> None:
    """Hold something for the duration of this task. Never a conclusion."""
    from aries.lifecycle import working
    try:
        await working.put(db, task_id, label=label, source=source,
                          content=content or "", sensitive=True)
        await db.commit()
    except Exception:                                # noqa: BLE001
        logger.exception("could not hold '%s' in the working set", label)


async def _record(db: AsyncSession, run: Run) -> None:
    """Audit what the Operator did, including where it was not believed.

    The honesty gap is written into the audit event rather than computed later,
    because it is the one number nobody should have to reconstruct.
    """
    from agentic_core.observability.audit import log_event
    try:
        await log_event(
            db, actor_type="system", actor="aries:operator", action="operator.ran",
            detail={"request": run.request[:300], "outcome": run.outcome,
                    "source": run.plan.source, "model": run.plan.model,
                    "reported_success": run.reported_success,
                    "verified_success": run.verified_success,
                    "honesty_gap": run.honesty_gap,
                    "steps": [{"goal": s.step.goal, "tool": s.step.tool,
                               "reported": s.reported,
                               "verdict": s.verification.verdict,
                               "grade": s.verification.grade} for s in run.steps]})
        await db.commit()
    except Exception:                                # noqa: BLE001
        logger.exception("could not record the operator run")
