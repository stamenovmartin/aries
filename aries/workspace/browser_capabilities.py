"""M15 adapters retain task ownership and the pinned public-browser transport."""
from pydantic import Field
from aries.workspace.capability_types import Input, Capability

class Session(Input):
    session: str = Field(min_length=1,max_length=80)
class Empty(Input): pass
class Navigate(Session):
    url: str = Field(min_length=1,max_length=2048)
class Click(Session):
    element_id: str = Field(min_length=1,max_length=80)
    expected_url: str = Field(min_length=1,max_length=2048)
class Type(Session):
    element_id: str = Field(min_length=1,max_length=80)
    value: str = Field(max_length=2000)
class Scroll(Session):
    pixels: int = Field(ge=-4000,le=4000)
class Wait(Session):
    milliseconds: int = Field(ge=0,le=10000)

async def owned(args,ctx):
    from aries.workspace import browser
    if not any(r['session']==args['session'] and r.get('owner')==ctx['task_id'] for r in await browser.inventory()):
        raise PermissionError('Only this task owns the requested browser session')

async def tabs(args,ctx):
    from aries.workspace import browser
    return {'tabs':[r for r in await browser.inventory() if r.get('owner')==ctx['task_id']]}

async def verify_tabs(args,result,ctx):
    return {'met':True,'type':'browser_inventory','data':await tabs(args,ctx)}

def operation(method, keys=(), suffix=()):
    async def execute(args,ctx):
        from aries.workspace import browser
        await owned(args,ctx)
        return await getattr(browser,method)(args['session'],*(str(args[k]) for k in keys),*suffix)
    return execute

async def verify_state(args,result,ctx):
    from aries.workspace.registry import browser_read
    fresh=await browser_read({'session':args['session']},ctx)
    expected=args.get('expected_url',args.get('url',result.get('url')))
    return {'met':bool(fresh.get('title')) and fresh.get('url')==expected,'type':'browser_state','data':fresh}

async def verify_elements(args,result,ctx):
    # Do not invalidate handles in the verifier by producing a new enumeration.
    from aries.workspace.registry import browser_read
    fresh=await browser_read(args,ctx)
    return {'met':fresh['url']==result['url'],'type':'browser_elements','data':{**result,'observed_page':fresh}}

async def verify_type(args,result,ctx):
    from aries.workspace import browser
    await owned(args,ctx)
    fresh=await browser.element_value(args['session'],args['element_id'])
    return {'met':fresh['observed_value']==args['value'],'type':'browser_field','data':fresh}

async def verify_scroll(args,result,ctx):
    from aries.workspace.registry import browser_read
    fresh=await browser_read({'session':args['session']},ctx)
    return {'met':fresh['url']==result['url'] and fresh['scroll']==result['scroll'],'type':'browser_viewport','data':fresh}

def register(registry):
    registry.register(Capability('browser.tabs','List only browser tabs owned by this task',Empty,tabs,verify_tabs))
    for name,schema,executor,verifier in [
        ('observe',Session,operation('observe'),verify_state),
        ('elements',Session,operation('elements'),verify_elements),
        ('navigate',Navigate,operation('navigate_page',('url',)),verify_state),
        ('click',Click,operation('click_element',('element_id',)),verify_state),
        ('type',Type,operation('type_element',('element_id','value')),verify_type),
        ('scroll',Scroll,operation('scroll_page',('pixels',)),verify_scroll),
        ('back',Session,operation('history_page',suffix=('back',)),verify_state),
        ('forward',Session,operation('history_page',suffix=('forward',)),verify_state),
        ('wait',Wait,operation('wait_page',('milliseconds',)),verify_state),
    ]:
        registry.register(Capability('browser.'+name,'Task-owned public browser '+name+'; observe again after action. No credentials or POST.',schema,executor,verifier,timeout_seconds=100,effect='read' if name in {'observe','elements','wait'} else 'open'))

class Download(Navigate):
    path: str = Field(min_length=1,max_length=2048)

async def download(args,ctx):
    import asyncio
    import hashlib
    import os
    from aries.workspace.registry import browser_read
    from aries.workspace.file_capabilities import path_for
    from aries.workspace.filesystem import open_nofollow
    from aries.news.fetch import fetch
    state=await browser_read({'session':args['session']},ctx)
    known={state['url'],*(link['url'] for link in state.get('links',[]))}
    if args['url'] not in known:raise ValueError('TARGET_NOT_FOUND: download URL must first be observed on this task page')
    destination=await path_for(ctx,args['path'],True)
    result=await fetch(args['url'],max_bytes=20_000_000,timeout=30,accept='*/*')
    if not result.ok or result.truncated or not result.body:raise ValueError('NETWORK_ERROR: download is incomplete or empty')
    def write():
        with os.fdopen(open_nofollow(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL),'wb') as f:
            f.write(result.body);f.flush();os.fsync(f.fileno())
    await asyncio.to_thread(write)
    return {'path':str(destination),'url':result.url,'requested_url':args['url'],'source_page':state['url'],'sha256':hashlib.sha256(result.body).hexdigest(),'size':len(result.body)}

async def verify_download(args,result,ctx):
    from aries.workspace.file_capabilities import metadata
    fresh=await metadata({'path':args['path']},ctx)
    return {'met':fresh['sha256']==result['sha256'] and fresh['size']==result['size'],'type':'downloaded_file','data':{**fresh,'source_url':result['url'],'source_page':result['source_page']}}

_register_browser=register

def register(registry):
    _register_browser(registry)
    registry.register(Capability('browser.download','Download an observed public link into a NEW reviewed local path; pinned GET, 20 MB maximum',Download,download,verify_download,effect='file_mutation',requires_approval=True,timeout_seconds=60))
