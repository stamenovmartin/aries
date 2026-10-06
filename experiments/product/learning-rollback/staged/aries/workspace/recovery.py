"""Continue bounded plans without replaying mutations or rewriting failed history."""
import copy
import json
import uuid
from pathlib import Path
from sqlalchemy import select, update
from aries.workspace.models import WorkspaceGoal

RETRY_READS = {'processes','system','list_apps','find_files','list_folder','read_file',
               'inspect_app','read_article','evaluation','learning_eval'}
VERIFY_EFFECTS = {'create_folder','create_file','move_file','trash_file','install_app','python_project','build_python'}
RECOVERABLE = {'partial','failed','interrupted','unconfirmed','held','empty'}


async def inspect(db, row):
    from aries.workspace import capabilities
    data = json.loads(row.result_json)
    checks = []
    def blocked(reason):
        return {'available':False, 'reason':reason, 'checks':checks, 'steps':[]}
    if row.state not in RECOVERABLE:
        return blocked('Only interrupted or unsuccessful tasks can be recovered')
    if data.get('agent'):
        from aries.workspace.registry import registry
        if data['agent'].get('engine') != 'm14':
            return blocked('Unknown dynamic execution engine')
        for step in data.get('steps',[]):
            try:
                cap=registry.get(step['capability'])
                registry.validate(cap.name,step['args'])
            except (KeyError,ValueError,TypeError):
                return blocked('A saved capability or its arguments are no longer supported')
            if cap.effect != 'read' or cap.name.startswith('browser.'):
                return blocked('Dynamic recovery permits only read-only non-browser history; uncertain effects are never replayed')
        limit=data['agent'].get('max_steps')
        if type(limit) is not int or limit<=0 or len(data.get('steps',[])) >= limit:
            return blocked('Original step budget is exhausted')
        calls=data['agent'].get('metrics',{}).get('planner_calls',0)
        if type(calls) is not int or calls>=2*(limit+2):
            return blocked('Original planner call budget is exhausted')
        return {'available':True,'reason':'Refresh read-only observations before bounded replanning',
                'checks':[], 'steps':copy.deepcopy(data['steps']), 'dynamic':True}
    if not data.get('steps'):
        return blocked('No saved steps to recover')
    planned = []
    for index, original in enumerate(data['steps']):
        step = copy.deepcopy(original)
        kind = step.get('capability')
        if step.get('kind') == 'research':
            # Research has no mutation to replay; collect fresh source results.
            planned.append({'kind':'research','request':step['request'], 'args':step.get('args',{})})
            continue
        if step.get('kind') != 'capability':
            return blocked('This plan contains an unverified desktop action; it will not be replayed')
        if kind in VERIFY_EFFECTS:
            try:
                for key in ('path','destination'):
                    if step.get('args',{}).get(key):
                        raw = step['args'][key]
                        checked = await capabilities.checked_path(db, raw)
                        if checked != Path(raw).absolute():
                            return blocked('A saved path now resolves to a different target')
                met, evidence = await capabilities.verify(kind, step['args'])
            except Exception as exc:
                met, evidence = False, str(exc)[:250]
            checks.append({'step':index, 'capability':kind, 'met':met is True, 'evidence':evidence})
            if met is not True:
                return blocked('A saved mutation cannot be confirmed. Review its target; it will not be retried automatically')
            step.update(state='done', inherited=True, recovery_verification={'met':True,'evidence':evidence})
            step.pop('approved',None)
            step.pop('proposal_id',None)
            planned.append(step)
        elif kind in RETRY_READS:
            # Even previously successful reads can be stale. Refresh rather than
            # use yesterday's observation as evidence for today's continuation.
            clean, _ = capabilities.validate_action(kind, step.get('args',{}))
            planned.append(clean)
        else:
            return blocked('This step has no safe recovery path yet; no action has been repeated')
    return {'available':True, 'reason':'Recheck completed changes and refresh read-only steps; no mutations are replayed',
            'checks':checks, 'steps':planned}


async def resume(db, goal_id):
    from aries.workspace import service
    from aries.settings import SettingsService
    if not await SettingsService(db).get('workspace.enabled'):
        raise ValueError('Goal dashboards are switched off')
    # Serialize recovery creation with queue claims and other recovery requests.
    async with service._lock:
        row = await db.get(WorkspaceGoal, goal_id, populate_existing=True)
        if row is None:
            raise LookupError('Task not found')
        original_json = row.result_json
        data = json.loads(original_json)
        child_id = data.get('recovery_child_id')
        if child_id:
            child = await db.get(WorkspaceGoal, child_id)
            if child is not None:
                return {'id':child.id, 'state':child.state, 'existing':True}
        pending = (await db.execute(select(WorkspaceGoal.id).where(WorkspaceGoal.state.in_(service.ACTIVE)).limit(20))).all()
        if len(pending)>=20:
            raise ValueError('The goal queue is full')
        plan = await inspect(db, row)
        if not plan['available']:
            raise ValueError(plan['reason'])
        child_id = uuid.uuid4().hex
        child_data = {'origin':data.get('origin'),'steps':plan['steps'], 'cards':[{'title':'Prior change verified',
            'text':s['request'], 'evidence':s['recovery_verification']['evidence']}
            for s in plan['steps'] if s.get('inherited')], 'gaps':[],
                      'recovery':{'parent_id':row.id,'parent_state':row.state,'checks':plan['checks']}}
        if plan.get('dynamic'):
            child_data=copy.deepcopy(data)
            child_data.pop('recovery_child_id',None)
            child_data['recovery']={'parent_id':row.id,'parent_state':row.state,'dynamic':True,'checks':[]}
            # The parent retains historical proof. A continuation starts with no
            # current evidence, even if a fresh observation fails before planning.
            for key in ('evidence','final_evidence_refs','cards','gaps','context','conclusions','related'):
                child_data[key]=[]
            child_data['agent'].pop('context',None)
            child_data['agent'].pop('summary',None)
            child_data['agent'].pop('completion_checks',None)
            child_data['agent']['finished']=False
            child_data['agent']['completion_feedback']='Resuming with fresh read-only observations; prior effects are not replayed'
            for step in child_data['steps']:
                for key in ('approved','proposal_id','execution_result','verification','observation_ref','result','error'):
                    step.pop(key,None)
                step.update(task_id=child_id,state='pending',execution_status='interrupted',
                            verification_status='pending',observation=None,evidence_refs=[])
        data['recovery_child_id'] = child_id
        changed = await db.execute(update(WorkspaceGoal).where(WorkspaceGoal.id==row.id,
            WorkspaceGoal.state==row.state, WorkspaceGoal.result_json==original_json).values(result_json=json.dumps(data)))
        if not changed.rowcount:
            await db.rollback()
            raise ValueError('The original task changed; inspect it again')
        child = WorkspaceGoal(id=child_id, request=row.request, state='queued', result_json=json.dumps(child_data))
        db.add(child)
        await service.audit(db, 'workspace.recovery_created', {'parent_id':row.id,'id':child_id})
        await db.commit()
        return {'id':child_id, 'state':'queued', 'existing':False}


async def recheck(db, data):
    """Revalidate after queueing, immediately before any continuation executes."""
    if not data.get('recovery'):
        return
    if data['recovery'].get('dynamic'):
        from aries.workspace.registry import registry, policy
        from aries.workspace.agent import evidence, error, transition
        import asyncio
        for step in data['steps']:
            cap=registry.get(step['capability'])
            if cap.effect!='read' or cap.name.startswith('browser.'):
                raise ValueError('Recovery policy changed; unsafe continuation refused')
            step['args']=registry.validate(cap.name,step['args'])
            ctx={'db':db,'task_id':step['task_id'],'goal':data['agent']['request']}
            if await policy(db,cap,step['args'],ctx['goal']) is not True:
                raise PermissionError('Recovery now requires approval; no action was executed')
            for key in ('execution_result','verification','observation_ref','error','result'):
                step.pop(key,None)
            step.update(verification_status='pending',evidence_refs=[],observation=None)
            try:
                fresh=await asyncio.wait_for(cap.executor(step['args'],ctx),cap.timeout_seconds)
                verification=await asyncio.wait_for(cap.verifier(step['args'],fresh,ctx),cap.timeout_seconds)
                verified=verification.get('met') is True
                step.update(execution_result=fresh,verification=verification,execution_status='observed',
                            verification_status='verified' if verified else 'verification_failed')
                proof=evidence(data,cap.name,verification['type'],verification['data'],verified=verified,step_id=step['step_id'])
                step['evidence_refs']=[proof['evidence_id']]
                step['observation']={'recovery_observation':verification['data']}
                transition(step,step['verification_status'])
                data['recovery']['checks'].append({'step_id':step['step_id'],'met':verified})
            except Exception as exc:
                failure=error(exc)
                step.update(execution_status='failed',verification_status='verification_failed',
                            error=failure,observation={'recovery_error':failure})
                proof=evidence(data,cap.name,'recovery_error',failure,verified=False,step_id=step['step_id'])
                step['evidence_refs']=[proof['evidence_id']]
                transition(step,'failed')
                data['recovery']['checks'].append({'step_id':step['step_id'],'met':False,'error':str(exc)[:500]})
        return
    from aries.workspace import capabilities
    for step in data['steps']:
        if not step.get('inherited'):
            continue
        for key in ('path','destination'):
            if step.get('args',{}).get(key):
                raw = step['args'][key]
                checked = await capabilities.checked_path(db,raw)
                if checked != Path(raw).absolute():
                    raise ValueError('Recovery stopped: saved path target changed while queued')
        met, evidence = await capabilities.verify(step['capability'],step['args'])
        if met is not True:
            raise ValueError('Recovery stopped: a completed change no longer matches its evidence')
        step['recovery_verification'] = {'met':True,'evidence':evidence}
