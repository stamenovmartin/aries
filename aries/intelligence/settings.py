from aries.settings.schema import SettingDef,define
from aries.intelligence.providers import loopback_url

def add(key,kind,default,description,**kw):
    define(SettingDef('intelligence.'+key,kind,default,key.replace('_',' ').title(),description,'intelligence',user_only=True,**kw))
add('router_enabled',bool,True,'Route workspace goals through rules, local decisions and explicit cloud policy.',control='toggle')
add('local_backend',str,'ollama','Runtime adapter; OpenAI-compatible supports llama.cpp/vLLM.',choices=['ollama','openai-compatible'])
add('gateway_url',str,'http://127.0.0.1:11435','Persistent local inference gateway.',validator=loopback_url)
add('gateway_enabled',bool,True,'Use the persistent local gateway; direct local fallback on gateway outage only.',control='toggle')
add('keep_alive',str,'15m','Local runtime model residency between requests; service stays alive independently.')
add('local_confidence_threshold',float,0.82,'Below this confidence recommend cloud; policy still controls network access.',minimum=0,maximum=1,control='number')
add('cloud_enabled',bool,False,'Explicit opt-in to send foreground tasks/context to configured cloud endpoint.',control='toggle')
add('cloud_provider',str,'claude-cli','Terminal cloud provider using existing CLI login, or explicitly selected HTTP adapter.',choices=['claude-cli','codex-cli','openai-compatible'])
add('cloud_cli_timeout_seconds',int,180,'Hard deadline for one CLI invocation.',minimum=10,maximum=600,control='number')
add('cloud_model',str,'','Optional CLI model override; empty uses CLI default. HTTP adapter requires a model.')
add('cloud_url',str,'https://api.openai.com/v1','Explicit cloud endpoint; API key only from ARIES_CLOUD_API_KEY environment.')
add('cloud_input_usd_per_million',float,0.0,'Configured price estimate; zero means unknown, not free.',minimum=0,control='number')
add('cloud_output_usd_per_million',float,0.0,'Configured price estimate; zero means unknown, not free.',minimum=0,control='number')
add('cloud_local_fallback',bool,True,'If cloud is unavailable, use local inference and record degradation.',control='toggle')
