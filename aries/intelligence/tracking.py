import json,uuid
from sqlalchemy import select
from aries.intelligence.models import IntelligenceEvent

async def record(db,kind,**data):
    from .context import current
    data = {**current(), **data}
    db.add(IntelligenceEvent(id=uuid.uuid4().hex,kind=kind,data_json=json.dumps(data)))
    await db.flush()

async def stats(db):
    # Bounded operational window, explicitly reported. Never invent token savings.
    rows=(await db.execute(select(IntelligenceEvent).order_by(IntelligenceEvent.created_at.desc()).limit(10000))).scalars().all()
    routes=[json.loads(r.data_json) for r in rows if r.kind=='route']
    calls=[json.loads(r.data_json) for r in rows if r.kind=='generation']
    outcomes=[json.loads(r.data_json) for r in rows if r.kind=='outcome']
    counts={k:sum(r['execution_level']==k for r in routes) for k in ('code','local','cloud')}
    cloud=[r for r in calls if r['level']=='cloud'];local=[r for r in calls if r['level']=='local']
    return {'window_events':len(rows),'window_limit':10000,'total_requests':len(routes),'requests_scope':'Router invocations, including previews; not distinct completed tasks',
        'usage_scope':'ARIES-initiated requests in retained events only; excludes other terminal sessions, applications and account-wide usage',
        'account_usage_available':False,'account_remaining_quota':None,
        'token_subtotals_note':'Measured fields sum available per-request reports only; incomplete coverage is not total consumption. Cached input may be included.',
        'cloud_input_tokens_total':None if any(r.get('input_tokens') is None for r in cloud) else sum(r['input_tokens'] for r in cloud),
        'cloud_output_tokens_total':None if any(r.get('output_tokens') is None for r in cloud) else sum(r['output_tokens'] for r in cloud),
        'routed_by_level':counts,'completed_by_level':{k:sum(r.get('level')==k and r.get('state')=='done' for r in outcomes) for k in counts},
        'unattributed_completed_tasks':sum(r.get('state')=='done' and r.get('level') not in counts for r in outcomes),
        'cloud_escalation_percent':100*counts['cloud']/len(routes) if routes else 0,
        'cloud_requests':len(cloud),'local_requests':len(local),'cloud_successful_responses':sum(r['ok'] for r in cloud),
        'measured_cloud_input_tokens':sum(r.get('input_tokens') or 0 for r in cloud),
        'measured_cloud_output_tokens':sum(r.get('output_tokens') or 0 for r in cloud),
        'cloud_usage_unknown':sum(r.get('input_tokens') is None or r.get('output_tokens') is None for r in cloud),
        'estimated_api_cost_usd':None if any(r.get('estimated_cost_usd') is None for r in cloud) else sum(r['estimated_cost_usd'] for r in cloud),
        'priced_requests_cost_usd':sum(r.get('estimated_cost_usd') or 0 for r in cloud),
        'unpriced_cloud_requests':sum(r.get('estimated_cost_usd') is None for r in cloud),
        'estimated_token_savings':None,'savings_note':'Requires measured matched all-cloud baseline; not inferred from routing.'}
