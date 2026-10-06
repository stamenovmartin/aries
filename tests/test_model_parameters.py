"""Do the tunable model parameters actually change the model? Measured, not assumed.

A temperature slider the runtime accepts and ignores is worse than no slider: it
makes the Settings app lie about the machine. So the live tests below read the
generated strings back and compare them — and print them — instead of asserting
that a request was merely sent.

Two databases are involved and they are deliberately different. Every `ai.*`
value read here comes from this process's THROWAWAY harness sqlite file (the
path is printed below); the running gateway keeps using its own live database
for where-to-reach-the-model, and takes the sampling parameters from the request
body ARIES sends it. No live setting is written by this file.
"""
import json,os,sys,urllib.error,urllib.request
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-model-parameters')
from agentic_core.database.base import async_session
from aries.settings import SettingsService
from aries.settings import schema
from aries.intelligence.generation import generate,sampling
from aries.intelligence.schemas import Decision

KEYS=('ai.temperature','ai.top_p','ai.context_tokens','ai.max_output_tokens')
# The literals these parameters replaced. A default that differs from one of
# these would change today's answers, which reads as a regression, not a feature.
WAS={'ai.temperature':0.1,'ai.top_p':0.9,'ai.context_tokens':8192,'ai.max_output_tokens':4096}
GATEWAY='http://127.0.0.1:11435'
RUNTIME='http://127.0.0.1:11434'
SEA='Write one sentence about the sea.'


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url),timeout=5).read())


def live():
    """Is the running gateway answering with a loaded model?"""
    try:return bool(get(GATEWAY+'/health').get('backend',{}).get('model_available'))
    except (OSError,urllib.error.URLError,ValueError):return False


def show(label,value):
    print(f'      {label:26} {value!r}')


async def say(db,prompt=SEA,tokens=120,shape=None,purpose='measure.sampling'):
    text,usage=await generate(db,[{'role':'user','content':prompt}],shape,purpose=purpose,max_tokens=tokens)
    return text.strip(),usage


async def tuned(db,**values):
    s=SettingsService(db)
    for key,value in values.items():
        await s.set('ai.'+key,value,set_by='user')


async def test_1_schema():
    print('      harness database:',os.environ['DATABASE_URL'])
    await reset_db()
    defined={d.key:d for d in schema.matching('ai') if d.key in KEYS}
    check('all four parameters are declared under ai.*',set(defined)==set(KEYS))
    check('every default is exactly the literal it replaced',
          all(defined[k].default==WAS[k] for k in KEYS))
    check('each one renders as a real control with bounds',
          all(defined[k].control in ('slider','number') and defined[k].minimum is not None
              and defined[k].maximum is not None for k in KEYS))
    async with async_session() as db:
        s=SettingsService(db)
        check('unset values resolve to the previous behaviour',
              all([(await s.get(k))==WAS[k] for k in KEYS]))
        for key,bad in [('ai.temperature',2.5),('ai.temperature',-0.1),('ai.top_p',1.4),
                        ('ai.top_p',0.0),('ai.context_tokens',64),('ai.context_tokens',99999),
                        ('ai.max_output_tokens',8192),('ai.max_output_tokens',1),
                        ('ai.temperature','hot')]:
            try:await s.set(key,bad,set_by='user');refused=False
            except Exception:refused=True
            check(f'out-of-range {key}={bad!r} refused',refused)
        check('a machine may not raise the context window',
              not await _allowed(s.learn('ai.context_tokens',32768,confidence=0.9,rationale='test')))
        check('a machine may suggest a temperature',
              await _allowed(s.learn('ai.temperature',0.7,confidence=0.9,rationale='test')))


async def _allowed(coro):
    try:
        await coro;return True
    except Exception:return False


def test_2_output_ceiling():
    """The ceiling lowers a caller's budget and never raises it."""
    cfg={'sampling':{'ai.temperature':0.1,'ai.top_p':0.9,'ai.context_tokens':8192,'ai.max_output_tokens':512}}
    check('a lower ceiling caps a large caller budget',sampling(cfg,4096)[0]==512)
    check('a ceiling never lengthens a small budget',sampling(cfg,300)[0]==300)
    cfg['sampling']['ai.max_output_tokens']=4096
    check('the default ceiling leaves the gateway bound intact',sampling(cfg,4096)[0]==4096)


async def test_3_request_body():
    """The values reach the wire — both the gateway body and the runtime options."""
    await reset_db()
    seen={}
    class Reply:
        def __init__(self,payload):self.payload=payload
        def raise_for_status(self):pass
        def json(self):return self.payload
    def recorder(payload):
        async def post(self,url,*,json=None,**kw):
            seen.update({'url':url,'body':json});return Reply(payload)
        return post
    async with async_session() as db:
        await tuned(db,temperature=1.7,top_p=0.44,context_tokens=4096,max_output_tokens=300)
        with patch('httpx.AsyncClient.post',recorder(
                {'text':'x','input_tokens':1,'output_tokens':1,'provider':'stub','model':'stub'})):
            await say(db,tokens=4096,purpose='test.gateway-body')
        body=seen['body']
        check('gateway body carries the tuned sampling values',
              (body['temperature'],body['top_p'],body['context_tokens'])==(1.7,0.44,4096))
        check('gateway body carries the capped output budget',body['max_tokens']==300)
        await SettingsService(db).set('intelligence.gateway_enabled',False,set_by='user')
        with patch('httpx.AsyncClient.post',recorder(
                {'message':{'content':'x'},'prompt_eval_count':1,'eval_count':1})):
            await say(db,tokens=4096,purpose='test.direct-body')
        check('the direct runtime fallback tunes the same request',
              seen['body']['options']=={'temperature':1.7,'top_p':0.44,'num_predict':300,'num_ctx':4096})


async def test_4_temperature():
    if not live():
        check('skipped — the local inference gateway is not answering',True);return
    await reset_db()
    async with async_session() as db:
        await tuned(db,temperature=0.0)
        # The first generation against a cold prompt cache is discarded. Measured
        # on the bare runtime with ARIES out of the picture: call 1 differs and
        # calls 2..6 are byte-identical, because llama.cpp's numerics depend on
        # the batch and KV-cache state it starts from. That is the runtime, not
        # the temperature, and a test that blamed the slider would be lying.
        await say(db)
        cold=[(await say(db))[0] for _ in range(2)]
        for i,t in enumerate(cold):show(f'temperature 0.0 #{i+1}',t[:110])
        check('temperature 0.0 repeats itself exactly on a warm slot',cold[0]==cold[1])
        await tuned(db,temperature=1.8)
        hot=[(await say(db))[0] for _ in range(4)]
        for i,t in enumerate(hot):show(f'temperature 1.8 #{i+1}',t[:110])
        check('temperature 1.8 diverges run to run',len(set(hot))>1)
        check('high temperature leaves the deterministic answer behind',cold[0] not in hot)


async def test_5_top_p():
    if not live():
        check('skipped — the local inference gateway is not answering',True);return
    await reset_db()
    async with async_session() as db:
        await tuned(db,temperature=1.8,top_p=1.0)
        wide=[(await say(db))[0] for _ in range(3)]
        await tuned(db,top_p=0.05)
        narrow=[(await say(db))[0] for _ in range(3)]
        for i,t in enumerate(wide):show(f'temp 1.8 top_p 1.00 #{i+1}',t[:110])
        for i,t in enumerate(narrow):show(f'temp 1.8 top_p 0.05 #{i+1}',t[:110])
        print(f'      distinct: wide={len(set(wide))}/3  narrow={len(set(narrow))}/3')
        check('a narrow nucleus reins in a high temperature',len(set(narrow))<len(set(wide)))
        check('top_p changes the answer at equal temperature',not set(narrow)&set(wide))


async def test_6_context_tokens():
    if not live():
        check('skipped — the local inference gateway is not answering',True);return
    await reset_db()
    def loaded():
        # The runtime reports the context window it actually allocated, which is
        # the only honest way to see a num_ctx arrive: the answer text does not
        # reveal it.
        return [m.get('context_length') for m in get(RUNTIME+'/api/ps').get('models',[])]
    async with async_session() as db:
        # Downward only. Raising num_ctx reloads the model with a larger KV cache
        # and this machine has no spare VRAM to lose a test to.
        await tuned(db,context_tokens=4096,temperature=0.0)
        await say(db,'Reply with the single word OK.',tokens=64)
        show('runtime context_length',loaded())
        check('the runtime allocates the configured context window',4096 in loaded())
        await tuned(db,context_tokens=8192)
        await say(db,'Reply with the single word OK.',tokens=64)
        show('runtime context_length',loaded())
        check('the default restores the previous window',8192 in loaded())


async def test_7_max_output_tokens():
    if not live():
        check('skipped — the local inference gateway is not answering',True);return
    await reset_db()
    long_prompt='List 60 cities, each on its own line with one sentence about it.'
    async with async_session() as db:
        # Direct runtime path: through the gateway the provider's ValueError is
        # masked as an opaque 503, and the point here is the exact failure.
        await SettingsService(db).set('intelligence.gateway_enabled',False,set_by='user')
        await tuned(db,temperature=0.0,max_output_tokens=4096)
        text,usage=await say(db,'Reply with the single word OK.',tokens=4096,purpose='measure.ceiling')
        show('answer inside the default ceiling',(text,usage['eval_count']))
        check('an answer inside the ceiling completes normally',usage['eval_count']<256)
        await tuned(db,max_output_tokens=256)
        try:
            text,usage=await say(db,long_prompt,tokens=4096,purpose='measure.ceiling')
            show('unexpected completion',(usage['eval_count'],text[-60:]))
            check('a 256 ceiling bounds an answer that wanted more',usage['eval_count']<=256)
        except ValueError as exc:
            show('ceiling outcome',f'{type(exc).__name__}: {exc}')
            check('exceeding the ceiling fails loudly rather than truncating silently',
                  str(exc)=='Model exhausted output budget')


async def test_8_structured_output_at_high_temperature():
    """Grammar-constrained decoding keeps the JSON valid; the CONTENT still moves."""
    if not live():
        check('skipped — the local inference gateway is not answering',True);return
    await reset_db()
    shape=Decision.model_json_schema()
    ask='compare four papers on retrieval augmented generation and synthesise the evidence'
    async with async_session() as db:
        await tuned(db,temperature=0.0,top_p=0.9,max_output_tokens=4096)
        base,_=await say(db,ask,tokens=450,shape=shape,purpose='measure.structured')
        show('temperature 0.0 decision',base[:110])
        check('a low temperature decision validates',_validates(base))
        await tuned(db,temperature=1.8)
        hot=[(await say(db,ask,tokens=450,shape=shape,purpose='measure.structured'))[0] for _ in range(3)]
        for i,t in enumerate(hot):show(f'temperature 1.8 decision #{i+1}',t[:110])
        valid=sum(_validates(t) for t in hot)
        parses=sum(_is_json(t) for t in hot)
        print(f'      at temperature 1.8: {parses}/3 parse as JSON, {valid}/3 satisfy the schema')
        check('the grammar keeps high-temperature output parseable',parses==3)
        check('the decision content itself moves',len(set(hot))>1 or base not in hot)
        # This is the real risk of a high temperature on a structured path: the
        # JSON stays well formed and the FIELDS go out of range.
        check('an out-of-range confidence is still refused, so routing fails closed',
              not _validates('{"intent":"CODING","confidence":95,"reason":"x"}'))
        if valid<len(hot):
            print('      NOTE: a high temperature degrades structured extraction — '
                  'the JSON parses and the values stop being usable.')


def _validates(raw):
    try:
        Decision.model_validate_json(raw);return True
    except Exception:return False


def _is_json(raw):
    try:
        json.loads(raw);return True
    except ValueError:return False


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
