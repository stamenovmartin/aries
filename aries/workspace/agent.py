"""M14 execution in the existing durable WorkspaceGoal, never a second queue."""
import asyncio
import json
import time
import uuid
from pathlib import Path
from agentic_core.database.base import async_session
from aries.settings import SettingsService
from aries.workspace import agent_planner, contracts
from aries.workspace.registry import registry, policy, now


def error(exc):
    code = getattr(exc,'code',None)
    if not code:
        code = next((c for c in ('TRANSIENT','TARGET_NOT_FOUND','CAPABILITY_UNAVAILABLE','PERMISSION_REQUIRED','AUTH_REQUIRED','AMBIGUOUS','NETWORK_ERROR','VERIFICATION_FAILED','NON_RETRYABLE') if str(exc).startswith(c+':')),None)
    if not code:
        code = 'TARGET_NOT_FOUND' if isinstance(exc,FileNotFoundError) else 'PERMISSION_REQUIRED' if isinstance(exc,PermissionError) else 'TRANSIENT' if isinstance(exc,TimeoutError) else 'NETWORK_ERROR' if isinstance(exc,ConnectionError) else 'NON_RETRYABLE'
    return {'error_type':type(exc).__name__, 'code':code, 'message':str(exc)[:1200],
            'retryable':code in {'TRANSIENT','NETWORK_ERROR'}}


def evidence(data, source, kind, payload, *, verified, step_id=None):
    row = {'evidence_id':uuid.uuid4().hex, 'type':kind, 'source':source, 'timestamp':now(),
           'step_id':step_id, 'verified':verified, 'data':agent_planner.bounded(payload,max_chars=64000)}
    data['evidence'].append(row)
    return row


def transition(step, state):
    step['state'] = state
    step.setdefault('transitions', []).append({'state':state, 'timestamp':now()})


def mark_interrupted(data, state='interrupted'):
    if data.get('agent',{}).get('engine') != 'm14':
        return
    data['agent']['metrics']['task_final_status'] = state
    for step in data['steps']:
        if step.get('execution_status') == 'executing' or step.get('state') == 'observed':
            detail = {'error_type':'InterruptedExecution','message':'Process stopped before verification; no replay is authorized','retryable':False}
            step['error'] = detail
            step['verification_status'] = 'interrupted'
            step['finished_at'] = now()
            transition(step,'interrupted')
            row = evidence(data,step['capability'],'interrupted_execution',detail,verified=False,step_id=step['step_id'])
            step['observation_ref'] = row['evidence_id']


async def completion(data, decision, ctx):
    contract = data['agent']['contract']
    if not contract['supported']:
        return False, contract['reason'], []
    available = {e['evidence_id'] for e in data['evidence'] if e['verified']}
    refs = set(decision.evidence_refs)
    if not refs or not refs <= available:
        return False, 'Finish requires existing verified evidence IDs; unknown/failed references rejected', []
    selected, cursor = [], -1
    for requirement in contract['requirements']:
        found = None
        for index, step in enumerate(data['steps']):
            if index <= cursor or step.get('verification_status') != 'verified':
                continue
            if not set(step.get('evidence_refs', [])) & refs or not contracts.matches(requirement, step):
                continue
            cap = registry.get(step['capability'])
            try:
                if not await policy(ctx['db'], cap, step['args'], ctx['goal'], approved=bool(step.get('approved')),origin=ctx.get('origin')):
                    raise PermissionError('Current policy requires approval for this result')
                await ctx['db'].rollback()
                fresh = await _budgeted_capability(cap,step['args'],ctx,result=step['execution_result'],verification=True)
            except Exception as exc:
                fresh = {'met':False,'type':'goal_recheck','data':error(exc)}
            checked = evidence(data, cap.name, fresh['type'], fresh['data'], verified=bool(fresh['met']), step_id=step['step_id'])
            if contracts.evidence_matches(requirement, fresh):
                found, cursor = checked, index
                break
            # Historical proof remains immutable, but cannot keep satisfying the
            # planner after a current-state check has invalidated it. Only safe
            # reads with an actual changed observation may be repeated.
            step['verification_status']='stale'
            transition(step,'verification_failed')
            step['completion_recheck']=fresh
            step['error']={'code':'VERIFICATION_FAILED','error_type':'StaleObservation',
                'message':'Completion recheck no longer satisfies the goal; inspect current state again',
                'retryable':cap.effect=='read' and not cap.requires_approval and fresh['type']!='goal_recheck'}
        if found is None:
            return False, 'No current verified evidence satisfies ' + json.dumps(requirement), []
        selected.append(found)
    return True, contracts.answer(contract, selected), selected


async def run(goal_id, goal, data):
    from aries.intelligence import budgets
    from aries.intelligence.context import task_context
    root_id=(data.get('orchestration') or {}).get('parent_id') or goal_id
    async with async_session() as db:
        s=SettingsService(db)
        limits=await s.get_many(['workspace.goal_max_model_calls','workspace.goal_max_tokens',
            'workspace.goal_max_tool_calls','workspace.goal_deadline_seconds','workspace.goal_max_cost_usd'])
    await budgets.create(root_id,max_calls=limits['workspace.goal_max_model_calls'],
        max_tokens=limits['workspace.goal_max_tokens'],max_tools=limits['workspace.goal_max_tool_calls'],
        max_cost_micros=round(limits['workspace.goal_max_cost_usd']*1_000_000),
        seconds=limits['workspace.goal_deadline_seconds'])
    with task_context(goal_id,root_id=root_id,budgeted=True):
        from aries import flags
        if flags.enabled('ARIES_GOAL_TEAMS') and not data.get('execution_scope') and not data.get('graph_considered'):
            from aries.workspace.goal_graph import expand, eligible
            if eligible(goal):
                data['graph_considered']=True
                if await expand(goal_id,goal,data):
                    return
        if data.get('execution_scope'):
            from aries.workspace.scopes import use
            with use(data['execution_scope']):
                await _run(goal_id,goal,data)
        else:
            await _run(goal_id,goal,data)


async def _budgeted_capability(cap, args, ctx, *, result=None, verification=False):
    from aries.intelligence.context import current
    from aries.intelligence import budgets
    attribution=current()
    key=None
    if attribution.get('budgeted'):
        key=await budgets.reserve(attribution['root_id'],attribution['task_id'],
                                  'verification' if verification else 'tool',cost_micros=0)
    if 'metrics' in ctx:
        counter='verifier_calls' if verification else 'tool_calls'
        ctx['metrics'][counter]=ctx['metrics'].get(counter,0)+1
    try:
        call=cap.verifier(args,result,ctx) if verification else cap.executor(args,ctx)
        return await asyncio.wait_for(call,cap.timeout_seconds)
    finally:
        if key:await budgets.settle(key,tokens=0,cost_micros=0)


async def _run(goal_id, goal, data):
    from aries.workspace.service import save
    started = time.monotonic()
    if data.get('agent', {}).get('engine') != 'm14':
        async with async_session() as db:
            settings = SettingsService(db)
            limit = await settings.get('workspace.agent_max_steps')
            directory = str(Path(await settings.get('workspace.agent_demo_directory')).expanduser())
            from aries.workspace.reviews import relevant
            from aries.learning.feedback import standing_rules
            from aries.workspace.working_context import current
            historical = {'reviews':await relevant(db, goal), 'preferences':await standing_rules(db), 'working_context':await current(db)}
            # What the person has actually told ARIES, ranked for THIS goal. Until
            # 2026-10-03 the planner was given reviews, standing rules and the working
            # context but never the memories themselves, so a goal could not be
            # informed by anything the user had said in an earlier session. Verbatim
            # text and the layer that produced it travel together: a USER statement
            # and a LEARNED conclusion must not be indistinguishable in a prompt,
            # because the planner's trust in them is not the same.
            from aries import flags
            if flags.enabled('ARIES_PLAN_MEMORY') and not flags.enabled('ARIES_CONTEXT_ENGINE'):
                try:
                    from aries.workspace.memory import store as memory_store
                    scored = await memory_store.relevant(db, goal, limit=6)
                    historical['memories'] = [
                        {'text': row.get('text', '')[:300],
                         # store.py: MEMORY, CONCLUSION = "m", "c" — the key prefix is
                         # one character. Comparing against 'MEMORY' matched nothing and
                         # would have labelled every user statement a conclusion, which
                         # is the one confusion the separation exists to prevent.
                         'layer': 'user_said' if str(row.get('key', '')).startswith(
                             memory_store.MEMORY + ':') else 'aries_concluded',
                         'relevance': round(float(score), 3),
                         'confidence': row.get('confidence')}
                        for score, row, _ in scored]
                except Exception as exc:                   # noqa: BLE001
                    # A planner that cannot plan because memory is unavailable is
                    # worse than one planning without it; the absence is recorded.
                    historical['memories_unavailable'] = f'{type(exc).__name__}: {exc}'[:160]
            if flags.enabled('ARIES_TRACE_FEWSHOT'):
                try:
                    from aries.workspace import traces
                    examples = await traces.successes(db, goal, limit=3)
                    if examples:
                        historical['worked_before'] = {
                            'examples': examples,
                            'status': 'Past routes that were VERIFIED, not instructions. A route '
                                      'that worked once on a machine in one state is evidence; '
                                      'check the current state before copying it.'}
                except Exception as exc:                   # noqa: BLE001
                    historical['worked_before_unavailable'] = f'{type(exc).__name__}: {exc}'[:160]
            if flags.enabled('ARIES_CONTEXT_ENGINE'):
                from aries.workspace.context_engine import assemble
                packet=await assemble(db,goal,max_chars=2000)
                historical['memories']=packet['items']
                historical['context_coverage']={k:packet[k] for k in ('required_sources','missing_sources','estimated_context_tokens')}
                data['context_packet']=packet
        data.update(steps=[], evidence=[], schema_version=2)
        data['agent'] = {'engine':'m14', 'request':goal, 'finished':False, 'max_steps':limit,
            'contract':contracts.compile_goal(goal,directory), 'decisions':[],
            'context':agent_planner.bounded(historical,max_chars=2500),
            'environment':{'home':str(Path.home()), 'demo_directory':directory, 'now':now()},
            'metrics':{'planner_calls':0,'number_of_steps':0,'execution_time':0.,'planner_time':0.,
                       'capability_failures':0,'verification_failures':0,'retries':0,
                       'invalid_decisions':0,'wrong_capability_selections':0,
                       'tool_calls':0,'verifier_calls':0,'replans':0,
                       'input_tokens':0,'output_tokens':0,'total_tokens':0,'token_measurement_complete':True,
                       'estimated_input_tokens':0,'estimated_output_tokens':0}}
        data['agent']['context_data_classes']=(data.get('context_packet') or {}).get('data_classes',[])
        if data.get('context_packet'):
            from aries.workspace.context_engine import planner_context
            data['agent']['context']=planner_context(historical,data['context_packet'])
    agent = data['agent']
    metrics = agent['metrics']
    limit = agent['max_steps']

    async def persist(state='running'):
        metrics['number_of_steps'] = len(data['steps'])
        metrics['task_final_status'] = state
        await save(goal_id,data,state)

    async def finish(state, summary, refs=()):
        from aries.intelligence import budgets
        from aries.intelligence.context import current
        metrics['resource_budget']=await budgets.snapshot(current().get('root_id',goal_id))
        agent.update(finished=state in {'done', 'answered'}, summary=summary)
        metrics['wall_seconds'] = metrics.get('wall_seconds',0) + round(time.monotonic()-started,3)
        metrics['wall_seconds_scope'] = 'Active execution invocations, including planning; excludes queue and approval wait'
        data['final_evidence_refs'] = list(refs)
        data['cards'] = [{'title':'Verified goal result' if state=='done' else 'Answer' if state=='answered' else 'Goal outcome',
                          'text':summary, 'evidence':', '.join(refs) or 'See persisted step observations and failures'}]
        if state not in ('done', 'answered'):
            data.setdefault('gaps', []).append(summary)
        await persist(state)

    # Do not replay a step after uncertain process death, even if somebody queues
    # its row manually. Recovery of legacy bounded plans remains unchanged.
    if any(s.get('execution_status') == 'executing' for s in data['steps']):
        await finish('interrupted','An execution was interrupted; effects are uncertain and will not be replayed')
        return
    await persist()
    pending = next((s for s in data['steps'] if s.get('approved') and s.get('execution_status') == 'planned'),None)
    max_calls = 2*(limit+2)
    while metrics['planner_calls'] < max_calls:
        if pending is None:
            from aries.workspace.finish_proposal import propose
            decision = propose(data)
            if decision is not None:
                agent['automatic_finish_step_count']=len(data['steps'])
                metrics['automatic_finish_proposals']=metrics.get('automatic_finish_proposals',0)+1
                event={'index':len(agent['decisions']),'timestamp':now(),'source':'contract-evidence',
                       'usage':{'model_calls':0},'valid':True,'decision':decision.model_dump()}
                agent['decisions'].append(event)
                await persist()
            for attempt in range(2):
                if decision is not None:break
                if metrics['planner_calls'] >= max_calls:
                    break
                t0 = time.monotonic()
                metrics['planner_calls'] += 1
                if agent.pop('replan_after_rejected_finish',False):
                    metrics['replans']=metrics.get('replans',0)+1
                event = {'index':len(agent['decisions']), 'timestamp':now(), 'usage':{}, 'valid':False}
                agent['decisions'].append(event)
                await persist()  # record intent to call model before making the call
                try:
                    async with async_session() as db:
                        raw, usage = await agent_planner.plan(db,goal,data,max(0,limit-len(data['steps'])))
                    event.update(raw=raw[:12000],usage=usage)
                    metrics['estimated_context_tokens'] = metrics.get('estimated_context_tokens',0) + usage.get('context',{}).get('estimated_tokens',0)
                    measured = usage.get('measured',{})
                    for name in ('input_tokens','output_tokens','total_tokens'):
                        count = measured.get(name)
                        if isinstance(count,int):
                            metrics[name] += count
                        else:
                            metrics['token_measurement_complete'] = False
                    estimates = usage.get('estimated',{})
                    for name in ('input_tokens','output_tokens'):
                        metrics['estimated_'+name] += estimates.get(name,0)
                    decision = agent_planner.parse(raw)
                    event.update(valid=True, decision=decision.model_dump())
                except Exception as exc:
                    event['error'] = error(exc)
                    metrics['invalid_decisions'] += 1
                    if 'Unknown capability' in str(exc):
                        metrics['wrong_capability_selections'] += 1
                    agent['completion_feedback'] = 'Invalid decision: '+str(exc)[:800]
                    if attempt == 0:
                        metrics['retries'] += 1
                finally:
                    elapsed = time.monotonic()-t0
                    event['seconds'] = round(elapsed,4)
                    metrics['planner_time'] += elapsed
                    await persist()
                if decision is not None:
                    break
                if (event.get('error') or {}).get('code') == 'BUDGET_EXCEEDED':
                    await finish('partial' if any(e['verified'] for e in data['evidence']) else 'failed',
                                 event['error']['message'])
                    return
            if decision is None:
                await finish('partial' if any(e['verified'] for e in data['evidence']) else 'failed',
                             'Planner decision retry/call budget exhausted; invalid attempts are recorded')
                return
            if decision.action == 'fail' and not data['steps'] and not agent['contract']['supported'] \
                    and (decision.summary or decision.reason):
                # Nothing was asked of the machine — "do you have a student ID?",
                # "give me an example of ambiguity". The model's reply IS the
                # result; recording it as a failed task hid the answer behind a
                # red badge and counted conversation as execution failure.
                await finish('answered', decision.summary or decision.reason)
                return
            if decision.action == 'fail':
                await finish('partial' if any(e['verified'] for e in data['evidence']) else 'failed',
                             'Planner stopped: ' + (decision.summary or decision.reason or 'No further action proposed') +
                             (' (no environment evidence collected)' if not data['evidence'] else ' — see observed step results'))
                return
            if decision.action == 'finish':
                async with async_session() as db:
                    met, summary, selected = await completion(data,decision,{'db':db,'goal':goal,'task_id':goal_id,'metrics':metrics,'origin':data.get('origin')})
                agent['completion_checks'] = agent.get('completion_checks',[]) + [{'at':now(),'met':met,'reason':summary[:1500]}]
                if met:
                    state = 'answered' if agent['contract'].get('answer') == 'measurements' else 'done'
                    await finish(state,summary,[e['evidence_id'] for e in selected])
                    return
                metrics['verification_failures'] += 1
                agent['completion_feedback'] = summary
                agent['replan_after_rejected_finish']=True
                from aries import flags
                if flags.enabled('ARIES_COMPLETION_PROGRESS_GUARD'):
                    from aries.workspace.completion_progress import reject
                    if reject(agent, step_count=len(data['steps']), reason=summary):
                        await finish('partial' if any(e['verified'] for e in data['evidence']) else 'failed',
                                     agent['completion_feedback'])
                        return
                await persist()
                if not agent['contract']['supported'] or len(data['steps']) >= limit:
                    break
                continue
            if len(data['steps']) >= limit:
                agent['completion_feedback'] = 'Action budget exhausted without verified goal completion'
                break
            pending = {'step_id':uuid.uuid4().hex,'task_id':goal_id,'step_index':len(data['steps']),
                       'kind':'capability','request':decision.reason or decision.capability,
                       'planner_decision':decision.model_dump(),'capability':decision.capability,'args':decision.arguments,
                       'started_at':None,'finished_at':None,'execution_status':'planned','verification_status':'pending',
                       'observation':None,'error':None,'evidence_refs':[], 'model_usage':event['usage']}
            transition(pending,'planned')
            data['steps'].append(pending)
            await persist()
        step = pending
        pending = None
        cap = registry.get(step['capability'])
        t0 = time.monotonic()
        try:
            async with async_session() as db:
                ctx = {'db':db,'goal':goal,'task_id':goal_id,'metrics':metrics,'origin':data.get('origin')}
                authorized = await policy(db,cap,step['args'],goal,approved=bool(step.get('approved')),origin=data.get('origin'))
                wants_approval = step['planner_decision']['action'] == 'ask_approval' and not step.get('approved')
                if not authorized or wants_approval:
                    transition(step,'proposed')
                    metrics['wall_seconds'] = metrics.get('wall_seconds',0) + round(time.monotonic()-started,3)
                    metrics['wall_seconds_scope'] = 'Active execution invocations, including planning; excludes queue and approval wait'
                    # Exact frozen proposal stored before any effect. Existing API
                    # approval checks Permission.APPROVE and resumes this same step.
                    await persist('proposed')
                    return
                if any(s is not step and s['capability']==step['capability'] and s['args']==step['args'] and
                       (cap.effect!='read' or s.get('verification_status')=='verified' or
                        not (s.get('error') or {}).get('retryable',False)) for s in data['steps']):
                    # A retryable transport error does not prove a mutation had
                    # no effect. Only reads may be automatically retried here.
                    raise ValueError('Duplicate mutation, verified or non-retryable action rejected')
                if any(s is not step and s['capability']==step['capability'] and s['args']==step['args'] for s in data['steps']):
                    metrics['retries'] += 1
                step.update(execution_status='executing',started_at=now())
                transition(step,'executing')
                await persist()
                await db.rollback()  # no read snapshot held across budget admission or capability I/O
                result = await _budgeted_capability(cap,step['args'],ctx)
                step['execution_result'] = agent_planner.bounded(result,max_chars=64000)
                step['observation'] = agent_planner.bounded(result,max_chars=7000)
                step['execution_status'] = 'observed'
                transition(step,'observed')
                # Persist the actual executor result before the independent verifier.
                observed = evidence(data,cap.name,'execution_observation',step['observation'],verified=False,step_id=step['step_id'])
                step['observation_ref'] = observed['evidence_id']
                await persist()
                try:
                    await db.commit()
                    verification = await _budgeted_capability(cap,step['args'],ctx,result=result,verification=True)
                except Exception as exc:
                    verification = {'met':False,'type':'verification_error','data':error(exc)}
                step['verification'] = agent_planner.bounded(verification,max_chars=64000)
                step['verification_status'] = 'verified' if verification.get('met') is True else 'verification_failed'
                proof = evidence(data,cap.name,verification['type'],verification['data'],verified=verification.get('met') is True,step_id=step['step_id'])
                step['evidence_refs'].append(proof['evidence_id'])
                # Planner gets verified observations; preserve executor observation separately.
                # KEPT, not discarded: until 2026-10-03 this line overwrote the tool's own
                # report with the verifier's, so there was no way to show a planner what the
                # tool claimed WITHOUT also showing what the check found. That made the
                # control condition of the state-verification-feedback experiment impossible
                # to build honestly — removing `verification_status` while `observation`
                # still carried the verifier's data leaked the variable being withheld.
                step['executor_observation'] = step['observation']
                step['observation'] = agent_planner.bounded({'verification':verification['data'],'evidence_id':proof['evidence_id']},max_chars=8000)
                transition(step,step['verification_status'])
                if verification.get('met') is not True:
                    metrics['verification_failures'] += 1
                    step['error'] = {'error_type':'VerificationFailed','message':'Independent verification did not confirm execution','retryable':False}
        except asyncio.CancelledError:
            # Supervisor preserves the last durable executing/observed state.
            raise
        except Exception as exc:
            step['error'] = error(exc)
            step['execution_status'] = 'failed'
            transition(step,'failed')
            metrics['capability_failures'] += 1
            observed = evidence(data,cap.name,'execution_error',step['error'],verified=False,step_id=step['step_id'])
            step['observation_ref'] = observed['evidence_id']
            step['observation'] = {'capability':cap.name,'status':'failed',**step['error']}
        finally:
            step['finished_at'] = now()
            step['seconds'] = round(time.monotonic()-t0,4)
            metrics['execution_time'] += step['seconds']
            step['result'] = {'state':'done' if step['verification_status']=='verified' else step['state'],
                              'summary': 'Independently verified' if step['verification_status']=='verified' else (step.get('error') or {}).get('message','Pending'),
                              'elapsed_seconds':step['seconds']}
        await persist()
        from aries.workspace.terminal_failure import reason as terminal_reason
        terminal=terminal_reason(data,step)
        if terminal:
            agent['stop_reason']='REQUESTED_FILE_NOT_FOUND'
            metrics['terminal_read_failures']=metrics.get('terminal_read_failures',0)+1
            await finish('partial' if any(e['verified'] for e in data['evidence']) else 'failed',terminal)
            return
    await finish('partial' if any(e['verified'] for e in data['evidence']) else 'failed',
                 agent.get('completion_feedback') or 'Bounded planner budget exhausted')
