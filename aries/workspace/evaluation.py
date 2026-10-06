"""Operational outcomes from durable goals, never an invented maturity score."""
import json
from collections import Counter, defaultdict
from statistics import median
from sqlalchemy import select
from aries.workspace.models import WorkspaceGoal


async def report(db):
    rows = (await db.execute(select(WorkspaceGoal).order_by(WorkspaceGoal.created_at.desc()).limit(500))).scalars().all()
    groups = defaultdict(list)
    repairs = []
    for row in rows:
        data = json.loads(row.result_json)
        for step in data.get('steps', []):
            if step.get('inherited'):
                continue
            result = step.get('result', {})
            kind = step.get('capability') or step.get('kind', 'unknown')
            state = step.get('state', row.state)
            if step.get('verification_status') == 'verified':
                state = 'done'
            elif state == 'verification_failed':
                state = 'failed'
            if kind == 'evaluation':
                continue
            if state in {'done', 'partial', 'failed', 'unconfirmed', 'interrupted', 'empty', 'held'}:
                groups[kind].append({'state': state, 'goal': row.id,
                                     'elapsed_seconds': result.get('elapsed_seconds')})
            attempts = result.get('coding', {}).get('attempts', [])
            if len(attempts) > 1:
                repairs.append({'goal': row.id, 'attempts': len(attempts),
                                'recovered': attempts[0]['returncode'] != 0 and attempts[-1]['returncode'] == 0})
    from aries.workspace.reviews import report as review_report
    human = await review_report(db)
    counts = human["counts"]
    cards = [{"title":"Your task reviews", "text":f"{counts['useful']} useful · {counts['needs_work']} need correction · {counts['reviewed']} reviewed goals",
              "evidence":human["scope"]}]
    for kind, attempts in sorted(groups.items()):
        counts = Counter(r['state'] for r in attempts)
        times = sorted(r['elapsed_seconds'] for r in attempts if isinstance(r['elapsed_seconds'], (int, float)))
        timing = f" · median execution {median(times):.1f}s" if times else ' · execution timing not collected for older records'
        cards.append({'title': kind.replace('_', ' ').title(),
                      'text': f"{counts['done']}/{len(attempts)} recorded attempts completed" + timing,
                      'evidence': ', '.join(f'{k}: {v}' for k,v in sorted(counts.items())) + '. Historical operational outcomes; not a controlled benchmark.'})
    cards.append({'title': 'Measured code repair', 'text': f"{sum(r['recovered'] for r in repairs)}/{len(repairs)} recorded multi-attempt builds recovered from a failing generated suite",
                  'evidence': 'Task-local generated-test repair only. Production code and policies are not automatically rewritten.'})
    return {'state': 'done', 'summary': f'Evaluated recorded outcomes from the latest {len(rows)} goals',
            'cards': cards, 'scope': 'latest 500 durable goals; pending and cancelled attempts excluded',
            'capabilities': dict(groups), 'repairs': repairs, 'human_reviews':human['counts']}
