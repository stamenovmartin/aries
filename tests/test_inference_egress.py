"""Final provider boundary: assert on actual transport dispatch, not route labels."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-inference-egress')
from sqlalchemy import select
from agentic_core.database.base import async_session
from aries.settings import SettingsService
from aries.intelligence.egress import bind, planner_classes
from aries.intelligence.generation import generate
from aries.intelligence.providers import Generation
from aries.intelligence.models import IntelligenceEvent
from aries.intelligence.context import task_context

MESSAGES = [{'role':'system','content':'Return JSON'}, {'role':'user','content':'synthetic canary'}]
SCHEMA = {'type':'object'}


async def test_explicit_classification_has_bound_origin():
    await reset_db()
    from aries.intelligence.router import CloudDecisionProvider
    from aries.intelligence.egress import classify
    from aries.intelligence.schemas import Decision
    async def capture(db,messages,schema,**kwargs):
        classes=classify(messages,schema,kwargs['provenance'])
        private='private' in messages[-1]['content']
        check('explicit baseline binds current request privacy',('personal' in classes)==private and 'unknown' not in classes)
        check('explicit baseline never accepts a local substitute',kwargs['allow_fallback'] is False)
        return Decision(intent='UNKNOWN',confidence=0.5,tool='none',requires_cloud=False,estimated_complexity='simple',reason='fixture').model_dump_json(),{}
    async with async_session() as db:
        with patch('aries.intelligence.generation.generate',side_effect=capture):
            for text in ('Check system status','Classify my private notes'):
                await CloudDecisionProvider().decide(db,text)


async def test_transport_partition_and_task_lineage():
    await reset_db()
    async with async_session() as db:
        settings = SettingsService(db)
        await settings.set('intelligence.cloud_enabled',True,set_by='user')
        await settings.set('intelligence.cloud_provider','codex-cli',set_by='user')
        local = AsyncMock(return_value=Generation('{}',12,3,'local','test'))
        cloud = AsyncMock(return_value=Generation('{}',10,2,'codex-cli','test'))
        cases = [('public',True),('synthetic',True),('personal',False),('secret',False),
                 ('unknown',False),('file_content',False)]
        with patch('aries.intelligence.generation.local_generate',local), \
             patch('aries.intelligence.cli.executable',return_value='/fake/codex'), \
             patch('aries.intelligence.cli.CLIDecisionProvider.generate',cloud):
            for label, allowed in cases:
                before=cloud.await_count
                with task_context('child-'+label,root_id='root-test'):
                    _,usage=await generate(db,MESSAGES,SCHEMA,purpose='egress-test',
                        route={'execution_level':'cloud'},provenance=bind(MESSAGES,SCHEMA,{label}))
                check(label+' transport partition',(cloud.await_count>before)==allowed)
                check(label+' actual provider recorded',usage['execution_level']==('cloud' if allowed else 'local'))
            await settings.set('ai.send_file_contents',True,set_by='user')
            _,usage=await generate(db,MESSAGES,SCHEMA,purpose='file-opt-in',route={'execution_level':'cloud'},
                                 provenance=bind(MESSAGES,SCHEMA,{'file_content'}))
            check('explicit file sharing permits file content',usage['execution_level']=='cloud')
            _,usage=await generate(db,MESSAGES,SCHEMA,purpose='mixed-file-personal',route={'execution_level':'cloud'},
                                 provenance=bind(MESSAGES,SCHEMA,{'file_content','personal'}))
            check('file permission does not declassify personal data',usage['execution_level']=='local')
            await settings.set('privacy.mode',True,set_by='user')
            before=cloud.await_count
            _,usage=await generate(db,MESSAGES,SCHEMA,purpose='private-mode',route={'execution_level':'cloud'},
                                 provenance=bind(MESSAGES,SCHEMA,{'public'}))
            check('privacy mode wins over public route',usage['execution_level']=='local' and cloud.await_count==before)
        rows=(await db.execute(select(IntelligenceEvent))).scalars().all()
        events=[json.loads(r.data_json) for r in rows if r.kind=='generation']
        scoped=[e for e in events if e.get('root_id')=='root-test']
        check('all six calls attributed including local privacy redirects',len(scoped)==6)
        check('call identifiers unique',len({e['call_id'] for e in events})==len(events))
        check('task context does not leak to later calls',all('root_id' not in e for e in events if e not in scoped))
        check('canary text absent from inference audit',all('synthetic canary' not in r.data_json for r in rows))


async def test_missing_or_tampered_provenance_cannot_authorize_cloud():
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set('intelligence.cloud_enabled',True,set_by='user')
        local=AsyncMock(return_value=Generation('{}',1,1,'local','test'))
        cloud=AsyncMock(side_effect=AssertionError('private cloud dispatch'))
        stale=bind(MESSAGES,SCHEMA,{'public'})
        changed=[*MESSAGES,{'role':'user','content':'private appended observation'}]
        with patch('aries.intelligence.generation.local_generate',local), \
             patch('aries.intelligence.cli.CLIDecisionProvider.generate',cloud):
            for prompt,schema,provenance in [(MESSAGES,SCHEMA,None),(changed,SCHEMA,stale),
                                              (MESSAGES,{'description':'private schema data'},stale)]:
                _,usage=await generate(db,prompt,schema,purpose='tamper',
                    route={'execution_level':'cloud','data_classes':['public']},provenance=provenance)
                check('unbound content stays local',usage['execution_level']=='local')
            check('no cloud dispatch on any tamper case',cloud.await_count==0)
            try:
                await generate(db,MESSAGES,SCHEMA,purpose='strict-cloud',route={'execution_level':'cloud'},
                               allow_fallback=False)
                refused=False
            except ValueError as exc:
                refused=str(exc).startswith('PRIVACY_BLOCKED:')
            check('strict cloud experiment fails instead of relabelling local',refused)


async def test_label_origin_survives_history_and_context():
    check('desktop titles remain personal in final prompt',
          'personal' in planner_classes({}, {'goal':'show status','environment':{'windows':{'title':'private canary'}}}))
    check('explicit private user request stays local',
          'personal' in planner_classes({}, {'goal':'summarize my private notes'}))
    for data,label in [({'agent':{'context':{'preview':'short','truncated':True}}},'personal'),
                       ({'agent':{'context':{'working_context':{'entities':[{'value':'private path'}]}}}},'personal'),
                       ({'steps':[{'capability':'file.read'}]},'file_content'),
                       ({'steps':[{'capability':'screen.read'}]},'personal')]:
        check('planner origin class retained '+label,label in planner_classes(data))
    check('empty historical containers do not force local',
          planner_classes({'agent':{'context':{'reviews':[],'preferences':[],
              'working_context':{'entities':[],'ttl_minutes':30}}}})=={'instruction','user_request'})


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
