"""Ownership, observed completion, and persistent feedback regressions."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-window-lifecycle')
from agentic_core.database.base import async_session
from aries.workspace.models import WorkspaceGoal
from aries.workspace.service import cleanup_goal_browsers
from aries_ui.window_lifecycle import CompletionClose
from aries.learning import feedback


def test_completion_pin_and_reopen():
    now=[0]
    policy=CompletionClose(temporary=True, delay=45, clock=lambda:now[0])
    check('queued and running windows stay open',not policy.update('queued') and not policy.update('running'))
    check('completion gives time to read',not policy.update('done'))
    now[0]=44
    check('does not dismiss before deadline',not policy.update('done'))
    policy.pin(True)
    now[0]=100
    check('pin keeps completed result open',not policy.update('done'))
    policy.pin(False)
    check('unpin grants a new full reading interval',not policy.update('done'))
    now[0]=145
    check('completed temporary result closes after interval',policy.update('done'))
    check('failed or proposed work stays visible',not policy.update('failed') and not policy.update('proposed'))
    check('history opened deliberately stays open',not CompletionClose().update('done'))


async def test_cleanup_is_owned_and_preserves_evidence():
    await reset_db()
    async with async_session() as db:
        for id,state,agent in [('done','done',True),('waiting','proposed',True),('direct','done',False)]:
            data={'steps':[{'capability':'browser_open','result':{'browser':{'session':id}}},
                           {'capability':'browser_follow','args':{'session':'someone-else'},'result':{'browser':{'session':'someone-else'}}}],
                  'cards':[{'title':'Saved source','browser_session':id}]}
            if agent:data['agent']={'finished':state=='done'}
            db.add(WorkspaceGoal(id=id,request='test',state=state,result_json=json.dumps(data)))
        await db.commit()
    live=[{'session':s,'open':True} for s in ['done','waiting','direct','someone-else']]
    with patch('aries.workspace.browser.inventory',AsyncMock(return_value=live)), patch('aries.workspace.browser.close',AsyncMock()) as close:
        for id in ['done','waiting','direct','done']:
            await cleanup_goal_browsers(id)
        check('closes only finished agent-owned sessions exactly once',close.await_args_list and len(close.await_args_list)==1 and close.await_args.args==('done',))
    async with async_session() as db:
        row=await db.get(WorkspaceGoal,'done')
        data=json.loads(row.result_json)
        check('source result persists after closing its browser',data['cards'][0]['title']=='Saved source' and data['cards'][0]['browser_closed'])


async def test_explicit_learning_rules_reach_planner_without_granting_actions():
    await reset_db()
    async with async_session() as db:
        row=await feedback.submit(db,'Sekogas proveruvaj sto e otvoreno pred slednata akcija', context={'scope':'global'})
        check('arbitrary explicit standing rule is retained',row.classification=='persistent_rule' and not row.applied)
        applied=await feedback.submit(db,'Always close temporary agent browsers',context={'scope':'global'})
        check('known rule applies its actual setting',applied.applied)
        await feedback.submit(db,'just discussing something')
        rules=await feedback.standing_rules(db)
        check('ordinary conversation does not become a standing rule',len(rules)==2)
        from aries.workspace.planner import next_step
        reply=json.dumps({'capability':'list_apps','arguments':{},'reason':'Observe applications'})
        with patch('aries.intelligence.local_structured',AsyncMock(return_value=(reply,{}))) as model, patch('aries.workspace.service.runtime_state',AsyncMock(return_value={'desktop':{'available':True,'windows':[]}})):
            step,_,_=await next_step(db,'Show installed applications',[])
        messages=model.await_args.args[1]
        check('saved preference and fresh window state reach planner',any('Sekogas proveruvaj' in m['content'] and 'owned_browser_windows_now' in m['content'] for m in messages))
        check('feedback does not expand allowed task effects',step['capability']=='list_apps')

async def test_implementation_lessons_are_not_user_preferences_or_setting_changes():
    await reset_db()
    async with async_session() as db:
        row = await feedback.submit(db, 'Always keep temporary agent browsers open — test wording only; the fix was to record ownership.',
                                    context={'origin':'implementation','scope':'global'})
        check('engineering record never executes a setting correction', row.classification=='implementation_note' and not row.applied)
        check('engineering notes stay separate from explicit user rules', not await feedback.standing_rules(db) and len(await feedback.implementation_notes(db))==1)


if __name__=='__main__':
    sys.exit(run_module(sys.modules[__name__]))
