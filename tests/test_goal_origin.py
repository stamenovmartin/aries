"""Background goals cannot borrow interactive confirmation or user-memory identity."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-goal-origin')
from agentic_core.database.base import async_session
from aries.workspace import service,registry as capabilities
from aries.settings import SettingsService
from aries.workspace.memory import store
from aries.workspace.models import WorkspaceGoal
from tests.test_agent_execution import setup,run_goal,execute


async def test_origin_gate_preserves_review_and_other_policy_gates():
    await reset_db()
    async with async_session() as db:
        settings=SettingsService(db)
        await settings.set('operator.enabled',True)
        await settings.set('operator.confirm_model_plans',False)
        cap=capabilities.registry.get('browser.open')
        args={'url':'https://example.com'}
        for origin in (None,'automation:aries.dashboards','scheduler','unknown',{},''):
            check(f'{origin!r} mutation requires review despite relaxed user preference',
                  not await capabilities.policy(db,cap,args,'Open https://example.com',origin=origin))
        check('explicit interactive request retains configured confirmation choice',
              await capabilities.policy(db,cap,args,'Open https://example.com',origin='user'))
        check('reviewed frozen background step can proceed',
              await capabilities.policy(db,cap,args,'Open https://example.com',origin='automation:fixture',approved=True))
        read=capabilities.registry.get('system.status')
        check('background observation remains available',await capabilities.policy(db,read,{},'Check system status',origin='automation:fixture'))
        await settings.set('operator.enabled',False)
        try:await capabilities.policy(db,cap,args,'Open https://example.com',origin='automation:fixture',approved=True);denied=False
        except PermissionError:denied=True
        check('review never overrides disabled operator policy',denied)


async def test_submission_persists_origin_without_inventing_user_memory():
    await reset_db()
    with patch.object(store,'observe_later') as observe:
        async with async_session() as db:
            bg=await service.submit(db,'',capability='research',args={'query':'fixture'},origin='automation:fixture')
            check('background origin reaches durable goal',bg['origin']=='automation:fixture')
            check('automation text is never observed as a user statement',observe.call_count==0)
            unknown=await service.submit(db,'Check system status')
            check('omitted source cannot become user authority',unknown['origin']=='unknown' and observe.call_count==0)
            user=await service.submit(db,'Check system status',origin='user')
            check('interactive API has explicit durable user provenance',user['origin']=='user')
            check('user learning observation retains legitimate source',observe.call_count==1 and observe.call_args.kwargs['source']=='user')


async def test_actual_background_agent_stops_before_side_effect():
    await setup()
    async with async_session() as db:
        await SettingsService(db).set('operator.confirm_model_plans',False)
    original=service.submit
    async def background(db,*args,**kwargs):
        kwargs['origin']='automation:fixture'
        return await original(db,*args,**kwargs)
    cap=capabilities.registry.get('browser.open')
    from dataclasses import replace
    from unittest.mock import AsyncMock
    executor=AsyncMock(side_effect=AssertionError('must not execute'))
    with patch.object(service,'submit',side_effect=background),patch.dict(capabilities.registry._items,{'browser.open':replace(cap,executor=executor)}):
        result=await run_goal('Open https://example.com',[execute('browser.open',url='https://example.com')])
    check('actual planner-driven unattended mutation is proposed, not executed',result['state']=='proposed' and executor.call_count==0)


async def test_shell_endpoint_preserves_noninteractive_source():
    import httpx
    from aries.api.app import app
    from aries.workspace import agent_planner,runaway
    from tests.test_agent_execution import fake
    from dataclasses import replace
    from unittest.mock import AsyncMock
    await setup();runaway.resume()
    async with async_session() as db:await SettingsService(db).set('operator.confirm_model_plans',False)
    cap=capabilities.registry.get('browser.open');executor=AsyncMock(side_effect=AssertionError('must not execute'))
    with patch.object(agent_planner,'plan',side_effect=fake([execute('browser.open',url='https://example.com')])), \
         patch.dict(capabilities.registry._items,{'browser.open':replace(cap,executor=executor)}), \
         patch('aries.workspace.capabilities.execute',executor), \
         patch('aries.operator.service.run',AsyncMock(side_effect=AssertionError('no unattended presentation'))) as present:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.post('/api/aries/shell/act',json={'kind':'workspace','source':'automation','text':'Open https://example.com'})
        check('shell accepts and preserves declared background origin',response.status_code==200 and response.json()['result']['origin']=='automation')
        await service.dispatch()
        async with async_session() as db:row=await db.get(WorkspaceGoal,response.json()['result']['id'])
        check('real shell route cannot bypass origin review',row.state=='proposed' and executor.call_count==0 and present.call_count==0)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
