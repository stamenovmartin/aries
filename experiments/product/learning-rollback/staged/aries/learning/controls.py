"""Manual learned-value reset and undo; USER preferences and history are preserved.

Mutations run in the shared writer transaction. A preview revision prevents a
stale screen from resetting a newer inference, and undo refuses to overwrite
learning that appeared after the reset.
"""
import hashlib
import json
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text, select,func
from sqlalchemy.orm import Mapped, mapped_column
from agentic_core.database.base import Base
from agentic_core.database import writer
from agentic_core.observability.audit import log_event
from aries.interests.models import AriesInterest
from aries.settings.store import AriesSetting
from aries.settings.layers import Layer


class LearningControl(Base):
    __tablename__='aries_learning_controls'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    action: Mapped[str]=mapped_column(String(20))
    kind: Mapped[str]=mapped_column(String(20))
    target_id: Mapped[int]=mapped_column(Integer,index=True)
    label: Mapped[str]=mapped_column(String(200))
    scope: Mapped[str]=mapped_column(String(120),default='')
    before_json: Mapped[str]=mapped_column(Text)
    after_json: Mapped[str]=mapped_column(Text)
    undo_of: Mapped[int | None]=mapped_column(Integer,nullable=True,unique=True)
    actor: Mapped[str]=mapped_column(String(120))
    history_floor: Mapped[int]=mapped_column(Integer,default=0)
    setting_audit_floor: Mapped[int]=mapped_column(Integer,default=0)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)


def snapshot(row,kind):
    if row is None:return None
    if kind=='topic':
        return {'id':row.id,'topic':row.topic,'scope':row.scope,'learned_weight':row.learned_weight,
                'learned_confidence':row.learned_confidence,'learned_rationale':row.learned_rationale,
                'updated_at':row.updated_at.isoformat() if row.updated_at else None}
    if row.layer!=int(Layer.LEARNED):raise ValueError('Only learned settings can be reset')
    return {'id':row.id,'key':row.key,'scope':row.scope,'value_json':row.value_json,
            'confidence':row.confidence,'rationale':row.rationale,'set_by':row.set_by,
            'updated_at':row.updated_at.isoformat() if row.updated_at else None}


def revision(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def model(kind):
    if kind=='topic':return AriesInterest
    if kind=='setting':return AriesSetting
    raise ValueError('Unknown learned-value kind')


async def setting_stamp(db,key,scope):
    from agentic_core.database.models import AuditEvent
    return int(await db.scalar(select(func.max(AuditEvent.id)).where(
        AuditEvent.action.in_(('setting.changed','setting.cleared')),
        func.json_extract(AuditEvent.detail,'$.key')==key,
        func.json_extract(AuditEvent.detail,'$.layer')=='learned',
        func.coalesce(func.json_extract(AuditEvent.detail,'$.scope'),'')==scope)) or 0)


async def boundary(db,kind,label,scope):
    from aries.learning.history import AriesLearningChange
    from aries.learning.reversal import AriesReversal,PENDING,ABANDONED
    floor=int(await db.scalar(select(func.max(AriesLearningChange.id)).where(
        AriesLearningChange.target==label,AriesLearningChange.scope==scope)) or 0)
    if kind=='topic':
        pending=(await db.execute(select(AriesReversal).where(AriesReversal.target==label,
            AriesReversal.scope==scope,AriesReversal.status==PENDING))).scalars().all()
        for row in pending:
            row.status=ABANDONED;row.resolved_at=datetime.utcnow()
            row.reason='Manual learned-value control invalidated the pending reversal'
    return floor


async def _can_undo(db,event):
    if event.action!='reset':return False
    if await db.scalar(select(LearningControl.id).where(LearningControl.undo_of==event.id)):return False
    before=json.loads(event.before_json)
    if event.kind=='setting':
        row=await db.scalar(select(AriesSetting).where(AriesSetting.key==before['key'],
            AriesSetting.scope==before['scope'],AriesSetting.layer==int(Layer.LEARNED)))
        # A later reset of the same setting also invalidates an older undo.
        newer=await db.scalar(select(LearningControl.id).where(LearningControl.kind=='setting',
            LearningControl.label==event.label,LearningControl.scope==event.scope,
            LearningControl.id>event.id).limit(1))
        return row is None and newer is None and await setting_stamp(db,before['key'],before['scope'])==event.setting_audit_floor
    row=await db.get(AriesInterest,event.target_id,populate_existing=True)
    return row is not None and snapshot(row,'topic')==json.loads(event.after_json)


async def inspect(db,limit=50):
    items=[]
    truncated={}
    for kind,query in [('topic',select(AriesInterest).where(AriesInterest.learned_weight.is_not(None))),
                       ('setting',select(AriesSetting).where(AriesSetting.layer==int(Layer.LEARNED)))]:
        rows=(await db.execute(query.order_by(model(kind).id.desc()).limit(limit+1))).scalars().all()
        for row in rows[:limit]:
            saved=snapshot(row,kind)
            items.append({'kind':kind,'id':row.id,'label':row.topic if kind=='topic' else row.key,
                          'scope':row.scope,'value':row.learned_weight if kind=='topic' else row.decoded(),
                          'revision':revision(saved)})
        truncated[kind]=len(rows)>limit
    events=(await db.execute(select(LearningControl).order_by(LearningControl.id.desc()).limit(limit))).scalars().all()
    history=[{'id':e.id,'action':e.action,'kind':e.kind,'label':e.label,'scope':e.scope,
              'undo_of':e.undo_of,'at':e.created_at.isoformat(),'can_undo':await _can_undo(db,e)} for e in events]
    return {'items':items,'history':history,'truncated':truncated,'note':'Reset removes only the current learned value. Future learning may infer another value; disable the learning loop to prevent that. Undo restores the previous value and stability history; cancelled pending reversals stay cancelled.'}


async def reset(kind,target_id,expected_revision,*,actor):
    async with writer.write_session(name='learning.reset') as db:
        row=await db.get(model(kind),target_id,populate_existing=True)
        if row is None:raise ValueError('Learned value no longer exists; refresh the page')
        before=snapshot(row,kind)
        if revision(before)!=expected_revision:raise ValueError('Learned value changed; refresh before resetting')
        if kind=='topic':
            if row.learned_weight is None:raise ValueError('There is no learned value to reset')
            label=row.topic
            row.learned_weight=row.learned_confidence=row.learned_rationale=None
            row.updated_at=datetime.utcnow()
            await db.flush()
            after=snapshot(row,kind)
        else:
            label=row.key
            await db.delete(row)
            after=None
        event=LearningControl(action='reset',kind=kind,target_id=target_id,label=label,scope=before['scope'],
            before_json=json.dumps(before),after_json=json.dumps(after),actor=actor,
            history_floor=await boundary(db,kind,label,before['scope']),
            setting_audit_floor=await setting_stamp(db,label,before['scope']) if kind=='setting' else 0)
        db.add(event);await db.flush()
        await log_event(db,actor_type='human',actor=actor,action='learning.reset',
                        entity_type='learning_control',entity_id=str(event.id),
                        detail={'kind':kind,'target_id':target_id,'label':label,'scope':before['scope']})
        return {'id':event.id,'action':'reset','kind':kind,'label':label,'can_undo':True}


async def undo(event_id,*,actor):
    async with writer.write_session(name='learning.undo') as db:
        event=await db.get(LearningControl,event_id)
        if event is None or not await _can_undo(db,event):
            raise ValueError('Reset can no longer be undone: newer learning or another undo exists')
        before=json.loads(event.before_json)
        if event.kind=='topic':
            row=await db.get(AriesInterest,event.target_id)
            for field in ('learned_weight','learned_confidence','learned_rationale'):
                setattr(row,field,before[field])
            row.updated_at=datetime.utcnow()
        else:
            from aries.settings import SettingsService
            await SettingsService(db,scope=before['scope'] or None).learn(before['key'],json.loads(before['value_json']),
                confidence=before['confidence'],rationale=before['rationale'],
                scope=before['scope'],set_by=actor,commit=False)
            row=await db.scalar(select(AriesSetting).where(AriesSetting.key==before['key'],
                AriesSetting.scope==before['scope'],AriesSetting.layer==int(Layer.LEARNED)))
        if event.kind=='setting':
            # Attribution of this undo is in the human audit event; retain the
            # inference's original author in the restored learned row.
            row.set_by=before['set_by']
        await db.flush()
        await db.refresh(row)
        prior_floor=await db.scalar(select(LearningControl.history_floor).where(
            LearningControl.label==event.label,LearningControl.scope==event.scope,
            LearningControl.id<event.id).order_by(LearningControl.id.desc()).limit(1))
        restored=snapshot(row,event.kind)
        undo_event=LearningControl(action='undo',kind=event.kind,target_id=row.id,label=event.label,
            scope=event.scope,before_json=event.after_json,after_json=json.dumps(restored),undo_of=event.id,actor=actor,
            history_floor=int(prior_floor or 0))
        db.add(undo_event);await db.flush()
        await log_event(db,actor_type='human',actor=actor,action='learning.undo',
                        entity_type='learning_control',entity_id=str(undo_event.id),detail={'undo_of':event.id})
        return {'id':undo_event.id,'action':'undo','undo_of':event.id,'label':event.label}
