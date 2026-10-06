"""The Attention Pass — what ARIES read, and what of it needs you.

WHY THIS IS THE FIRST REAL ORCHESTRATION IN ARIES
-------------------------------------------------
Everything before it was one step: measure the machine, fetch feeds, run a
health check. This is the first automation that is genuinely a *pipeline* with a
judgement in the middle, and it runs through the engine's task lifecycle — so it
gets retries, replans, escalation to a human, evaluators and a trace, none of
which this file implements.

    collect     read every connected source into the working set
    understand  ask the LOCAL model what each item is — summary and category
                only, never an action (see untrusted.py)
    weigh       rank by urgency and what the user said they care about
    report      one answer: what needs you, what can wait, what was noise

THE JUDGEMENT IS NOT THE MODEL'S
--------------------------------
The model says "this looks like it needs action, urgency: today". Whether that
reaches the user is decided by ARIES's own notification policy, the interest
profile and quiet hours — the same three gates every other notification passes.
A model that could notify directly would be a model that could be made to notify
by anyone who can send mail.

WHAT IT NEVER DOES
------------------
Reply, forward, delete, mark as read, or act on anything it read. It reports.
Every action remains the Operator's, through the fixed goal vocabulary, with a
confirmation. That is the boundary that makes reading mail safe at all.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from agentic_core.evaluators.base import Evaluator, issue
from agentic_core.orchestrator.lifecycle import LifecyclePolicy
from agentic_core.scheduler.queue import register_kind
from agentic_core.security.permissions import Permission
from agentic_core.workflows import spec as wf

from aries.automations.genome import AutomationSpec, register
from aries.settings.schema import SettingDef, define

logger = logging.getLogger(__name__)

AUTOMATION_ID = "aries.attention"
TASK_KIND = "aries.attention.pass"
WORKFLOW = "aries.attention"

define(SettingDef("connect.attention_enabled", bool, False, "Attention Pass",
                  "Read the sources you have connected, understand each item on the local "
                  "model, and tell you what needs you. Reports only — it never replies, "
                  "forwards, deletes or marks anything as read.",
                  "connect", control="toggle", user_only=True))

define(SettingDef("connect.attention_interval_minutes", int, 60, "How often to look",
                  "How often the Attention Pass reads your connected sources.",
                  "connect", control="number", minimum=5, maximum=1440, unit="minutes",
                  advanced=True))

# Which categories are worth interrupting a person for. Declared rather than
# hard-coded in a branch so the vocabulary and the policy stay in one place.
NEEDS_YOU = ("action_needed",)
WORTH_SAYING = ("action_needed", "suspicious")
URGENCY_ORDER = {"now": 0, "today": 1, "this_week": 2, "whenever": 3, "none": 4}


async def collect(ctx: dict) -> dict:
    """Read every enabled connected source into this task's working set."""
    from agentic_core.database.base import async_session

    from aries.connect import base, service
    from aries.sources import service as sources

    task_id = str(ctx.get("task_id") or "attention")
    read, failures = [], []
    async with async_session() as db:
        rows = await sources.list_sources(db, enabled=True)
        for source in rows:
            if not base.have(source.type):
                continue                   # described, not readable — not a failure
            try:
                out = await service.read(db, source.source_id, task_id=task_id)
            except service.NotConnected as exc:
                failures.append({"source_id": source.source_id, "why": str(exc)[:200]})
                continue
            read.append(out)
    ctx["read"] = read
    ctx["failures"] = failures
    ctx["sources_considered"] = len(read) + len(failures)
    return ctx


async def understand(ctx: dict) -> dict:
    """Ask the local model what each item is. One call per item, bounded."""
    from agentic_core.database.base import async_session

    from aries.connect import base, service
    from aries.sources import service as sources

    understood = []
    async with async_session() as db:
        for batch in ctx.get("read") or []:
            source = await sources.get(db, batch["source"])
            connector = base.get(source.type) if source else None
            if connector is None:
                continue
            # Re-read from the connector rather than from the batch: the batch
            # carries descriptions, and the body lives in the working set. This
            # keeps the rule that bodies never travel in a return value.
            items = await connector.read(source, limit=len(batch["items"]))
            for item in items:
                verdict = await service.understand(db, item)
                understood.append({
                    "item_id": item.item_id, "title": item.title,
                    "source_id": source.source_id, "source_type": source.type,
                    "author": item.author,
                    "at": item.at.isoformat() if item.at else None,
                    **{k: verdict.get(k) for k in
                       ("understood", "why", "summary", "category", "urgency",
                        "about", "mentions_deadline")},
                    "injection_attempts": verdict.get("attempts") or [],
                })
    ctx["understood"] = understood
    return ctx


async def weigh(ctx: dict) -> dict:
    """Rank what was understood. Deterministic — the model scored nothing.

    The model said what each item IS. What matters is ARIES's decision, made
    from the user's own interest profile and a declared urgency order, so that a
    piece of content cannot promote itself by claiming to be urgent.
    """
    from agentic_core.database.base import async_session

    from aries.interests import service as interests

    items = list(ctx.get("understood") or [])
    async with async_session() as db:
        # `Matchable`, not a dict — the matcher's own shape, so the weights here
        # are the same numbers the interest profile actually scores with.
        profile = {m.key.lower(): (0.0 if m.avoid else float(m.weight))
                   for m in await interests.profile(db)}

    for item in items:
        urgency = URGENCY_ORDER.get(str(item.get("urgency") or "none"), 4)
        topics = [str(t).lower() for t in (item.get("about") or []) if t]
        interest = max((profile.get(t, 0.0) for t in topics), default=0.0)
        # An item that tried to give ARIES instructions is surfaced regardless
        # of what it claims to be about: the user wants to know someone tried.
        suspicious = bool(item.get("injection_attempts"))
        item["rank"] = (0 if suspicious else 1, urgency, -interest)
        item["interest"] = round(interest, 2)
        item["suspicious"] = suspicious

    items.sort(key=lambda i: i["rank"])
    ctx["needs_you"] = [i for i in items
                        if i.get("category") in NEEDS_YOU or i["suspicious"]]
    ctx["can_wait"] = [i for i in items if i not in ctx["needs_you"]]
    return ctx


async def report(ctx: dict) -> dict:
    """One answer, and one notification at most.

    Through the notification policy, not around it: quiet hours, the repeat gate
    and severity all apply. A model that could notify directly would be a model
    that could be made to notify by anyone who can send mail.
    """
    from agentic_core.database.base import async_session

    from aries.notify import policy as notify
    from aries.settings import SettingsService

    needs = ctx.get("needs_you") or []
    wait = ctx.get("can_wait") or []
    attempts = sum(len(i.get("injection_attempts") or []) for i in needs + wait)
    unread_model = [i for i in needs + wait if not i.get("understood")]

    if not (needs or wait):
        summary = (f"nothing to read from {ctx.get('sources_considered', 0)} source(s)"
                   if ctx.get("sources_considered") else "no source is connected yet")
    else:
        summary = (f"{len(needs)} need(s) you, {len(wait)} can wait, "
                   f"from {ctx.get('sources_considered', 0)} source(s)")
        if attempts:
            summary += f", {attempts} instruction attempt(s) in the content"
        if unread_model:
            summary += f", {len(unread_model)} not understood"

    if needs:
        async with async_session() as db:
            cfg = await SettingsService(db).section("notifications")
            title = needs[0]["title"][:200]
            body = "\n".join(
                f"· {i['title'][:90]} — {str(i.get('summary') or '')[:120]}"
                for i in needs[:5])
            await notify.emit(
                db, key=f"attention:{datetime.now(timezone.utc):%Y-%m-%d-%H}",
                title=(f"{len(needs)} thing(s) need you" if len(needs) > 1 else title),
                severity=notify.Severity.NOTICE, source=AUTOMATION_ID,
                body=body, config=cfg)
            await db.commit()

    return {"result": {
        "success": True, "status": "ok", "summary": summary,
        "needs_you": [_public(i) for i in needs[:20]],
        "can_wait": [_public(i) for i in wait[:20]],
        "injection_attempts": attempts,
        "not_understood": len(unread_model),
        "sources_considered": ctx.get("sources_considered", 0),
        "failures": ctx.get("failures") or [],
    }}


def _public(item: dict) -> dict:
    """What may leave this automation. Summaries and categories — never a body.

    The body is in the working set and is released when the task ends. Letting
    one out here would put the contents of a mailbox into a run record that
    nothing ever deletes.
    """
    return {k: item.get(k) for k in
            ("item_id", "title", "source_id", "source_type", "author", "at",
             "summary", "category", "urgency", "about", "mentions_deadline",
             "interest", "suspicious", "injection_attempts", "understood", "why")}


async def run_pass(ctx: dict) -> dict:
    """The whole pass in one call — for the CLI and for tests.

    The scheduled path does NOT come through here: it runs the workflow below,
    so every node's decision is persisted and a failure names the step it
    happened in. This exists because "read my sources once, now" is a reasonable
    thing to ask for without a task, and duplicating the four calls in a CLI
    command is how the two would drift.
    """
    ctx = await collect(ctx)
    ctx = await understand(ctx)
    ctx = await weigh(ctx)
    return await report(ctx)


# ── the workflow (§9, §10) ──────────────────────────────────────────────────
#
# A graph rather than a function, for the reason the News Radar is one: every
# node's decision is persisted, so a pass that produced nothing can be asked
# WHERE it produced nothing — the sources were unreachable, the model did not
# answer, or there was genuinely nothing to say. Those need different fixes and
# a single `run()` reports them identically.

@wf.gate("attention_read_something")
def _read_something(ctx) -> tuple[bool, str]:
    n = sum(batch.get("count", 0) for batch in (ctx.get("read") or []))
    return bool(n), f"{n} item(s) read" if n else "nothing was read from any source"


@wf.gate("attention_understood_something")
def _understood_something(ctx) -> tuple[bool, str]:
    n = sum(1 for i in (ctx.get("understood") or []) if i.get("understood"))
    return bool(n), f"{n} item(s) understood" if n else "the local model answered for none"

SPEC_WF = wf.register(wf.WorkflowSpec(
    WORKFLOW,
    description="Read the connected sources, understand each item on the local model, "
                "rank what was found against the user's own interests, and report what "
                "needs them — without ever acting on any of it.",
    nodes=[
        wf.NodeSpec("collect", label="Read the connected sources", fn=collect),
        wf.NodeSpec("understand", label="Understand each item, locally", fn=understand,
                    depends_on=["collect"], gate="attention_read_something"),
        wf.NodeSpec("weigh", label="Rank against my interests", fn=weigh,
                    depends_on=["understand"], gate="attention_understood_something"),
        # Depends on COLLECT, not on weigh — the lesson the News Radar learned
        # expensively. The step that REPORTS must not be skippable by the
        # conditions it is reporting on, or a pass in which nothing worked is
        # recorded as a success with an empty result.
        wf.NodeSpec("report", label="Say what needs me", fn=report,
                    depends_on=["collect"]),
    ]))


# ── evaluators: did the PASS work, separately from what it found ────────────

async def _pass_worked(result, task, ctx) -> list:
    """A pass that read nothing because nothing is connected has WORKED.

    The same distinction the health monitor is built around: whether the check
    ran and whether the news is good are independent questions. Every source
    failing is a broken pass; no sources at all is an empty one.
    """
    considered = (result or {}).get("sources_considered", 0)
    failures = (result or {}).get("failures") or []
    if considered and len(failures) >= considered:
        return [issue("error", "all_sources_failed",
                      f"every connected source failed ({len(failures)} of {considered})")]
    return [issue("warn", "source_failed", f["why"]) for f in failures[:5]]


async def _understood_enough(result, task, ctx) -> list:
    """'Nothing needs you' and 'I could not read any of it' are different facts,
    and only one of them is reassuring."""
    total = (len((result or {}).get("needs_you") or [])
             + len((result or {}).get("can_wait") or []))
    missed = (result or {}).get("not_understood", 0)
    if total and missed == total:
        return [issue("error", "nothing_understood",
                      "the local model answered for none of the items — this is not "
                      "an empty inbox, it is an unread one")]
    if missed:
        return [issue("warn", "partly_understood",
                      f"{missed} of {total} item(s) were not understood")]
    return []


EVALUATORS = [
    Evaluator("the_pass_ran", _pass_worked, weight=2.0),
    Evaluator("understanding", _understood_enough, weight=1.0),
]

SPEC = register(AutomationSpec(
    automation_id=AUTOMATION_ID,
    name="Attention Pass",
    version="1.0.1",
    purpose="Read the folders and mailboxes you connected, understand each item on the "
            "local model, and say what needs you. Reports only — it never replies, "
            "forwards, deletes or marks anything as read.",
    run=run_pass,
    trigger="schedule",
    schedule_setting="connect.attention_interval_minutes",
    default_interval_minutes=60,
    conditions=["connect.enabled is on", "at least one source has a connector"],
    input_sources=["directory", "documents", "repository", "email"],
    task_kind=TASK_KIND,
    agents=[],
    tools=[],
    permissions=[Permission.VIEW_DATA],
    memory_dependencies=["aries_working_set", "aries_interests"],
    enabled_setting="connect.attention_enabled",
    writes_settings=[],
    # Medium: it reads personal content. It changes nothing, which is why it is
    # not high — but "read my mail" is not a low-risk sentence.
    risk="medium",
    # One local-model call per connected item can keep CPU inference busy for
    # minutes. This is a batch, not one lightweight classification request.
    workload="heavy_cpu",
    requires_approval=False,
    evaluation_metrics=["items_read", "understood_rate", "needs_you_precision",
                        "injection_attempts_detected"],
    reward_signals=["user acted on something it surfaced",
                    "user dismissed a surfaced item as noise",
                    "something it filed as 'can wait' turned out to be urgent"],
))

register_kind(TASK_KIND, workflow=WORKFLOW, evaluators=EVALUATORS,
              # Reading is idempotent and cheap to repeat, but a model that
              # failed once will usually fail again in the same minute; one
              # retry, then report honestly.
              policy=LifecyclePolicy(max_retries=1, max_replans=0, pass_threshold=0.6))
