"""Bounded goal execution. Content is evidence, never executable instructions."""
import asyncio
import json
import re
import uuid
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit
from sqlalchemy import select, update
from agentic_core.database.base import async_session
from agentic_core.database import writer
from agentic_core.observability.audit import log_event
from aries.settings import SettingsService
from aries.workspace.models import WorkspaceGoal

ACTIVE = {"queued", "running"}
_lock = asyncio.Lock()
_tasks = {}
_supervisors = {}
_resources = {}
MAX_CONCURRENT = 3
RESEARCH = re.compile(r"\b(research|investigate|dashboard|news about|find .*about|istrazi|istraži|vesti|najdi|истражи|вести|најди|дашборд|prepare me)\b", re.I)
OPEN = re.compile(r"^(?:please\s+)?(?:open|launch|start|otvori|отвори|пушти|pusti)\s+", re.I)

def plan(request):
    from aries.workspace.capabilities import recognize
    whole = recognize(request)
    if whole and whole["capability"] in {"system", "processes", "create_file", "remember", "build_python", "browser_fill", "agent_task"}:
        return [{"kind": "capability", "request": request, **whole}]
    # Natural multi-step requests not recognized by the deterministic vocabulary
    # enter the same queue as a capability agent. Keep explicit legacy workflows.
    from aries.workspace.contracts import compile_goal
    contract = compile_goal(request, str(__import__('pathlib').Path.home()/'Documents/ARIES-Demo'))
    if (contract['supported'] and (not whole or len(contract['requirements']) > 1 or contract.get('answer'))) or (not whole and not re.search(r';|\bthen\b', request, re.I)):
        return [{'kind':'capability','capability':'agent_task','args':{'task':request},'request':request}]
    clauses = [x.strip() for x in re.split(r"\s*(?:;(?=\s)|\n|\band then\b|\bthen\b|\band (?=open |launch )|\bi (?=otvori )|\bи (?=отвори ))\s*", request, flags=re.I) if x.strip()]
    if len(clauses) > 6:
        raise ValueError("Use at most six steps in one request")
    from aries.workspace.capabilities import recognize
    seen = [(clause, recognize(clause)) for clause in clauses]
    # A COMPOUND WHOSE CLAUSES THE VOCABULARY DOES NOT ALL RECOGNISE IS NOT SPLIT.
    #
    # Splitting it was the defect behind five of the agent suite's multi-step failures.
    # "what is the state of the user service aries-core.service" ALONE routes to
    # `agent_task` eight lines above, is planned, and comes back `verified`. The same
    # clause inside "A; B" fell to `kind: desktop`, whose operator chose the
    # approval-gated `service_control` with no arguments, so the goal sat at `proposed`
    # with no evidence at all.
    #
    # Two narrower fixes were tried first and both measured WORSE, so they are named
    # here rather than repeated. Routing the clause to `agent_task` in place: any
    # `agent_task` step makes the whole goal an m14 agent goal, the agent consumed only
    # the first clause, and three goals turned from honest failures into FALSE
    # SUCCESSES — partial success reported with `steps=1` for a two-clause request.
    # Fanning the clauses out as child goals: `orchestration.fan_out` validates every
    # sub-goal against the capability registry, which has no `agent_task`, so the API
    # answered `400 Unknown capability: agent_task` for all five.
    #
    # Not splitting is what is left, and it is also what the planner is for: it decides
    # one step, executes, reads the verifier, and decides the next. A two-part request
    # is two steps of that loop, and the contract covers both requirements at once.
    # Compounds whose clauses are ALL recognised keep the split, because the
    # deterministic path already handles them and does not need a model.
    if any(found is None and not RESEARCH.search(clause) for clause, found in seen):
        return [{'kind': 'capability', 'capability': 'agent_task',
                 'args': {'task': request}, 'request': request}]
    steps = []
    for clause, recognized in seen:
        if recognized:
            kind = "research" if recognized["capability"] in {"research", "dashboard"} else "capability"
        else:
            kind = "research"
        steps.append({"kind": kind, "request": clause, **(recognized or {})})
    return steps

def safe_link(url):
    try:
        p = urlsplit(url)
        return bool(p.scheme in ("http", "https") and p.hostname and not p.username and not p.password)
    except ValueError:
        return False

async def audit(db, action, detail):
    await log_event(db, actor_type="system", actor="aries:workspace", action=action, detail=detail)

async def submit(db, request, *, capability=None, args=None, present=False, intelligence_routing=None, evaluation_architecture=None, origin=None):
    origin='unknown' if origin is None else origin
    if not isinstance(origin,str) or not origin or len(origin)>120:
        raise ValueError('A goal needs a valid submission origin')
    from agentic_core.security import principal
    from agentic_core.security.permissions import Permission
    who = principal.current()
    if who is not None and not who.can(Permission.MANAGE_TOOLS):
        raise ValueError("Submitting executable goals needs manage_tools permission")
    structured = None
    if capability is not None:
        from aries.workspace.capabilities import validate_action
        structured, request = validate_action(capability, args or {})
    request = request.strip()
    if not request or len(request) > 2000:
        raise ValueError("A goal needs between 1 and 2000 characters")
    if not await SettingsService(db).get("workspace.enabled"):
        raise ValueError("Goal dashboards are switched off")
    reference = None
    if structured is None:
        from aries.workspace.clarification import question
        clarification = question(request)
        from aries.workspace.working_context import resolve
        if clarification is None:
            try:
                request, reference = await resolve(db, request)
            except ValueError as exc:
                if not str(exc).startswith('AMBIGUOUS:'):
                    raise
                clarification = question(request, unresolved_reference=True)
        if clarification is None:
            from aries.workspace.capabilities import missing_reference
            from aries.workspace.clarification import reference_question
            missing = missing_reference(request)
            if missing:
                clarification = reference_question(request, missing)
        if clarification is not None:
            data = {'steps': [], 'cards': [{'title': clarification['question'],
                    'text': '\n'.join(clarification['choices'])}], 'gaps': [],
                    'clarification': clarification, 'summary': clarification['question']}
            if origin:
                data['origin'] = origin
            row = WorkspaceGoal(id=uuid.uuid4().hex, request=request,
                                state='needs_clarification', result_json=json.dumps(data))
            db.add(row)
            await audit(db, 'workspace.clarification_requested', {'id': row.id, 'steps': 0})
            await db.commit()
            await db.refresh(row)
            return row.as_dict()
        # Independent measurement questions may run together without asking a
        # model to invent dependencies or authorise mutations.
        from aries.workspace import contracts
        from aries.workspace.measurement_requests import questions
        clauses = questions(request) or []
        compiled = [contracts.compile_goal(part, '') for part in clauses]
        if clauses and all(c.get('answer') == 'measurements' for c in compiled):
            from aries.workspace.orchestration import fan_out
            result = await fan_out(db, request, [
                {'capability': c['requirements'][0]['capability'], 'args': {}, 'request': part}
                for part, c in zip(clauses, compiled)], source=origin or 'user', present=present,
                check_loop=False)  # shell/act already charged this utterance once.
            return (await db.get(WorkspaceGoal, result['id'])).as_dict()
    steps = [structured] if structured else plan(request)
    pending = (await db.execute(select(WorkspaceGoal.id).where(WorkspaceGoal.state.in_(ACTIVE)).limit(20))).all()
    if len(pending) >= 20:
        raise ValueError("The goal queue is full; finish or cancel a task first")
    row = WorkspaceGoal(id=uuid.uuid4().hex, request=request,
                        result_json=json.dumps({"steps": steps, "cards": [], "gaps": [], "present_dashboard": present,
                                                "agent_engine":"m14" if any(s.get('capability')=='agent_task' for s in steps) else None}))
    if reference:
        data=json.loads(row.result_json);data['working_reference']=reference;row.result_json=json.dumps(data)
    if origin:
        data=json.loads(row.result_json);data['origin']=origin;row.result_json=json.dumps(data)
    if intelligence_routing:
        data=json.loads(row.result_json);data['routing']=intelligence_routing
        data['evaluation_architecture']=evaluation_architecture;row.result_json=json.dumps(data)
    db.add(row)
    from aries.intelligence.router import RuleDecisionProvider
    from aries.intelligence.tracking import record
    if intelligence_routing:
        await record(db,'route',**intelligence_routing,background=False,task_id=row.id)
    elif not any(s.get('capability') in {'agent_task','build_python','read_article'} or s.get('kind')=='research' for s in steps):
        decision=await RuleDecisionProvider().decide(db,request)
        routing={'execution_level':'code','source':'rule','intent':decision.intent if decision else 'UNKNOWN',
                 'tool':decision.tool if decision else 'workspace','confidence':1.0,'requires_cloud':False,
                 'estimated_complexity':'simple','reason':'Existing deterministic workspace plan'}
        data=json.loads(row.result_json);data['routing']=routing;row.result_json=json.dumps(data)
        await record(db,'route',**routing,background=False,task_id=row.id)
    await audit(db, "workspace.submitted", {"id": row.id, "steps": len(steps)})
    await db.commit()
    await db.refresh(row)
    # The unasked write. DEBOUNCED AND OFF THE PATH: this returns immediately,
    # and the cascade runs seconds later in its own session, so a request that
    # is acted on in 25 ms is never made to wait for an embedding or a model.
    # Whether anything is kept is decided in aries/workspace/memory/extraction.py.
    from aries.workspace.memory import store as memory_store
    if origin in memory_store.USER_SOURCES:
        memory_store.observe_later(request, source=origin)
    return row.as_dict()

async def snapshot(db, goal_id=None):
    from aries.workspace.memory import store as memory_store
    if goal_id:
        selected = await db.get(WorkspaceGoal, goal_id)
        goals = [selected] if selected else []
    else:
        goals = (await db.execute(select(WorkspaceGoal).order_by(WorkspaceGoal.created_at.desc()).limit(25))).scalars().all()
        pending = (await db.execute(select(WorkspaceGoal).where(WorkspaceGoal.state.in_(ACTIVE | {"proposed"})).order_by(WorkspaceGoal.created_at.desc()))).scalars().all()
        goals = sorted({g.id: g for g in [*goals, *pending]}.values(), key=lambda g: g.created_at, reverse=True)
    memories = await memory_list(db)
    memory_by_id = {m["id"]: m for m in memories}
    from aries.workspace.reviews import latest
    reviews = {r["goal_id"]:r for r in await latest(db, [g.id for g in goals])}
    rendered = []
    for row in goals:
        goal = row.as_dict()
        review = reviews.get(row.id)
        goal["review"] = {k:review[k] for k in ("id", "rating", "comment")} if review else None
        goal["context"] = [memory_by_id[m["id"]] for m in goal.get("context", []) if m.get("id") in memory_by_id]
        rendered.append(goal)
    runtime = {"available": False, "scope": "selected task only"} if goal_id else await runtime_state()
    return {"goals": rendered, "memories": [] if goal_id else memories,
            "conclusions": [] if goal_id else await conclusion_list(db),
            "memory_replacements": [] if goal_id else await memory_store.pending_replacements(db),
            "runtime": runtime,
            "auto_close_results": await SettingsService(db).get('workspace.auto_close_results'),
            "web_search": await SettingsService(db).get("workspace.web_search"),
            "scheduler": {"capacity": MAX_CONCURRENT, "running": len(_supervisors),
                          "resources": {k: sorted(v) for k, v in _resources.items()}}}

async def runtime_state():
    from aries.workspace import browser
    from aries.operator import desktop
    try:
        windows = await asyncio.wait_for(browser.inventory(), timeout=2)
        runtime = {"available": True, "browsers": windows, "observed_at": datetime.utcnow().isoformat()}
    except Exception as exc:
        runtime = {"available": False, "browsers": [], "reason": str(exc)[:200]}
    try:
        observed = await asyncio.wait_for(asyncio.to_thread(desktop.observe), 3)
        runtime['desktop'] = {'available': observed.can_see_windows,
            'windows': [w.as_dict() for w in (observed.windows or [])],
            'reason': observed.windows_unavailable}
    except Exception as exc:
        runtime['desktop'] = {'available': False, 'windows': [], 'reason': str(exc)[:200]}
    return runtime


def _excluded(text, topics):
    return any(str(t).casefold() in text.casefold() for t in topics if t)

async def memory_list(db):
    # No LIMIT. Scoring 10^4 memories is 1 ms of brute-force matrix multiply
    # (aries/workspace/memory/vectors.py), so a cap of 200 bought nothing and
    # silently made everything older than the 200th unrememberable.
    excluded = await SettingsService(db).get("privacy.excluded_memory_topics")
    from aries.workspace.memory import store
    rows = await store.utterances(db)
    return [r.as_dict() for r in rows if not _excluded(r.text, excluded)]

async def conclusion_list(db):
    """What ARIES concluded — a separate read, because it is a separate table."""
    excluded = await SettingsService(db).get("privacy.excluded_memory_topics")
    from aries.workspace.memory import store
    rows = await store.conclusions(db)
    return [r.as_dict() for r in rows if not _excluded(r.text, excluded)]

async def remember(db, text):
    from aries.workspace.memory import store
    row = await store.remember(db, text, source="user")
    await audit(db, "workspace.remembered", {"id": row.id, "source": "user"})
    await db.commit()
    return row.as_dict()

async def forget(db, memory_id):
    # Expire, never DELETE: "why did you stop thinking that?" must stay
    # answerable, and a mistaken forget must be one UPDATE from being undone.
    from aries.workspace.memory import store
    if not await store.forget(db, memory_id):
        return False
    await audit(db, "workspace.forgotten", {"id": memory_id, "method": "expired"})
    await db.commit()
    return True

async def cancel(db, goal_id):
    changed = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == goal_id, WorkspaceGoal.state.in_(ACTIVE | {"proposed"})).values(state="cancelled", updated_at=datetime.utcnow()))
    await db.commit()
    task = _tasks.get(goal_id)
    if task is None:
        task = _supervisors.get(goal_id)
    if task:
        task.cancel()
    await audit(db, "workspace.cancelled", {"id": goal_id, "changed": bool(changed.rowcount)})
    await db.commit()
    return bool(changed.rowcount)

async def save(goal_id, data, state="running"):
    async with writer.write_session(name=f"workspace.save:{goal_id[:8]}") as db:
        changed = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == goal_id, WorkspaceGoal.state == "running").values(result_json=json.dumps(data), state=state, updated_at=datetime.utcnow()))
    if not changed.rowcount:
        raise asyncio.CancelledError()


async def progress(goal_id, message):
    if not goal_id:
        return
    async with writer.write_session(name=f"workspace.progress:{goal_id[:8]}") as db:
        row = await db.get(WorkspaceGoal, goal_id)
        if not row or row.state != 'running':
            raise asyncio.CancelledError()
        data = json.loads(row.result_json)
        data['progress'] = message[:300]
        await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == goal_id, WorkspaceGoal.state == 'running').values(result_json=json.dumps(data), updated_at=datetime.utcnow()))

async def research(request):
    from aries.news.fetch import fetch
    from aries.news import feed
    from aries.news.models import AriesNewsItem
    words = [w.casefold() for w in re.findall(r"\w+", request) if len(w) > 1 and w.casefold() not in {"me", "to", "my", "of", "on", "in", "za", "mi", "se", "da", "research", "dashboard", "about", "news", "find", "for", "the", "and", "istrazi", "vesti", "najdi", "истражи", "вести", "најди"}]
    query = " ".join(words) or "latest news"
    cards, gaps = [], []
    async with async_session() as db:
        web = await SettingsService(db).get("workspace.web_search")
        rows = (await db.execute(select(AriesNewsItem).where(AriesNewsItem.excluded_by.is_(None), AriesNewsItem.dismissed.is_(False)).order_by(AriesNewsItem.first_seen_at.desc()).limit(300))).scalars().all()
        for r in rows:
            if words and not any(w in (r.title + " " + r.summary).casefold() for w in words):
                continue
            if safe_link(r.link):
                cards.append({"title": r.title, "text": r.summary[:500], "url": r.link,
                              "source": r.source_id, "published": r.published_at.isoformat() if r.published_at else None,
                              "evidence": "Collected news; publisher claims have not been independently verified"})
    if web:
        try:
            result = await fetch("https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-US&gl=US&ceid=US:en", max_bytes=1_000_000, timeout=15)
            if not result.ok or result.truncated:
                raise ValueError(f"news search returned HTTP {result.status} or incomplete content")
            for item in feed.parse(result.body, max_items=18).items:
                if safe_link(item.link):
                    cards.append({"title": item.title, "text": feed.clean(item.summary, limit=500),
                                  "url": item.link, "source": "Google News search",
                                  "published": item.published.isoformat() if item.published else None,
                                  "evidence": "Search result; full article not read"})
        except Exception as exc:
            gaps.append("Public news search unavailable: " + str(exc)[:200])
    else:
        gaps.append("Public news search is off. Showing matching news already collected by ARIES.")
    seen = set()
    unique = []
    for c in cards:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)
    if not unique:
        gaps.append("No matching source material found for: " + request)
    return unique[:24], gaps

async def approve(db, goal_id):
    from aries.workspace import capabilities
    from agentic_core.security import approvals, principal
    from agentic_core.security.permissions import Permission
    who = principal.current()
    if who is not None and not who.can(Permission.APPROVE):
        raise ValueError("Approving a change needs approval permission")
    row = await db.get(WorkspaceGoal, goal_id)
    if row is None or row.state != "proposed":
        raise ValueError("That task has no pending proposal")
    data = json.loads(row.result_json)
    pending = next((s for s in data["steps"] if s.get("state") == "proposed"), None)
    if pending is None:
        raise ValueError("The saved proposal is missing")
    if data.get('agent', {}).get('engine') == 'm14':
        original_json = row.result_json
        from aries.workspace.registry import registry
        registry.validate(pending['capability'], pending['args'])
        pending.update(approved=True, state='planned')
        data['gaps'] = []
        changed = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id==goal_id,
            WorkspaceGoal.state=='proposed', WorkspaceGoal.result_json==original_json).values(
                state='queued',result_json=json.dumps(data),updated_at=datetime.utcnow()))
        if not changed.rowcount:
            await db.rollback()
            raise ValueError('The proposed task changed; inspect its current state')
        await audit(db, 'workspace.m14.approved', {'id':goal_id, 'step_id':pending['step_id']})
        await db.commit()
        return {'queued':True,'id':goal_id}
    if pending.get("proposal_id"):
        from agentic_core.database.models import ActionProposal
        proposal = await db.get(ActionProposal, pending["proposal_id"])
        expected = {"capability": pending["capability"], "args": pending["args"]}
        if proposal is None or proposal.tool != "workspace." + pending["capability"] or json.loads(proposal.payload) != expected:
            raise ValueError("The proposal does not match the saved action")
        await approvals.approve(db, proposal.id, decided_by=who.username if who and hasattr(who, "username") else "user")
        if proposal.status != "approved":
            raise ValueError("This proposal has already been decided or expired")
    pending["approved"] = True
    pending["state"] = "queued"
    data["gaps"] = []
    changed = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == goal_id, WorkspaceGoal.state == "proposed").values(state="queued", result_json=json.dumps(data), updated_at=datetime.utcnow()))
    await audit(db, "workspace.approved", {"id": goal_id, "step": pending["request"][:120]})
    await db.commit()
    return {"queued": bool(changed.rowcount), "id": goal_id}

async def _tell_voice_outcome(db, row, data):
    """Spoken commands run without a window, so the outcome has to reach the
    person another way: an answer is delivered, a failure is explained, and a
    plain success stays silent — the song playing is the confirmation."""
    if row.state in {'done', 'cancelled'}:
        return
    from aries.health.findings import Severity
    from aries.notify import policy as notify
    text = next((c.get('text') for c in data.get('cards') or [] if c.get('text')), '') \
        or '; '.join(map(str, data.get('gaps') or [])) or row.state
    answered = row.state == 'answered'
    await notify.emit(db, key=f"voice.{row.id}", source="aries.voice",
                      title=(row.request if answered else f"Could not: {row.request}")[:200],
                      body=str(text)[:1500], severity=Severity.WARNING if not answered else Severity.NOTICE)
    await db.commit()


async def execute(goal_id, request):
    """Keep routing telemetry outside the executor and never treat it as success."""
    await _execute(goal_id, request)
    from aries.intelligence.tracking import record
    from aries.intelligence.router import learn_verified
    async with async_session() as db:
        row = await db.get(WorkspaceGoal, goal_id)
        data = json.loads(row.result_json)
        if data.get('origin') == 'voice':
            await _tell_voice_outcome(db, row, data)
        if row.state in {'done','partial','failed'}:
            routing=data.get('routing', {})
            levels={d.get('usage',{}).get('native',{}).get('execution_level') for d in data.get('agent',{}).get('decisions',[])}
            actual='cloud' if 'cloud' in levels else 'local' if 'local' in levels else routing.get('execution_level','unknown')
            await record(db,'outcome',task_id=goal_id,state=row.state,level=actual,recommended_level=routing.get('execution_level'))
            if routing:
                await learn_verified(db,request,routing,verified=row.state=='done')
            await db.commit()

async def _execute(goal_id, request):
    from aries.workspace import capabilities
    async with async_session() as db:
        row = await db.get(WorkspaceGoal, goal_id)
        data = json.loads(row.result_json)
        from aries.workspace.recovery import recheck
        await recheck(db, data)
        # Exact whole-word matching on words longer than three characters was
        # wrong for an inflected language: `сакам`, `сакаше` and `сакав` are
        # one verb and never matched each other, so a Macedonian speaker's
        # memory was unreachable by anything but the exact form they first used.
        # Ranking now goes through the versioned scheme, which folds inflection
        # (`retrieval.stem`) and, at `semantic-v3`, does not compare strings.
        from aries.workspace import retrieval as memory_retrieval
        from aries.workspace.memory import store as memory_store
        scored = await memory_store.relevant(db, request, limit=8)
        excluded = await SettingsService(db).get("privacy.excluded_memory_topics")
        data["context"] = [{"id": item["id"]} for _, item, _ in scored
                           if item["layer"] >= 60 and not _excluded(item["text"], excluded)]
        data["conclusions"] = [{"id": item["id"], "confidence": item.get("confidence")}
                               for _, item, _ in scored if item["layer"] < 60]
        terms = memory_retrieval.stems(request)
        data["related"] = [{"id": g.id, "request": g.request} for g in (await db.execute(select(WorkspaceGoal).where(WorkspaceGoal.id != goal_id, WorkspaceGoal.state.in_(["done", "partial"])).order_by(WorkspaceGoal.created_at.desc()).limit(20))).scalars() if terms & memory_retrieval.stems(g.request)][:5]
    from aries.workspace.registry import interactive_origin
    if data.pop("present_dashboard", False) and interactive_origin(data.get("origin")):
        # Compatibility with the installed shell: its run_automation action already
        # posts here. Present through the existing verified desktop capability,
        # avoiding a forced shell reload or logout just to add a command kind.
        from aries.operator import service as operator
        async with async_session() as db:
            presented = await operator.run(db, "open dashboard", dashboard_goal_id=goal_id)
            data["presentation"] = presented.as_dict()
    data.setdefault("collected_at", datetime.utcnow().isoformat())
    if data.get('agent_engine') == 'm14':
        from aries.workspace.agent import run
        goal = data.get('agent', {}).get('request') or data['steps'][0]['args']['task']
        await run(goal_id, goal, data)
        return
    if any(s.get('capability') == 'agent_task' for s in data['steps']):
        if len(data['steps']) != 1:
            raise ValueError('Submit an agent goal as one standalone request')
        data['agent'] = {'request':data['steps'][0]['args']['task'], 'finished':False}
        data['steps'] = []
    async def advance():
        from aries.workspace.planner import next_step
        await save(goal_id, data)
        await progress(goal_id, 'Planning the next action from observed results')
        async with async_session() as db:
            step, summary, usage = await next_step(db, data['agent']['request'], data['steps'])
        data['agent'].setdefault('model_usage', []).append(usage)
        if step is None:
            data['agent'].update(finished=True, summary=summary)
            data['cards'].insert(0, {'title':'Goal report', 'text':summary, 'evidence':'Local model summary of recorded tool results; per-step evidence follows'})
        else:
            data['steps'].append(step)
        await save(goal_id, data)
    if data.get('agent') and not data['steps']:
        await advance()
    from aries.operator.plan import _from_router
    expanded = []
    for step in data["steps"]:
        if step["kind"] == "desktop" and not step.get("state") and _from_router(step["request"]) is None:
            async with async_session() as db:
                translated = await capabilities.translate(db, step["request"])
            expanded.extend(translated or [step])
        else:
            expanded.append(step)
    if len(expanded) > (8 if data.get('agent') else 6):
        raise ValueError("The interpreted plan exceeds its action budget; split the request")
    data["steps"] = expanded
    if any(s.get('capability') == 'agent_task' for s in expanded):
        if len(expanded) != 1:
            raise ValueError('Submit an agent goal as one standalone request')
        from aries.workspace.agent import run
        data['agent_engine'] = 'm14'
        await run(goal_id, expanded[0]['args']['task'], data)
        return
    await save(goal_id, data)
    research_steps = [s for s in data["steps"] if s["kind"] == "research" and not s.get("state")]
    if research_steps:
        for step in research_steps:
            step["state"] = "running"
        await save(goal_id, data)
        results = await asyncio.gather(*(research(s.get("args", {}).get("query", s["request"])) for s in research_steps), return_exceptions=True)
        for step, result in zip(research_steps, results):
            if isinstance(result, BaseException):
                step["state"] = "failed"
                data["gaps"].append(str(result)[:200])
            else:
                cards, gaps = result
                step["state"] = "done" if cards else "empty"
                # Research is the one step kind for which no independent re-read can
                # exist: collecting sources cannot confirm that what was collected is
                # what the question needed. It was recording `done` with no
                # verification field at all, which made 6 223 of 6 322 unverified
                # steps in the whole history look indistinguishable from verified
                # ones. Saying "unverifiable" out loud is the honest state; silence
                # read as success.
                step["verification"] = {
                    "met": None, "unverifiable": True,
                    "evidence": f"Collected {len(cards)} source(s). No independent "
                                "re-read can confirm relevance or completeness."}
                data["cards"].extend(cards)
                data["gaps"].extend(gaps)
        from aries.workspace.verification import record as record_verification
        for step in research_steps:
            record_verification(step)
        await save(goal_id, data)
        async with async_session() as db:
            if data['cards'] and await SettingsService(db).get('workspace.ai_briefings'):
                from aries.workspace.reader import summarize
                sources = [c for c in data['cards'] if c.get('url')][:12]
                material = '\n\n'.join(c['title']+'\n'+c.get('text','') for c in sources)
                try:
                    brief = await summarize(db, request, material, request=request,
                                            coverage='collected headlines and feed excerpts, not full articles')
                    brief.update(source='News briefing', evidence='AI synthesis of the linked excerpts; open an article for a full-text reading summary',
                                 source_links=[{'title':c['title'],'url':c['url']} for c in sources])
                    data['cards'].insert(0,brief)
                except Exception as exc:
                    data['gaps'].append('AI briefing unavailable: '+str(exc)[:200])
        await save(goal_id, data)
    for step in data["steps"]:
        if step["kind"] == "research" or step.get("state") == "done":
            continue
        await save(goal_id, data)
        # Legacy deterministic commands use a different executor from the registry
        # agent. Unknown effects are review-only for unattended submissions too.
        legacy_reads = {"processes", "system", "services", "disk", "package_info",
                        "evaluation", "learning_eval", "list_apps", "find_files",
                        "list_folder", "read_file", "read_article", "inspect_app",
                        "browser_inspect", "read_screen", "clipboard_read",
                        "editable_fields", "network_status", "wifi_list", "brightness"}
        observation = step["kind"] == "capability" and step.get("capability") in legacy_reads
        if not observation and not step.get("approved") and not interactive_origin(data.get("origin")):
            step["state"] = "proposed"
            step["review_reason"] = "An unattended or unattributed action needs review before changing state"
            await save(goal_id, data, "proposed")
            return
        if step["kind"] == "capability":
            async with async_session() as db:
                if not step.get("prepared"):
                    started = time.monotonic()
                    try:
                        prepared = await capabilities.prepare(db, step)
                    except Exception as exc:
                        from aries.workspace.verification import record_failure
                        record_failure(step, exc, phase='prepare',
                                       elapsed_seconds=time.monotonic() - started)
                        await db.rollback()
                        await save(goal_id, data)
                        raise
                    step.update(prepared)
                    step["prepared"] = True
                if step["capability"] in capabilities.SENSITIVE and not step.get("approved") and not step["args"].get("already_installed"):
                    from agentic_core.security import approvals
                    proposal = await approvals.propose(db, kind="execute_tool", tool="workspace." + step["capability"], title=step["request"], payload={"capability": step["capability"], "args": step["args"]}, rationale="Exact user-requested target; review before changing it", risk="medium", created_by="aries:workspace")
                    await db.commit()
                    step.update(state="proposed", proposal_id=proposal.id)
                    await save(goal_id, data, "proposed")
                    return
                if step.get("from_model") and not step.get("approved") and await SettingsService(db).get("operator.confirm_model_plans"):
                    step["state"] = "proposed"
                    await save(goal_id, data, "proposed")
                    return
                # Save the exact executing step before crossing the action boundary.
                step["state"] = "running"
                step["goal_id"] = goal_id
                await save(goal_id, data)
                started = time.monotonic()
                try:
                    result = await capabilities.execute(db, step, approved=bool(step.get("approved")))
                except Exception as exc:                                    # noqa: BLE001
                    from aries.workspace.verification import record_failure
                    record_failure(step, exc, phase='execute',
                                   elapsed_seconds=time.monotonic() - started)
                    # Release any failed transaction before the separate save.
                    await db.rollback()
                    await save(goal_id, data)
                    raise
                result['elapsed_seconds'] = round(time.monotonic() - started, 3)
                step["result"] = result
                step["state"] = result["state"]
                data["cards"].extend(result.get("cards", []))
                if result.get("operator", {}).get("proposed"):
                    step["operator_plan"] = result["operator"]["plan"]
        else:
            from aries.operator import service as operator
            async with async_session() as db:
                run = await operator.run(db, step["request"], approve=bool(step.get("approved")), prepared_plan=step.get("operator_plan"))
            step["result"] = run.as_dict()
            step["state"] = run.outcome
            if run.proposed:
                step["operator_plan"] = run.plan.as_dict()
        from aries.workspace.verification import record as record_verification
        record_verification(step)
        await save(goal_id, data)
        if step["state"] != "done":
            if step["state"] != "proposed":
                data["gaps"].append(step["result"].get("summary", "Step did not complete"))
            break
        if data.get('agent') and step is data['steps'][-1] and not data['agent']['finished']:
            await advance()
    complete = all(s.get("state") == "done" for s in data["steps"])
    if data.get('agent'):
        complete = complete and data['agent']['finished']
    state = "done" if complete and not data["gaps"] else "partial"
    if any(s.get("state") == "proposed" for s in data["steps"]):
        state = "proposed"
    await save(goal_id, data, state)
    async with async_session() as db:
        await audit(db, "workspace.finished", {"id": goal_id, "state": state, "cards": len(data["cards"])})
        await db.commit()

def resources_for(data):
    """Reserve shared resources for the entire goal, including its later steps."""
    resources = set()
    if data.get('execution_scope'):
        from aries.workspace.scopes import Grant
        from aries.workspace.orchestration import lanes_for
        grant=Grant.model_validate(data['execution_scope']).validate_registry()
        return set().union(*(lanes_for(name) for name in grant.capabilities))
    if data.get('agent') or any(s.get('capability') == 'agent_task' for s in data.get('steps', [])):
        return {'desktop','files','local-model','browser'}
    reads = {"processes", "system", "list_apps", "find_files", "list_folder", "read_file", "remember", "evaluation", "learning_eval"}
    for step in data.get("steps", []):
        kind = step.get("capability")
        if kind in {"find_files", "list_folder", "read_file"}:
            resources.add("files")
        if step.get("kind") == "desktop":
            resources.update({'local-model','files','browser'})
        if step.get("kind") == "research" or kind in {"read_article", "build_python"}:
            resources.add("local-model")
        if kind in reads or kind in {"research", "read_article"}:
            continue
        if kind and kind.startswith("browser_"):
            resources.add("browser")
        elif kind in {"create_folder", "create_file", "move_file", "trash_file", "python_project", "build_python"}:
            resources.add("files")
            if kind in {"python_project", "build_python"}:
                resources.add("desktop")
        else:
            resources.add("desktop")
    return resources


async def cleanup_goal_browsers(goal_id):
    """Close only sessions opened by this agent, never another goal's browser."""
    from aries.workspace import browser
    async with async_session() as db:
        row = await db.get(WorkspaceGoal, goal_id)
        if not row or row.state in ACTIVE | {'proposed'}:
            return
        data = json.loads(row.result_json)
        if not data.get('agent') or not await SettingsService(db).get('workspace.auto_close_tools'):
            return
        owned = {s.get('result', {}).get('browser', {}).get('session') for s in data.get('steps', [])
                 if s.get('capability') in {'browser_open', 'open_url'}} - {None}
        try:
            current = await asyncio.wait_for(browser.inventory(), 3)
        except Exception as exc:
            current = []
            data['window_cleanup_error'] = str(exc)[:200]
        owned.update(r['session'] for r in current if r.get('owner') == goal_id)
        records = data.setdefault('window_cleanup', [])
        closed = {r['session'] for r in records if r.get('closed')}
        for key in owned - closed:
            try:
                current = await asyncio.wait_for(browser.inventory(), 3)
                if any(r['session'] == key and r['open'] for r in current):
                    await asyncio.wait_for(browser.close(key), 10)
                records.append({'session': key, 'closed': True, 'reason': 'Agent finished; result retained'})
            except Exception as exc:
                records.append({'session': key, 'closed': False, 'reason': str(exc)[:200]})
        if owned:
            for card in data.get('cards', []):
                if card.get('browser_session') in {r['session'] for r in records if r['closed']}:
                    card['browser_closed'] = True
            row.result_json = json.dumps(data)
            await db.commit()


async def _supervise(goal_id, request):
    task = asyncio.create_task(execute(goal_id, request))
    _tasks[goal_id] = task
    try:
        deadline = time.monotonic() + 1800
        while not task.done():
            if time.monotonic() >= deadline:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise TimeoutError("Goal exceeded its 30-minute deadline")
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=15)
            except asyncio.TimeoutError:
                async with async_session() as db:
                    changed = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == goal_id, WorkspaceGoal.state == "running").values(updated_at=datetime.utcnow()))
                    await db.commit()
                    if not changed.rowcount:
                        task.cancel()
        await task
    except (Exception, asyncio.CancelledError) as exc:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        async with async_session() as db:
            row = await db.get(WorkspaceGoal, goal_id)
            if row and row.state == 'cancelled':
                data = json.loads(row.result_json)
                from aries.workspace.agent import mark_interrupted
                mark_interrupted(data, 'cancelled')
                row.result_json = json.dumps(data)
                await db.commit()
            if row and row.state == "running":
                data = json.loads(row.result_json)
                data.setdefault("gaps", []).append("Task interrupted or deadline exceeded" if isinstance(exc, (TimeoutError, asyncio.CancelledError)) else str(exc)[:300])
                row.state = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
                from aries.workspace.agent import mark_interrupted
                mark_interrupted(data, row.state)
                row.result_json = json.dumps(data)
                await db.commit()
    finally:
        try:
            await cleanup_goal_browsers(goal_id)
        finally:
            _tasks.pop(goal_id, None)
            _resources.pop(goal_id, None)
            _supervisors.pop(goal_id, None)


async def dispatch(*, wait=True, slot_limit=None):
    # Lock only claiming, never the execution. The scheduled tick returns quickly.
    launched = []
    async with _lock:
        from aries.runtime import maintenance
        if maintenance.active():
            return {"launched":0,"running":len(_supervisors),"maintenance":True,"idle":True}
        capacity = (MAX_CONCURRENT if slot_limit is None else min(MAX_CONCURRENT, slot_limit)) - len(_supervisors)
        if capacity <= 0:
            return {"busy": True, "running": len(_supervisors)}
        async with async_session() as db:
            orphaned = (await db.execute(select(WorkspaceGoal).where(WorkspaceGoal.state=='running',
                WorkspaceGoal.updated_at < datetime.utcnow()-timedelta(minutes=5)))).scalars().all()
            for orphan in orphaned:
                if orphan.id in _supervisors:
                    continue
                data = json.loads(orphan.result_json)
                role = (data.get('orchestration') or {}).get('role')
                if role == 'parent':
                    continue  # The orchestration tick owns parent liveness.
                if role == 'child':
                    from aries.workspace.orchestration import _interrupt
                    _interrupt(data, 'Executor stopped before verification; effects will not be replayed')
                else:
                    from aries.workspace.agent import mark_interrupted
                    mark_interrupted(data)
                orphan.result_json = json.dumps(data)
                orphan.state = 'interrupted'
            # Avoid an unconditional writer lock on every idle two-second poll.
            await db.commit()
            rows = (await db.execute(select(WorkspaceGoal).where(WorkspaceGoal.state == "queued").order_by(WorkspaceGoal.created_at).limit(20))).scalars().all()
            occupied = set().union(*_resources.values()) if _resources else set()
            for row in rows:
                data = json.loads(row.result_json)
                if (data.get('orchestration') or {}).get('role'):
                    continue
                resources = resources_for(data)
                if resources & occupied:
                    continue
                claim = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id == row.id, WorkspaceGoal.state == "queued").values(state="running", updated_at=datetime.utcnow()))
                if not claim.rowcount:
                    continue
                # Persist the claim before execution can touch the desktop.
                await db.commit()
                _resources[row.id] = resources
                occupied.update(resources)
                task = asyncio.create_task(_supervise(row.id, row.request))
                _supervisors[row.id] = task
                launched.append(task)
                if len(launched) >= capacity:
                    break
            await db.commit()
    if wait and launched:
        await asyncio.gather(*launched)
    return {"launched": len(launched), "running": len(_supervisors), "capacity": MAX_CONCURRENT,
            "idle": not launched}


async def shutdown():
    tasks = list(_supervisors.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    from aries.workspace.browser import close_all
    await close_all()


from agentic_core.scheduler.registry import register
from agentic_core.scheduler.worker import Worker


class WorkspaceWorker(Worker):
    async def _due(self):
        # This is a queue poll, not a calendar job. asyncio.sleep in Worker
        # supplies the cadence. A future checkpoint after NTP corrects the
        # clock backwards must never freeze submitted work for hours.
        return True, None

    async def stop(self):
        await super().stop()
        await shutdown()


async def tick():
    from aries.workspace.orchestration import tick as orchestrate
    return await orchestrate(wait=False)


register(WorkspaceWorker("aries.workspace", tick, every=timedelta(seconds=2), check_every_s=2, enabled=lambda: True,
                         quiet=True))
