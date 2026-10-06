"""Routing policy invariants with deterministic providers; live evaluation is separate."""
import asyncio,json,sys
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-intelligence')
from agentic_core.database.base import async_session
from aries.settings import SettingsService
from aries.intelligence.schemas import Decision,Classification
from aries.intelligence.router import route,learn_verified
from aries.intelligence.providers import Generation,loopback_url
from aries.intelligence.generation import generate
from aries.intelligence.tracking import stats
from aries.workspace import service

class Fake:
    def __init__(self,**kw):self.kw=kw
    async def decide(self,db,text):return Decision(intent='CLASSIFY',tool='classifier',confidence=0.95,reason='test',**self.kw)

async def test_rules_no_model():
    await reset_db()
    async with async_session() as db:
        with patch('aries.intelligence.router.LocalLLMDecisionProvider.decide',AsyncMock(side_effect=AssertionError('LLM called'))) as model:
            for goal,intent in [('open YouTube','OPEN_URL'),('open Gmail','OPEN_URL'),('show system status','SYSTEM_ACTION'),('open Downloads','FILE_ACTION'),('run system health','SYSTEM_ACTION')]:
                r=await route(db,goal);check(goal+' code and intent',r.execution_level=='code' and r.intent==intent)
            check('deterministic requests zero LLM',model.await_count==0)
        item=await service.submit(db,'show system status')
        check('system status queue avoids agent',item.get('agent_engine') is None)
        counts=await stats(db);check('no cloud consumption',counts['cloud_requests']==0)

async def test_confidence_background_and_schema():
    await reset_db()
    class Low:
        async def decide(self,db,text):return Decision(intent='UNKNOWN',confidence=0.7,reason='uncertain')
    async with async_session() as db:
        check('high confidence stays local',(await route(db,'classify this email',provider=Fake())).execution_level=='local')
        check('low confidence recommends cloud',(await route(db,'ambiguous request',provider=Low())).execution_level=='cloud')
        await SettingsService(db).set('intelligence.local_confidence_threshold',0.6,set_by='user')
        check('threshold configurable',(await route(db,'ambiguous request',provider=Low())).execution_level=='local')
        r=await route(db,'complex background event',background=True,provider=Fake(requires_cloud=True,estimated_complexity='complex'))
        check('background cloud prohibited',r.execution_level=='local' and bool(r.blocked_reason))
        for raw in ['not json','{"intent":"SHELL","confidence":1,"reason":"x"}', '{"intent":"CODING","confidence":2,"reason":"x"}', '{"intent":"CODING","confidence":1,"reason":"x","command":"rm"}']:
            try:Decision.model_validate_json(raw);ok=False
            except ValueError:ok=True
            check('invalid schema rejected '+raw[:20],ok)
        with patch('aries.intelligence.local_structured',AsyncMock(return_value=('not json',{}))):
            try:await route(db,'unrecognized arbitrary goal');ok=False
            except ValueError:ok=True
            check('invalid decision fails closed',ok)
        try:Classification(category='urgent',should_notify=True,should_execute=True,confidence=1.0,reason='x');ok=False
        except ValueError:ok=True
        check('classification cannot authorize execution',ok)
        from aries.intelligence.schemas import apply_notification_policy
        candidate=Classification(category='low',should_notify=True,confidence=0.9,reason='routine')
        check('low importance notification veto is deterministic',not apply_notification_policy(candidate).should_notify and candidate.should_notify)

async def test_provider_outage_and_loopback():
    await reset_db()
    for url in ['http://0.0.0.0:11434','http://192.168.1.5:1','http://127.0.0.1.evil.test','https://127.0.0.1','http://user:pass@127.0.0.1','http://localhost:1']:
        try:loopback_url(url);ok=False
        except ValueError:ok=True
        check('nonliteral/exposed URL rejected '+url,ok)
    check('literal loopback accepted',loopback_url('http://127.0.0.1:11434')=='http://127.0.0.1:11434')
    class Broken:
        async def decide(self,db,text):raise ConnectionError('down')
    async with async_session() as db:
        r=await route(db,'ambiguous foreground',provider=Broken())
        check('outage records fallback recommendation',r.source=='fallback' and r.execution_level=='cloud')
        with patch('aries.intelligence.generation.local_generate',AsyncMock(return_value=Generation('ok',10,2,'fake-local','test'))),patch('aries.intelligence.generation.OpenAICompatibleProvider.generate',AsyncMock(side_effect=AssertionError('CLOUD CALLED'))) as cloud:
            raw,u=await generate(db,[],None,purpose='test',route=r.model_dump())
            check('disabled cloud falls back locally',raw=='ok' and u['execution_level']=='local' and cloud.await_count==0)
        await SettingsService(db).set('intelligence.cloud_local_fallback',False,set_by='user')
        try:await generate(db,[],None,purpose='test',route=r.model_dump());ok=False
        except ValueError:ok=True
        check('fallback can fail closed',ok)

async def test_cloud_usage_and_failure():
    import httpx
    await reset_db()
    async with async_session() as db:
        for key,value in [('cloud_provider','openai-compatible'),('cloud_enabled',True),('cloud_model','test'),('cloud_input_usd_per_million',2.0),('cloud_output_usd_per_million',4.0)]:
            await SettingsService(db).set('intelligence.'+key,value,set_by='user')
        with patch.dict('os.environ',{'ARIES_CLOUD_API_KEY':'fake-test-key'}),patch('aries.intelligence.generation.OpenAICompatibleProvider.generate',AsyncMock(return_value=Generation('{}',100,20,'mock-cloud','test'))):
            _,u=await generate(db,[],None,purpose='test-complex',route={'execution_level':'cloud','reason':'complex'})
            check('explicit cloud path observed',u['execution_level']=='cloud')
            counts=await stats(db)
            check('native tokens and configured cost recorded',counts['measured_cloud_input_tokens']==100 and abs(counts['estimated_api_cost_usd']-0.00028)<1e-10)
            check('no invented savings',counts['estimated_token_savings'] is None)
        with patch.dict('os.environ',{'ARIES_CLOUD_API_KEY':'fake-test-key'}),patch('aries.intelligence.generation.OpenAICompatibleProvider.generate',AsyncMock(side_effect=httpx.ConnectError('unavailable'))),patch('aries.intelligence.generation.local_generate',AsyncMock(return_value=Generation('{}',20,5,'fake-local','test'))):
            _,u=await generate(db,[],None,purpose='test-cloud-failure',route={'execution_level':'cloud','reason':'complex'})
            check('cloud outage falls back locally',u['execution_level']=='local')
            counts=await stats(db);check('failed cloud attempts retained',counts['cloud_requests']==2 and counts['cloud_successful_responses']==1 and counts['cloud_usage_unknown']==1)

async def test_safe_cache_and_service_boundary():
    import httpx
    from aries.intelligence.server import app
    await reset_db()
    async with async_session() as db:
        d=Decision(intent='CLASSIFY',confidence=0.99,reason='verified').model_dump()
        check('unverified mapping not cached',not await learn_verified(db,'classify email',d,verified=False))
        check('verified harmless hint cached',await learn_verified(db,'classify email',d,verified=True))
        await db.commit()
        check('cache avoids classifier',(await route(db,'classify email',provider=Fake())).source=='cache')
        d['intent']='SEND_EMAIL';check('sensitive mappings not learned',not await learn_verified(db,'send email',d,verified=True))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',123)),base_url='http://127.0.0.1') as c:
        check('web origin refused',(await c.post('/classify',json={'text':'hello'},headers={'origin':'https://evil.test'})).status_code==403)
        check('invalid local payload refused',(await c.post('/generate',json={'messages':[],'command':'rm'})).status_code==422)
        with patch('aries.intelligence.server.provider',AsyncMock(side_effect=ConnectionError('down'))):
            check('gateway health honest on runtime outage',(await c.get('/health')).status_code==503)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('192.168.1.5',123)),base_url='http://127.0.0.1') as c:
        check('LAN peer refused',(await c.get('/health')).status_code==403)


async def test_http_provider_adapters_and_api():
    import httpx
    from aries.intelligence.providers import OllamaProvider,OpenAICompatibleProvider
    from aries.api.app import app
    await reset_db()
    original=httpx.AsyncClient
    seen=[]
    def respond(request):
        seen.append(request)
        if request.url.path=='/api/chat':
            return httpx.Response(200,json={'message':{'content':'{}'},'prompt_eval_count':12,'eval_count':3})
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}],
                                      'usage':{'prompt_tokens':10,'completion_tokens':4}})
    def client(**kw):return original(transport=httpx.MockTransport(respond),**kw)
    with patch('httpx.AsyncClient',side_effect=client):
        g=await OllamaProvider('http://127.0.0.1:11434','test').generate([],{},20)
        check('Ollama adapter preserves native counts',g.input_tokens==12 and g.output_tokens==3)
        check('Ollama requests reusable model residency',json.loads(seen[-1].content)['keep_alive']=='15m')
        g=await OpenAICompatibleProvider('http://127.0.0.1:8080/v1','test').generate([],{},20)
        check('alternative local runtime uses compatible protocol',g.provider=='local-openai-compatible' and seen[-1].url.path=='/v1/chat/completions')
    async with original(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
        r=await c.post('/api/aries/intelligence/route',json={'text':'open YouTube'})
        check('router integrated through existing API',r.status_code==200 and r.json()['execution_level']=='code')
        r=await c.get('/api/aries/intelligence/stats')
        check('usage API available without UI database access',r.status_code==200 and r.json()['cloud_requests']==0)
        r=await c.post('/api/aries/intelligence/ab-task',json={'text':'show system status','architecture':'A'})
        check('all-cloud baseline cannot silently become local',r.status_code==409)
        r=await c.post('/api/aries/intelligence/route',json={'text':'open YouTube','shell':'pwd'})
        check('API refuses extra executable fields',r.status_code==422)
    async with async_session() as db:
        await SettingsService(db).set('intelligence.location','none',set_by='user')
        try:await generate(db,[],None,purpose='disabled',route={'execution_level':'cloud'});ok=False
        except ValueError:ok=True
        check('model-off setting also prevents cloud',ok)


async def test_coding_routes_once_and_preserves_structured_boundary():
    from aries.workspace.coding import generate as coding_generate
    from aries.intelligence.schemas import Route
    await reset_db()
    candidate=json.dumps({'title':'Test','code':'def add(a,b):\n return a+b\n',
                          'tests':'import unittest\nclass Test(unittest.TestCase):\n def test_add(self): self.assertEqual(2+3,5)\n','explanation':'Test'})
    decision=Route(intent='CODING',confidence=0.9,reason='complex code',requires_cloud=True,execution_level='cloud',source='local')
    async with async_session() as db:
        with patch('aries.intelligence.router.route',AsyncMock(return_value=decision)) as router,patch('aries.intelligence.structured',AsyncMock(return_value=(candidate,{}))) as model:
            await coding_generate(db,'Implement an architectural analyzer')
            await coding_generate(db,'Implement an architectural analyzer','repair feedback')
            check('coding repair reuses route instead of reclassifying',router.await_count==1)
            check('coding uses selected structured provider boundary',model.call_args.kwargs['route']['execution_level']=='cloud')


async def test_terminal_cloud_protocol_and_boundaries():
    from aries.intelligence.cli import argv_for,decode,CLIProviderError,CLIDecisionProvider
    from aries.intelligence.generation import cloud_unavailable,config
    from tempfile import TemporaryDirectory
    the reviewing agent=argv_for('claude-cli','/usr/bin/the reviewing agent','','/tmp/owned')
    codex=argv_for('codex-cli','/usr/bin/codex','','/tmp/owned')
    check('the reviewing agent tools disabled while login retained','--safe-mode' in the reviewing agent and the reviewing agent[the reviewing agent.index('--tools')+1]=='')
    check('Codex shell and app tools disabled','features.shell_tool=false' in codex and 'features.apps=false' in codex and 'read-only' in codex)
    check('prompt passed via stdin not executable argv',codex[-1]=='-' and '--dangerously-bypass-approvals-and-sandbox' not in codex)
    g=decode('claude-cli',json.dumps({'type':'result','subtype':'success','result':'{}','usage':{'input_tokens':4,'cache_read_input_tokens':12,'cache_creation_input_tokens':3,'output_tokens':2},'total_cost_usd':0.01}))
    check('the reviewing agent cached and uncached usage measured separately',g.input_tokens==19 and g.usage_details['cache_read_input_tokens']==12 and g.reported_cost_usd==0.01)
    g=decode('codex-cli','{"type":"turn.completed","usage":{"input_tokens":20,"output_tokens":3}}','{}')
    check('Codex JSONL native usage parsed',g.input_tokens==20 and g.output_tokens==3)
    for provider,raw in [('claude-cli','{"is_error":true,"api_error_status":429}'),('codex-cli','{"type":"turn.failed"}'),('codex-cli','{"type":"item.completed","item":{"type":"command_execution"}}\n{"type":"turn.completed","usage":{}}')]:
        try:decode(provider,raw,'{}');ok=False
        except RuntimeError:ok=True
        check('CLI failure/tool attempt never becomes success '+provider,ok)
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set('intelligence.cloud_enabled',True,set_by='user')
        cfg=await config(db)
        with patch('aries.intelligence.cli.executable',return_value='/usr/bin/the reviewing agent'):
            check('CLI login path needs no separate API key/model',cloud_unavailable(cfg) is None)
        with patch('aries.intelligence.cli.CLIDecisionProvider.generate',AsyncMock(return_value=Generation('{}',20,3,'claude-cli','cli-default',reported_cost_usd=0.01))):
            _,usage=await generate(db,[],None,purpose='cli-test',route={'execution_level':'cloud'})
            check('CLI nominal cost is not billed API cost',usage['estimated_cost_usd'] is None and usage['reported_cost_usd']==0.01)
    with TemporaryDirectory() as directory:
        binary=Path(directory)/'fake-cli'
        binary.write_text('#!/usr/bin/python3\nimport time\ntime.sleep(30)\n');binary.chmod(0o700)
        with patch('aries.intelligence.cli.executable',return_value=str(binary)):
            try:await CLIDecisionProvider('codex-cli',timeout=0.1).generate([],None);ok=False
            except TimeoutError:ok=True
            check('hung CLI terminated by bounded timeout',ok)

async def test_usage_scope_and_missing_counts():
    from aries.intelligence.tracking import record
    await reset_db()
    async with async_session() as db:
        await record(db,'generation',level='cloud',ok=True,input_tokens=12,output_tokens=3)
        await record(db,'generation',level='cloud',ok=False,input_tokens=None,output_tokens=None)
        result=await stats(db)
        check('known request usage remains a subtotal',result['measured_cloud_input_tokens']==12)
        check('unknown consumption is not zero',result['cloud_input_tokens_total'] is None and result['cloud_output_tokens_total'] is None)
        check('external account usage and remaining quota unavailable',result['account_usage_available'] is False and result['account_remaining_quota'] is None)
        check('usage explicitly scoped to ARIES', 'ARIES-initiated' in result['usage_scope'])

if __name__=='__main__':run_module(sys.modules[__name__])
