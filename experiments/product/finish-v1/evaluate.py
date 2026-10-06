"""Native paired completion-call ablation with filesystem fixture oracles."""
import asyncio,hashlib,json,os,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from tests._bootstrap import bootstrap,reset_db
bootstrap('aries-finish-native-eval')
from agentic_core.database.base import async_session
from aries.workspace import agent
from aries.workspace.models import WorkspaceGoal
from aries.intelligence import budgets
from aries.settings import SettingsService
OUT=Path(__file__).resolve().parent


def hashes():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'aries').rglob('*.py'))}


async def trial(case,repeat,enabled,directory):
    await reset_db()
    a,b,missing=[directory/name for name in ['a.txt','b.txt','missing.txt']]
    a.write_text('alpha');b.write_text('beta')
    goal={'single':f'Read {a}','compound':f'Read {a} and read {b}','missing':f'Read {missing}'}[case]
    expected={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in ([a,b] if case=='compound' else [a] if case=='single' else [])}
    async with async_session() as db:
        await SettingsService(db).set('privacy.mode',True,set_by='user')
        db.add(WorkspaceGoal(id='root',request=goal,state='running',result_json='{}'));await db.commit()
    start=time.monotonic();error=None
    try:
        with patch.dict(os.environ,{'ARIES_CONTRACT_FINISH':str(int(enabled)),'ARIES_GOAL_TEAMS':'0',
                'ARIES_STATE_SNAPSHOT':'0','ARIES_PLAN_MEMORY':'0','ARIES_TRACE_FEWSHOT':'0'}):
            await asyncio.wait_for(agent.run('root',goal,{}),120)
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    async with async_session() as db:
        row=await db.get(WorkspaceGoal,'root');data=json.loads(row.result_json);state=row.state
    refs=set(data.get('final_evidence_refs',[]))
    observed={e['data'].get('path'):e['data'].get('sha256') for e in data.get('evidence',[]) if e['evidence_id'] in refs and e['verified']}
    passed=(state=='done' and observed==expected) if case!='missing' else (state=='failed' and not missing.exists() and not refs)
    return {'case':case,'repeat':repeat,'arm':'automatic' if enabled else 'model-finish','state':state,
        'oracle_passed':passed and error is None,'positive_verified':case!='missing' and passed,
        'final_proof_count':len(refs),'budget':await budgets.snapshot('root'),
        'metrics':data.get('agent',{}).get('metrics'),'error':error,'latency_ms':(time.monotonic()-start)*1000}


async def main():
    before=hashes();rows=[]
    with tempfile.TemporaryDirectory(dir=Path.home(),prefix='aries-finish-eval-') as tmp:
        for repeat in range(2):
            for case in ['single','compound','missing']:
                for enabled in ([False,True] if repeat==0 else [True,False]):
                    rows.append(await trial(case,repeat,enabled,Path(tmp)))
                    (OUT/'trials.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    totals={}
    for arm in ['model-finish','automatic']:
        rs=[r for r in rows if r['arm']==arm]
        totals[arm]={'assigned':len(rs),'oracle_passed':sum(r['oracle_passed'] for r in rs),
            'positive_verified':sum(r['positive_verified'] for r in rs),
            'model_calls':sum(r['budget']['calls'] for r in rs),'tokens':sum(r['budget']['tokens'] for r in rs),
            'tool_verifier_calls':sum(r['budget']['tools'] for r in rs),
            'latency_ms':sum(r['latency_ms'] for r in rs),'cost_usd':None}
    stable=before==hashes()
    summary={'assigned':12,'completed':len(rows),'source_stable':stable,'source_hashes':before,'arms':totals,
             'failures':[r for r in rows if not r['oracle_passed']],
             'scope':'Native local paired file-read fixtures, two repeats; no general long-horizon or paid-cost claim'}
    summary['admitted']=stable and not summary['failures'] and totals['automatic']['model_calls']<totals['model-finish']['model_calls'] and totals['automatic']['tokens']<totals['model-finish']['tokens']
    (OUT/'evaluation.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='source_hashes'}))
    if not summary['admitted']:raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
