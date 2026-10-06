"""Recovery preserves failures, rechecks effects and never replays mutations."""
import json,sys,tempfile
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-recovery')
from agentic_core.database.base import async_session
from aries.workspace.models import WorkspaceGoal
from aries.workspace import recovery,service
from aries.settings import SettingsService

async def seed(folder, *, effect_state='done', agent=False):
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set('privacy.excluded_paths',[],set_by='user')
        # Test data is in the user's temp test directory, explicitly allowed.
        await SettingsService(db).set('workspace.enabled',True,set_by='user')
        data={'steps':[{'kind':'capability','capability':'create_file','request':'Create note',
                'state':effect_state,'args':{'path':str(folder/'note.txt'),'content':'original'}},
               {'kind':'capability','capability':'read_file','request':'Read followup',
                'state':'failed','args':{'path':str(folder/'followup.txt')},'result':{'state':'failed','summary':'File unavailable'}}],
              'cards':[],'gaps':['Read failed']}
        if agent:data['agent']={'finished':False}
        db.add(WorkspaceGoal(id='original',request='Create note then read followup',state='partial',result_json=json.dumps(data)))
        await db.commit()

async def checked_path(_db, raw, **kwargs):return Path(raw).resolve()

async def test_completed_mutation_not_replayed_and_parent_retained():
    with tempfile.TemporaryDirectory() as tmp, patch('aries.workspace.capabilities.checked_path',checked_path):
        folder=Path(tmp);(folder/'note.txt').write_text('original');(folder/'followup.txt').write_text('available now')
        await seed(folder)
        async with async_session() as db:
            first=await recovery.resume(db,'original')
            second=await recovery.resume(db,'original')
            check('repeated resume returns the same child',first['id']==second['id'] and second['existing'])
        from aries.workspace import capabilities
        real_execute=capabilities.execute
        called=[]
        async def execute(db,step,**kw):
            called.append(step['capability'])
            return await real_execute(db,step,**kw)
        with patch('aries.workspace.capabilities.execute',execute):await service.dispatch()
        async with async_session() as db:
            parent=await db.get(WorkspaceGoal,'original');child=await db.get(WorkspaceGoal,first['id'])
            check('parent failure remains unchanged',parent.state=='partial' and 'Read failed' in parent.result_json)
            check('child completes after fresh read',child.state=='done' and 'available now' in child.result_json)
            check('create file was never executed again',called==['read_file'] and (folder/'note.txt').read_text()=='original')
            from aries.workspace.evaluation import report
            evaluated=await report(db)
            check('inherited mutation is not counted as a second execution',len(evaluated['capabilities']['create_file'])==1)

async def test_changed_file_between_queue_and_execute_stops_recovery():
    with tempfile.TemporaryDirectory() as tmp, patch('aries.workspace.capabilities.checked_path',checked_path):
        folder=Path(tmp);(folder/'note.txt').write_text('original');(folder/'followup.txt').write_text('next')
        await seed(folder)
        async with async_session() as db:child=await recovery.resume(db,'original')
        (folder/'note.txt').write_text('user edit')
        with patch('aries.workspace.capabilities.execute',AsyncMock()) as execute:await service.dispatch()
        async with async_session() as db:
            row=await db.get(WorkspaceGoal,child['id'])
            check('queued target change blocks all continuation actions',row.state=='failed' and not execute.called)
            check('user edit is preserved',(folder/'note.txt').read_text()=='user edit')

async def test_uncertain_mutation_only_reconciles_if_effect_is_present():
    with tempfile.TemporaryDirectory() as tmp, patch('aries.workspace.capabilities.checked_path',checked_path):
        folder=Path(tmp)
        await seed(folder,effect_state='running')
        async with async_session() as db:
            try:await recovery.resume(db,'original')
            except ValueError:check('uncertain missing mutation is never replayed',True)
            else:check('uncertain missing mutation is never replayed',False)
            (folder/'note.txt').write_text('original')
            child=await recovery.resume(db,'original')
            row=await db.get(WorkspaceGoal,child['id'])
            check('uncertain effect can be reconciled from exact bytes',json.loads(row.result_json)['steps'][0]['inherited'])

async def test_unsupported_agent_plan_is_not_silently_restarted():
    with tempfile.TemporaryDirectory() as tmp, patch('aries.workspace.capabilities.checked_path',checked_path):
        await seed(Path(tmp),agent=True)
        async with async_session() as db:
            plan=await recovery.inspect(db,await db.get(WorkspaceGoal,'original'))
            check('dynamic agent recovery is explicitly unavailable',not plan['available'] and 'Unknown dynamic' in plan['reason'])

async def test_dynamic_read_reobserves_changed_state():
    await reset_db()
    from aries.workspace.registry import file_snapshot
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'read.txt';path.write_text('before')
        old=file_snapshot(path)
        step={'step_id':'step1','task_id':'original','kind':'capability','request':'Read file','capability':'file.read','args':{'path':str(path)},'execution_status':'observed','verification_status':'verified','execution_result':old,'evidence_refs':['old']}
        data={'agent_engine':'m14','agent':{'engine':'m14','request':'Read '+str(path),'max_steps':8,'finished':False},'steps':[step],'evidence':[]}
        async with async_session() as db:
            db.add(WorkspaceGoal(id='original',request='Read '+str(path),state='interrupted',result_json=json.dumps(data)));await db.commit()
            child=await recovery.resume(db,'original')
            child_row=await db.get(WorkspaceGoal,child['id']);state=json.loads(child_row.result_json)
            path.write_text('after restart')
            await recovery.recheck(db,state)
            check('dynamic read refreshed after restart',state['steps'][0]['verification']['data']['text']=='after restart')
            check('parent observations retained',json.loads((await db.get(WorkspaceGoal,'original')).result_json)['steps'][0]['execution_result']['text']=='before')
            check('fresh recovery evidence persisted in child state',state['evidence'][-1]['verified'])

def dynamic_state(path):
    return {'agent_engine':'m14',
            'agent':{'engine':'m14','request':'Read '+str(path),'max_steps':8,'finished':False,
                     'metrics':{'planner_calls':1}, 'context':{'old':'stale context'}},
            'steps':[{'step_id':'step1','task_id':'original','kind':'capability','request':'Read file',
                      'capability':'file.read','args':{'path':str(path)},'state':'verified',
                      'execution_status':'observed','verification_status':'verified',
                      'execution_result':{'text':'stale contents'},
                      'verification':{'met':True,'type':'file','data':{'text':'stale contents'}},
                      'observation':{'text':'stale contents'},'evidence_refs':['old']}],
            'evidence':[{'evidence_id':'old','verified':True,'data':{'text':'stale contents'}}],
            'final_evidence_refs':['old'],'cards':[{'text':'old success'}],'gaps':['old failure']}


async def test_recovery_obeys_a_current_approval_requirement():
    from dataclasses import replace
    from aries.workspace.registry import registry
    await reset_db()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'note.txt';path.write_text('current')
        data=dynamic_state(path);data['recovery']={'dynamic':True,'checks':[]}
        execute=AsyncMock(return_value={})
        cap=replace(registry.get('file.read'),requires_approval=True,executor=execute)
        with patch.dict(registry._items,{'file.read':cap}):
            async with async_session() as db:
                try:await recovery.recheck(db,data)
                except PermissionError:pass
        check('read-only classification cannot bypass a newly required approval',not execute.called)


async def test_recovery_discards_stale_proof_on_failed_refresh():
    await reset_db()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'gone.txt'
        data=dynamic_state(path)
        async with async_session() as db:
            db.add(WorkspaceGoal(id='original',request='Read '+str(path),state='interrupted',result_json=json.dumps(data)))
            await db.commit()
            result=await recovery.resume(db,'original')
            child=await db.get(WorkspaceGoal,result['id']);fresh=json.loads(child.result_json)
            check('continuation exposes no old final answer or planning context',
                  not fresh.get('final_evidence_refs') and not fresh.get('cards') and not fresh['agent'].get('context'))
            await recovery.recheck(db,fresh)
            step=fresh['steps'][0]
            check('failed refresh cannot retain old verified evidence',
                  not any(e.get('verified') for e in fresh['evidence']) and 'old' not in step['evidence_refs'])
            check('failed refresh removes stale execution result and verifier payload',
                  not step.get('execution_result') and step.get('verification',{}).get('met') is not True)
            check('fresh failed observation belongs to the continuation',step['task_id']==result['id'])
            parent=json.loads((await db.get(WorkspaceGoal,'original')).result_json)
            check('original evidence remains inspectable without being reused',parent['evidence'][0]['verified'])


async def test_recovery_requires_boolean_verifier_success():
    from dataclasses import replace
    from aries.workspace.registry import registry
    await reset_db()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'note.txt';path.write_text('current')
        data=dynamic_state(path);data['recovery']={'dynamic':True,'checks':[]}
        cap=replace(registry.get('file.read'),verifier=AsyncMock(return_value={'met':'false','type':'bad','data':{}}))
        with patch.dict(registry._items,{'file.read':cap}):
            async with async_session() as db:await recovery.recheck(db,data)
        check('truthy malformed verifier output never becomes verified',
              data['steps'][0]['verification_status']!='verified' and data['evidence'][-1]['verified'] is False)


async def test_recovery_rejects_removed_capability_and_exhausted_planner():
    await reset_db()
    async with async_session() as db:
        data=dynamic_state('/tmp/missing');data['steps'][0]['capability']='removed.capability'
        row=WorkspaceGoal(id='unsupported',request='Read',state='interrupted',result_json=json.dumps(data))
        try:plan=await recovery.inspect(db,row)
        except ValueError:plan={'available':True}
        check('removed capability is a recoverability refusal, not a server error',not plan['available'])
        data=dynamic_state('/tmp/missing');data['agent']['metrics']['planner_calls']=20
        row.result_json=json.dumps(data)
        plan=await recovery.inspect(db,row)
        check('exhausted planner budget does not create an unusable continuation',not plan['available'])


async def test_dynamic_continuation_runs_through_the_real_queue():
    from aries.workspace import agent_planner
    await reset_db()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'resume.txt';path.write_text('before interruption')
        count=0
        async def initial(db,goal,data,budget):
            nonlocal count
            count+=1
            decision=({'action':'execute','capability':'file.read','arguments':{'path':str(path)}}
                      if count==1 else {'action':'fail','reason':'simulated planner interruption'})
            return json.dumps(decision),{'measured':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
        # The test deliberately interrupts before completion; disable the separate
        # automatic-completion optimization so the planner's failure is reached.
        with patch.object(agent_planner,'plan',initial), patch.dict('os.environ',{'ARIES_CONTRACT_FINISH':'0'}):
            async with async_session() as db:
                queued=await service.submit(db,'',capability='agent_task',args={'task':'Read '+str(path)},origin='user')
            await service.dispatch()
        async with async_session() as db:
            parent=await db.get(WorkspaceGoal,queued['id'])
            check('real dynamic parent records a partial attempt',parent.state=='partial')
            child=await recovery.resume(db,parent.id)
        path.write_text('fresh continuation content')
        async def complete(db,goal,data,budget):
            refs=[e['evidence_id'] for e in data['evidence'] if e['verified']]
            return json.dumps({'action':'finish','evidence_refs':refs}),{'measured':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
        with patch.object(agent_planner,'plan',complete):await service.dispatch()
        async with async_session() as db:
            result=await db.get(WorkspaceGoal,child['id']);state=json.loads(result.result_json)
            check('dynamic continuation finishes with freshly verified file contents',
                  result.state=='done' and state['steps'][0]['verification']['data']['text']=='fresh continuation content')
            check('recovery does not need to replay or add a file action',len(state['steps'])==1)
            old=await db.get(WorkspaceGoal,queued['id'])
            check('real parent retains its original state and observation',
                  old.state=='partial' and json.loads(old.result_json)['steps'][0]['execution_result']['text']=='before interruption')


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
