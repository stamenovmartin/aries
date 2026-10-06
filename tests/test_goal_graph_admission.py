"""Independent authority and cancellation oracles for child admission."""
import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-goal-graph-admission')
from agentic_core.database.base import async_session
from sqlalchemy import update
from sqlalchemy.sql.dml import Update
from aries.workspace import goal_graph as graph, orchestration, service, scopes
from aries.workspace.registry import registry
from aries.workspace.models import WorkspaceGoal


async def test_grants_derive_from_each_nodes_contract():
    a, b = '/tmp/aries-a', '/tmp/aries-b'
    plan = {'nodes': [
        {'id':'a','role':'reader','goal':f'Read {a}','capabilities':sorted(graph.SAFE_READS)},
        {'id':'b','role':'reader','goal':f'Read {b}','capabilities':['file.read']}]}
    _, grants, _ = graph.validate(plan, f'Read {a} and read {b}', 'root', expires_at=time.time()+60)
    check('first reader receives only its requested file and capability',
          grants['a']['paths']==[a] and grants['a']['capabilities']==['file.read'])
    with scopes.use(grants['a']):
        scopes.enforce(registry.get('file.read'), {'path':a})
        for name, args in [('file.read', {'path':b}), ('system.processes', {}), ('system.status', {})]:
            try:
                scopes.enforce(registry.get(name), args)
                denied=False
            except PermissionError:
                denied=True
            check(f'sibling/unrequested access {name} {args} is denied at executor boundary', denied)
    plan['nodes'].reverse()
    try:
        graph.validate(plan, f'Read {a} and read {b}', 'root', expires_at=time.time()+60)
        denied=False
    except ValueError:
        denied=True
    check('reversed order cannot create an unverifiable team', denied)


async def seed(db, parent_state, kind='agent'):
    if parent_state is not None:
        db.add(WorkspaceGoal(id='parent',request='root',state=parent_state,result_json='{}'))
    subgoal={'kind':kind,'capability':'system.status','args':{},'request':'Check system status'}
    data={'steps':[], 'orchestration':{'role':'child','parent_id':'parent','depends_on':[], 'subgoal':subgoal}}
    db.add(WorkspaceGoal(id='child',request='Check system status',state='queued',result_json=json.dumps(data)))
    await db.commit()
    return data


async def test_cancelled_missing_or_finished_parent_never_launches():
    for kind in ('agent','capability'):
        for state in ('cancelled','done','failed',None):
            await reset_db()
            async with async_session() as db:
                data=await seed(db,state,kind)
                ready, reason=await graph.dependencies_ready(db,data)
                check(f'{kind}: {state} parent cannot authorize dependencies', not ready and bool(reason))
                with patch.object(orchestration,'_drive',AsyncMock()) as drive:
                    launched=await orchestration.claim(db,1)
                check(f'{kind}: {state} parent starts no work', launched==[] and drive.call_count==0)
                child=await db.get(WorkspaceGoal,'child',populate_existing=True)
                check('orphan child is durably cancelled', child.state=='cancelled')


async def test_parent_cancellation_between_read_and_child_update_wins():
    await reset_db()
    async with async_session() as db:
        await seed(db,'running')
        execute=db.execute
        cancelled=False
        async def race(statement,*args,**kwargs):
            nonlocal cancelled
            if isinstance(statement,Update) and not cancelled:
                cancelled=True
                await execute(update(WorkspaceGoal).where(WorkspaceGoal.id=='parent').values(state='cancelled'))
            return await execute(statement,*args,**kwargs)
        with patch.object(db,'execute',side_effect=race), patch.object(orchestration,'_drive',AsyncMock()) as drive:
            launched=await orchestration.claim(db,1)
        check('race was exercised at the actual durable transition', cancelled)
        check('atomic admission sees cancellation', launched==[] and drive.call_count==0)
        child=await db.get(WorkspaceGoal,'child',populate_existing=True)
        check('no running child or reserved lane leaks', child.state=='queued' and 'child' not in service._resources)


if __name__=='__main__':
    sys.exit(run_module(sys.modules[__name__]))
