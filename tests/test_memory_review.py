"""Unconfirmed interpretations never replace USER-backed facts; explicit review is narrow."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests import test_workspace as harness
from tests._bootstrap import check,run_module
from agentic_core.database.base import async_session
from aries.workspace.memory import store
from aries.workspace.models import WorkspaceConclusion,WorkspaceMemory
import httpx

async def proposal():
    await harness.setup()
    async with async_session() as db:
        old_user=await store.record(db,'My preferred editor is Alpha.')
        old=await store.conclude(db,text=old_user.text,sources=[old_user.id],decision='APPEND',confidence=1.,rationale='test',stage='model')
        new_user=await store.record(db,'My preferred editor is Beta.')
        new=await store.conclude(db,text=new_user.text,sources=[new_user.id],decision='SUPERSEDE',confidence=1.,rationale='test',stage='model')
        expired,reason=await store.arbitrate(db,new,'c:'+old.id,commit=True)
        check('confidence1 cannot bypass review',expired is None and old.expired_at is None and new.decision=='PENDING_REPLACE')
        check('explicit confirmation reason','confirmation' in reason.lower())
        check('USER records never suppressed',not await store.withdrawn_sources(db))
        candidates=await store.relevant(db,old_user.text,version='focused-v2',limit=50,touch_retrieved=False)
        ids=[row['id'] for _,row,_ in candidates]
        check('pending interpretation excluded from context',new.id not in ids)
        check('old USER statement remains searchable',old_user.id in ids)
        return old_user.id,new_user.id,old.id,new.id

async def test_confirmation_and_repeated_review():
    a,b,old,new=await proposal()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=harness.app),base_url='http://test') as client:
        view=(await client.get('/api/aries/workspace')).json()['memory_replacements']
        check('review displays exact old and proposed facts',view[0]['target_id']==old and 'Alpha' in view[0]['old'] and 'Beta' in view[0]['proposed'])
        path='/api/aries/workspace/memory-replacements/'+new+'/review'
        for body in [{'target_id':old},{'target_id':old,'approved':'true'},{'target_id':'wrong','approved':True}]:
            r=await client.post(path,json=body)
            check('missing, coerced or stale confirmation rejected',r.status_code in {409,422})
        from agentic_core.security.principal import Principal
        from agentic_core.security.permissions import Role
        denied=Principal(user_id=None,role=Role.READONLY)
        with patch('agentic_core.security.principal.current',return_value=denied):
            r=await client.post(path,json={'target_id':old,'approved':True})
        check('review requires permission',r.status_code==403)
        r=await client.post(path,json={'target_id':old,'approved':True})
        check('explicit reviewed proposal applied',r.status_code==200 and r.json()['approved'] is True)
        r=await client.post(path,json={'target_id':old,'approved':True})
        check('replay rejected',r.status_code==409)
    async with async_session() as db:
        check('confirmed learned interpretation superseded',(await db.get(WorkspaceConclusion,old)).expired_at is not None)
        check('both USER statements survive confirmation',all([(await db.get(WorkspaceMemory,i)).expired_at is None for i in [a,b]]))
        check('confirmation never hides USER records',not await store.withdrawn_sources(db))

async def test_keep_previous():
    a,b,old,new=await proposal()
    async with async_session() as db:
        result=await store.review_replacement(db,new,old,approved=False)
        check('keep previous recorded',result['approved'] is False)
        check('previous fact untouched',(await db.get(WorkspaceConclusion,old)).expired_at is None)
        check('proposal withdrawn',(await db.get(WorkspaceConclusion,new)).decision=='REJECTED_REPLACE')

async def test_direct_USER_target_never_expires():
    a,b,old,new=await proposal()
    async with async_session() as db:
        row,reason=await store.arbitrate(db,await db.get(WorkspaceConclusion,new),'m:'+a,confirmed=True)
        check('even review cannot supersede USER row',row is None and (await db.get(WorkspaceMemory,a)).expired_at is None)

async def test_excluded_fact_not_disclosed_or_reviewed():
    a,b,old,new=await proposal()
    from aries.settings import SettingsService
    async with async_session() as db:
        await SettingsService(db).set('privacy.excluded_memory_topics',['Alpha'],set_by='user');await db.commit()
        check('excluded old fact not exposed in proposals',await store.pending_replacements(db)==[])
        try:await store.review_replacement(db,new,old,approved=True)
        except store.MemoryRefused:check('excluded proposal cannot be approved',True)
        else:check('excluded proposal cannot be approved',False)

async def test_concurrent_review_is_applied_once():
    import asyncio
    a,b,old,new=await proposal()
    async def review():
        async with async_session() as db:
            try:
                await store.review_replacement(db,new,old,approved=True)
                return True
            except store.MemoryRefused:
                return False
    result=await asyncio.gather(review(),review())
    check('concurrent approval applied exactly once',sum(result)==1)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
