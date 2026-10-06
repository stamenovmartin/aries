"""Explicit human judgments linked to bounded, immutable task evidence.

Reviews never change execution status, settings, or model weights. Only the most
recent review per goal contributes to counts or retrieval; earlier rows remain
in feedback history. Retiring the latest review does not revive an older one.
"""
import hashlib
import json
import re
from collections import Counter
from sqlalchemy import func, select
from aries.learning.feedback import AriesFeedback, TASK
from aries.workspace.models import WorkspaceGoal

RATINGS = {'useful', 'needs_work'}
TERMINAL = {'done', 'answered', 'partial', 'failed', 'interrupted', 'cancelled', 'unconfirmed', 'held', 'empty'}


def episode(goal):
    data = json.loads(goal.result_json)
    return {'goal_id': goal.id, 'request': goal.request[:2000], 'state': goal.state,
            'result_digest': hashlib.sha256(goal.result_json.encode()).hexdigest(),
            'steps': [{'capability': s.get('capability') or s.get('kind', 'unknown'),
                       'state': s.get('state', 'unknown'), 'inherited':bool(s.get('inherited')),
                       'summary': str(s.get('result', {}).get('summary', ''))[:600],
                       'verification': {k: (v if k == 'met' and isinstance(v, (bool, type(None))) else str(v)[:800])
                                        for k, v in (s.get('recovery_verification', {}) if s.get('inherited') else s.get('result', {}).get('verification', {})).items()
                                        if k in {'met', 'evidence'}}}
                      for s in data.get('steps', [])[:8]],
            'limitations': [str(x)[:400] for x in data.get('gaps', [])[:8]]}


def display(row):
    context = json.loads(row.context_json)
    return {'id': row.id, 'goal_id': row.scope_target, 'rating': context['rating'],
            'comment': row.text, 'episode': context['episode'],
            'at': row.created_at.isoformat() if row.created_at else None}


async def latest(db, goal_ids=None, limit=500):
    newest = select(func.max(AriesFeedback.id)).where(AriesFeedback.classification == 'task_review')
    if goal_ids is not None:
        if not goal_ids:
            return []
        newest = newest.where(AriesFeedback.scope_target.in_(goal_ids))
    newest = newest.group_by(AriesFeedback.scope_target)
    rows = (await db.execute(select(AriesFeedback).where(AriesFeedback.id.in_(newest))
                            .order_by(AriesFeedback.id.desc()).limit(limit))).scalars().all()
    return [display(r) for r in rows if r.scope == TASK]


async def submit(db, goal_id, rating, comment=''):
    from agentic_core.observability.audit import log_event
    if rating not in RATINGS:
        raise ValueError('Choose useful or needs_work')
    comment = comment.strip()
    if len(comment) > 2000:
        raise ValueError('A correction can contain at most 2000 characters')
    if rating == 'needs_work' and not comment:
        raise ValueError('Describe what needs correcting so ARIES can use the feedback')
    goal = await db.get(WorkspaceGoal, goal_id)
    if goal is None:
        raise LookupError('Task not found')
    if goal.state not in TERMINAL:
        raise ValueError('Review a task after it finishes; active work and approvals are not completed results')
    captured = episode(goal)
    previous = await latest(db, [goal_id])
    if previous and previous[0]['rating'] == rating and previous[0]['comment'] == comment and previous[0]['episode'] == captured:
        return previous[0]
    row = AriesFeedback(text=comment, classification='task_review', scope=TASK,
        scope_target=goal_id, confidence=1.0, ambiguous=False, applied=False,
        reason='Explicit human review of the captured task outcome; execution status remains independent',
        policy_version='task-review-v1', context_json=json.dumps({'origin':'user', 'task':goal_id,
            'rating':rating, 'episode':captured}))
    db.add(row)
    await db.flush()
    await log_event(db, actor_type='human', actor='user', action='workspace.reviewed',
                    entity_type='feedback', entity_id=row.id,
                    detail={'goal_id':goal_id, 'rating':rating, 'result_digest':captured['result_digest']})
    await db.commit()
    await db.refresh(row)
    return display(row)


async def report(db):
    from aries.settings import SettingsService
    version = await SettingsService(db).get('workspace.review_retrieval')
    rows = await latest(db)
    counts = Counter(r['rating'] for r in rows)
    return {'retrieval_version':version, 'reviews':rows, 'counts':{'reviewed':len(rows), 'useful':counts['useful'], 'needs_work':counts['needs_work']},
            'scope':'Latest active review per goal, up to 500 goals. Human judgment, not verified execution success or model training.'}


_STOP = set('the and this that with from please task open show report final page title aries do for sto toa da mi vo na se kako sakam otvori napravi'.split())
def words(text):
    return {w for w in re.findall(r'\w+', text.casefold()) if len(w)>2 and w not in _STOP}


async def relevant(db, request):
    from aries.settings import SettingsService
    from aries.workspace.retrieval import rank
    version = await SettingsService(db).get('workspace.review_retrieval')
    rows = rank(await latest(db, limit=200), request, version)
    # No old paths, session handles, source contents or executable arguments.
    return [{'review_id':r['id'], 'goal_id':r['goal_id'], 'retrieval_version':version,
             'request':r['episode']['request'][:700], 'execution_state':r['episode']['state'],
             'human_rating':r['rating'], 'correction':r['comment'][:1000],
             'steps':[{'capability':s['capability'], 'state':s['state'], 'inherited':s.get('inherited',False)} for s in r['episode']['steps']]}
            for r in rows]
