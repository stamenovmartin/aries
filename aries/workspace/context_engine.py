"""Select bounded evidence while retaining origin, expiry and privacy labels."""
from dataclasses import dataclass, asdict
import hashlib
import json
import math
import time
from aries.workspace.retrieval import stems


@dataclass(frozen=True)
class Item:
    id: str
    source: str
    text: str
    data_class: str = 'personal'
    authority: str = 'untrusted_data'
    observed_at: float = 0.0
    expires_at: float | None = None
    relevance: float = 0.0

    def packet(self):
        return {**asdict(self),'sha256':hashlib.sha256(self.text.encode()).hexdigest()}


def required_sources(goal):
    words=stems(goal)
    if 'tomorrow' in goal.casefold() or 'утре' in goal.casefold():
        return ['memory','calendar','tasks','projects','messages','news']
    if words & stems('project repository blocking build'):
        return ['memory','projects','files','tasks']
    if words & stems('news headlines'):
        return ['news']
    if words & stems('tasks pending failed'):
        return ['tasks']
    return []


def select(items, goal, *, max_chars=5000, limit=5, now=None):
    """Bound selected evidence including metadata; audit omissions stay separate."""
    if max_chars<256 or not 1<=limit<=20:
        raise ValueError('Invalid context budget')
    now=time.time() if now is None else now
    wanted=stems(goal)
    candidates=[]
    seen=set()
    omitted=[]
    for item in items:
        if item.expires_at is not None and item.expires_at<=now:
            omitted.append({'id':item.id,'reason':'expired'});continue
        if item.data_class not in {'personal','public','file_content','secret','unknown','synthetic'}:
            omitted.append({'id':item.id,'reason':'unknown_data_class'});continue
        digest=hashlib.sha256(item.text.encode()).hexdigest()
        key=(item.source,item.id)
        if key in seen or ('text',digest) in seen:
            omitted.append({'id':item.id,'reason':'duplicate'});continue
        seen.update({key,('text',digest)})
        lexical=len(wanted & stems(item.text))/max(1,len(wanted))
        score=max(lexical,item.relevance)
        if not math.isfinite(score) or score<=0:
            omitted.append({'id':item.id,'reason':'irrelevant'});continue
        candidates.append((score,item))
    candidates.sort(key=lambda pair:(-pair[0],-pair[1].observed_at,pair[1].source,pair[1].id))
    selected=[]
    for _,item in candidates:
        proposed=[*selected,item.packet()]
        if len(selected)>=limit or len(json.dumps(proposed,ensure_ascii=False))>max_chars:
            omitted.append({'id':item.id,'reason':'budget'});continue
        selected=proposed
    chars=len(json.dumps(selected,ensure_ascii=False))
    return {'items':selected,'omitted':omitted,'data_classes':sorted({i['data_class'] for i in selected}),
            'context_chars':chars,'estimated_context_tokens':math.ceil(chars/4),
            'token_method':'character-count / 4 estimate; not tokenizer measurement',
            'required_sources':required_sources(goal),
            'missing_sources':[s for s in required_sources(goal) if s not in {i['source'] for i in selected}]}


async def assemble(db,goal,*,max_chars=5000):
    from aries.workspace.memory import store
    from aries.workspace.context_sources import collect
    from aries.intelligence.context import current
    now=time.time();unavailable={}
    try:
        rows=await store.relevant(db,goal,limit=12,touch_retrieved=False)
    except Exception as exc:
        rows=[];unavailable['memory']=type(exc).__name__
    items=[Item(id=str(row.get('key') or row.get('id')),source='memory',text=row.get('text',''),
                authority='user_statement' if str(row.get('key','')).startswith('m:') else 'learned_conclusion',
                relevance=float(score)) for score,row,_ in rows]
    extra,status=await collect(db,goal,now=now,root_id=current().get('root_id'))
    packet=select([*items,*extra],goal,max_chars=max_chars,now=now)
    packet['source_status']=status
    if unavailable:packet['unavailable']=unavailable
    return packet


def planner_context(historical,packet,*,max_chars=2500):
    """Keep complete source records, never an opaque slice of serialized JSON."""
    now=time.time()
    result={'memories':[i for i in packet['items'] if i.get('expires_at') is None or i['expires_at']>now],
            'context_coverage':{k:packet[k] for k in ('required_sources','missing_sources','token_method')}}
    omitted_items=[{'id':i['id'],'source':i['source'],'reason':'expired'}
                   for i in packet['items'] if i.get('expires_at') is not None and i['expires_at']<=now]
    def coverage():
        present={item['source'] for item in result['memories']}
        result['context_coverage']['missing_sources']=[s for s in packet['required_sources'] if s not in present]
        if omitted_items:
            result['context_coverage']['omitted_items']=omitted_items
    coverage()
    if packet.get('source_status'):
        result['context_coverage']['source_status']={k:{'status':v['status'],'truncated':v.get('truncated',False)}
                                                  for k,v in packet['source_status'].items()}
    size=lambda:len(json.dumps(result,ensure_ascii=False))
    # User preferences outrank recalled task/news text. Keep the existing bounded
    # representation for oversized preference data rather than silently dropping it.
    if historical.get('preferences'):
        from aries.workspace.agent_planner import bounded
        result['preferences']=bounded(historical['preferences'],max_chars=max_chars//3)
    while result['memories'] and size()>max_chars:
        item=result['memories'].pop()
        omitted_items.append({'id':item['id'],'source':item['source'],'reason':'budget'})
        coverage()
    omitted=[]
    for key,value in historical.items():
        if key in result:continue
        result[key]=value
        if size()>max_chars-150:
            result.pop(key);omitted.append(key)
    if omitted:result['omitted_sections']=omitted
    if size()>max_chars:raise ValueError('Context metadata exceeds planner budget')
    return result
