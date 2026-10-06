"""Bounded reads of existing local records; no fetches or inferred credentials.

These are historical hints, never current execution evidence. Source permissions
are checked on every assembly, including when content was cached earlier.
"""
import json
import re
from datetime import datetime,timezone,timedelta
from sqlalchemy import select
from aries.workspace.context_engine import Item,required_sources
from aries.workspace.retrieval import stems

MAX_ROWS=64
TASK_AGE=14*86400
NEWS_AGE=2*86400


def timestamp(value):
    if value is None:return None
    if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def overlap(goal,text):
    generic=stems('continue working project repository blocking build prepare tomorrow task news recent latest review failed pending completed')
    wanted=stems(goal)-generic
    project=re.search(r'\bproject\s+["\x27]?([\w.-]+)',goal,re.I)
    if project:
        # Shared words such as "failed build" must not match a different project.
        name=project.group(1)
        if not re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',text,re.I):return 0.
        return max(.75,len(wanted & stems(text))/max(1,len(wanted)))
    return len(wanted & stems(text))/max(1,len(wanted))


def daily(goal):
    return 'tomorrow' in goal.casefold() or 'утре' in goal.casefold()


async def tasks(db,goal,*,now,root_id=None):
    from aries.workspace.models import WorkspaceGoal
    since=datetime.fromtimestamp(now-TASK_AGE,timezone.utc).replace(tzinfo=None)
    q=select(WorkspaceGoal).where(WorkspaceGoal.updated_at>=since)
    if root_id:q=q.where(WorkspaceGoal.id!=root_id)
    rows=(await db.execute(q.order_by(WorkspaceGoal.updated_at.desc(),WorkspaceGoal.id).limit(MAX_ROWS+1))).scalars().all()
    items=[];invalid=0
    for row in rows[:MAX_ROWS]:
        try:
            data=json.loads(row.result_json)
            if not isinstance(data,dict):raise ValueError('Invalid task record')
            orchestration=data.get('orchestration') or {}
            if not isinstance(orchestration,dict):raise ValueError('Invalid task lineage')
            if orchestration.get('role')=='child' or (root_id and orchestration.get('parent_id')==root_id):continue
            # Titles are user requests; generated summaries are not verified facts.
            score=overlap(goal,row.request)
            if daily(goal) and row.state in {'queued','running','proposed','failed','partial','held'}:
                score=max(score,.6)
            if score<=0:continue
            observed=timestamp(row.updated_at)
            if observed is None or observed>now:continue
            text=f'Historical ARIES task {row.id}; state at observation: {row.state}. Request: {row.request[:650]}'
            items.append(Item(row.id,'tasks',text,authority='historical_task_record',
                observed_at=observed,expires_at=min(observed+TASK_AGE,now+300),relevance=score))
        except (ValueError,TypeError,AttributeError):invalid+=1
    return items,{'status':'bounded_history','scanned':min(len(rows),MAX_ROWS),
        'truncated':len(rows)>MAX_ROWS,'invalid_rows':invalid,
        'scope':'Recent ARIES goals only; not an external task manager or deadline calendar'}


async def news(db,goal,*,now):
    from aries.sources.service import for_agent
    from aries.news.models import AriesNewsItem
    sources=await for_agent(db,types_=['rss','website'],capability='read',limit=MAX_ROWS)
    allowed=[]
    for source in sources:
        try:
            permissions=json.loads(source.permissions_json)
            # The legacy property defaults malformed JSON to read; retrieval fails closed.
            if isinstance(permissions,list) and 'read' in permissions:allowed.append(source.source_id)
        except (TypeError,ValueError):continue
    if not allowed:return [],{'status':'unavailable','reason':'No permitted enabled global news sources'}
    since=datetime.fromtimestamp(now-NEWS_AGE,timezone.utc).replace(tzinfo=None)
    q=select(AriesNewsItem).where(AriesNewsItem.source_id.in_(allowed),
        AriesNewsItem.first_seen_at>=since,AriesNewsItem.dismissed.is_(False),
        AriesNewsItem.excluded_by.is_(None),AriesNewsItem.is_representative.is_(True),
        AriesNewsItem.disposition.in_(['delivered','held']))
    rows=(await db.execute(q.order_by(AriesNewsItem.first_seen_at.desc(),AriesNewsItem.id).limit(MAX_ROWS+1))).scalars().all()
    items=[]
    for row in rows[:MAX_ROWS]:
        observed=timestamp(row.first_seen_at)
        published=timestamp(row.published_at) or observed
        if not observed or not published or observed>now or published>now or published+NEWS_AGE<=now:continue
        score=overlap(goal,row.title+' '+row.summary[:600])
        if daily(goal) and row.relevance>=.5:score=max(score,.5)
        if score<=0:continue
        text=f'Cached news from {row.source_id}; published {datetime.fromtimestamp(published,timezone.utc).isoformat()}. {row.title[:250]}\n{row.summary[:550]}'
        items.append(Item(row.item_id,'news',text,authority='untrusted_cached_source',
            observed_at=observed,expires_at=published+NEWS_AGE,relevance=score))
    return items,{'status':'bounded_cache','scanned':min(len(rows),MAX_ROWS),
        'truncated':len(rows)>MAX_ROWS,'source_limit':MAX_ROWS,
        'scope':'Previously cached permitted news only; no live fetch or completeness guarantee'}


async def collect(db,goal,*,now,root_id=None):
    items=[];status={}
    for name,adapter in [('tasks',tasks),('news',news)]:
        if name not in required_sources(goal):continue
        try:
            kwargs={'now':now}
            if name=='tasks':kwargs['root_id']=root_id
            selected,detail=await adapter(db,goal,**kwargs)
            items.extend(selected);status[name]=detail
        except Exception as exc:
            # Isolate this source's failure without hiding the missing domain.
            status[name]={'status':'unavailable','error_type':type(exc).__name__}
    return items,status
