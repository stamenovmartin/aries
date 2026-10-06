import copy,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.test_agent_execution import setup,run_goal,execute,finish
from tests._bootstrap import check,run_module
from aries.workspace import terminal_failure,contracts


def fixture():
    err={'code':'TARGET_NOT_FOUND','error_type':'FileNotFoundError','retryable':False,'message':'missing'}
    step={'step_id':'s','capability':'file.read','args':{'path':'/tmp/missing'},'started_at':'now',
          'execution_status':'failed','observation_ref':'e','error':err}
    data={'agent':{'contract':contracts.compile_goal('Read /tmp/missing','/tmp')},
          'evidence':[{'evidence_id':'e','source':'file.read','step_id':'s','type':'execution_error','verified':False,'data':copy.deepcopy(err)}]}
    return data,step


async def test_narrow_terminal_condition():
    with patch.dict('os.environ',{'ARIES_TERMINAL_READ_FAILURE':'1'}):
        data,step=fixture();check('actual exact missing-read evidence stops repeats',bool(terminal_failure.reason(data,step)))
        for change in ['wrong-path','transient','permission','no-attempt','no-observation','wrong-observation','unrelated-error','compound','unsupported']:
            data,step=fixture()
            if change=='wrong-path':step['args']['path']='/tmp/other'
            if change=='transient':step['error']['retryable']=True
            if change=='permission':step['error']['error_type']='PermissionError'
            if change=='no-attempt':step['started_at']=None
            if change=='no-observation':data['evidence']=[]
            if change=='wrong-observation':data['evidence'][0]['step_id']='another'
            if change=='unrelated-error':data['evidence'][0]['data']['message']='different error'
            if change=='compound':data['agent']['contract']['requirements']*=2
            if change=='unsupported':data['agent']['contract']['supported']=False
            check('keep planner control: '+change,terminal_failure.reason(data,step) is None)
    with patch.dict('os.environ',{'ARIES_TERMINAL_READ_FAILURE':'0'}):
        check('ablation restores old loop',terminal_failure.reason(*fixture()) is None)


async def test_missing_target_stops_after_actual_read_only():
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        missing=str(Path(directory)/'missing.txt')
        for enabled in ['0','1']:
            await setup(limit=3)
            with patch.dict('os.environ',{'ARIES_TERMINAL_READ_FAILURE':enabled}):
                result=await run_goal('Read '+missing,[execute('file.read',path=missing)])
            check('missing target is never reported successful '+enabled,result['state']=='failed' and not result.get('final_evidence_refs'))
            if enabled=='1':
                check('exact missing read stops after one model call',result['agent']['metrics']['planner_calls']==1)
                check('typed failure and observation retained',result['steps'][0]['error']['code']=='TARGET_NOT_FOUND' and bool(result['steps'][0]['observation_ref']))
                check('reason visible separately from exhausted budget',result['agent']['stop_reason']=='REQUESTED_FILE_NOT_FOUND')
            else:check('control really repeats planning',result['agent']['metrics']['planner_calls']>1)


async def test_wrong_target_and_compound_goal_keep_recovery():
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        good=Path(directory)/'good.txt';good.write_text('good');missing=Path(directory)/'missing.txt'
        with patch.dict('os.environ',{'ARIES_TERMINAL_READ_FAILURE':'1'}):
            await setup()
            result=await run_goal('Read '+str(good),[execute('file.read',path=str(missing)),execute('file.read',path=str(good)),finish])
            check('wrong target can be corrected',result['state']=='done' and result.get('final_evidence_refs'))
            await setup()
            result=await run_goal(f'Read {missing} and read {good}',[execute('file.read',path=str(missing)),execute('file.read',path=str(good)),{'action':'fail','reason':'One file missing'}])
            check('compound goal retains useful remaining work',result['state']=='partial' and any(s['verification_status']=='verified' for s in result['steps']))


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
