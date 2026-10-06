"""Runtime adapters. No tool execution, remote defaults or implicit retries."""
import ipaddress
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit
import httpx


def loopback_url(url):
    p = urlsplit(url)
    try:
        local = ipaddress.ip_address(p.hostname or '').is_loopback
    except ValueError:
        local = False  # literal addresses only: no DNS rebinding or proxy surprises
    if p.scheme != 'http' or not local or p.username or p.password or p.query or p.fragment:
        raise ValueError('Local inference requires an HTTP literal loopback URL')
    return url.rstrip('/')

@dataclass
class Generation:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider: str = ''
    model: str = ''
    usage_details: dict | None = None
    reported_cost_usd: float | None = None

class ModelProvider(Protocol):
    async def generate(self, messages, schema, max_tokens=2048, *, temperature=None,
                       top_p=None, context_tokens=None) -> Generation: ...
    async def health(self) -> dict: ...

class OllamaProvider:
    def __init__(self, url, model, keep_alive='15m'):
        self.url, self.model, self.keep_alive = loopback_url(url), model, keep_alive
    async def health(self):
        async with httpx.AsyncClient(timeout=3, trust_env=False) as c:
            r=await c.get(self.url+'/api/tags'); r.raise_for_status()
            names=[m['name'] for m in r.json().get('models',[])]
        return {'reachable':True,'model_available':self.model in names,'models':names}
    async def generate(self, messages, schema, max_tokens=2048, *, temperature=0.1,
                       top_p=0.9, context_tokens=8192):
        # The keyword defaults are the literals this adapter hardcoded before the
        # settings existed (top_p 0.9 is also the runtime's own default), so a
        # caller that threads nothing still gets exactly the previous behaviour.
        async with httpx.AsyncClient(timeout=180, trust_env=False) as c:
            r=await c.post(self.url+'/api/chat',json={'model':self.model,'messages':messages,
                'stream':False,'format':schema or '', 'keep_alive':self.keep_alive,
                'options':{'temperature':temperature,'top_p':top_p,
                           'num_predict':max_tokens,'num_ctx':context_tokens}})
            r.raise_for_status();d=r.json()
        if d.get('done_reason')=='length':raise ValueError('Model exhausted output budget')
        return Generation(d['message']['content'],d.get('prompt_eval_count'),d.get('eval_count'),'ollama',self.model)

class OpenAICompatibleProvider:
    """Local llama.cpp/vLLM or explicit HTTPS cloud. Uses the existing engine protocol."""
    def __init__(self,url,model,key='',*,local=True):
        if local:url=loopback_url(url)
        elif urlsplit(url).scheme!='https' or urlsplit(url).username or urlsplit(url).password:
            raise ValueError('Cloud endpoint requires HTTPS without URL credentials')
        self.url,self.model,self.key,self.local=url.rstrip('/'),model,key,local
    async def health(self):
        async with httpx.AsyncClient(timeout=3,trust_env=False) as c:
            r=await c.get(self.url+'/models',headers=self.headers());r.raise_for_status()
        return {'reachable':True,'model_available':any(m.get('id')==self.model for m in r.json().get('data',[]))}
    def headers(self):return {'Authorization':'Bearer '+self.key} if self.key else {}
    async def generate(self,messages,schema,max_tokens=2048,*,temperature=None,
                       top_p=None,context_tokens=None):
        payload={'model':self.model,'messages':messages,'max_tokens':max_tokens}
        # Sent only when asked for: this class is also the cloud adapter, and a
        # local sampling preference must not silently retune a cloud model.
        # context_tokens is accepted and ignored — llama.cpp/vLLM fix the context
        # window when the server starts; no request field can change it.
        if temperature is not None:payload['temperature']=temperature
        if top_p is not None:payload['top_p']=top_p
        if schema:payload['response_format']={'type':'json_schema','json_schema':{'name':'aries_decision','schema':schema}}
        async with httpx.AsyncClient(timeout=180,trust_env=False) as c:
            r=await c.post(self.url+'/chat/completions',headers=self.headers(),json=payload)
            r.raise_for_status();d=r.json()
        if d['choices'][0].get('finish_reason')=='length':raise ValueError('Model exhausted output budget')
        u=d.get('usage',{})
        return Generation(d['choices'][0]['message']['content'],u.get('prompt_tokens'),u.get('completion_tokens'),
                          'local-openai-compatible' if self.local else 'openai-compatible',self.model)

BACKENDS={'ollama':OllamaProvider,'openai-compatible':OpenAICompatibleProvider}

def local_provider(backend,url,model,keep_alive='15m'):
    if backend not in BACKENDS:raise ValueError('Unknown local inference backend')
    return OllamaProvider(url,model,keep_alive) if backend=='ollama' else BACKENDS[backend](url,model)


def local_status(backend,url,model):
    """Synchronous status adapter for the existing desktop status endpoint."""
    url=loopback_url(url)
    if backend not in BACKENDS:raise ValueError('Unknown local inference backend')
    path='/api/tags' if backend=='ollama' else '/models'
    with httpx.Client(timeout=3,trust_env=False) as c:
        r=c.get(url+path);r.raise_for_status();data=r.json()
    names=[m.get('name','') for m in data.get('models',[])] if backend=='ollama' else [m.get('id','') for m in data.get('data',[])]
    return {'reachable':True,'models':names,'has_model':model in names if model else bool(names),'detail':f'{len(names)} model(s) available'}
