"""A scheduler tick is not a new observation; consumption survives new sessions."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-learning-evidence-reuse')
from agentic_core.database.base import async_session
from sqlalchemy import select,func
from aries.learning import propose,apply,history,controls
from aries.learning.evidence_use import EvidenceUse
from aries.interests import service as interests
from aries.interests.models import AriesInterest
from aries.news.models import AriesNewsItem,fingerprint
from tests.test_learning import _items


async def seed():
    await reset_db()
    async with async_session() as db:await interests.add(db,topic='fixture-comet')
    await _items('fixture-comet',shown=80,engaged=80)


async def pass_once():
    async with async_session() as db:
        proposals=await propose(db)
        await apply(db,proposals)
        row=await interests.get(db,'fixture-comet')
        return row.learned_weight,proposals


async def test_identical_evidence_moves_only_once_and_new_evidence_can_move():
    await seed()
    values=[]
    for _ in range(4):values.append((await pass_once())[0])
    check('four sessions reuse one evidence set without ratcheting',values==[.75]*4)
    async with async_session() as db:
        check('one durable evidence receipt',await db.scalar(select(func.count()).select_from(EvidenceUse))==1)
        check('one applied change in append-only history',await db.scalar(select(func.count()).select_from(history.AriesLearningChange))==1)
        db.add(AriesNewsItem(item_id=fingerprint('new-observation'),source_id='s',title='new',disposition='delivered',
            relevance=.8,matched_json=json.dumps([{'topic':'fixture-comet','weight':.8}]),engaged=True,dismissed=False))
        await db.commit()
    new,_=await pass_once()
    check('new actual observation can support a new bounded step',new==.9)
    check('unchanged new evidence is again consumed only once',(await pass_once())[0]==.9)


async def test_failed_history_write_rolls_back_value_and_receipt_together():
    await seed()
    with patch.object(history,'record',side_effect=RuntimeError('synthetic ledger failure')):
        value,proposals=await pass_once()
    check('failed ledger cannot leave a changed value',value is None)
    check('failed proposal is not marked applied',all(not p.applied for p in proposals))
    async with async_session() as db:
        check('failed application cannot consume evidence',await db.scalar(select(func.count()).select_from(EvidenceUse))==0)
    check('retry after actual repair can apply evidence',(await pass_once())[0]==.75)


async def test_user_reset_is_not_immediately_undone_by_identical_evidence():
    await seed();await pass_once()
    async with async_session() as db:
        row=await interests.get(db,'fixture-comet')
        key,rev=row.id,controls.revision(controls.snapshot(row,'topic'))
    await controls.reset('topic',key,rev,actor='user:fixture')
    check('repeated old observations cannot recreate a reset inference',(await pass_once())[0] is None)


async def test_reset_between_proposal_and_application_wins_even_at_same_numeric_base():
    await seed()
    async with async_session() as db:
        row=await interests.get(db,'fixture-comet');row.learned_weight=.6
        await db.commit();await db.refresh(row)
        key,rev=row.id,controls.revision(controls.snapshot(row,'topic'))
        proposals=await propose(db)
        await db.commit()
    await controls.reset('topic',key,rev,actor='user:fixture')
    async with async_session() as db:
        await apply(db,proposals)
        row=await interests.get(db,'fixture-comet')
        check('stale apply cannot undo reset even when fallback equals erased value',row.learned_weight is None)
        check('stale proposal leaves no consumed evidence',await db.scalar(select(func.count()).select_from(EvidenceUse))==0)


async def test_concurrent_duplicate_passes_have_one_receipt_and_one_change():
    await seed()
    async with async_session() as db:first=await propose(db)
    async with async_session() as db:second=await propose(db)
    async def execute(proposals):
        async with async_session() as db:return await apply(db,proposals)
    results=await asyncio.gather(execute(first),execute(second))
    check('one concurrent proposal applies',sum(p.applied for rows in results for p in rows)==1)
    async with async_session() as db:
        check('unique receipt survives concurrent writers',await db.scalar(select(func.count()).select_from(EvidenceUse))==1)
        check('concurrency does not duplicate history',await db.scalar(select(func.count()).select_from(history.AriesLearningChange))==1)


async def test_reused_evidence_report_does_not_claim_application():
    from aries.learning.loop import run_pass
    from aries.settings import SettingsService
    await seed();await pass_once()
    async with async_session() as db:
        await SettingsService(db).set('learning.apply_changes',True)
        result=await run_pass({'db':db})
        check('consumed evidence report counts zero applied changes',result['applied_count']==0 and result['applied'] is False)
        check('skipped proposals remain visible without a success claim','not applied' in result['summary'] and not result['reversals_applied'])


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
