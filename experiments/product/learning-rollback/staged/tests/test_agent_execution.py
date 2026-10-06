"""M14 deterministic planners, real queue/API/files/probes, hostile completion controls."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-m14')
import httpx
from agentic_core.database.base import async_session
from agentic_core.config.settings import settings as engine_settings
from aries.settings import SettingsService
from aries.workspace import service, agent_planner, contracts
from aries.workspace.models import WorkspaceGoal
from aries.workspace.registry import registry, Registry, Capability, Empty, policy
from aries.api import routes
from aries.api.app import app


async def setup(limit=8):
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set('operator.enabled',True,set_by='user')
        await SettingsService(db).set('operator.confirm_model_plans',False,set_by='user')
        await SettingsService(db).set('workspace.agent_max_steps',limit,set_by='user')
        await db.commit()


def execute(capability, **args):
    return {'action':'execute','capability':capability,'arguments':args,'reason':'Required by user goal'}


def finish(data):
    return {'action':'finish','summary':'MODEL CLAIM MUST NOT BE TRUSTED',
            'evidence_refs':[e['evidence_id'] for e in data.get('evidence',[]) if e['verified']]}


def fake(sequence):
    index = 0
    async def plan(db, goal, data, budget):
        nonlocal index
        choice = sequence[min(index,len(sequence)-1)]
        index += 1
        value = choice(data) if callable(choice) else choice
        return (value if isinstance(value,str) else json.dumps(value)), {'measured':{'input_tokens':20,'output_tokens':10,'total_tokens':30}}
    return plan


async def run_goal(goal, sequence):
    with patch.object(agent_planner,'plan',side_effect=fake(sequence)), patch.object(engine_settings,'dry_run',False), patch.object(engine_settings,'live_tools',','.join(__import__('aries.workspace.capabilities',fromlist=['TOOL_NAMES']).TOOL_NAMES)):
        async with async_session() as db:
            row = await service.submit(db,'',capability='agent_task',args={'task':goal},origin='user')
        await service.dispatch()
        async with async_session() as db:
            return (await db.get(WorkspaceGoal,row['id'])).as_dict()


async def test_file_workflow_and_persistent_api():
    await setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'aries-m14-test.txt'
        goal=f'Create a file called aries-m14-test.txt in {directory} containing:\nARIES M14 verified execution\nThen read it back.'
        result=await run_goal(goal,[execute('file.write',path=str(path),content='ARIES M14 verified execution'),execute('file.read',path=str(path)),finish])
        check('file scenario completes only with OS verified bytes',result['state']=='done' and path.read_text()=='ARIES M14 verified execution')
        check('model completion prose is not the final answer','MODEL CLAIM' not in result['agent']['summary'])
        check('each executed step has execution and verification evidence',all(s.get('observation_ref') and s['evidence_refs'] for s in result['steps']))
        check('explicit lifecycle persisted', [x['state'] for x in result['steps'][0]['transitions']]==['planned','executing','observed','verified'])
        from aries import flags
        expected_calls=2 if flags.enabled('ARIES_CONTRACT_FINISH') else 3
        check('measured tokens and calls persist',result['agent']['metrics']['planner_calls']==expected_calls and
              result['agent']['metrics']['total_tokens']==30*expected_calls)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            for suffix,key in [('', 'id'),('/steps','steps'),('/evidence','evidence')]:
                response=await client.get('/api/aries/workspace/'+result['id']+suffix)
                check('persisted API '+suffix,response.status_code==200 and key in response.json())
            missing=await client.get('/api/aries/workspace/no-such-task/evidence')
            check('missing task returns 404',missing.status_code==404)


async def test_system_storage_answer_is_computed_from_probe():
    await setup()
    result=await run_goal('Check disk usage and report which filesystem has the highest percentage used.',[execute('system.storage'),finish])
    check('storage scenario completes',result['state']=='done')
    evidence=next(e for e in result['evidence'] if e['evidence_id']==result['final_evidence_refs'][0])
    rows=evidence['data']['filesystems'];top=max(rows,key=lambda r:r['value'])
    check('highest filesystem is derived from measured data',str(top['subject']) in result['agent']['summary'] and str(top['value']) in result['agent']['summary'])


async def test_macedonian_measurement_finishes_as_a_verified_answer():
    await setup()
    result = await run_goal('колку место има на дискот?', [execute('system.storage'), finish])
    check('a measured Macedonian question is answered rather than reported partial',
          result['state'] == 'answered' and result['agent']['finished'])
    check('the answer retains independent proof IDs', bool(result['final_evidence_refs'])
          and all(e['verified'] for e in result['evidence'] if e['evidence_id'] in result['final_evidence_refs']))
    check('the spoken answer comes from readings, never the model finish claim',
          'Дискот' in result['agent']['summary'] and 'MODEL CLAIM' not in result['agent']['summary'])


async def test_browser_scenario_and_unavailable_browser():
    await setup()
    state={'session':'owned','url':'https://www.python.org/','title':'Observed Python title','text':'public page'}
    cap=registry.get('browser.open');read=registry.get('browser.read')
    async def open_(a,c):return state
    async def verify(a,r,c):return {'met':True,'type':'browser_state','data':state}
    with patch.dict(registry._items,{'browser.open':replace(cap,executor=open_,verifier=verify),'browser.read':replace(read,executor=open_,verifier=verify)}):
        result=await run_goal('Open https://www.python.org and report the observed page title.',[execute('browser.open',url='https://www.python.org'),execute('browser.read',session='owned'),finish])
    check('browser goal requires both open and observed read',result['state']=='done' and result['agent']['summary'].startswith('Observed Python title'))
    async def offline(a,c):raise ConnectionError('Browser is unavailable')
    with patch.dict(registry._items,{'browser.open':replace(cap,executor=offline)}):
        result=await run_goal('Open https://www.python.org and report the observed page title.',[execute('browser.open',url='https://www.python.org'),{'action':'fail','reason':'Browser unavailable'}])
    check('unavailable browser cannot become done',result['state']=='failed' and result['steps'][0]['error']['error_type']=='ConnectionError')


async def test_negative_control_real_missing_file():
    await setup()
    path='/this/path/does/not/exist/aries.txt'
    result=await run_goal('Read '+path,[execute('file.read',path=path),{'action':'finish','evidence_refs':[]},{'action':'fail','reason':'No readable file'}])
    check('negative control never reports done',result['state']=='failed')
    check('real read error and unsuccessful evidence retained',result['steps'][0]['error'] and not any(e['verified'] for e in result['evidence']))


def test_registry_and_schema_validation():
    check('all fifteen M14 capabilities remain registered', {'file.read','file.write','file.list','file.search','file.exists','browser.open','browser.read','browser.search','desktop.launch','desktop.focus','system.status','system.storage','system.processes','task.inspect','notification.send'} <= {c['name'] for c in registry.describe_allowed()})
    for raw in ['not json','{}',json.dumps(execute('shell.run',command='echo unsafe')),json.dumps(execute('file.read',path=12)),json.dumps(execute('file.read',path='/tmp/x',shell='rm')),json.dumps({'action':'finish','capability':'file.write','arguments':{}})]:
        try:agent_planner.parse(raw)
        except ValueError:check('invalid decision is rejected: '+raw[:35],True)
        else:check('invalid decision is rejected: '+raw[:35],False)
    r=Registry();r.register(registry.get('file.read'))
    try:r.register(registry.get('file.read'))
    except ValueError:check('duplicate registry entry rejected',True)
    else:check('duplicate registry entry rejected',False)


async def test_invalid_model_retry_is_recorded_and_bounded():
    await setup()
    result=await run_goal('Show system status',['{broken','{broken'])
    check('invalid JSON stops after two attempts',result['state']=='failed' and result['agent']['metrics']['planner_calls']==2 and not result['steps'])
    check('invalid raw output persisted',all(d.get('raw')=='{broken' and d.get('error') for d in result['agent']['decisions']))
    result=await run_goal('Show system status',[execute('shell.run',command='whoami'),execute('system.status'),finish])
    check('unknown capability retry cannot execute unknown tool',result['state']=='done' and len(result['steps'])==1 and result['agent']['metrics']['wrong_capability_selections']==1)


async def test_policy_and_approval_are_before_execution():
    await setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'unauthorized'
        result=await run_goal('Show system status',[execute('file.write',path=str(path),content='not requested'),{'action':'fail'}])
        check('file create without user intent is rejected',not path.exists() and result['steps'][0]['error']['error_type']=='PermissionError')
        result=await run_goal('Create /etc/aries-test containing no',[execute('file.write',path='/etc/aries-test',content='no'),{'action':'fail'}])
        check('system path write rejected',result['state']=='failed' and not Path('/etc/aries-test').exists())
    result=await run_goal('Notify me when checked',[{'action':'ask_approval','capability':'notification.send','arguments':{'title':'M14','body':'test'}}])
    check('approval request persists frozen inputs without executing',result['state']=='proposed' and result['steps'][0]['execution_status']=='planned' and not result['evidence'])


async def test_verification_failure_and_later_recovery():
    await setup()
    cap=registry.get('system.status')
    async def bad(a,r,c):return {'met':False,'type':'system_probe','data':{'reason':'no independent observation'}}
    with patch.dict(registry._items,{'system.status':replace(cap,verifier=bad)}):
        result=await run_goal('Show system status',[execute('system.status'),finish,{'action':'fail'}])
    check('executor success is not verification success',result['state']=='failed' and result['steps'][0]['state']=='verification_failed')
    check('verification failures counted separately',result['agent']['metrics']['verification_failures']>=1 and result['agent']['metrics']['capability_failures']==0)
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        real=Path(directory)/'real';real.write_text('actual')
        result=await run_goal('Read '+str(real),[execute('file.read',path=str(real)+'-missing'),execute('file.read',path=str(real)),finish])
        check('planner may change arguments after failure and complete',result['state']=='done' and result['agent']['metrics']['capability_failures']==1)


async def test_finish_empty_unrelated_and_changed_state():
    await setup(limit=2)
    result=await run_goal('Show system status',[{'action':'finish','evidence_refs':[]}])
    check('finish without evidence remains failed and bounded',result['state']=='failed' and result['agent']['metrics']['planner_calls']<=8)
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'expected';path.write_text('before')
        other=Path(directory)/'other';other.write_text('irrelevant')
        result=await run_goal('Read '+str(path),[execute('file.read',path=str(other)),finish,{'action':'fail'}])
        check('unrelated verified action cannot satisfy goal',result['state']=='partial')
        def changed(data):path.write_text('changed by user');return finish(data)
        # This fault is injected inside the model callback; automatic completion
        # has its own verifier-boundary state-change fixture in test_finish_proposal.
        with patch.dict('os.environ',{'ARIES_CONTRACT_FINISH':'0'}):
            result=await run_goal('Read '+str(path),[execute('file.read',path=str(path)),changed,{'action':'fail'}])
        check('finish reobserves changed external state',result['state']=='partial' and not result.get('final_evidence_refs'))


async def test_budget_and_unsupported_goal():
    await setup(limit=1)
    result=await run_goal('Check disk usage and report which filesystem has the highest percentage used.',[execute('system.status'),execute('system.storage')])
    check('action budget cannot be exceeded',len(result['steps'])==1 and result['state']=='partial')
    result=await run_goal('Do something impressive',[execute('system.status'),finish])
    check('unsupported semantic goal cannot be marked done',result['state']=='partial' and not result['agent']['contract']['supported'])


def test_observation_bound_and_natural_routing():
    large={'files':['x'*5000]*20000}
    result=agent_planner.bounded(large,max_chars=3000)
    check('huge observations remain valid bounded JSON',len(json.dumps(result,ensure_ascii=False))<=3000 and result['truncated'])
    for request in ['Create a file called test.txt in the ARIES demo directory containing:\nhello\nThen read it back.', 'Check disk usage and report which filesystem has the highest percentage used.', 'Open https://www.python.org and report the observed page title.', 'Read /this/path/does/not/exist/aries.txt']:
        check('natural goal routed to registry agent',service.plan(request)[0]['capability']=='agent_task')


async def test_restart_keeps_history_and_never_replays_uncertain_write():
    await setup()
    from aries.workspace import recovery
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'once'
        result=await run_goal('Create '+str(path)+' containing hello',[execute('file.write',path=str(path),content='hello'),finish])
        async with async_session() as db:
            row=await db.get(WorkspaceGoal,result['id'])
            data=json.loads(row.result_json)
            data['steps'][0]['execution_status']='executing'
            row.result_json=json.dumps(data);row.state='queued';await db.commit()
        with patch.object(agent_planner,'plan',AsyncMock()) as plan:
            await service.dispatch()
        async with async_session() as db:
            row=await db.get(WorkspaceGoal,result['id'])
            info=await recovery.inspect(db,row)
            check('restart cannot replay uncertain create',row.state=='interrupted' and not plan.called and path.read_text()=='hello')
            check('dynamic recovery explicitly refuses automatic replay',not info['available'] and len(json.loads(row.result_json)['steps'])==1)


async def test_user_write_target_and_confirmation_policy():
    await setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        requested=Path(directory)/'requested';other=Path(directory)/'other'
        goal='Create '+str(requested)+' containing hello'
        result=await run_goal(goal,[execute('file.write',path=str(other),content='hello'),{'action':'fail'}])
        check('known user target enforced before write',not other.exists() and result['state']=='failed')
        result=await run_goal(goal,[execute('file.write',path=str(requested),content='wrong'),{'action':'fail'}])
        check('known user content enforced before write',not requested.exists() and result['state']=='failed')
        async with async_session() as db:
            await SettingsService(db).set('operator.confirm_model_plans',True,set_by='user');await db.commit()
        result=await run_goal(goal,[execute('file.write',path=str(requested),content='hello')])
        check('existing model confirmation setting is honored',result['state']=='proposed' and not requested.exists())
        async def approve_once():
            async with async_session() as db:
                try:return await service.approve(db,result['id'])
                except ValueError:return None
        responses=await asyncio.gather(approve_once(),approve_once())
        check('concurrent approval queues exactly one frozen proposal',sum(r is not None for r in responses)==1)
        from aries.workspace.capabilities import TOOL_NAMES
        with patch.object(agent_planner,'plan',side_effect=fake([finish])), patch.object(engine_settings,'dry_run',False), patch.object(engine_settings,'live_tools',','.join(TOOL_NAMES)):
            await service.dispatch()
        async with async_session() as db:row=(await db.get(WorkspaceGoal,result['id'])).as_dict()
        check('approved frozen write executes once and verifies',row['state']=='done' and len(row['steps'])==1 and requested.read_text()=='hello')
        m=row['agent']['metrics']
        check('active elapsed time accumulates across approval resume',m['wall_seconds']+.05>=m['planner_time']+m['execution_time'])


def test_descriptor_path_and_search_goal_false_positive_controls():
    from aries.workspace.filesystem import open_nofollow
    import os
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);(root/'real').mkdir();(root/'alias').symlink_to(root/'real',target_is_directory=True)
        try:fd=open_nofollow(root/'alias'/'created',os.O_WRONLY|os.O_CREAT|os.O_EXCL)
        except OSError:check('parent symlink cannot redirect file syscall',not (root/'real'/'created').exists())
        else:os.close(fd);check('parent symlink cannot redirect file syscall',False)
    required={'capability':'browser.search','query':'NVIDIA GTC keynote','site':'youtube'}
    for url in ['https://consent.youtube.com/', 'https://www.youtube.com/results?search_query=wrong', 'https://www.youtube.com/watch?search_query=NVIDIA%20GTC%20keynote']:
        check('unrelated search state cannot satisfy query',not contracts.evidence_matches(required,{'met':True,'data':{'url':url,'title':'Some page'}}))
    check('observed exact search URL satisfies query',contracts.evidence_matches(required,{'met':True,'data':{'url':'https://www.youtube.com/results?search_query=NVIDIA%20GTC%20keynote','title':'Search'}}))


async def test_registry_extension_and_persist_before_boundaries():
    await setup()
    observed=[]
    async def probe(args,ctx):
        async with async_session() as db:
            row=await db.get(WorkspaceGoal,ctx['task_id']);d=json.loads(row.result_json)
            observed.append(d['steps'][-1]['state']=='executing')
        return {'value':42}
    async def verify(args,result,ctx):
        async with async_session() as db:
            row=await db.get(WorkspaceGoal,ctx['task_id']);d=json.loads(row.result_json)
            observed.append(d['steps'][-1]['state']=='observed' and bool(d['steps'][-1]['observation_ref']))
        return {'met':True,'type':'test_probe','data':{'observed':42}}
    custom=Capability('test.probe','Test extension',Empty,probe,verify)
    with patch.dict(registry._items,{'test.probe':custom}):
        result=await run_goal('Inspect new capability',[execute('test.probe'),finish])
    check('new capability executes without modifying planner core',result['steps'][0]['verification_status']=='verified')
    check('execution and observation persisted before external boundaries',observed==[True,True])
    check('extension needs independent goal oracle before done',result['state']=='partial')



async def test_a_question_is_answered_not_failed():
    await setup()
    result=await run_goal('Do you have a student ID?',[{'action':'fail','summary':"No, I'm an AI assistant."}])
    check('a request that asks nothing of the machine ends answered', result['state']=='answered')
    check('the reply is shown as the answer', result['cards'][0]['title']=='Answer' and 'AI assistant' in result['cards'][0]['text'])
    check('and is not recorded as a gap', not result.get('gaps'))
    result=await run_goal('Show system status',[execute('system.status'),{'action':'fail','summary':'gave up'}])
    check('a supported task that gives up is still a failure, not an answer', result['state']!='answered')


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
