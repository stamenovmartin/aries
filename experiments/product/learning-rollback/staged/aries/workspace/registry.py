"""M14 capability authority, built on workspace policy, tools and observations."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Literal
import asyncio
import hashlib
import json
import os
import re
from urllib.parse import quote, urlsplit
from pydantic import BaseModel, ConfigDict, Field


def now():
    return datetime.now(timezone.utc).isoformat()


from aries.workspace.capability_types import Input, Capability


class Empty(Input):
    pass


class FileInput(Input):
    path: str = Field(min_length=1, max_length=2048)


class WriteInput(FileInput):
    content: str = Field(min_length=1, max_length=50000)


class SearchInput(FileInput):
    query: str = Field(min_length=1, max_length=160)
    modified_after: str | None = Field(default=None, max_length=40)
    modified_before: str | None = Field(default=None, max_length=40)


class URLInput(Input):
    url: str = Field(min_length=1, max_length=2048)


class BrowserInput(Input):
    session: str = Field(min_length=1, max_length=80)


class WebSearchInput(Input):
    query: str = Field(min_length=1, max_length=400)
    site: Literal['web', 'youtube'] = 'web'


class AppInput(Input):
    app: str = Field(min_length=1, max_length=160)


class FocusInput(AppInput):
    window_id: str | None = Field(default=None, max_length=80)


class TaskInput(Input):
    task_id: str = Field(min_length=1, max_length=40)


class NoticeInput(Input):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1000)




class Registry:
    def __init__(self):
        self._items = {}

    def register(self, capability):
        if capability.name in self._items:
            raise ValueError('Duplicate capability: ' + capability.name)
        self._items[capability.name] = capability

    def get(self, name):
        if name not in self._items:
            raise ValueError('Unknown capability: ' + str(name))
        return self._items[name]

    def validate(self, name, arguments):
        return self.get(name).input_model.model_validate(arguments).model_dump()

    def describe_allowed(self):
        return [c.describe() for c in self._items.values()]


registry = Registry()


def interactive_origin(origin):
    return isinstance(origin,str) and origin in {'user','voice','chat','shell','ui'}


async def policy(db, cap, args, goal, *, approved=False, origin=None):
    from aries.workspace.scopes import enforce
    enforce(cap,args)
    from aries.workspace.capabilities import checked_path
    from aries.settings import SettingsService
    if cap.effect != 'read' and not await SettingsService(db).get('operator.enabled'):
        raise PermissionError('Operator actions are disabled')
    # An unattended or legacy unattributed goal cannot borrow the interactive
    # user's relaxed confirmation setting. Only an explicit frozen-step review
    # can authorize its mutation. Origin is persisted by submission code, not
    # accepted from model decisions.
    if cap.effect != 'read' and not approved and not interactive_origin(origin):
        return False
    if cap.effect == 'create' and not re.search(r'\b(create|write|save|make|создај|зачувај|напиши|направи)\b', goal, re.I):
        raise PermissionError('The user goal did not request file creation')
    if cap.effect == 'create':
        from aries.workspace.contracts import compile_goal
        contract = compile_goal(goal, str(Path(await SettingsService(db).get('workspace.agent_demo_directory')).expanduser()))
        writes = [r for r in contract['requirements'] if r['capability']=='file.write']
        if contract['supported']:
            requested = next((r for r in writes if Path(r['path']).absolute()==Path(args['path']).expanduser().absolute()), None)
            if requested is None or hashlib.sha256(args['content'].encode()).hexdigest() != requested['content_sha256']:
                raise PermissionError('Proposed write does not match the user-requested path and content')
        elif not approved:
            # A model interpretation cannot authorize a destination/content that
            # the deterministic user-goal parser cannot bind. Freeze for review.
            return False
    if 'path' in args:
        await checked_path(db, args['path'], write=cap.effect == 'create')
    if 'url' in args:
        from aries.workspace.service import safe_link
        if not safe_link(args['url']):
            raise PermissionError('Only public HTTP(S) navigation is supported')
    if cap.requires_approval and not approved:
        return False
    if cap.effect != 'read' and not approved and await SettingsService(db).get('operator.confirm_model_plans'):
        return False
    return True


async def path_for(ctx, raw, write=False):
    from aries.workspace.capabilities import checked_path
    return await checked_path(ctx['db'], raw, write=write)


def file_snapshot(path, include_text=True):
    # No FIFO/device reads, bounded bytes, no final symlink following.
    import stat
    from aries.workspace.filesystem import open_nofollow
    fd = open_nofollow(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size > 100000:
            raise ValueError('Only regular files up to 100 KB may be read')
        data = stream.read(100001)
        if len(data) > 100000:
            raise ValueError('File exceeded 100 KB')
    result = dict(path=str(path), size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                  inode=st.st_ino, observed_at=now())
    if include_text:
        result['text'] = data.decode('utf-8')
    return result


async def read_file(args, ctx):
    return await asyncio.to_thread(file_snapshot, await path_for(ctx, args['path']))


async def verify_read(args, result, ctx):
    fresh = await read_file(args, ctx)
    return dict(met=fresh['sha256'] == result.get('sha256') and fresh['path'] == result.get('path'),
                type='file_state', data=fresh)


async def write_file(args, ctx):
    # Reuse the registered tool's exclusive create, permission/rate gates and audit.
    from aries.workspace import capabilities
    step = {'kind':'capability', 'capability':'create_file', 'args':args,
            'request':ctx['goal'], 'goal_id':ctx['task_id']}
    step = await capabilities.prepare(ctx['db'], step)
    result = await capabilities.execute(ctx['db'], step)
    if result['state'] != 'done':
        raise RuntimeError(result.get('summary', 'File creation refused'))
    return {'path':step['args']['path'], 'write_call_completed':True}


async def verify_write(args, result, ctx):
    fresh = await read_file({'path':args['path']}, ctx)
    expected = args['content'].encode('utf-8')
    return dict(met=fresh['size'] > 0 and fresh['sha256'] == hashlib.sha256(expected).hexdigest(), type='file_state', data=fresh)


async def exists(args, ctx):
    p = await path_for(ctx, args['path'])
    return {'path':str(p), 'exists':p.exists(), 'is_file':p.is_file(), 'observed_at':now()}


async def verify_exists(args, result, ctx):
    fresh = await exists(args, ctx)
    return {'met':fresh['exists'] == result.get('exists'), 'type':'file_state', 'data':fresh}


async def listing(args, ctx):
    p = await path_for(ctx, args['path'])
    entries = []
    truncated = False
    with os.scandir(p) as stream:
        for index, entry in enumerate(stream):
            if index >= 200:
                truncated = True
                break
            try:
                checked = await path_for(ctx, entry.path)
                entries.append({'name':entry.name, 'path':str(checked), 'directory':entry.is_dir(follow_symlinks=False)})
            except ValueError:
                continue
    return {'path':str(p), 'entries':entries, 'count':len(entries), 'count_is_lower_bound':truncated,
            'truncated':truncated, 'observed_at':now()}


async def search(args, ctx):
    root = await path_for(ctx, args['path'])
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    bounds = [datetime.fromisoformat(args[k]).timestamp() if args.get(k) else None
              for k in ('modified_after', 'modified_before')]
    results, scanned, truncated = [], 0, False
    # Finite filesystem enumeration. Prune excluded/hidden/symlink directories.
    for directory, dirs, names in os.walk(root, followlinks=False):
        valid = []
        for name in dirs[:200]:
            p = Path(directory)/name
            if name.startswith('.') or p.is_symlink():
                continue
            try:
                await path_for(ctx, str(p))
                valid.append(name)
            except ValueError:
                pass
        dirs[:] = valid
        for name in names:
            scanned += 1
            if scanned > 5000 or len(results) >= 100:
                truncated = True
                break
            if args['query'].casefold() not in name.casefold():
                continue
            try:
                p = await path_for(ctx, str(Path(directory)/name))
                st = p.stat()
                if not p.is_file() or (bounds[0] is not None and st.st_mtime < bounds[0]) or (bounds[1] is not None and st.st_mtime >= bounds[1]):
                    continue
                results.append({'path':str(p), 'size':st.st_size, 'modified_at':datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
            except (OSError, ValueError):
                continue
        if truncated:
            break
    return {'root':str(root), 'matches':results, 'count':len(results), 'scanned':scanned,
            'truncated':truncated, 'observed_at':now()}


def verify_probe(executor, evidence_type):
    async def verify(args, result, ctx):
        from aries.workspace.probe_verification import agrees
        fresh = await executor(args, ctx)
        mode='fresh_observation' if evidence_type in {'system_probe','storage_probe','process_probe'} else 'snapshot_agreement'
        return {'met':agrees(evidence_type,args,result,fresh), 'type':evidence_type, 'data':fresh,
                'verification_mode':mode}
    return verify


async def browser_open(args, ctx):
    from aries.workspace import capabilities
    step = dict(kind='capability', capability='browser_open', args=args, request=ctx['goal'], goal_id=ctx['task_id'])
    result = await capabilities.execute(ctx['db'], step)
    if result['state'] != 'done':
        raise RuntimeError(result.get('summary', 'Browser navigation failed'))
    return result['browser']


async def browser_read(args, ctx):
    from aries.workspace import browser
    inventory = await browser.inventory()
    if not any(r['session'] == args['session'] and r.get('owner') == ctx['task_id'] for r in inventory):
        raise PermissionError('Only browser sessions owned by this task may be inspected')
    return await browser.observe(args['session'])


async def verify_browser(args, result, ctx):
    fresh = await browser_read({'session':result.get('session') or args.get('session', '')}, ctx)
    # The pinned transport already checked response status, redirects and public IPs.
    # Reobserve URL/title through the browser, not model/executor prose.
    met = bool(fresh.get('title') and fresh.get('url') and fresh['url'] == result.get('url'))
    if 'query' in args:
        from urllib.parse import parse_qs
        parsed = urlsplit(fresh.get('url',''))
        youtube = args.get('site') == 'youtube'
        met = met and parsed.hostname == ('www.youtube.com' if youtube else 'duckduckgo.com') and (not youtube or parsed.path == '/results') and parse_qs(parsed.query).get('search_query' if youtube else 'q') == [args['query']]
    return {'met':met, 'type':'browser_state', 'data':{**fresh, 'transport':'ARIES pinned GET / Playwright DOM', 'observed_at':now()}}


async def browser_search(args, ctx):
    url = ('https://www.youtube.com/results?search_query=' if args['site'] == 'youtube' else 'https://duckduckgo.com/?q=') + quote(args['query'])
    return await browser_open({'url':url}, ctx)


async def storage(args, ctx):
    from aries.health.probes import probe_disk
    probe = await probe_disk()
    rows = [r.as_dict() for r in probe.readings if r.value is not None]
    if not probe.ok or not rows:
        raise RuntimeError('No filesystem storage observations available')
    return {'probe':'statvfs', 'filesystems':rows, 'highest':max(rows, key=lambda r:r['value']), 'observed_at':now()}


async def status(args, ctx):
    from aries.health.probes import run_all
    probes = await run_all(['cpu','memory','disk'])
    result = [p.as_dict() for p in probes]
    if not any(p.ok for p in probes):
        raise RuntimeError('System probes unavailable')
    return {'probes':result, 'observed_at':now()}


async def processes(args, ctx):
    from aries.operator.desktop import read_processes
    rows = await asyncio.to_thread(read_processes)
    return {'count':len(rows), 'processes':[{'pid':p.pid,'name':p.name} for p in rows[:100]],
            'truncated':len(rows)>100, 'observed_at':now()}


async def desktop_launch(args, ctx):
    from aries.operator.service import _arm
    from aries.settings import SettingsService
    from agentic_core.tools.calling import call_tool
    settings = SettingsService(ctx['db'])
    _arm(True,max_actions_per_hour=await settings.get('operator.max_actions_per_hour'))
    # Exact tool dispatch: never reroute free-form app text through another model.
    result = await call_tool(ctx['db'],'desktop.open_app',args,actor='workspace:m14')
    if not result.get('success') or result.get('dry_run') or result.get('skipped'):
        raise RuntimeError(result.get('details', 'Application launch not confirmed'))
    return {'launch_requested':True, 'app':args['app']}


async def desktop_focus(args, ctx):
    from aries.operator import desktop, tools
    windows, why, _ = await asyncio.to_thread(desktop.read_windows)
    identity = tools._desktop_file(args['app'])
    matches = [w for w in windows or [] if identity and w.app_id == identity]
    if args.get('window_id'):
        matches = [w for w in matches if w.id == args['window_id']]
    if len(matches)>1:
        raise ValueError('AMBIGUOUS: multiple application windows; choose an observed window_id')
    if not matches:
        raise ValueError('No observed window for this installed application: '+why)
    ok, why = await asyncio.to_thread(desktop.focus_window, matches[0])
    if not ok:
        raise RuntimeError(why)
    return {'app':args['app'], 'window_id':matches[0].id, 'app_id':matches[0].app_id, 'focus_requested':True}


async def verify_focus(args, result, ctx):
    from aries.workspace.desktop_capabilities import verifier
    return await verifier('focus')({'window_id':result['window_id'],'app_id':result['app_id']},result,ctx)


async def verify_desktop(args, result, ctx):
    from aries.operator.service import _watch
    from aries.settings import SettingsService
    verdict, _ = await _watch('open_app',args,ctx['db'],seconds=await SettingsService(ctx['db']).get('operator.settle_seconds'))
    data = verdict.as_dict()
    # Process command lines may contain private arguments; window identity suffices.
    for process in data.get('evidence', {}).get('processes', []):
        process.pop('cmdline', None)
    return {'met':verdict.met, 'type':'desktop_state', 'data':data}


async def inspect_task(args, ctx):
    from aries.workspace.models import WorkspaceGoal
    row = await ctx['db'].get(WorkspaceGoal, args['task_id'], populate_existing=True)
    if row is None:
        raise LookupError('Task not found')
    data = json.loads(row.result_json)
    return {'task_id':row.id, 'state':row.state, 'steps':len(data.get('steps', [])),
            'evidence_ids':[e['evidence_id'] for e in data.get('evidence', [])], 'observed_at':now()}


async def notification(args, ctx):
    from aries.notify import emit
    from aries.health.findings import Severity
    _, row = await emit(ctx['db'], key='m14:'+ctx['task_id'], title=args['title'],
                     severity=Severity.NOTICE, source='workspace', body=args['body'])
    await ctx['db'].commit()
    return {'notification_id':row.id}


async def verify_notification(args, result, ctx):
    from aries.notify import AriesNotification
    row = await ctx['db'].get(AriesNotification, result['notification_id'], populate_existing=True)
    return {'met':bool(row and row.title == args['title'] and row.body == args['body'] and row.key == 'm14:'+ctx['task_id']), 'type':'notification_record',
            'data':{'notification_id':result['notification_id'], 'scope':'persisted notification; not proof the user saw it', 'observed_at':now()}}


for cap in [
    Capability('file.read','Read a regular UTF-8 text file up to 100 KB', FileInput, read_file, verify_read),
    Capability('file.write','Create a NEW nonempty text file; never overwrite. Parent must exist.', WriteInput, write_file, verify_write, effect='create'),
    Capability('file.list','List at most 200 allowed directory entries', FileInput, listing, verify_probe(listing,'directory_state')),
    Capability('file.search','Search filenames under a directory, optionally within an ISO modification-time range', SearchInput, search, verify_probe(search,'file_search'), timeout_seconds=30),
    Capability('file.exists','Check existence only when asked about existence. For read goals use file.read directly, which reports missing-path errors.', FileInput, exists, verify_exists),
    Capability('browser.open','Open a public URL in a task-owned browser and observe navigation', URLInput, browser_open, verify_browser, timeout_seconds=100, effect='open'),
    Capability('browser.read','Read a task-owned browser session using its observed session ID', BrowserInput, browser_read, verify_browser),
    Capability('browser.search','Open public web or YouTube search for a literal query', WebSearchInput, browser_search, verify_browser, timeout_seconds=100, effect='open'),
    Capability('desktop.launch','Open an installed application by name; verify visible focused window', AppInput, desktop_launch, verify_desktop, effect='open', timeout_seconds=60),
    Capability('desktop.focus','Focus an already observed installed app; never launch a replacement', FocusInput, desktop_focus, verify_focus, effect='open'),
    Capability('system.status','Observe current CPU, memory and disk probes', Empty, status, verify_probe(status,'system_probe')),
    Capability('system.storage','Measure filesystem usage; highest is computed from measured percentages', Empty, storage, verify_probe(storage,'storage_probe')),
    Capability('system.processes','Observe bounded process names and IDs; no command lines', Empty, processes, verify_probe(processes,'process_probe')),
    Capability('task.inspect','Inspect a persisted task by ID', TaskInput, inspect_task, verify_probe(inspect_task,'task_state')),
    Capability('notification.send','Create a policy-controlled notification record; approval required', NoticeInput, notification, verify_notification, requires_approval=True, effect='notify'),
]:
    registry.register(cap)

# Capability implementations extend the authority without modifying the planner.
from aries.workspace.desktop_capabilities import register as register_desktop
register_desktop(registry)
from aries.workspace.browser_capabilities import register as register_browser
register_browser(registry)
from aries.workspace.file_capabilities import register as register_files
register_files(registry)
# Registered on the user's explicit say-so, 2026-09-29, after they had first
# declined the prompt and then asked for it. Worth knowing before touching it:
# clipboard_write and type_text both require approval, type_text refuses anything
# that is not still editable, focused and not a password field, and typing goes
# through AT-SPI rather than keystroke synthesis because Mutter SILENTLY DROPS
# Cyrillic it cannot map to the active layout. clipboard_read is the one that is
# ungated, and it can return a password — its own description says never to call
# it for context.
from aries.workspace.network_capabilities import register as register_network
register_network(registry)
from aries.workspace.screen_capabilities import register as register_screen
register_screen(registry)
from aries.workspace.system_capabilities import register as register_system
register_system(registry)
from aries.workspace.input_capabilities import register as register_input
register_input(registry)
