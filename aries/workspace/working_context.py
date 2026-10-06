"""Short-lived references derived from existing verified task evidence, not memory.

No new durable data store. Source artifacts keep their existing audit retention;
reference eligibility expires after thirty minutes and never authorizes effects.
"""
import json
import re
from datetime import datetime, timedelta
from sqlalchemy import select
from aries.workspace.models import WorkspaceGoal

TTL_MINUTES=30

async def current(db):
    rows=(await db.execute(select(WorkspaceGoal).where(WorkspaceGoal.updated_at>=datetime.utcnow()-timedelta(minutes=TTL_MINUTES),WorkspaceGoal.state.in_(['done','answered','partial'])).order_by(WorkspaceGoal.updated_at.desc()).limit(8))).scalars().all()
    entities=[];seen=set()
    for row in rows:
        data=json.loads(row.result_json)
        for evidence in reversed(data.get('evidence',[]) [-32:]):
            if not isinstance(evidence, dict) or evidence.get('verified') is not True:continue
            payload=evidence.get('data',{})
            if not isinstance(payload, dict):continue
            candidates=[payload]
            # Several search candidates stay ambiguous until one is read/opened.
            if isinstance(payload.get('matches'),list):candidates+=payload['matches'][:10]
            for candidate in candidates:
                if not isinstance(candidate, dict):continue
                for kind,key in [('file','path'),('url','url')]:
                    value=candidate.get(key)
                    if not isinstance(value,str) or not value or (kind,value) in seen:continue
                    seen.add((kind,value))
                    entities.append({'kind':kind,'value':value,'task_id':row.id,'evidence_id':evidence['evidence_id'],'observed_at':evidence.get('timestamp'),'label':str(candidate.get('title') or value)[:200]})
                    if len(entities)>=20:break
                if len(entities)>=20:break
            if len(entities)>=20:break
        if len(entities)>=20:break
    return {'ttl_minutes':TTL_MINUTES,'entities':entities,'scope':'recent verified task artifacts; no unverified model references'}

async def resolve(db,text):
    match=re.fullmatch(r'(open|read|отвори|прочитај|otvori|prochitaj)\s+(it|that|the paper|the file|the previous one|ја|го|тоа|датотеката|претходната|претходниот|ja|go|toa|datotekata|prethodnata|prethodniot)[.!]?',text.strip(),re.I)
    if not match:return text,None
    verb = 'read' if match[1].casefold() in {'read','прочитај','prochitaj'} else 'open'
    target = match[2].casefold()
    mk = match[1].casefold() not in {'open','read'}
    context=await current(db)
    candidates=context['entities']
    if verb=='read' or target in {'the file','датотеката','datotekata'}:candidates=[c for c in candidates if c['kind']=='file']
    if target in {'the previous one','претходната','претходниот','prethodnata','prethodniot'}:
        # Explicit ordinal only where two distinct observations exist.
        if len(candidates)==2:candidates=candidates[1:]
        else:candidates=[]
    if len(candidates)!=1:
        choices='; '.join(c['value'] for c in candidates[:4])
        if mk:
            raise ValueError('AMBIGUOUS: наведи ја датотеката или адресата; '+(choices or 'нема единствена неодамна проверена референца'))
        raise ValueError('AMBIGUOUS: specify the file or URL; '+(choices or 'no unique recent verified reference'))
    chosen=candidates[0]
    return verb.capitalize()+' '+chosen['value'], {'original':text,'resolved':chosen,'ttl_minutes':TTL_MINUTES}
