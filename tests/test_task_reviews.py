"""Task judgments cannot fabricate execution success or inflate evidence counts."""
import json,sys
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-task-reviews')
import httpx
from agentic_core.database.base import async_session
from aries.api.app import app
from aries.workspace.models import WorkspaceGoal
from aries.workspace import reviews
from aries.learning import feedback

async def seed():
    await reset_db()
    async with async_session() as db:
        for id,state in [('completed','done'),('failed','failed'),('pending','running')]:
            db.add(WorkspaceGoal(id=id,request='Build Python median statistics',state=state,
                result_json=json.dumps({'steps':[{'capability':'build_python','state':state,'args':{'secret':'not-for-replay'},
                    'result':{'summary':'Observed test output','elapsed_seconds':2 if state=='done' else 4,'verification':{'met':state=='done','evidence':'Test process output'}}}], 'gaps':[]})))
        await db.commit()

async def test_explicit_review_keeps_state_and_snapshot():
    await seed()
    async with async_session() as db:
        r=await reviews.submit(db,'failed','useful','The failure explained what to fix')
        g=await db.get(WorkspaceGoal,'failed')
        check('positive judgment does not turn failed execution into success',g.state=='failed' and r['episode']['state']=='failed')
        g.result_json='{}';await db.commit()
        saved=(await reviews.latest(db))[0]
        check('review retains original bounded evidence',saved['episode']['steps'][0]['verification']['met'] is False)
        check('raw executable arguments are not retained','secret' not in json.dumps(saved))
        check('review never becomes a global preference',not await feedback.standing_rules(db))

async def test_latest_wins_and_retiring_does_not_resurrect():
    await seed()
    async with async_session() as db:
        first=await reviews.submit(db,'completed','useful')
        repeat=await reviews.submit(db,'completed','useful')
        check('unchanged repeat reuses the same review',first['id']==repeat['id'])
        second=await reviews.submit(db,'completed','needs_work','Handle an empty list')
        report=await reviews.report(db)
        check('changed judgment counts once per goal',report['counts']=={'reviewed':1,'useful':0,'needs_work':1})
        await feedback.answer(db,second['id'],scope='current_result')
        check('retiring latest does not revive previous positive review',not await reviews.latest(db))
        check('history still retains both reviews',len(await feedback.recent(db))==2)

async def test_relevance_and_planner_limits():
    await seed()
    async with async_session() as db:
        await reviews.submit(db,'completed','needs_work','Reject empty input explicitly')
        check('unrelated task receives no old review',not await reviews.relevant(db,'Read weather news'))
        matched=await reviews.relevant(db,'Build Python statistics again')
        check('similar task receives actual correction',len(matched)==1 and matched[0]['correction']=='Reject empty input explicitly')
        from aries.workspace.planner import next_step
        response=json.dumps({'capability':'list_apps','arguments':{},'reason':'Observe'})
        with patch('aries.intelligence.local_structured',AsyncMock(return_value=(response,{}))) as model, patch('aries.workspace.service.runtime_state',AsyncMock(return_value={})):
            await next_step(db,'Show Python statistics applications',[])
        check('planner receives reviewed task context',any('Reject empty input explicitly' in m['content'] for m in model.await_args.args[1]))
        check('review is historical data rather than replayed arguments','secret' not in json.dumps(matched))

async def test_http_validates_target_rating_and_completion():
    await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        for goal,payload,code in [('missing',{'rating':'useful'},404),('pending',{'rating':'useful'},400),
            ('completed',{'rating':'invented'},400),('completed',{'rating':'needs_work'},400),
            ('completed',{'rating':'useful','comment':'x'*2001},400)]:
            r=await c.post('/api/aries/learning/task-reviews/'+goal,json=payload)
            check('invalid review refused '+goal+' '+str(payload['rating'])+' '+str(len(payload.get('comment',''))),r.status_code==code)
        r=await c.post('/api/aries/learning/task-reviews/completed',json={'rating':'needs_work','comment':'Handle zero inputs'})
        check('review submitted through real route',r.status_code==201 and r.json()['episode']['goal_id']=='completed')
        report=(await c.get('/api/aries/learning/task-reviews')).json()
        check('learning API shows one human review',report['counts']['needs_work']==1)
        from aries.workspace.evaluation import report as evaluate
        async with async_session() as db:
            result=await evaluate(db)
        check('human review counts are separate from tool execution',result['human_reviews']['needs_work']==1 and next(x for x in result['capabilities']['build_python'] if x['goal']=='completed')['state']=='done')
        check('even-sample execution median uses both middle values',any('median execution 3.0s' in c['text'] for c in result['cards']))

if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
