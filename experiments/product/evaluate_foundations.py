"""Reproducible component ablation; deterministic planners, real tools and proofs.

This is not a model-quality benchmark. It cannot establish token/cost savings.
Run from the repository root with .venv/bin/python experiments/product/evaluate_foundations.py.
"""
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tests._bootstrap import bootstrap,reset_db
bootstrap('aries-product-foundations-evaluation')
from agentic_core.database.base import async_session
from aries.workspace import agent,agent_planner,goal_graph,orchestration
from aries.workspace.models import WorkspaceGoal
from aries.intelligence import budgets


def hashes():
    files=[*ROOT.glob('aries/workspace/*.py'),*ROOT.glob('aries/intelligence/*.py')]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


async def trial(seed,team,directory):
    await reset_db()
    paths=[directory/'alpha.txt',directory/'beta.txt']
    contents=[f'alpha-{seed}',f'beta-{seed}']
    for p,value in zip(paths,contents):p.write_text(value)
    goal=' and '.join('Read '+str(p) for p in paths)
    plan=goal_graph.Plan(nodes=[goal_graph.Node(id=f'n{i}',role='reader',goal=f'Read {p}',
        capabilities=['file.read']) for i,p in enumerate(paths)])
    calls=0
    async def planner(db,request,data,budget):
        nonlocal calls
        calls+=1
        pending=[r for r in data['agent']['contract']['requirements'] if
                 not any(s['args'].get('path')==r['path'] for s in data['steps'])]
        if pending:
            decision={'action':'execute','capability':'file.read','arguments':{'path':pending[0]['path']}}
        else:decision={'action':'finish','evidence_refs':[e['evidence_id'] for e in data['evidence'] if e['verified']]}
        return json.dumps(decision),{'measured':{'input_tokens':None,'output_tokens':None,'total_tokens':None}}
    async with async_session() as db:
        db.add(WorkspaceGoal(id='root',request=goal,state='running',result_json='{}'));await db.commit()
    start=time.monotonic()
    error=None
    try:
        with patch.object(agent_planner,'plan',side_effect=planner), \
             patch.object(goal_graph,'propose',AsyncMock(return_value=(plan,{}))), \
             patch.object(orchestration,'capacity',AsyncMock(return_value=orchestration.Capacity(4,'fixture'))), \
             patch.dict(os.environ,{'ARIES_GOAL_TEAMS':str(int(team)),'ARIES_CONTEXT_ENGINE':'0',
                                   'ARIES_PLAN_MEMORY':'0','ARIES_TRACE_FEWSHOT':'0'}):
            await agent.run('root',goal,{})
            if team:await orchestration.tick(wait=True)
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    elapsed=(time.monotonic()-start)*1000
    async with async_session() as db:
        root=await db.get(WorkspaceGoal,'root');data=json.loads(root.result_json)
        state=root.state
    refs=set(data.get('final_evidence_refs',[]))
    proofs=[e for e in data.get('evidence',[]) if e['evidence_id'] in refs and e['verified']]
    # Independent fixture oracle knows expected bytes, not executor's success flag.
    expected={str(p):hashlib.sha256(v.encode()).hexdigest() for p,v in zip(paths,contents)}
    observed={e['data'].get('path'):e['data'].get('sha256') for e in proofs}
    return {'case_id':'two-file-reads','seed':seed,'arm':'teams' if team else 'single',
        'success':state=='done','verified_success':state=='done' and observed==expected,
        'state':state,'error':error,'latency_ms':elapsed,'simulated_planner_calls':calls,
        'simulated_decomposition_calls':int(team),'tokens':None,'context_tokens':None,'cost_usd':None,
        'budget':await budgets.snapshot('root'),'proof_count':len(proofs),
        'fixture_unchanged':all(p.read_text()==v for p,v in zip(paths,contents))}


async def main():
    output=ROOT/'experiments/product/20261006'
    before=hashes();rows=[]
    with tempfile.TemporaryDirectory(dir=Path.home(),prefix='aries-product-eval-') as tmp:
        for seed in range(5):
            for team in ([False,True] if seed%2==0 else [True,False]):
                row=await trial(seed,team,Path(tmp));rows.append(row)
                (output/'component-trials.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    after=hashes()
    result={'scope':'component ablation with deterministic planner; no native model efficiency claim',
        'assigned':10,'completed':len(rows),'verified_success':sum(r['verified_success'] for r in rows),
        'failures':[r for r in rows if not r['verified_success']],
        'source_stable':before==after,'source_before':before,'source_after':after,
        'promotion_admitted':False,'reason':'No real-model comparative token/cost/quality evidence',
        'rollback':'ARIES_GOAL_TEAMS=0 and ARIES_CONTEXT_ENGINE=0; in-flight children retain scopes and root budgets'}
    (output/'component-evaluation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if not k.startswith('source_')}))
    if result['failures'] or before!=after:raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
