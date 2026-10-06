"""Pinned task polling must not serialize unrelated tasks or survey the desktop."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-workspace-polling')
from agentic_core.database.base import async_session
from aries.workspace import service
from aries.workspace.models import WorkspaceGoal
from unittest.mock import AsyncMock,patch

async def test_pinned_task_is_bounded_and_dashboard_is_preserved():
    await reset_db()
    async with async_session() as db:
        db.add(WorkspaceGoal(id='selected',request='Read my fixture',state='done',result_json=json.dumps({'steps':[], 'cards':[{'text':'selected result'}]})))
        db.add(WorkspaceGoal(id='unrelated',request='Other user task',state='proposed',result_json=json.dumps({'steps':[], 'cards':[{'text':'x'*200000}]})))
        await db.commit()
        with patch.object(service,'runtime_state',AsyncMock(side_effect=AssertionError('desktop queried for task poll'))):
            data=await service.snapshot(db,goal_id='selected')
            check('only exact selected goal returned',[g['id'] for g in data['goals']]==['selected'])
            check('selected result retained',data['goals'][0]['cards'][0]['text']=='selected result')
            check('unrelated payload not serialized',len(json.dumps(data))<10000)
            missing=await service.snapshot(db,goal_id='missing')
            check('missing task does not fall back to other tasks',missing['goals']==[])
        with patch.object(service,'runtime_state',AsyncMock(return_value={'available':True})):
            data=await service.snapshot(db)
            check('full dashboard retains both goals',{g['id'] for g in data['goals']}=={'selected','unrelated'})
            check('full dashboard retains runtime',data['runtime']['available'])

if __name__=='__main__':run_module(sys.modules[__name__])
