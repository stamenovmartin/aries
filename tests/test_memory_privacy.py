"""Changing exclusions affects existing context, provenance and model neighbours."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-memory-privacy')
from agentic_core.database.base import async_session
from aries.settings import SettingsService
from aries.workspace import retrieval
from aries.workspace.memory import store, extraction
from aries.workspace.models import WorkspaceMemory, WorkspaceConclusion


async def seed(db):
    hidden=await store.record(db,'My therapy project is called Cedar.')
    visible=await store.record(db,'My public project is called Cedar.')
    derived=await store.conclude(db,text='Cedar appointments are on Tuesday.',sources=[hidden.id],
        decision='APPEND',confidence=.9,rationale='fixture',stage='test')
    await SettingsService(db).set('privacy.excluded_memory_topics',['therapy'],set_by='user')
    await db.commit()
    return hidden,visible,derived


async def test_exclusions_precede_ranking_and_cover_provenance():
    await reset_db();store.reset_cache()
    async with async_session() as db:
        hidden,visible,derived=await seed(db)
        real=retrieval.score_memories
        with patch.object(retrieval,'score_memories',wraps=real) as score:
            result=await store.relevant(db,'Cedar project appointments',version='focused-v2',limit=1)
        ranked={r['key'] for r in score.call_args.args[0]}
        check('excluded memory and its differently worded conclusion never enter ranking',
              ranked=={'m:'+visible.id})
        check('an excluded neighbour cannot consume the allowed result slot',
              len(result)==1 and result[0][1]['id']==visible.id)
        await db.refresh(hidden);await db.refresh(derived)
        check('excluded rows are not marked as retrieved',not hidden.retrievals and not derived.retrievals)
        check('exclusion does not expire or delete the original evidence',
              hidden.expired_at is None and derived.expired_at is None)
        await SettingsService(db).set('privacy.excluded_memory_topics',[],set_by='user');await db.commit()
        with patch.object(retrieval,'score_memories',wraps=real) as score:
            await store.relevant(db,'Cedar project appointments',version='focused-v2',limit=8)
        check('removing an exclusion restores all rows without a rewrite',
              {r['key'] for r in score.call_args.args[0]}=={'m:'+hidden.id,'m:'+visible.id,'c:'+derived.id})


async def test_privacy_read_failures_never_default_to_permission():
    await reset_db();store.reset_cache()
    async with async_session() as db:
        hidden,_,_=await seed(db)
        real=SettingsService.get
        async def unavailable(self,key,*args,**kwargs):
            if key.startswith('privacy.'):raise RuntimeError('settings unavailable')
            return await real(self,key,*args,**kwargs)
        with patch.object(SettingsService,'get',unavailable), \
                patch.object(store,'_try_cache',AsyncMock(return_value=None)) as cache:
            try:found=await store.relevant(db,'Cedar',version='focused-v2')
            except Exception:found=None
            check('unreadable privacy policy supplies no optional context',found==[])
            try:await store.remember(db,'My therapy project is called Willow.')
            except (ValueError,RuntimeError):refused=True
            else:refused=False
            check('explicit memory write refuses an unreadable exclusion policy',refused)
            result=await store.observe(db,'My therapy project is called Willow.')
            check('automatic memory write aborts at the privacy gate',
                  result['stored'] is None and result['verdict']['stage']=='gate' and 'privacy' in result['verdict']['reason'].lower())
            check('unreadable policy is checked before loading an embedder',not cache.called)
        await db.refresh(hidden)
        check('policy failure did not touch an existing memory',not hidden.retrievals)


async def test_excluded_neighbours_never_reach_the_model_or_get_bumped():
    await reset_db();store.reset_cache()
    async with async_session() as db:
        hidden,visible,derived=await seed(db)
        neighbours=[('m:'+hidden.id,.99,hidden.text),('c:'+derived.id,.98,derived.text),
                    ('m:'+visible.id,.90,visible.text)]
        cache=SimpleNamespace(embedder=SimpleNamespace(passages=lambda texts:[[1.0]]),
                              neighbours=lambda vector,limit:neighbours[:limit])
        seen=[]
        def decide(text,rows,**kwargs):
            seen.extend(rows)
            # Even an invalid model/stub relation must not bump a hidden row.
            return extraction.Verdict('NOOP','novelty','fixture',related_to='m:'+hidden.id)
        with patch.object(store,'_try_cache',AsyncMock(return_value=cache)):
            await store.observe(db,'My public project has a new milestone.',cascade=SimpleNamespace(run=decide))
        check('excluded source and derived texts are absent from model neighbours',
              [r[0] for r in seen]==['m:'+visible.id])
        await db.refresh(hidden)
        check('a model relation cannot bump a now-excluded memory',not hidden.retrievals)


async def test_privacy_change_during_inference_prevents_a_write():
    import asyncio,threading
    await reset_db();store.reset_cache()
    entered,release=threading.Event(),threading.Event()
    def decide(*args,**kwargs):
        entered.set()
        release.wait(3)
        return extraction.Verdict('APPEND','novelty','fixture')
    cache=SimpleNamespace(embedder=SimpleNamespace(passages=lambda texts:[[1.0]]),
                          neighbours=lambda vector,limit:[])
    async with async_session() as db:
        with patch.object(store,'_try_cache',AsyncMock(return_value=cache)):
            task=asyncio.create_task(store.observe(db,'My therapy project is called Cedar.',cascade=SimpleNamespace(run=decide)))
            try:
                started=await asyncio.to_thread(entered.wait,3)
                check('privacy-change test reaches inference',started)
                async with async_session() as other:
                    await SettingsService(other).set('privacy.excluded_memory_topics',['therapy'],set_by='user')
                    await other.commit()
            finally:release.set()
            result=await task
        check('a newly excluded topic is not saved after pending inference finishes',
              result['stored'] is None and 'excluded' in result['verdict']['reason'])
        check('privacy change leaves no raw or derived rows',
              not await store.utterances(db) and not await store.conclusions(db))


async def test_real_task_context_excludes_old_private_conclusions():
    import tempfile,json
    from aries.workspace import service
    from aries.workspace.models import WorkspaceGoal
    await reset_db();store.reset_cache()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'Cedar-project.txt';path.write_text('public project')
        async with async_session() as db:
            hidden,visible,derived=await seed(db)
            goal=await service.submit(db,'Cedar project appointments',capability='read_file',args={'path':str(path)})
        with patch.object(store,'_try_cache',AsyncMock(return_value=None)):
            await service.dispatch()
        async with async_session() as db:
            row=await db.get(WorkspaceGoal,goal['id']);data=json.loads(row.result_json)
            ids={r['id'] for r in data.get('context',[])+data.get('conclusions',[])}
            check('real queued task completes with allowed memory context',row.state=='done' and visible.id in ids)
            check('task result contains no excluded memory or derived-conclusion references',
                  hidden.id not in ids and derived.id not in ids)


def test_information_questions_do_not_become_automatic_facts():
    for phrase in ('што има денас од вести','Колку меморија се користи?',
                   'Ari, kolku mesto imam na diskot','What is the latest news?',
                   'How much free space do I have?','Дали има нови вести?'):
        verdict=extraction.gate(phrase)
        check('question refused: '+phrase,verdict is not None and verdict.stage=='gate')
    for phrase in ('Работам на проект што се вика АРИЕС.',
                   'I know where my project files are stored.',
                   'Can you always use Macedonian for my summaries?'):
        check('statement or standing preference remains eligible: '+phrase,extraction.gate(phrase) is None)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
