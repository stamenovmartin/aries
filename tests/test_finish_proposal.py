import copy
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch,AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-finish-proposal')
from aries.workspace import finish_proposal,contracts,agent,agent_planner
from aries.workspace.registry import registry
from aries.workspace.models import WorkspaceGoal
from agentic_core.database.base import async_session


def fixture():
    steps=[];evidence=[]
    for name in ['a','b']:
        steps.append({'step_id':name,'capability':'file.read','args':{'path':'/tmp/'+name},
            'execution_status':'observed','verification_status':'verified','evidence_refs':[name],
            'verification':{'met':True,'data':{'path':'/tmp/'+name}}})
        evidence.append({'evidence_id':name,'step_id':name,'source':'file.read','verified':True})
    return {'agent':{'contract':contracts.compile_goal('Read /tmp/a and read /tmp/b','/tmp')},'steps':steps,'evidence':evidence}


async def test_proposal_requires_ordered_proof_not_tool_success():
    with patch.dict('os.environ',{'ARIES_CONTRACT_FINISH':'1'}):
        data=fixture();check('ordered proof permits proposal',finish_proposal.propose(data).evidence_refs==['a','b'])
        for mutation in ['order','missing','unverified','wrong-source','wrong-step','wrong-path','unsupported','rejected']:
            data=fixture()
            if mutation=='order':data['steps'].reverse()
            if mutation=='missing':data['steps'].pop()
            if mutation=='unverified':data['evidence'][0]['verified']=False
            if mutation=='wrong-source':data['evidence'][0]['source']='file.write'
            if mutation=='wrong-step':data['evidence'][0]['step_id']='elsewhere'
            if mutation=='wrong-path':data['steps'][0]['verification']['data']['path']='/tmp/other'
            if mutation=='unsupported':data['agent']['contract']['supported']=False
            if mutation=='rejected':data['agent']['automatic_finish_step_count']=2
            check('no automatic proposal: '+mutation,finish_proposal.propose(data) is None)
    with patch.dict('os.environ',{'ARIES_CONTRACT_FINISH':'0'}):
        check('rollback returns ordinary planner path',finish_proposal.propose(fixture()) is None)


async def exercise(*,change=False,deny=False):
    await reset_db()
    with tempfile.TemporaryDirectory(dir=Path.home()) as temp:
        path=Path(temp)/'fixture.txt';path.write_text('initial');goal=f'Read {path}'
        async with async_session() as db:
            db.add(WorkspaceGoal(id='root',request=goal,state='running',result_json='{}'));await db.commit()
        calls=0;checks=0
        original=registry.get('file.read')
        async def verify(args,result,ctx):
            nonlocal checks
            checks+=1
            if change and checks==2:path.write_text('changed')
            return await original.verifier(args,result,ctx)
        async def planner(db,goal,data,budget):
            nonlocal calls
            calls+=1
            if deny and data['steps']:decision={'action':'fail','reason':'Current permission denied'}
            else:decision={'action':'execute','capability':'file.read','arguments':{'path':str(path)}}
            return json.dumps(decision),{'measured':{'input_tokens':10,'output_tokens':5,'total_tokens':15}}
        old_policy=agent.policy
        async def policy(db,cap,args,goal,**kwargs):
            if deny and checks>=1:raise PermissionError('Permission revoked before completion')
            return await old_policy(db,cap,args,goal,**kwargs)
        with patch.dict('os.environ',{'ARIES_CONTRACT_FINISH':'1','ARIES_GOAL_TEAMS':'0'}), \
             patch.dict(registry._items,{'file.read':replace(original,verifier=verify)}), \
             patch.object(agent_planner,'plan',side_effect=planner),patch.object(agent,'policy',side_effect=policy):
            await agent.run('root',goal,{})
        async with async_session() as db:
            row=await db.get(WorkspaceGoal,'root');data=json.loads(row.result_json)
        if deny:
            check('revoked permission prevents automatic success',row.state=='partial' and not data.get('final_evidence_refs'))
            check('rejected proposal falls back once to planner',calls==2 and data['agent']['metrics']['automatic_finish_proposals']==1)
        elif change:
            check('changed file causes failed independent recheck',data['agent']['completion_checks'][0]['met'] is False)
            check('planner can recover with a new verified observation',row.state=='done' and calls==2)
        else:
            check('verified goal finishes with one planner invocation',row.state=='done' and calls==1)
            check('independent final recheck remains mandatory',checks==2)
            check('automatic proposal is distinct from model telemetry',data['agent']['decisions'][-1]['source']=='contract-evidence')


async def test_real_read_still_independently_rechecked():await exercise()
async def test_state_change_requires_replan():await exercise(change=True)
async def test_permission_revoked_before_finish():await exercise(deny=True)


async def test_stale_write_never_becomes_retryable():
    data=fixture();step=data['steps'][0]
    data['steps']=[step];data['evidence']=data['evidence'][:1]
    step.update(capability='file.write',args={'path':'/tmp/a','content':'alpha'},execution_result={})
    data['evidence'][0]['source']='file.write'
    data['agent']['contract']=contracts.compile_goal('Write file /tmp/a with content: alpha','/tmp')
    cap=registry.get('file.write')
    verifier=AsyncMock(return_value={'met':False,'type':'file_state','data':{'path':'/tmp/a'}})
    with patch.dict(registry._items,{'file.write':replace(cap,verifier=verifier)}),patch.object(agent,'policy',AsyncMock(return_value=True)):
        met,_,_=await agent.completion(data,agent_planner.Decision(action='finish',evidence_refs=['a']),
                                      {'db':AsyncMock(),'goal':'Write file /tmp/a with content: alpha','task_id':'root'})
    check('stale mutation never authorizes a replay',not met and step['error']['retryable'] is False)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
