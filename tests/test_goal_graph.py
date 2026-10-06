"""Real queue + independent file reads with deterministic model proposals."""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-goal-graph')
from agentic_core.database.base import async_session
from aries.workspace import goal_graph as graph, service, orchestration, agent_planner, agent
from aries.workspace.scopes import Grant,use
from aries.workspace.registry import registry,policy
from aries.workspace.models import WorkspaceGoal
from aries.intelligence import budgets


async def test_invalid_graphs_and_resource_escape():
    node={'id':'one','role':'file reader','goal':'Read /tmp/user-file','capabilities':['file.read']}
    for nodes in [[node,node],[{**node,'depends_on':['missing']}],
                  [{**node,'depends_on':['one']}]]:
        try:graph.Plan.model_validate({'nodes':nodes});refused=False
        except ValueError:refused=True
        check('duplicate unknown or cyclic graph rejected',refused)
    for candidate in [{**node,'goal':'Read /tmp/not-authorized'},
                      {**node,'capabilities':['file.write']},
                      {**node,'goal':'Invent tomorrow appointments'}]:
        try:graph.validate({'nodes':[candidate]},'Read /tmp/user-file','root',expires_at=time.time()+30);refused=False
        except (ValueError,PermissionError):refused=True
        check('hallucinated resource mutation or unverifiable goal refused',refused)
    await reset_db()
    grant=Grant(root_id='root',capabilities=['file.read'],paths=['/tmp/user-file'],expires_at=time.time()+30)
    async with async_session() as db:
        with use(grant):
            try:await policy(db,registry.get('file.read'),{'path':'/tmp/user-file-evil'},'Read it',approved=True);refused=False
            except PermissionError:refused=True
            check('approval cannot override resource scope',refused)
            try:await policy(db,registry.get('system.status'),{},'Check status',approved=True);refused=False
            except PermissionError:refused=True
            check('executor rejects capability omitted from grant',refused)
            names={c['name'] for c in agent_planner.scoped_capabilities()}
            check('planner catalogue restricted to same grant',names=={'file.read'})
            wider=grant.model_copy(update={'capabilities':['file.read','system.status']})
            try:
                with use(wider):pass
                refused=False
            except PermissionError:refused=True
            check('nested agent cannot widen parent grant',refused)


async def exercise_team(*, supported=False):
    await reset_db()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        a,b=Path(directory)/'a.txt',Path(directory)/'b.txt'
        a.write_text('alpha');b.write_text('beta')
        goal=f'Read {a} and read {b}' if supported else f'Summarize the files {a} and {b}'
        plan=graph.Plan(nodes=[graph.Node(id='a',role='reader-a',goal=f'Read {a}',capabilities=['file.read']),
                               graph.Node(id='b',role='reader-b',goal=f'Read {b}',capabilities=['file.read'])])
        async with async_session() as db:
            root=WorkspaceGoal(id='root-test',request=goal,state='running',result_json='{}')
            db.add(root);await db.commit()
        await budgets.create('root-test')
        plan,grants,contract=graph.validate(plan,goal,'root-test',expires_at=time.time()+60)
        if supported:
            with patch.object(graph,'propose',AsyncMock(return_value=(plan,{}))), \
                 patch.dict('os.environ',{'ARIES_GOAL_TEAMS':'1'}):
                await agent.run('root-test',goal,{})
        else:
            check('team saved atomically in existing queue',await graph.persist('root-test',goal,{},plan,grants,contract,{'missing_sources':[]}))
        overlaps=[];active=0
        async def planner(db,request,data,budget):
            nonlocal active
            active+=1;overlaps.append(active)
            await asyncio.sleep(.03)
            active-=1
            if not data['steps']:
                d={'action':'execute','capability':'file.read','arguments':{'path':request[5:]}}
            else:
                d={'action':'finish','evidence_refs':[e['evidence_id'] for e in data['evidence'] if e['verified']]}
            return json.dumps(d),{'measured':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
        with patch.object(agent_planner,'plan',side_effect=planner), \
             patch.object(orchestration,'capacity',AsyncMock(return_value=orchestration.Capacity(4,'fixture'))), \
             patch.dict('os.environ',{'ARIES_PLAN_MEMORY':'0','ARIES_TRACE_FEWSHOT':'0'}):
            await orchestration.tick(wait=True)
        async with async_session() as db:
            root=await db.get(WorkspaceGoal,'root-test');data=json.loads(root.result_json)
            children=[await db.get(WorkspaceGoal,key) for key in data['orchestration']['children']]
            check('two real temporary planner loops completed',[r.state for r in children]==['done','done'])
            check('scoped planners actually overlap',max(overlaps)==2)
            check('root completion follows independent contract',root.state==('done' if supported else 'partial'))
            if supported:
                check('parent independently rechecks both requested files',len(data.get('final_evidence_refs',[]))==2)
            check('each specialist has independently checked evidence',all(json.loads(r.result_json)['final_evidence_refs'] for r in children))
            check('read-only agents reserve no desktop lane',all(service.resources_for(json.loads(r.result_json))==set() for r in children))
        state=await budgets.snapshot('root-test')
        check('root accounts child and parent verification',state['tools']==(8 if supported else 6))


async def test_temporary_agents_run_through_real_dispatcher():
    await exercise_team(supported=True)


async def test_unsupported_root_cannot_delegate_unrequested_reads():
    plan={'nodes':[{'id':'a','role':'reader','goal':'Check system status',
                    'capabilities':['system.status']}]}
    try:
        graph.validate(plan,'Prepare a project briefing','root',expires_at=time.time()+60)
        refused=False
    except ValueError:
        refused=True
    check('unsupported root stays with ordinary planner, without child authority',refused)


async def test_root_input_expands_and_verifies_compound_contract():
    await exercise_team(supported=True)


async def test_cancellation_wins_before_graph_creation():
    await reset_db()
    goal='Check system status and list running processes'
    plan=graph.Plan(nodes=[graph.Node(id='status',role='status',goal='Check system status',capabilities=['system.status']),
                          graph.Node(id='processes',role='processes',goal='List running processes',capabilities=['system.processes'])])
    plan,grants,contract=graph.validate(plan,goal,'cancelled',expires_at=time.time()+60)
    async with async_session() as db:
        db.add(WorkspaceGoal(id='cancelled',request=goal,state='cancelled',result_json='{}'))
        await db.commit()
    check('cancelled parent cannot spawn specialists',not await graph.persist('cancelled',goal,{},plan,grants,contract,{'missing_sources':[]}))
    from sqlalchemy import select
    async with async_session() as db:
        check('cancelled expansion creates no orphan children',len((await db.execute(select(WorkspaceGoal))).scalars().all())==1)


async def test_failed_dependency_blocks_downstream():
    await reset_db()
    async with async_session() as db:
        db.add(WorkspaceGoal(id='failed',request='read',state='failed',result_json='{}'))
        await db.commit()
        ready,reason=await graph.dependencies_ready(db,{'orchestration':{'depends_on':['failed']}})
        check('terminal failure cannot enable dependent action',not ready and bool(reason))


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
