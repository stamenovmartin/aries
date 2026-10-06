"""Cost-aware inference. Cloud can only enter through an explicit foreground route."""
import os,time,logging,uuid,json,math
import httpx
from aries.settings import SettingsService
from .providers import local_provider,OpenAICompatibleProvider,Generation,loopback_url
from .tracking import record

# The user-tunable sampling parameters, fetched in one query. They are `ai.*`
# and not `intelligence.*` because they describe the answer the user wants, not
# where ARIES thinks; the Settings app groups them with the rest of the AI panel.
SAMPLING=('ai.temperature','ai.top_p','ai.context_tokens','ai.max_output_tokens')

async def config(db):
    s=SettingsService(db)
    keys=['location','local_backend','local_url','local_model','keep_alive','gateway_enabled','gateway_url',
          'cloud_provider','cloud_cli_timeout_seconds','cloud_enabled','cloud_url','cloud_model','cloud_local_fallback','cloud_input_usd_per_million','cloud_output_usd_per_million']
    cfg={k:await s.get('intelligence.'+k) for k in keys}
    cfg['sampling']=await s.get_many(SAMPLING)
    cfg['privacy']=await s.get_many(('privacy.mode','ai.send_file_contents'))
    return cfg

def sampling(cfg,max_tokens):
    """The user's sampling parameters, plus the output budget they cap.

    ai.max_output_tokens is a CEILING, never a request: it can only lower what a
    caller already asked for, so lowering it cannot make any caller exceed the
    gateway's own transport bound, and raising it cannot lengthen a decision that
    was deliberately budgeted small.
    """
    p=cfg['sampling']
    return min(max_tokens,int(p['ai.max_output_tokens'])),{
        'temperature':float(p['ai.temperature']),'top_p':float(p['ai.top_p']),
        'context_tokens':int(p['ai.context_tokens'])}

async def local_generate(cfg,messages,schema,max_tokens):
    if cfg['location']!='local':raise ValueError('Language models are disabled')
    budget,tune=sampling(cfg,max_tokens)
    if cfg['gateway_enabled']:
        try:
            async with httpx.AsyncClient(timeout=185,trust_env=False) as c:
                r=await c.post(loopback_url(cfg['gateway_url'])+'/generate',json={
                    'messages':messages,'schema_spec':schema,'max_tokens':budget,**tune})
                r.raise_for_status()
                return Generation(**r.json())
        except (httpx.ConnectError,httpx.ConnectTimeout):
            # Same local runtime, no privacy-changing remote fallback.
            logging.getLogger(__name__).warning('Local gateway unavailable; using the same loopback runtime directly')
    p=local_provider(cfg['local_backend'],cfg['local_url'],cfg['local_model'],cfg['keep_alive'])
    return await p.generate(messages,schema,budget,**tune)

async def generate(db,messages,schema,*,purpose,max_tokens=4096,force_local=False,route=None,allow_fallback=True,provenance=None):
    cfg=await config(db)
    allow_fallback=allow_fallback and not (route or {}).get('no_fallback',False)
    if cfg['location']=='none':raise ValueError('Language models are disabled')
    requested='local' if force_local or not route else route.get('execution_level','local')
    level='cloud' if requested=='cloud' else 'local'
    reason=(route or {}).get('reason','Local-only caller; no cloud authorization')
    from .egress import classify, cloud_block
    classes=classify(messages,schema,provenance)
    blocked=cloud_block(classes,privacy_mode=cfg['privacy'].get('privacy.mode'),
                        send_file_contents=cfg['privacy'].get('ai.send_file_contents'))
    if level=='cloud' and blocked:
        await record(db,'egress',purpose=purpose,requested_level='cloud',execution_level='local',
                     data_classes=sorted(classes),blocked_reason=blocked)
        await db.commit()
        if not allow_fallback or not cfg['cloud_local_fallback']:
            raise ValueError('PRIVACY_BLOCKED: '+blocked)
        level='local'
        reason=blocked
    unavailable=None
    if level=='cloud':
        unavailable=cloud_unavailable(cfg)
        if unavailable:
            await record(db,'fallback',purpose=purpose,reason=unavailable,from_level='cloud',to_level='local')
            if not allow_fallback or not cfg['cloud_local_fallback']:raise ValueError(unavailable)
            level='local'
    async def attempt(which):
        start=time.monotonic();g=None;error=None;error_detail=None
        call_id=uuid.uuid4().hex
        from .context import current
        from . import budgets
        attribution=current()
        reservation=None
        if attribution.get('budgeted'):
            # UTF-8 bytes plus schema and transport allowance, explicitly an
            # admission estimate, not a claim of measured tokenizer usage.
            prompt_bound=len(json.dumps([messages,schema],ensure_ascii=False).encode())+1024
            cost_bound=0 if which=='local' else None
            if which=='cloud' and cfg['cloud_provider']=='openai-compatible' and cfg['cloud_input_usd_per_million']>0 and cfg['cloud_output_usd_per_million']>0:
                cost_bound=math.ceil(prompt_bound*cfg['cloud_input_usd_per_million']+max_tokens*cfg['cloud_output_usd_per_million'])
            reservation=await budgets.reserve(attribution['root_id'],attribution['task_id'],'model',
                tokens=prompt_bound+max_tokens,cost_micros=cost_bound)
        try:
            if which=='cloud':
                if cfg['cloud_provider'] in {'claude-cli','codex-cli'}:
                    from .cli import CLIDecisionProvider
                    p=CLIDecisionProvider(cfg['cloud_provider'],cfg['cloud_model'],cfg['cloud_cli_timeout_seconds'])
                else:
                    p=OpenAICompatibleProvider(cfg['cloud_url'],cfg['cloud_model'],os.environ['ARIES_CLOUD_API_KEY'],local=False)
                g=await p.generate(messages,schema,max_tokens)
            else:g=await local_generate(cfg,messages,schema,max_tokens)
            return g
        except Exception as exc:
            error=type(exc).__name__
            error_detail=getattr(exc,"safe_detail",None)
            raise
        finally:
            cost=None
            if which=='cloud' and cfg['cloud_provider']=='openai-compatible' and g and g.input_tokens is not None and g.output_tokens is not None and cfg['cloud_input_usd_per_million']>0 and cfg['cloud_output_usd_per_million']>0:
                cost=(g.input_tokens*cfg['cloud_input_usd_per_million']+g.output_tokens*cfg['cloud_output_usd_per_million'])/1_000_000
            if reservation:
                measured=g.input_tokens+g.output_tokens if g and type(g.input_tokens) is int and type(g.output_tokens) is int else None
                await budgets.settle(reservation,tokens=measured,
                    cost_micros=0 if which=='local' else math.ceil(cost*1_000_000) if cost is not None else None,
                    known=measured is not None)
            await record(db,'generation',call_id=call_id,data_classes=sorted(classes),level=which,provider=g.provider if g else (cfg['cloud_provider'] if which=='cloud' else cfg['local_backend']),
                model=g.model if g else cfg['cloud_model' if which=='cloud' else 'local_model'],task_type=purpose,reason=reason,
                input_tokens=g.input_tokens if g else None,output_tokens=g.output_tokens if g else None,
                estimated_cost_usd=cost,reported_cost_usd=g.reported_cost_usd if g else None,usage_details=g.usage_details if g else None,billing_basis='CLI account usage; reported cost is not an invoice' if cfg['cloud_provider'].endswith('-cli') and which=='cloud' else 'API configured price',price_source='configured USD per million; not a current price quote',
                latency_ms=round((time.monotonic()-start)*1000),ok=g is not None,error=error,error_detail=error_detail)
            # Persist failures as well as success. Callers must not have pending side effects here.
            await db.commit()
    try:g=await attempt(level)
    except (httpx.HTTPError,RuntimeError,TimeoutError) as exc:
        if level!='cloud' or not allow_fallback or not cfg['cloud_local_fallback']:raise
        await record(db,'fallback',purpose=purpose,reason=type(exc).__name__,from_level='cloud',to_level='local')
        g=await attempt('local');level='local'
    cost=None
    if level=='cloud' and cfg['cloud_provider']=='openai-compatible' and g.input_tokens is not None and g.output_tokens is not None and cfg['cloud_input_usd_per_million']>0 and cfg['cloud_output_usd_per_million']>0:
        cost=(g.input_tokens*cfg['cloud_input_usd_per_million']+g.output_tokens*cfg['cloud_output_usd_per_million'])/1_000_000
    return g.text,{'data_classes':sorted(classes),'egress_blocked_reason':blocked if requested=='cloud' else None,'usage_details':g.usage_details,'reported_cost_usd':g.reported_cost_usd,'estimated_cost_usd':cost,'prompt_eval_count':g.input_tokens,'eval_count':g.output_tokens,'provider':g.provider,'model':g.model,'execution_level':level}


def cloud_unavailable(cfg):
    if not cfg['cloud_enabled']:return 'Cloud disabled by policy'
    if cfg['cloud_provider'] in {'claude-cli','codex-cli'}:
        from .cli import executable
        return None if executable(cfg['cloud_provider']) else 'Configured cloud CLI is not installed'
    if not cfg['cloud_model'] or not os.environ.get('ARIES_CLOUD_API_KEY'):return 'Cloud model or credentials unavailable'
    return None
