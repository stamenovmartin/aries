"""Context does not turn stale/forbidden/cached records into current proof."""
import json
import sys
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-context-sources')
from agentic_core.database.base import async_session
from aries.workspace.models import WorkspaceGoal
from aries.workspace import context_sources as sources,context_engine as context
from aries.sources.models import AriesSource
from aries.news.models import AriesNewsItem
from aries.settings import SettingsService
from aries.intelligence.context import task_context


def ago(seconds=0):return datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=seconds)


async def test_task_scope_staleness_and_corrupt_records():
    await reset_db()
    async with async_session() as db:
        for key,request,data,age in [('comet','Fix project comet build','{}',10),
                ('other','Fix project zephyr build','{}',10),
                ('stale','Fix comet build','{}',15*86400),
                ('root','Continue comet','{}',10),
                ('child','Fix comet','{"orchestration":{"role":"child","parent_id":"root"}}',10),
                ('broken','Fix comet','[]',10)]:
            db.add(WorkspaceGoal(id=key,request=request,state='failed',result_json=data,updated_at=ago(age)))
        await db.commit()
        items,status=await sources.tasks(db,'Continue working on project comet',now=time.time(),root_id='root')
        check('only related historical task survives',[i.id for i in items]==['comet'])
        check('history cannot claim current state',items[0].authority=='historical_task_record' and 'at observation' in items[0].text)
        check('task context remains local-only',items[0].data_class=='personal')
        check('task hint expires within five minutes',items[0].expires_at<=time.time()+300)
        check('corrupt record disclosed',status['invalid_rows']==1)
        for goal,expected in [('Review failed tasks for project comet',['comet']),
                              ('Review failed tasks for project quasar',[])]:
            selected,_=await sources.tasks(db,goal,now=time.time(),root_id='root')
            check('shared failure words cannot cross project identity',[i.id for i in selected]==expected)
        with patch.object(sources,'MAX_ROWS',2):
            _,status=await sources.tasks(db,'Prepare me for tomorrow',now=time.time())
            check('bounded history exposes truncation',status['scanned']==2 and status['truncated'])


async def seed_news(db):
    for name in ['allowed','disabled','blocked','no-read','corrupt','scoped']:
        db.add(AriesSource(source_id=name,name=name,type='rss',location='https://example.invalid/'+name,
            enabled=name!='disabled',trust=0 if name=='blocked' else 50,
            permissions_json='invalid' if name=='corrupt' else '[]' if name=='no-read' else '["read"]',
            scope='project:other' if name=='scoped' else ''))
        db.add(AriesNewsItem(item_id=name,source_id=name,title='Comet release',summary='A comet update',
            first_seen_at=ago(10),published_at=ago(100),disposition='delivered',relevance=.8))
    for key,age,dismissed,excluded,representative in [('old',3*86400,False,None,True),
            ('future',-3600,False,None,True),('dismissed',10,True,None,True),
            ('excluded',10,False,'user exclusion',True),('duplicate',10,False,None,False)]:
        db.add(AriesNewsItem(item_id=key,source_id='allowed',title='Comet release',summary='comet',
            first_seen_at=ago(10),published_at=ago(age),disposition='delivered',relevance=.8,
            dismissed=dismissed,excluded_by=excluded,is_representative=representative))
    await db.commit()


async def test_cached_news_rechecks_permissions_and_freshness():
    await reset_db()
    async with async_session() as db:
        await seed_news(db)
        items,status=await sources.news(db,'Comet news',now=time.time())
        check('only permitted fresh undismissed news survives',[i.id for i in items]==['allowed'])
        check('cache never claims a live fetch',status['status']=='bounded_cache')
        check('untrusted text cannot become instructions',items[0].authority=='untrusted_cached_source')
        check('news choices stay personal',items[0].data_class=='personal')
        await SettingsService(db).set('privacy.mode',True,set_by='user')
        items,status=await sources.news(db,'Comet news',now=time.time())
        check('source privacy policy is preserved',not items and status['status']=='unavailable')


async def test_assembly_isolates_memory_failure_and_preserves_coverage():
    await reset_db()
    async with async_session() as db:
        db.add(WorkspaceGoal(id='previous',request='Fix comet build',state='failed',result_json='{}',updated_at=ago(10)))
        db.add(WorkspaceGoal(id='root',request='Continue comet',state='running',result_json='{}',updated_at=ago(10)))
        await db.commit()
        with patch('aries.workspace.memory.store.relevant',AsyncMock(side_effect=RuntimeError('private error content'))),task_context('root'):
            packet=await context.assemble(db,'Continue working on project comet',max_chars=2000)
        check('memory outage does not erase task context',[i['id'] for i in packet['items']]==['previous'])
        check('raw provider exception is not copied to prompt',packet['unavailable']=={'memory':'RuntimeError'})
        check('unavailable project and files remain explicit',{'projects','files','memory'}<=set(packet['missing_sources']))
        prompt=context.planner_context({},packet)
        check('bounded history warning reaches planner',prompt['context_coverage']['source_status']['tasks']['status']=='bounded_history')
        check('planner retains provenance and hash',prompt['memories'][0]['source']=='tasks' and len(prompt['memories'][0]['sha256'])==64)


async def test_irrelevant_goals_do_not_scan_extra_domains():
    with patch.object(sources,'tasks',AsyncMock(side_effect=AssertionError('unnecessary task query'))), \
         patch.object(sources,'news',AsyncMock(side_effect=AssertionError('unnecessary news query'))):
        items,status=await sources.collect(None,'Check system status',now=time.time())
        check('simple command activates no extra source',items==[] and status=={})


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
