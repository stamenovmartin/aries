"""Probe verifiers must reject wrong identities, malformed data and changed snapshots."""
import copy
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,run_module
bootstrap('aries-probe-verification')
from aries.workspace.registry import verify_probe
from aries.workspace.probe_verification import agrees


def sample(kind):
    metric={'metric':'disk.used_pct','value':25.0,'subject':'/','unit':'%'}
    if kind=='system_probe':
        return {'probes':[{'probe':p,'ok':True,'readings':[{**metric,'metric':p+'.used_pct'}]}
                          for p in ('cpu','memory','disk')],'observed_at':'now'}
    if kind=='storage_probe':
        return {'probe':'statvfs','filesystems':[metric],'highest':metric,'observed_at':'now'}
    if kind=='process_probe':
        return {'count':1,'processes':[{'pid':1,'name':'init'}],'truncated':False,'observed_at':'now'}
    return {'task_id':'task','state':'done','steps':1,'evidence_ids':['proof'],'observed_at':'now'}


async def test_registered_factory_rejects_empty_and_forged_results():
    for kind in ('system_probe','storage_probe','process_probe','task_state'):
        data=sample(kind);args={'task_id':'task'} if kind=='task_state' else {}
        async def fresh(a,c):return data
        verifier=verify_probe(fresh,kind)
        check(f'{kind} valid observation passes',(await verifier(args,copy.deepcopy(data),{}))['met'])
        check(f'{kind} empty executor claim fails',not (await verifier(args,{},{}))['met'])
        data={}
        check(f'{kind} empty second read fails',not (await verifier(args,sample(kind),{}))['met'])
    before=sample('system_probe');after=copy.deepcopy(before)
    after['probes'][0]['readings'][0]['value']=95
    check('a real changing CPU sample is not a false disagreement',agrees('system_probe',{},before,after))
    after['probes'][0]['readings'][0]['value']=float('nan')
    check('nonfinite measurement cannot verify',not agrees('system_probe',{},before,after))
    after=sample('storage_probe');after['highest']={'value':99}
    check('unobserved highest filesystem is rejected',not agrees('storage_probe',{},sample('storage_probe'),after))
    after=sample('process_probe');after['count']=7
    check('undisclosed truncated process set fails',not agrees('process_probe',{},sample('process_probe'),after))
    check('wrong task identity fails',not agrees('task_state',{'task_id':'other'},sample('task_state'),sample('task_state')))


async def test_directory_and_search_compare_actual_snapshot():
    with tempfile.TemporaryDirectory() as directory:
        for kind,key,items in [('directory_state','path','entries'),('file_search','root','matches')]:
            row={'name':'a','path':directory+'/a','directory':False} if items=='entries' else {
                'path':directory+'/a','size':1,'modified_at':'now'}
            before={key:directory,items:[row],'count':1,'truncated':False,'observed_at':'first'}
            after=copy.deepcopy(before);after['observed_at']='second'
            check(f'{kind} identical independent contents pass',agrees(kind,{'path':directory},before,after))
            after[items]=[];after['count']=0
            check(f'{kind} vanished file falsifies the old claim',not agrees(kind,{'path':directory},before,after))
            check(f'{kind} wrong requested root fails',not agrees(kind,{'path':directory+'/other'},before,before))
            check(f'{kind} malformed claim fails',not agrees(kind,{'path':directory},{},before))


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
