"""Learned resets are reversible, scoped, stale-safe and never USER-layer writes."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-learning-controls')
from sqlalchemy import select
from agentic_core.database.base import async_session
from aries.learning import controls
from aries.interests.models import AriesInterest
from aries.settings import SettingsService,Layer
from aries.settings.store import AriesSetting


async def topic():
    async with async_session() as db:
        row=AriesInterest(topic='comet',scope='',weight=.9,learned_weight=.4,
                          learned_confidence=.8,learned_rationale='fixture')
        db.add(row);await db.commit();await db.refresh(row)
        return row.id,controls.revision(controls.snapshot(row,'topic'))


async def test_topic_reset_undo_and_duplicate_requests():
    await reset_db();key,rev=await topic()
    results=await asyncio.gather(*(controls.reset('topic',key,rev,actor='user:fixture') for _ in range(2)),return_exceptions=True)
    done=[r for r in results if isinstance(r,dict)]
    check('concurrent same-revision reset has one winner',len(done)==1 and sum(isinstance(r,ValueError) for r in results)==1)
    async with async_session() as db:
        row=await db.get(AriesInterest,key)
        check('reset clears only learned fields',row.learned_weight is None and row.learned_confidence is None and row.weight==.9)
        view=await controls.inspect(db)
        check('reset remains visible and undoable',len(view['history'])==1 and view['history'][0]['can_undo'])
    await controls.undo(done[0]['id'],actor='user:fixture')
    async with async_session() as db:
        row=await db.get(AriesInterest,key)
        check('undo restores exact learned value and evidence metadata',row.learned_weight==.4 and row.learned_confidence==.8 and row.learned_rationale=='fixture')
        check('explicit preference survives reset and undo',row.weight==.9)
        events=(await db.execute(select(controls.LearningControl))).scalars().all()
        check('history is appended, never erased',[e.action for e in events]==['reset','undo'])
    try:await controls.undo(done[0]['id'],actor='user:fixture');denied=False
    except ValueError:denied=True
    check('undo cannot be replayed',denied)


async def test_newer_learning_blocks_stale_reset_and_undo():
    await reset_db();key,rev=await topic()
    async with async_session() as db:
        row=await db.get(AriesInterest,key);row.learned_weight=.6;await db.commit()
    try:await controls.reset('topic',key,rev,actor='user:fixture');denied=False
    except ValueError:denied=True
    check('stale preview cannot erase newer learning',denied)
    async with async_session() as db:
        row=await db.get(AriesInterest,key);rev=controls.revision(controls.snapshot(row,'topic'))
    event=await controls.reset('topic',key,rev,actor='user:fixture')
    async with async_session() as db:
        row=await db.get(AriesInterest,key);row.learned_weight=.7;await db.commit()
    try:await controls.undo(event['id'],actor='user:fixture');denied=False
    except ValueError:denied=True
    check('undo cannot overwrite learning after reset',denied)


async def test_scoped_settings_preserve_user_layer_and_refuse_newer_undo():
    await reset_db()
    async with async_session() as db:
        settings=SettingsService(db)
        await settings.learn('news.relevance_threshold',.4,scope='project:comet',confidence=.8,rationale='fixture')
        await settings.set('news.relevance_threshold',.9,scope='project:comet')
        row=await db.scalar(select(AriesSetting).where(AriesSetting.layer==int(Layer.LEARNED)))
        key,rev=row.id,controls.revision(controls.snapshot(row,'setting'))
        user=await db.scalar(select(AriesSetting).where(AriesSetting.layer==int(Layer.USER)))
        user_id=user.id
        user_revision=controls.revision({'id':user.id,'key':user.key,'scope':user.scope,
            'value_json':user.value_json,'confidence':user.confidence,'rationale':user.rationale,
            'set_by':user.set_by,'updated_at':user.updated_at.isoformat() if user.updated_at else None})
    event=await controls.reset('setting',key,rev,actor='user:fixture')
    async with async_session() as db:
        check('scoped USER value remains effective',await SettingsService(db,scope='project:comet').get('news.relevance_threshold')==.9)
        check('learned row actually removed',await db.scalar(select(AriesSetting.id).where(AriesSetting.layer==int(Layer.LEARNED))) is None)
    await controls.undo(event['id'],actor='user:fixture')
    async with async_session() as db:
        row=await db.scalar(select(AriesSetting).where(AriesSetting.layer==int(Layer.LEARNED)))
        check('undo restores same scope and learned value',row.scope=='project:comet' and row.decoded()==.4 and row.rationale=='fixture')
        key,rev=row.id,controls.revision(controls.snapshot(row,'setting'))
    event=await controls.reset('setting',key,rev,actor='user:fixture')
    async with async_session() as db:
        await SettingsService(db).learn('news.relevance_threshold',.6,scope='project:comet',confidence=.9,rationale='new')
    try:await controls.undo(event['id'],actor='user:fixture');denied=False
    except ValueError:denied=True
    check('new scoped setting cannot be overwritten by undo',denied)
    try:await controls.reset('setting',user_id,user_revision,actor='user:fixture');reason=''
    except ValueError as exc:reason=str(exc)
    check('USER setting is refused by layer guard, even with its exact revision',reason=='Only learned settings can be reset')


async def test_http_path_and_permission_registration():
    import httpx
    from aries.api.app import app
    from agentic_core.security.permissions import permission_for,Permission
    await reset_db();key,rev=await topic()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        before=await client.get('/api/aries/learning/controls')
        check('preview is reachable over HTTP',before.status_code==200 and before.json()['items'][0]['revision']==rev)
        reset=await client.post('/api/aries/learning/controls/reset',json={'kind':'topic','target_id':key,'revision':rev})
        check('reset is reachable over HTTP',reset.status_code==200)
        undo=await client.post(f"/api/aries/learning/controls/{reset.json()['id']}/undo",json={})
        check('undo is reachable over HTTP',undo.status_code==200)
        stale=await client.post('/api/aries/learning/controls/reset',json={'kind':'topic','target_id':key,'revision':rev})
        check('stale HTTP request gives conflict',stale.status_code==409)
    check('mutation requires operator configuration permission',permission_for('POST','/api/aries/learning/controls/reset')==Permission.MANAGE_TOOLS)
    from agentic_core.security import principal
    from agentic_core.security.permissions import Role
    from unittest.mock import AsyncMock,patch
    with patch.object(principal,'from_token',AsyncMock(return_value=principal.build(None,Role.READONLY))):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',
                                    headers={'X-API-Key':'agc_synthetic'}) as client:
            denied=await client.post('/api/aries/learning/controls/reset',json={'kind':'topic','target_id':key,'revision':rev})
            check('actual read-only HTTP principal receives403',denied.status_code==403)


async def test_setting_undo_detects_intervening_learn_and_clear_and_audits_human():
    from agentic_core.database.models import AuditEvent
    await reset_db()
    async with async_session() as db:
        await SettingsService(db,scope='project:comet').learn('news.relevance_threshold',.4,
            scope='project:comet',confidence=.8,rationale='fixture')
        row=await db.scalar(select(AriesSetting).where(AriesSetting.layer==int(Layer.LEARNED)))
        key,rev=row.id,controls.revision(controls.snapshot(row,'setting'))
    reset=await controls.reset('setting',key,rev,actor='user:fixture')
    await controls.undo(reset['id'],actor='user:fixture')
    async with async_session() as db:
        event=await db.scalar(select(AuditEvent).where(AuditEvent.action=='setting.changed').order_by(AuditEvent.id.desc()))
        check('restored setting audit identifies the human actor',event.actor_type=='human' and event.actor=='user:fixture')
        row=await db.scalar(select(AriesSetting).where(AriesSetting.layer==int(Layer.LEARNED)))
        key,rev=row.id,controls.revision(controls.snapshot(row,'setting'))
    reset=await controls.reset('setting',key,rev,actor='user:fixture')
    async with async_session() as db:
        s=SettingsService(db,scope='project:comet')
        await s.learn('news.relevance_threshold',.7,scope='project:comet',confidence=.9,rationale='new')
        await s.clear('news.relevance_threshold',scope='project:comet',layer=Layer.LEARNED)
    try:await controls.undo(reset['id'],actor='user:fixture');denied=False
    except ValueError:denied=True
    check('absence after a newer learn/clear cannot resurrect stale value',denied)


async def test_reset_starts_new_history_epoch_without_erasing_old_changes():
    from aries.learning import history,reversal
    await reset_db();key,rev=await topic()
    async with async_session() as db:
        await history.record(db,kind='topic_weight',target='comet',previous=.6,applied=.4,direction='down',
            confidence=.8,rationale='old',shadowed=False,commit=True)
        pending=reversal.AriesReversal(target='comet',scope='',established=.4,direction='up',
            classification='sustained',status=reversal.PENDING)
        db.add(pending);await db.commit()
    await controls.reset('topic',key,rev,actor='user:fixture')
    async with async_session() as db:
        row=await history.record(db,kind='topic_weight',target='comet',previous=.9,applied=.95,direction='up',
            confidence=.8,rationale='new',shadowed=False,commit=True)
        check('new inference after reset is not a reversal of discarded history',not row.reversal)
        check('pre-reset changes remain inspectable',len(await history.history(db,'comet'))==2)
        stable=await history.stability(db,'comet')
        check('damping sees only current epoch',stable.changes==1 and stable.reversals==0)
        pending=await db.scalar(select(reversal.AriesReversal))
        check('old pending reversal is retained as abandoned',pending.status==reversal.ABANDONED)


async def test_undo_restores_oscillation_freeze_and_damping():
    from aries.learning import history
    await reset_db();key,rev=await topic()
    async with async_session() as db:
        for index,direction in enumerate(('down','up','down','up')):
            await history.record(db,kind='topic_weight',target='comet',previous=.5,applied=.4 if direction=='down' else .6,
                direction=direction,confidence=.8,rationale='oscillation fixture',shadowed=False,commit=True)
        before=await history.stability(db,'comet')
    reset=await controls.reset('topic',key,rev,actor='user:fixture')
    await controls.undo(reset['id'],actor='user:fixture')
    async with async_session() as db:
        after=await history.stability(db,'comet')
        check('undo restores frozen target instead of enabling full-step learning',before.frozen and after.frozen)
        check('undo retains original damping and reversal count',after.damping==before.damping and after.reversals==before.reversals)


async def test_setting_undo_allows_user_layer_edit_and_retains_original_author():
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).learn('news.relevance_threshold',.4,confidence=.8,rationale='fixture',set_by='learning')
        row=await db.scalar(select(AriesSetting).where(AriesSetting.layer==int(Layer.LEARNED)))
        key,rev=row.id,controls.revision(controls.snapshot(row,'setting'))
    reset=await controls.reset('setting',key,rev,actor='user:fixture')
    async with async_session() as db:await SettingsService(db).set('news.relevance_threshold',.8)
    await controls.undo(reset['id'],actor='user:fixture')
    async with async_session() as db:
        row=await db.scalar(select(AriesSetting).where(AriesSetting.layer==int(Layer.LEARNED)))
        check('undo retains learned author and original value',row.set_by=='learning' and row.decoded()==.4)
        check('user-layer change does not block or get overwritten by learned undo',await SettingsService(db).get('news.relevance_threshold')==.8)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
