#!/usr/bin/env python3
"""H8 mutant runner (docs/preregistration/H8-verifier-fault-injection.md, registered at 0731857).

For every mutant in a manifest, and for every clean replay, one fresh fake world is built, the capability's
executor runs (honestly, or mutated as the operator says), and then the UNCHANGED verifier of the frozen
registry runs. The verdict is recorded (primary: killed = verdict not met), plus whether a false value
reached the verification evidence (secondary).

Never touches the live system:
- file capabilities use real files in a fresh temporary folder under the home directory;
  notification.send and task.inspect use a fresh test SQLite database (APP_ENV=test);
- system.status, system.storage, system.disk and system.processes read the real machine read-only;
- every other collaborator is replaced in its module's namespace by a fake that reads and writes the
  fake world (the stub table is FAKES below);
- a tripwire makes any attempt to start gdbus, nmcli, systemctl, busctl, wl-copy, wl-paste, xdotool,
  ydotool, gnome-screenshot, tesseract, playwright or a browser raise immediately (TRIPWIRE);
- one process, address space capped at 3 GiB (RLIMIT_AS), no model, no network.

The mutation replaces only the executor the harness calls. Verifiers call the original functions, and a
counter on the mutated entry proves it: a mutant whose verifier called the mutated entry is reported as
invalid.

    .venv/bin/python experiments/thesis-followup-20261012/h8/run_mutants.py --selftest
    .venv/bin/python experiments/thesis-followup-20261012/h8/run_mutants.py --manifest h8/mutants.json --label baseline
    .venv/bin/python experiments/thesis-followup-20261012/h8/run_mutants.py --manifest h8/mutants.json --label hardened --hardened
    (--sealed instead of --manifest runs h8/sealed/mutants-sealed.json after checking its SHA-256)

--selftest runs only the honest executors and checks the fake world directly; it never calls a verifier.
--smoke runs the clean replays of file.read and file.write only (the registered smoke test).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import random
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCRATCH = Path(tempfile.mkdtemp(prefix='aries-h8-'))
os.environ.update(APP_ENV='test', DATABASE_URL=f'sqlite+aiosqlite:///{SCRATCH}/h8.db', DATA_DIR=str(SCRATCH),
                  RUNTIME_STORE=f'{SCRATCH}/runtime.json', CONTEXT_DIR=f'{SCRATCH}/context', AI_PROVIDER='template',
                  DRY_RUN='true', LIVE_TOOLS='', API_KEY='', ARIES_FLAG_FILE=f'{SCRATCH}/flags.env')
os.environ.pop('CREDENTIALS_KEY', None)
for p in (ROOT / 'vendor/agentic-core', ROOT / 'vendor', ROOT):
    sys.path.insert(0, str(p))
resource.setrlimit(resource.RLIMIT_AS, (3 << 30, 3 << 30))

# ───────────────────────────────────────────────────────────── tripwire
TRIPWIRE = {'gdbus', 'nmcli', 'systemctl', 'busctl', 'wl-copy', 'wl-paste', 'xdotool', 'ydotool', 'gnome-screenshot',
            'tesseract', 'playwright', 'chromium', 'chromium-browser', 'google-chrome', 'firefox', 'notify-send',
            'dbus-send', 'gsettings', 'brightnessctl', 'snap', 'dpkg-query', 'gtk-launch', 'xdg-open'}


class TripwireError(RuntimeError):
    pass


def _check(argv):
    name = os.path.basename(str((argv[0] if isinstance(argv, (list, tuple)) else str(argv).split()[0])))
    if name in TRIPWIRE:
        raise TripwireError(f'H8 tripwire: refused to start {name!r} (the harness never touches the live system)')


import subprocess as _subprocess                                          # noqa: E402
_real_run, _real_popen = _subprocess.run, _subprocess.Popen


def _guarded_run(argv, *a, **k):
    _check(argv)
    return _real_run(argv, *a, **k)


class _GuardedPopen(_real_popen):
    def __init__(self, argv, *a, **k):
        _check(argv)
        super().__init__(argv, *a, **k)


_subprocess.run, _subprocess.Popen = _guarded_run, _GuardedPopen
_real_exec = asyncio.create_subprocess_exec


async def _guarded_exec(*argv, **k):
    _check(list(argv))
    return await _real_exec(*argv, **k)


asyncio.create_subprocess_exec = _guarded_exec

# No network at all: every name lookup and outgoing connection raises.
import socket as _socket                                                   # noqa: E402


def _no_network(*a, **k):
    raise TripwireError('H8 tripwire: network access refused (the harness is offline by design)')


_socket.getaddrinfo = _no_network
_socket.create_connection = _no_network
_real_connect = _socket.socket.connect


def _guarded_connect(self, address):
    if self.family in (_socket.AF_INET, _socket.AF_INET6):
        _no_network()
    return _real_connect(self, address)


_socket.socket.connect = _guarded_connect

# ───────────────────────────────────────────────────────────── the fake world
W = {'cur': None}            # the world the fakes read and write; swapped for twin runs


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def sha(text):
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


APP = 'org.gnome.Calculator'
APP_ID = 'org.gnome.Calculator.desktop'


def new_state():
    return {
        'windows': [
            {'id': '101', 'title': 'Calculator', 'wm_class': 'gnome-calculator', 'app_id': APP_ID, 'pid': 4101,
             'focused': True, 'workspace': 0, 'minimised': False, 'maximized': False,
             'geometry': {'x': 100, 'y': 100, 'width': 640, 'height': 480}, 'monitor': 0,
             'work_area': {'x': 0, 'y': 32, 'width': 1920, 'height': 1048}},
            {'id': '102', 'title': 'Files', 'wm_class': 'org.gnome.Nautilus', 'app_id': 'org.gnome.Nautilus.desktop',
             'pid': 4102, 'focused': False, 'workspace': 0, 'minimised': False, 'maximized': False,
             'geometry': {'x': 800, 'y': 200, 'width': 900, 'height': 600}, 'monitor': 0,
             'work_area': {'x': 0, 'y': 32, 'width': 1920, 'height': 1048}}],
        'processes': [{'pid': 4101, 'name': 'gnome-calculator', 'cmdline': 'gnome-calculator'},
                      {'pid': 4102, 'name': 'nautilus', 'cmdline': 'nautilus'}],
        'launchable': {APP: {'title': 'Calculator', 'wm_class': 'gnome-calculator', 'app_id': APP_ID,
                             'process': 'gnome-calculator'}},
        'sites': {f'https://site{i}.example/': {'title': f'Site {i}', 'text': f'Page {i} body',
                                               'links': [{'name': f'Next {i}', 'url': f'https://site{i + 1}.example/'},
                                                         {'name': 'File', 'url': f'https://site{i}.example/file.bin'}]}
                  for i in range(1, 6)},
        'downloads': {f'https://site{i}.example/file.bin': f'binary payload {i}' for i in range(1, 6)},
        'sessions': {},
        'clipboard': 'previous clipboard text',
        'nodes': {'0/1': 'first field text', '0/2': 'second field text'},
        'screen': {'frames': {}, 'text': 'Calculator Files window titles visible'},
        'network': {'internet_reachable': True, 'link_up': True,
                    'profiles': {'uuid-home': {'name': 'HomeNet', 'state': 'activated'},
                                 'uuid-office': {'name': 'OfficeNet', 'state': 'deactivated'},
                                 'uuid-cafe': {'name': 'CafeNet', 'state': 'deactivated'}},
                    'visible': [{'ssid': 'HomeNet', 'signal': 80, 'saved': True},
                                {'ssid': 'OfficeNet', 'signal': 60, 'saved': True},
                                {'ssid': 'Neighbour', 'signal': 40, 'saved': False}]},
        'brightness': 60,
        'units': {u: {'LoadState': 'loaded', 'ActiveState': 'active', 'SubState': 'running',
                      'InvocationID': sha(u)[:32], 'Description': u}
                  for u in ('aries-voice.service', 'mpris-proxy.service', 'ollama.service')},
        'packages': {'bash': '5.2-1', 'coreutils': '9.4-1'},
    }


class World:
    def __init__(self, sandbox=None, state=None):
        self.sandbox = Path(sandbox or tempfile.mkdtemp(prefix='aries-h8-', dir=Path.home()))
        self.state = state if state is not None else new_state()

    def twin(self):
        t = World(tempfile.mkdtemp(prefix='aries-h8-twin-', dir=Path.home()), copy.deepcopy(self.state))
        shutil.rmtree(t.sandbox)
        shutil.copytree(self.sandbox, t.sandbox, symlinks=True)
        return t

    def snapshot(self):
        snap = World(tempfile.mkdtemp(prefix='aries-h8-snap-', dir=Path.home()), copy.deepcopy(self.state))
        shutil.rmtree(snap.sandbox)
        shutil.copytree(self.sandbox, snap.sandbox, symlinks=True)
        return snap

    def restore(self, snap):
        """undone_after_report: put the world back exactly as it was before the executor ran."""
        shutil.rmtree(self.sandbox)
        shutil.copytree(snap.sandbox, self.sandbox, symlinks=True)
        self.state.clear()
        self.state.update(copy.deepcopy(snap.state))

    def discard(self):
        shutil.rmtree(self.sandbox, ignore_errors=True)


# ───────────────────────────────────────────────────────────── fakes (the stub table)
def install_fakes():
    from aries.operator import desktop as D
    from aries.workspace import browser as B, input_capabilities as I, network_capabilities as N
    from aries.workspace import screen_capabilities as S, system_capabilities as Y, capabilities as C
    import agentic_core.tools.calling as calling
    import aries.news.fetch  # noqa: F401  (aries.news re-exports the function under the module's name)
    fetchmod = sys.modules['aries.news.fetch']

    # Desktop: one D-Bus entry point, parsed by ARIES's own read_windows().
    def call_shell(method, timeout=None, *, args=()):
        st = W['cur'].state
        if method == 'Windows':
            return json.dumps({'windows': st['windows'], 'shell': {'fake': True}}), ''
        if method == 'FocusWindow':
            for w in st['windows']:
                w['focused'] = (w['id'] == args[0] and w['app_id'] == args[1])
                if w['focused']:
                    w['minimised'] = False
            return json.dumps({'accepted': True}), ''
        if method == 'WindowAction':
            req = json.loads(args[0])
            w = next((x for x in st['windows'] if x['id'] == req['id']), None)
            if w is None:
                return json.dumps({'accepted': False, 'code': 'TARGET_NOT_FOUND', 'reason': 'no such window'}), ''
            act, out = req['action'], {'accepted': True}
            if act == 'close':
                st['windows'].remove(w)
            elif act == 'minimize':
                w['minimised'], w['focused'] = True, False
            elif act == 'maximize':
                w['maximized'] = True
            elif act == 'unmaximize':
                w['maximized'] = False
            elif act == 'move':
                w['geometry'].update(x=req['x'], y=req['y'])
            elif act == 'resize':
                w['geometry'].update(width=req['width'], height=req['height'])
            elif act == 'tile':
                wa = w['work_area']
                half = wa['width'] // 2
                rect = {'x': wa['x'] + (half if req['side'] == 'right' else 0), 'y': wa['y'],
                        'width': half if req['side'] in ('left', 'right') else wa['width'], 'height': wa['height']}
                w['geometry'] = dict(rect)
                out['expected'] = rect
            return json.dumps(out), ''
        return None, f'fake shell has no method {method}'

    def capabilities():
        return {'available': True, 'protocol_version': 4, 'compatibility': 'compatible',
                'window_actions': ['close', 'minimize', 'maximize', 'unmaximize', 'move', 'resize', 'tile', 'focus'],
                'methods': ['Windows', 'FocusWindow', 'WindowAction', 'Capabilities', 'Ping'], 'missing': []}

    real_read_processes = D.read_processes

    def read_processes():
        extra = [D.Process(pid=p['pid'], name=p['name'], cmdline=p['cmdline']) for p in W['cur'].state['processes']] \
            if W['cur'] else []
        return extra + list(real_read_processes())

    D._call_shell, D.capabilities, D.read_processes = call_shell, capabilities, read_processes
    D.tile_expectation = lambda window, side, monitors=None: {'side': side, 'rect': None, 'scale': 1, 'aligned': True}

    # Launch: the exact tool dispatch, as a fake; verification stays ARIES's own _watch / goals.verify.
    real_call_tool = calling.call_tool

    async def call_tool(db, name, args, **kw):
        if name != 'desktop.open_app':
            return await real_call_tool(db, name, args, **kw)
        st = W['cur'].state
        spec = st['launchable'].get(args['app'])
        if spec is None:
            return {'success': False, 'details': 'not installed'}
        pid = 5000 + len(st['processes'])
        for w in st['windows']:
            w['focused'] = False
        st['windows'].append({'id': str(pid), 'title': spec['title'], 'wm_class': spec['wm_class'],
                              'app_id': spec['app_id'], 'pid': pid, 'focused': True, 'workspace': 0,
                              'minimised': False, 'maximized': False,
                              'geometry': {'x': 50, 'y': 50, 'width': 500, 'height': 400}, 'monitor': 0,
                              'work_area': {'x': 0, 'y': 32, 'width': 1920, 'height': 1048}})
        st['processes'].append({'pid': pid, 'name': spec['process'], 'cmdline': spec['process']})
        return {'success': True}

    calling.call_tool = call_tool

    # Browser: the module's public functions, over a dict of sessions.
    def page(key):
        s = W['cur'].state['sessions'].get(key)
        if s is None:
            raise LookupError('unknown browser session')
        return s

    def render(key):
        s = page(key)
        site = W['cur'].state['sites'].get(s['url'], {'title': '', 'text': '', 'links': []})
        return {'title': site['title'], 'url': s['url'], 'text': site['text'], 'links': site['links'],
                'fields': [{'label': e, 'type': 'text'} for e in s['elements']], 'scroll': dict(s['scroll']),
                'session': key, 'blocked_resources': 0, 'requests': 1, 'evidence': 'fake browser'}

    async def inventory():
        return [{'session': k, 'owner': s['owner'], 'open': True, 'url': s['url']}
                for k, s in W['cur'].state['sessions'].items()]

    async def b_observe(key):
        return render(key)

    async def b_elements(key):
        s = page(key)
        return {'session': key, 'url': s['url'], 'truncated': False,
                'elements': [{'element_id': e, 'role': 'textbox', 'name': e} for e in s['elements']]}

    def goto(s, url):
        s['history'] = s['history'][:s['index'] + 1] + [url]
        s['index'] = len(s['history']) - 1
        s['url'], s['scroll'] = url, {'x': 0, 'y': 0}

    async def navigate_page(key, url):
        goto(page(key), url)
        return render(key)

    async def click_element(key, element_id):
        s = page(key)
        link = next((l for l in W['cur'].state['sites'].get(s['url'], {}).get('links', []) if l['name'] == element_id),
                    None)
        if link is None:
            raise ValueError('TARGET_NOT_FOUND: no such element')
        goto(s, link['url'])
        return render(key)

    async def type_element(key, element_id, value):
        s = page(key)
        if element_id not in s['elements']:
            raise ValueError('TARGET_NOT_FOUND: no such field')
        s['elements'][element_id] = value
        return {**render(key), 'element_id': element_id, 'observed_value': value}

    async def element_value(key, element_id):
        return {'session': key, 'element_id': element_id, 'observed_value': page(key)['elements'][element_id]}

    async def history_page(key, direction):
        s = page(key)
        s['index'] = max(0, min(len(s['history']) - 1, s['index'] + (-1 if direction == 'back' else 1)))
        s['url'] = s['history'][s['index']]
        return render(key)

    async def scroll_page(key, pixels):
        page(key)['scroll']['y'] += int(pixels)
        return render(key)

    async def wait_page(key, milliseconds):
        return render(key)

    B.inventory, B.observe, B.elements = inventory, b_observe, b_elements
    B.navigate_page, B.click_element, B.type_element, B.element_value = navigate_page, click_element, type_element, element_value
    B.history_page, B.scroll_page, B.wait_page = history_page, scroll_page, wait_page

    real_execute = C.execute

    async def execute(db, step):
        if step.get('capability') != 'browser_open':
            return await real_execute(db, step)
        st = W['cur'].state
        url = step['args']['url']
        if url not in st['sites'] and urlsplit(url).hostname in ('duckduckgo.com', 'www.youtube.com'):
            # Amendment 1: a real search-results page has a title; the fake one had none (3 false alarms).
            st['sites'][url] = {'title': 'Search results', 'text': 'results for the query', 'links': []}
        key = f"s{len(st['sessions']) + 1}"
        st['sessions'][key] = {'owner': step['goal_id'], 'url': step['args']['url'], 'history': [step['args']['url']],
                               'index': 0, 'scroll': {'x': 0, 'y': 0}, 'elements': {'q': ''}}
        return {'state': 'done', 'browser': render(key)}

    C.execute = execute

    class Fetched:
        def __init__(self, url, body):
            self.ok, self.truncated, self.url, self.body = body is not None, False, url, body

    async def fetch(url, **kw):
        body = W['cur'].state['downloads'].get(url)
        return Fetched(url, body.encode() if body is not None else None)

    fetchmod.fetch = fetch

    # Input: the one AT-SPI / clipboard worker entry point.
    async def worker(op, payload, timeout=None):
        st = W['cur'].state
        if op == 'clipboard_read':
            text = st['clipboard']
            return {'bytes': len(text.encode()), 'sha256': sha(text), 'has_text': True, 'text': text}
        if op == 'clipboard_write':
            st['clipboard'] = payload['text']
            return {'served': ['text/plain;charset=utf-8']}
        if op == 'targets':
            return {'app': payload['app'], 'targets': [{'node': n, 'role': 'text', 'name': n} for n in st['nodes']]}
        if op == 'type':
            node = payload['node']
            if node not in st['nodes']:
                raise I.InputCapabilityError('TARGET_NOT_FOUND', 'no such node')
            new = payload['text'] if payload.get('mode') == 'replace' else st['nodes'][node] + payload['text']
            st['nodes'][node] = new
            return {'typed': len(payload['text']), 'expected_sha256': sha(new)}
        if op == 'read_node':
            text = st['nodes'].get(payload['node'], '')
            return {'node': payload['node'], 'sha256': sha(text), 'characters': len(text)}
        raise RuntimeError('fake worker has no op ' + op)

    I.worker = worker

    # Screen: capture writes a frame into the fake store; inspect re-reads it from there.
    def frame_for(window_id):
        st = W['cur'].state['screen']
        data = ('frame:' + st['text'] + ':' + str(window_id)).encode()
        path = str(W['cur'].sandbox / f'.screen-{len(st["frames"]) + 1}.png')
        st['frames'][path] = {'bytes': data, 'width': 1920, 'height': 1080}
        return path, data

    def s_capture(window_id=None):
        path, data = frame_for(window_id)
        return {'path': path, 'sha256': sha(data), 'width': 1920, 'height': 1080, 'bytes': len(data),
                'content': {'uniform': False}, 'scope': 'window' if window_id else 'screen', 'region': None,
                'observed_at': now()}

    def s_inspect(path):
        f = W['cur'].state['screen']['frames'].get(str(path))
        if f is None:
            raise OSError('capture no longer exists')
        return {'path': str(path), 'sha256': sha(f['bytes']), 'width': f['width'], 'height': f['height'],
                'bytes': len(f['bytes']), 'content': {'uniform': False}, 'observed_at': now()}

    def s_read(window_id=None, language='eng+mkd'):
        cap = s_capture(window_id)
        text = W['cur'].state['screen']['text']
        return {'capture': cap, 'text': text, 'characters': len(text), 'words': len(text.split()),
                'mean_confidence': 75.0, 'language': language, 'observed_at': now()}

    S.capture, S.inspect, S.read = s_capture, s_inspect, s_read

    # Network and display.
    def n_status(*, probe=True):
        n = W['cur'].state['network']
        return {'internet_reachable': n['internet_reachable'], 'link_up': n['link_up'],
                'active': [p['name'] for p in n['profiles'].values() if p['state'] == 'activated'], 'observed_at': now()}

    def n_wifi_list():
        n = W['cur'].state['network']
        return {'networks': [dict(r) for r in n['visible']], 'count': len(n['visible']),
                'saved_profiles': [{'name': p['name'], 'uuid': u, 'ssid': p['name']} for u, p in n['profiles'].items()],
                'scan': 'fake', 'observed_at': now()}

    def n_connection_state(name):
        n = W['cur'].state['network']
        uuid = name if name in n['profiles'] else next((u for u, p in n['profiles'].items() if p['name'] == name), None)
        if uuid is None:
            return None, 'no such profile'
        p = n['profiles'][uuid]
        return {'name': p['name'], 'uuid': uuid, 'type': '802-11-wireless', 'state': p['state'], 'device': 'wlan0',
                'observed_at': now()}, None

    def n_wifi_connect(name, *, wait=25):
        n = W['cur'].state['network']
        uuid = next((u for u, p in n['profiles'].items() if p['name'] == name), None)
        if uuid is None:
            raise N.NetworkCapabilityError('TARGET_NOT_FOUND', 'no saved profile ' + name)
        before = n['profiles'][uuid]['state']
        for p in n['profiles'].values():
            p['state'] = 'deactivated'
        n['profiles'][uuid]['state'] = 'activated'
        return {'ok': True, 'profile': {'name': name, 'uuid': uuid, 'type': '802-11-wireless'}, 'accepted': True,
                'accept_detail': 'fake activation', 'was': before, 'now': 'activated', 'verified': True,
                'state_unavailable': None, 'observed_at': now()}

    def n_brightness(level=None):
        st = W['cur'].state
        if level is not None:
            st['brightness'] = int(level)
            return {'ok': True, 'detail': None, 'mechanism': 'fake', 'requested': int(level),
                    'brightness': st['brightness'], 'verified': True, 'sources': [], 'observed_at': now()}
        return {'ok': True, 'brightness': st['brightness'], 'sources': [], 'controllable': True, 'detail': None,
                'observed_at': now()}

    N.status, N.wifi_list, N.connection_state = n_status, n_wifi_list, n_connection_state
    N.wifi_connect, N.brightness = n_wifi_connect, n_brightness

    # Services and packages: the subprocess entry point, answered in systemctl / dpkg-query format, so that
    # ARIES's own show() / list-units parsing stays real.
    async def y_run(argv, timeout=12):
        st = W['cur'].state
        if argv[0] == 'dpkg-query':
            name = argv[-1]
            v = st['packages'].get(name)
            return (0, f'{name}\t{v}\tinstalled\tinstall\n', '') if v else (1, '', f'dpkg-query: no packages found matching {name}')
        if argv[0] == 'snap':
            return 1, '', 'error: no matching snaps installed'
        if argv[0] != 'systemctl':
            raise TripwireError('fake _run got an unexpected command ' + argv[0])
        rest = argv[3:] if argv[3:4] == ['--user'] else argv[3:]
        rest = [a for a in rest if a != '--user']
        verb = rest[0]
        units = rest[rest.index('--') + 1:] if '--' in rest else []
        if verb == 'list-units':
            rows = [{'unit': u, 'load': v['LoadState'], 'active': v['ActiveState'], 'sub': v['SubState'],
                     'description': v['Description']} for u, v in st['units'].items()]
            return 0, json.dumps(rows), ''
        if verb == 'show':
            blocks = []
            for u in units:
                v = st['units'].get(u)
                if v is None:
                    blocks.append(f'Id={u}\nLoadState=not-found\nActiveState=inactive\nSubState=dead')
                else:
                    blocks.append('\n'.join([f'Id={u}', f"Description={v['Description']}", f"LoadState={v['LoadState']}",
                                             f"ActiveState={v['ActiveState']}", f"SubState={v['SubState']}",
                                             f"InvocationID={v['InvocationID']}", 'CanStart=yes', 'CanStop=yes',
                                             'UnitFileState=enabled']))
            return 0, '\n\n'.join(blocks) + '\n', ''
        if verb in ('start', 'stop', 'restart'):
            for u in units:
                v = st['units'][u]
                if verb == 'stop':
                    v.update(ActiveState='inactive', SubState='dead')
                else:
                    v.update(ActiveState='active', SubState='running',
                             InvocationID=sha(v['InvocationID'] + verb + str(time.time()))[:32])
            return 0, '', ''
        raise TripwireError('fake systemctl verb not modelled: ' + verb)

    Y._run = y_run
    Y.own_unit = lambda: 'aries-core.service'


# ───────────────────────────────────────────────────────────── per-capability cases
class Case:
    """How to set up one capability, what its valid args are, and how each operator perturbs it."""

    def __init__(self, name, setup, *, target=None, value=None, side=None, partial=None, falsify=None):
        self.name, self.setup = name, setup
        self.target, self.value, self.side, self.partial, self.falsify = target, value, side, partial, falsify


def write(world, rel, text):
    p = world.sandbox / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return str(p)


def files_setup(world, rng):
    write(world, 'docs/a.txt', 'alpha ' + str(rng.random()))
    write(world, 'docs/b.txt', 'bravo ' + str(rng.random()))
    write(world, 'docs/notes/c.md', 'charlie notes')
    (world.sandbox / 'out').mkdir(exist_ok=True)
    return world


def marker(rng):
    return 'H8FALSE-' + hex(rng.getrandbits(32))[2:]


def falsify_report(result, rng, keys):
    """Change the first present field in `keys` to a false value; return the false value."""
    def walk(obj):
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and not isinstance(obj[k], (dict, list)):
                    v = obj[k]
                    new = (not v) if isinstance(v, bool) else (v + 1 + rng.randrange(5)) if isinstance(v, (int, float)) \
                        else sha(marker(rng)) if k == 'sha256' or k.endswith('_sha256') else (str(v) + ' ' + marker(rng))
                    obj[k] = new
                    return new
            for v in obj.values():
                got = walk(v)
                if got is not None:
                    return got
        if isinstance(obj, list):
            for v in obj:
                got = walk(v)
                if got is not None:
                    return got
        return None
    return walk(result)


READ_KEYS = ('sha256', 'exists', 'count', 'url', 'title', 'text', 'observed_value', 'brightness', 'internet_reachable',
             'installed', 'state', 'active_state', 'load_state', 'unit', 'value', 'name', 'pid', 'mountpoint', 'used_pct',
             'characters', 'tabs')


def build_cases():
    cases = {}

    def add(case):
        cases[case.name] = case

    # Files (real, sandboxed).
    def fpath(w, rel):
        return str(w.sandbox / rel)
    add(Case('file.read', lambda w, r: {'path': fpath(files_setup(w, r), 'docs/a.txt')},
             target=lambda w, a, r: {**a, 'path': fpath(w, 'docs/b.txt')}))
    add(Case('file.exists', lambda w, r: {'path': fpath(files_setup(w, r), 'docs/a.txt')},
             target=lambda w, a, r: {**a, 'path': fpath(w, 'docs/missing.txt')}))
    add(Case('file.metadata', lambda w, r: {'path': fpath(files_setup(w, r), 'docs/a.txt')},
             target=lambda w, a, r: {**a, 'path': fpath(w, 'docs/b.txt')}))
    add(Case('file.list', lambda w, r: {'path': fpath(files_setup(w, r), 'docs')},
             target=lambda w, a, r: {**a, 'path': fpath(w, 'docs/notes')}))
    add(Case('file.search', lambda w, r: {'path': fpath(files_setup(w, r), 'docs'), 'query': 'a'},
             target=lambda w, a, r: {**a, 'path': fpath(w, 'docs/notes')}))
    add(Case('file.semantic_search', lambda w, r: {'path': fpath(files_setup(w, r), 'docs'), 'query': 'alpha'},
             target=lambda w, a, r: {**a, 'path': fpath(w, 'docs/notes')}))

    def write_setup(w, r):
        files_setup(w, r)
        return {'path': fpath(w, 'out/new.txt'), 'content': 'new content ' + str(r.random())}
    add(Case('file.write', write_setup,
             target=lambda w, a, r: {**a, 'path': fpath(w, 'out/other.txt')},
             value=lambda w, a, r: {**a, 'content': a['content'] + ' ' + marker(r)},
             partial=lambda w, a, r: {**a, 'content': a['content'][:max(1, len(a['content']) // 2)]},
             side=lambda w, a, r: write(w, 'docs/outside.txt', 'side effect ' + marker(r))))

    def copy_setup(w, r):
        files_setup(w, r)
        src = fpath(w, 'docs/a.txt')
        return {'path': src, 'destination': fpath(w, 'out/a-copy.txt'), 'expected_sha256': sha(Path(src).read_bytes())}
    add(Case('file.copy', copy_setup,
             target=lambda w, a, r: {**a, 'destination': fpath(w, 'out/elsewhere.txt')},
             value=lambda w, a, r: ({**a, 'path': fpath(w, 'docs/b.txt'),
                                     'expected_sha256': sha(Path(fpath(w, 'docs/b.txt')).read_bytes())}),
             partial='truncate_destination', side=lambda w, a, r: write(w, 'docs/outside.txt', 'side ' + marker(r))))

    def edit_setup(w, r):
        files_setup(w, r)
        p = fpath(w, 'docs/a.txt')
        old = Path(p).read_text()
        return {'path': p, 'old_text': old[:5], 'new_text': 'EDITED', 'expected_sha256': sha(old.encode())}
    add(Case('file.edit', edit_setup,
             target='edit_other_file', value=lambda w, a, r: {**a, 'new_text': 'EDITED ' + marker(r)},
             partial='edit_half', side=lambda w, a, r: write(w, 'docs/outside.txt', 'side ' + marker(r))))

    def move_setup(w, r, dest='out/moved.txt'):
        files_setup(w, r)
        src = fpath(w, 'docs/a.txt')
        return {'path': src, 'destination': fpath(w, dest), 'expected_sha256': sha(Path(src).read_bytes())}
    for name, dest in (('file.move', 'out/moved.txt'), ('file.rename', 'docs/a-renamed.txt')):
        add(Case(name, (lambda d: lambda w, r: move_setup(w, r, d))(dest),
                 target=(lambda d: lambda w, a, r: {**a, 'destination': fpath(w, 'out/elsewhere.txt')})(dest),
                 value=lambda w, a, r: {**a, 'path': fpath(w, 'docs/b.txt'),
                                        'expected_sha256': sha(Path(fpath(w, 'docs/b.txt')).read_bytes())},
                 partial='copy_without_delete', side=lambda w, a, r: write(w, 'docs/outside.txt', 'side ' + marker(r))))

    # Database.
    add(Case('notification.send', lambda w, r: {'title': 'H8 title ' + str(r.random())[:6], 'body': 'H8 body'},
             value=lambda w, a, r: {**a, 'body': a['body'] + ' ' + marker(r)},
             side='extra_notification'))
    add(Case('task.inspect', 'task_setup', target='other_task'))

    # Real read-only system probes (no target argument: wrong_target falsifies an identity field).
    for name, args in (('system.status', {}), ('system.storage', {}), ('system.disk', {}), ('system.processes', {})):
        add(Case(name, (lambda a: lambda w, r: dict(a))(args)))

    # Browser.
    def b_session(w, r, url='https://site1.example/'):
        w.state['sessions']['s1'] = {'owner': 'h8-task', 'url': url, 'history': ['https://site2.example/', url],
                                     'index': 1, 'scroll': {'x': 0, 'y': 0}, 'elements': {'q': '', 'name': ''}}
        w.state['sessions']['s9'] = {'owner': 'h8-task', 'url': 'https://site4.example/', 'history': ['https://site4.example/'],
                                     'index': 0, 'scroll': {'x': 0, 'y': 0}, 'elements': {'q': ''}}
        return w
    other = lambda w, a, r: {**a, 'session': 's9'}
    add(Case('browser.tabs', lambda w, r: (b_session(w, r), {})[1]))
    add(Case('browser.observe', lambda w, r: (b_session(w, r), {'session': 's1'})[1], target=other))
    add(Case('browser.elements', lambda w, r: (b_session(w, r), {'session': 's1'})[1], target=other))
    add(Case('browser.read', lambda w, r: (b_session(w, r), {'session': 's1'})[1], target=other))
    add(Case('browser.wait', lambda w, r: (b_session(w, r), {'session': 's1', 'milliseconds': 0})[1], target=other))
    add(Case('browser.navigate', lambda w, r: (b_session(w, r), {'session': 's1', 'url': 'https://site3.example/'})[1],
             target=other, value=lambda w, a, r: {**a, 'url': 'https://site5.example/'}))
    add(Case('browser.click', lambda w, r: (b_session(w, r), {'session': 's1', 'element_id': 'Next 1',
                                                             'expected_url': 'https://site2.example/'})[1],
             target=lambda w, a, r: {**a, 'session': 's9', 'element_id': 'Next 4', 'expected_url': 'https://site5.example/'},
             value=lambda w, a, r: {**a, 'element_id': 'File'}))
    add(Case('browser.type', lambda w, r: (b_session(w, r), {'session': 's1', 'element_id': 'q', 'value': 'hello'})[1],
             target=lambda w, a, r: {**a, 'element_id': 'name'}, value=lambda w, a, r: {**a, 'value': 'hello ' + marker(r)}))
    add(Case('browser.scroll', lambda w, r: (b_session(w, r), {'session': 's1', 'pixels': 400})[1],
             target=other, value=lambda w, a, r: {**a, 'pixels': 1200}))
    add(Case('browser.back', lambda w, r: (b_session(w, r), {'session': 's1'})[1], target=other))
    add(Case('browser.forward', lambda w, r: (b_session(w, r, 'https://site2.example/'), 'forward_setup')[1], target=other))
    add(Case('browser.open', lambda w, r: {'url': 'https://site1.example/'},
             target=lambda w, a, r: {**a, 'url': 'https://site2.example/'},
             value=lambda w, a, r: {**a, 'url': 'https://site5.example/'}))
    add(Case('browser.search', lambda w, r: {'query': 'h8 query', 'site': 'web'}, target='search_other_site',
             value=lambda w, a, r: {**a, 'query': 'other ' + marker(r)}))

    def dl_setup(w, r):
        files_setup(w, r)
        b_session(w, r)
        return {'session': 's1', 'url': 'https://site1.example/file.bin', 'path': fpath(w, 'out/file.bin')}
    add(Case('browser.download', dl_setup,
             target=lambda w, a, r: {**a, 'path': fpath(w, 'out/elsewhere.bin')},
             value='download_other_body', partial='truncate_destination',
             side=lambda w, a, r: write(w, 'docs/outside.txt', 'side ' + marker(r))))

    # Desktop.
    win = {'window_id': '101', 'app_id': APP_ID}
    other_win = lambda w, a, r: {**a, 'window_id': '102', 'app_id': 'org.gnome.Nautilus.desktop'}
    def side_win(w, a, r):
        g = next(x for x in w.state['windows'] if x['id'] == '102')['geometry']
        g.update(x=g['x'] + 37)
    add(Case('desktop.observe', lambda w, r: {}))
    add(Case('desktop.windows', lambda w, r: {}))
    add(Case('desktop.close', lambda w, r: dict(win), target=other_win, value='other_action', side=side_win))
    add(Case('desktop.minimize', lambda w, r: dict(win), target=other_win, value='other_action', side=side_win))
    add(Case('desktop.maximize', lambda w, r: dict(win), target=other_win, value='other_action', side=side_win))
    add(Case('desktop.unmaximize', 'maximized_setup', target=other_win, value='other_action', side=side_win))
    add(Case('desktop.move', lambda w, r: {**win, 'x': 300, 'y': 260}, target=other_win,
             value=lambda w, a, r: {**a, 'x': a['x'] + 1 + r.randrange(50)}, side=side_win))
    add(Case('desktop.resize', lambda w, r: {**win, 'width': 700, 'height': 500}, target=other_win,
             value=lambda w, a, r: {**a, 'width': a['width'] + 1 + r.randrange(50)}, side=side_win))
    add(Case('desktop.tile', lambda w, r: {**win, 'side': 'left'}, target=other_win,
             value=lambda w, a, r: {**a, 'side': 'right'}, side=side_win))
    add(Case('desktop.focus', 'focus_setup', target='focus_other', value='focus_other'))
    add(Case('desktop.launch', 'launch_setup', target='launch_other', value='launch_other'))

    # Input.
    add(Case('input.clipboard_read', lambda w, r: {}))
    add(Case('input.clipboard_write', lambda w, r: {'text': 'clip ' + str(r.random())[:6]},
             target='clipboard_elsewhere', value=lambda w, a, r: {**a, 'text': a['text'] + ' ' + marker(r)}))
    add(Case('input.editable_targets', lambda w, r: {'app': 'gedit'}))
    typing = {'app': 'gedit', 'node': '0/1', 'pid': 4101, 'role': 'text', 'name': 'field one', 'text': 'typed',
              'mode': 'replace'}
    add(Case('input.type_text', lambda w, r: dict(typing), target=lambda w, a, r: {**a, 'node': '0/2'},
             value=lambda w, a, r: {**a, 'text': 'typed ' + marker(r)}))

    # Screen.
    add(Case('screen.capture', lambda w, r: {}))
    add(Case('screen.screenshot', lambda w, r: {}))
    add(Case('screen.read', lambda w, r: {}))

    # Network and display.
    add(Case('network.status', lambda w, r: {}))
    add(Case('network.wifi_list', lambda w, r: {}))
    add(Case('network.wifi_connect', lambda w, r: {'name': 'OfficeNet'}, target=lambda w, a, r: {**a, 'name': 'CafeNet'}))
    add(Case('display.brightness', lambda w, r: {}))
    add(Case('display.set_brightness', lambda w, r: {'level': 30},
             value=lambda w, a, r: {**a, 'level': 30 + 6 + r.randrange(40)}))

    # Services and packages.
    add(Case('system.services', lambda w, r: {'scope': 'user'}))
    add(Case('system.service', lambda w, r: {'unit': 'mpris-proxy.service', 'scope': 'user'},
             target=lambda w, a, r: {**a, 'unit': 'ollama.service'}))
    add(Case('system.service_control', lambda w, r: {'unit': 'mpris-proxy.service', 'action': 'restart', 'scope': 'user'},
             target=lambda w, a, r: {**a, 'unit': 'ollama.service'}))
    add(Case('system.packages', lambda w, r: {'package': 'bash'}, target=lambda w, a, r: {**a, 'package': 'coreutils'}))
    return cases


# ───────────────────────────────────────────────────────────── running one item
TASK_ID = 'h8-task'


async def ctx_for(db):
    return {'db': db, 'goal': 'H8 fault injection', 'task_id': TASK_ID, 'metrics': {}, 'origin': 'user'}


async def special_setup(case, world, rng, db):
    """Named setups that need the database or extra world state."""
    if case.setup == 'task_setup':
        from aries.workspace.models import WorkspaceGoal
        for tid, state in (('h8-target', 'done'), ('h8-other', 'failed')):
            await db.merge(WorkspaceGoal(id=tid, request='H8 task ' + tid, state=state,
                                 result_json=json.dumps({'steps': [{}] * (2 if tid == 'h8-target' else 5),
                                                         'evidence': [{'evidence_id': 'e-' + tid}]})))
        await db.commit()
        return {'task_id': 'h8-target'}
    if case.setup == 'maximized_setup':
        world.state['windows'][0]['maximized'] = True
        return {'window_id': '101', 'app_id': APP_ID}
    if case.setup == 'launch_setup':
        # The application is not running yet, so only a real launch can satisfy the verifier.
        world.state['windows'] = [w for w in world.state['windows'] if w['app_id'] != APP_ID]
        world.state['processes'] = [p for p in world.state['processes'] if p['name'] != 'gnome-calculator']
        for w in world.state['windows']:
            w['focused'] = True
        return {'app': APP}
    if case.setup == 'focus_setup':
        world.state['windows'][0]['focused'] = False
        world.state['windows'][1]['focused'] = True
        return {'app': APP}
    return case.setup(world, rng)


async def honest(cap, args, ctx):
    return await cap.executor(args, ctx)


def relabel(obj, mapping):
    """Rewrite identifiers in a report so that it claims the requested target (wrong_target / wrong_value).

    Only values are rewritten, never keys: a string equal to an old identifier becomes the new one, and a
    long identifier (a path, 8+ characters) is also replaced inside longer strings.
    """
    mapping = {str(k): str(v) for k, v in mapping.items() if str(k) and str(k) != str(v)}

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            if x in mapping:
                return mapping[x]
            for old, new in mapping.items():
                if len(old) >= 8 and old in x:
                    x = x.replace(old, new)
            return x
        return x
    return walk(obj)


def leaves(obj, skip=('observed_at', 'requested_at', 'seconds')):
    """Scalar values of a report, without timestamps."""
    if isinstance(obj, dict):
        return [x for k, v in obj.items() if k not in skip for x in leaves(v, skip)]
    if isinstance(obj, list):
        return [x for v in obj for x in leaves(v, skip)]
    return [obj] if isinstance(obj, (str, int, float, bool)) and not isinstance(obj, bool) or isinstance(obj, bool) else []


async def mutate(op, case, cap, world, args, ctx, rng):
    """Run the executor as the operator says. Returns (result, false_values, note)."""
    from aries.workspace.registry import registry
    effectful = cap.effect != 'read'
    if op == 'noop_success':
        twin = world.twin()
        prev = W['cur']
        W['cur'] = twin
        try:
            if not effectful:
                perturb(twin, rng)
            result = await honest(cap, relabel(args, {str(world.sandbox): str(twin.sandbox)}), ctx)
        finally:
            W['cur'] = prev
        result = relabel(result, {str(twin.sandbox): str(world.sandbox)})
        twin.discard()
        false, note = [], 'report produced in a twin world; the real world was not touched'
        if not effectful:
            # The values of the fabricated report that a real read would not give (secondary outcome only).
            real = await honest(cap, args, ctx)
            false = sorted(set(map(str, leaves(result))) - set(map(str, leaves(real))))
            if not false:
                # The twin could not differ (a database row, or a real read-only system probe): fabricate a value.
                false = [falsify_report(result, rng, READ_KEYS)]
                note = 'report fabricated without observing (a value changed, the twin could not differ)'
        return result, false, note
    if op in ('wrong_target', 'wrong_value') and not effectful and (case.target is None or op == 'wrong_value'):
        result = await honest(cap, args, ctx)
        false = falsify_report(result, rng, READ_KEYS)
        return result, [false], 'honest observation, then a field of the report falsified'
    if op in ('wrong_target', 'wrong_value'):
        spec = case.target if op == 'wrong_target' else (case.value or case.target)
        if isinstance(spec, str):
            return await named_variant(spec, op, case, cap, world, args, ctx, rng)
        alt = spec(world, dict(args), rng)
        result = await honest(cap, alt, ctx)
        result = relabel(result, {str(alt[k]): str(args[k]) for k in alt if k in args and alt[k] != args[k]})
        return result, [], f'executed on {op} variant, report relabelled to the requested arguments'
    if op == 'partial_effect':
        spec = case.partial
        if callable(spec):
            alt = spec(world, dict(args), rng)
            result = await honest(cap, alt, ctx)
            return relabel(result, {str(alt[k]): str(args[k]) for k in alt if alt[k] != args[k]}), [], 'partial content'
        return await named_variant(spec, op, case, cap, world, args, ctx, rng)
    if op == 'side_effect_outside_scope':
        result = await honest(cap, args, ctx)
        spec = case.side
        if spec == 'extra_notification':
            from aries.notify import emit
            from aries.health.findings import Severity
            await emit(ctx['db'], key='h8-side', title='side effect', severity=Severity.NOTICE, source='h8', body='x')
            await ctx['db'].commit()
        else:
            spec(world, args, rng)
        return result, [], 'honest effect plus a change outside the requested scope'
    if op == 'undone_after_report':
        snap = world.snapshot()
        result = await honest(cap, args, ctx)
        world.restore(snap)
        snap.discard()
        if cap.name == 'notification.send':
            from aries.notify import AriesNotification
            row = await ctx['db'].get(AriesNotification, result['notification_id'])
            if row is not None:
                await ctx['db'].delete(row)
                await ctx['db'].commit()
        return result, [], 'honest effect, then the world restored before verification'
    raise ValueError('unknown operator ' + op)


def perturb(world, rng):
    """For a read's noop: the twin world differs, so the fabricated report does not describe the real one."""
    st = world.state
    for p in sorted(world.sandbox.rglob('*.txt')) + sorted(world.sandbox.rglob('*.md')):
        p.write_text(p.read_text() + ' stale ' + marker(rng))
    st['clipboard'] += ' ' + marker(rng)
    st['brightness'] = (st['brightness'] + 17) % 100
    st['network']['internet_reachable'] = not st['network']['internet_reachable']
    st['network']['visible'][0]['saved'] = not st['network']['visible'][0]['saved']
    st['screen']['text'] += ' ' + marker(rng)
    for w in st['windows']:
        w['title'] += ' (stale)'
    for s in st['sessions'].values():
        s['scroll']['y'] += 123
    for u in st['units'].values():
        u['ActiveState'] = 'failed'


async def named_variant(spec, op, case, cap, world, args, ctx, rng):
    if spec == 'truncate_destination':
        result = await honest(cap, args, ctx)
        dest = Path(args.get('destination') or args['path'])
        data = dest.read_bytes()
        dest.write_bytes(data[:max(1, len(data) // 2)])
        return result, [], 'effect happened, then the destination truncated to half'
    if spec == 'copy_without_delete':
        result = await honest(cap, args, ctx)
        shutil.copy2(args['destination'], args['path'])
        return result, [], 'moved, then the source put back (a copy, not a move)'
    if spec == 'edit_half':
        p = Path(args['path'])
        old = p.read_text()
        result = await honest(cap, args, ctx)
        p.write_text(old.replace(args['old_text'], args['new_text'][: max(1, len(args['new_text']) // 2)], 1))
        return result, [], 'only part of the replacement written'
    if spec == 'edit_other_file':
        other = str(world.sandbox / 'docs/b.txt')
        text = Path(other).read_text()
        alt = {**args, 'path': other, 'old_text': text[:5], 'expected_sha256': sha(text.encode())}
        result = await honest(cap, alt, ctx)
        return relabel(result, {other: args['path']}), [], 'edited a different file, report relabelled'
    if spec == 'download_other_body':
        world.state['downloads'][args['url']] = 'a different body ' + marker(rng)
        result = await honest(cap, args, ctx)
        return result, [], 'the downloaded body differs from the observed link'
    if spec == 'search_other_site':
        from aries.workspace.registry import browser_search
        from urllib.parse import quote
        result = await browser_search({**args, 'site': 'youtube'}, ctx)
        asked = 'https://duckduckgo.com/?q=' + quote(args['query'])
        return relabel(result, {result['url']: asked}), [], 'searched another site, report relabelled'
    if spec == 'other_task':
        result = await honest(cap, {**args, 'task_id': 'h8-other'}, ctx)
        return relabel(result, {'h8-other': args['task_id']}), [], 'inspected another task, report relabelled'
    if spec == 'launch_other':
        world.state['launchable']['org.gnome.Nautilus'] = {'title': 'Files 2', 'wm_class': 'org.gnome.Nautilus',
                                                           'app_id': 'org.gnome.Nautilus.desktop', 'process': 'nautilus'}
        result = await honest(cap, {**args, 'app': 'org.gnome.Nautilus'}, ctx)
        return relabel(result, {'org.gnome.Nautilus': args['app']}), [], 'launched another app, report relabelled'
    if spec == 'other_action':
        from aries.workspace.desktop_capabilities import executor as window_executor
        other = {'close': 'minimize', 'minimize': 'maximize', 'maximize': 'minimize',
                 'unmaximize': 'minimize'}[cap.name.split('.')[1]]
        result = await window_executor(other)(args, ctx)
        result['requested'] = cap.name.split('.')[1]
        return result, [], f'performed {other} instead, report relabelled'
    if spec == 'focus_other':
        result = await honest(cap, {**args, 'app': 'org.gnome.Nautilus'}, ctx)
        return relabel(result, {'org.gnome.Nautilus': args['app'], '102': '101',
                                'org.gnome.Nautilus.desktop': APP_ID}), [], 'focused another window, report relabelled'
    if spec == 'clipboard_elsewhere':
        result = await honest(cap, args, ctx)
        world.state['clipboard'] = 'other application text ' + marker(rng)
        return result, [], 'clipboard written, then owned by another application'
    raise ValueError('unknown named variant ' + spec)


async def run_item(item, cases, flag_hardened):
    from agentic_core.database.base import async_session
    from aries.workspace.registry import registry
    cap = registry._items[item['capability']]
    case = cases[item['capability']]
    rng = random.Random(item.get('variant_seed', 0) if 'operator' in item else hash(item['id']) & 0xffffffff)
    world = World()
    W['cur'] = world
    rec = {'id': item['id'], 'capability': item['capability'], 'verifier_class': item['verifier_class'],
           'operator': item.get('operator', 'clean'), 'effect': cap.effect}
    t0 = time.monotonic()
    try:
        async with async_session() as db:
            ctx = await ctx_for(db)
            args = await special_setup(case, world, rng, db)
            if item['capability'] == 'browser.forward':
                world.state['sessions']['s1'].update(history=['https://site2.example/', 'https://site3.example/'], index=0,
                                                     url='https://site2.example/')
                args = {'session': 's1'}
            args = registry.validate(item['capability'], args)
            calls = {'n': 0}
            original = cap.executor

            if 'operator' in item:
                result, false_values, note = await mutate(item['operator'], case, cap, world, args, ctx, rng)
            else:
                result, false_values, note = await honest(cap, args, ctx), [], 'clean replay'

            async def counted(*a, **k):
                calls['n'] += 1
                return await original(*a, **k)
            # Capability is frozen: swap the whole registry entry, so that any verifier call through the
            # registered executor is counted, then put the original back.
            import dataclasses
            registry._items[item['capability']] = dataclasses.replace(cap, executor=counted)
            verifier_exception = None
            try:
                verification = await cap.verifier(args, result, ctx)
            except TripwireError:
                raise
            except Exception as exc:                               # noqa: BLE001
                # As aries/workspace/agent.py does (Amendment 1): an exception raised by the verifier is a
                # negative verdict, not a harness error.
                verifier_exception = f'{type(exc).__name__}: {str(exc)[:300]}'
                verification = {'met': False, 'type': 'verification_error', 'data': {'error': verifier_exception}}
            finally:
                registry._items[item['capability']] = cap
        met = verification.get('met') is True and verification.get('status') != 'UNVERIFIED'
        evidence = json.dumps(verification.get('data'), default=str)
        reached = any(v is not None and json.dumps(v, default=str).strip('"') in evidence for v in false_values)
        rec.update(verdict_met=met, killed=not met if 'operator' in item else None,
                   false_alarm=(not met) if 'operator' not in item else None,
                   false_value_in_evidence=reached if 'operator' in item else None,
                   verifier_called_mutated_entry=calls['n'] > 0, verifier_exception=verifier_exception,
                   note=note, error=None)
    except TripwireError as exc:
        rec.update(error='TRIPWIRE: ' + str(exc), killed=None)
    except Exception as exc:                                       # noqa: BLE001
        rec.update(error=f'{type(exc).__name__}: {str(exc)[:300]}', killed=None)
    finally:
        W['cur'] = None
        world.discard()
    rec['seconds'] = round(time.monotonic() - t0, 3)
    return rec


def fingerprint(world):
    """The fake world's dict state (without screen frames, which every read adds) plus the sandbox's files."""
    st = {k: v for k, v in world.state.items() if k != 'screen'}
    files = sorted((str(p.relative_to(world.sandbox)), sha(p.read_bytes())) for p in world.sandbox.rglob('*')
                   if p.is_file() and not p.name.startswith('.screen-'))
    return sha(json.dumps([st, files], sort_keys=True, default=str))


async def selftest(cases):
    """Honest executors only, never a verifier: does each case set up and execute against its fake world?"""
    from agentic_core.database.base import async_session
    from aries.workspace.registry import registry
    out = {}
    for name in sorted(registry._items):
        cap, case = registry._items[name], cases[name]
        world = World()
        W['cur'] = world
        try:
            async with async_session() as db:
                ctx = await ctx_for(db)
                args = await special_setup(case, world, random.Random(1), db)
                if name == 'browser.forward':
                    world.state['sessions']['s1'].update(history=['https://site2.example/', 'https://site3.example/'],
                                                         index=0, url='https://site2.example/')
                    args = {'session': 's1'}
                args = registry.validate(name, args)
                before = fingerprint(world)
                result = await cap.executor(args, ctx)
                changed = fingerprint(world) != before
            if name == 'notification.send':
                changed = True        # its effect is a database row, checked by the row's id in the result
            expected = cap.effect != 'read'
            out[name] = {'ok': changed == expected, 'effect': cap.effect, 'world_changed': changed,
                         'result_keys': sorted(result)[:12] if isinstance(result, dict) else type(result).__name__,
                         **({} if changed == expected else
                            {'error': ('the executor did not change the fake world' if expected
                                       else 'a read changed the fake world')})}
        except Exception as exc:                                    # noqa: BLE001
            out[name] = {'ok': False, 'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
        finally:
            W['cur'] = None
            world.discard()
    return out


async def prepare_db():
    sys.path.insert(0, str(ROOT))
    from tests._bootstrap import reset_db
    from agentic_core.database.base import async_session
    from aries.settings import SettingsService
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set('operator.enabled', True, set_by='user')
        await SettingsService(db).set('operator.settle_seconds', 0.3, set_by='user')
        await db.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest')
    ap.add_argument('--sealed', action='store_true')
    ap.add_argument('--label')
    ap.add_argument('--hardened', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--smoke', action='store_true')
    ap.add_argument('--selftest-out', default='selftest.json')
    cli = ap.parse_args()
    os.environ['ARIES_VERIFY_HARDENED'] = '1' if cli.hardened else '0'
    install_fakes()
    # As tests/test_agent_execution.py does: the engine executes real tools (file writes land in the
    # sandbox), and every desktop, network and system path is behind the fakes and the tripwires above.
    from agentic_core.config.settings import settings as engine_settings
    from aries.workspace.capabilities import TOOL_NAMES
    engine_settings.dry_run = False
    engine_settings.live_tools = ','.join(TOOL_NAMES)
    cases = build_cases()
    from aries.workspace.registry import registry
    missing = sorted(set(registry._items) - set(cases))
    if missing:
        raise SystemExit(f'cases missing for {missing}')
    asyncio.run(prepare_db())
    if cli.selftest:
        res = asyncio.run(selftest(cases))
        bad = {k: v for k, v in res.items() if not v['ok']}
        if (HERE / cli.selftest_out).exists():
            raise SystemExit(f'REFUSED: {cli.selftest_out} exists; earlier selftests are kept, pass a new --selftest-out')
        (HERE / cli.selftest_out).write_text(json.dumps({'when': now(), 'ok': len(res) - len(bad), 'failed': bad,
                                                        'all': res}, indent=1) + '\n')
        print(f'selftest: {len(res) - len(bad)}/{len(res)} executors ran against the fake world')
        for k, v in bad.items():
            print('  FAIL', k, v['error'])
        return
    if cli.sealed:
        path = HERE / 'sealed/mutants-sealed.json'
        want = (HERE / 'sealed/SEALED.sha256').read_text().split()[0]
        if sha(path.read_bytes()) != want:
            raise SystemExit('REFUSED: the sealed set does not match its committed SHA-256')
    else:
        path = Path(cli.manifest).resolve()
    manifest = json.loads(path.read_text())
    items = manifest['clean_replays'] + manifest['mutants']
    if cli.smoke:
        items = [i for i in manifest['clean_replays'] if i['capability'] in ('file.read', 'file.write')]
    out_dir = HERE / 'runs' / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{cli.label or ('smoke' if cli.smoke else 'run')}"
    out_dir.mkdir(parents=True)
    records = []

    async def go():
        for item in items:
            records.append(await run_item(item, cases, cli.hardened))
    asyncio.run(go())
    with (out_dir / 'records.jsonl').open('w') as f:
        for r in records:
            f.write(json.dumps(r, default=str) + '\n')
    (out_dir / 'run.json').write_text(json.dumps({
        'manifest': str(path.relative_to(ROOT)), 'manifest_sha256': sha(path.read_bytes()),
        'runner_sha256': sha(Path(__file__).read_bytes()), 'hardened': cli.hardened, 'smoke': cli.smoke,
        'items': len(items), 'finished_at': now()}, indent=1) + '\n')
    print(f'{len(records)} items -> {out_dir.relative_to(ROOT)}')
    shutil.rmtree(SCRATCH, ignore_errors=True)


if __name__ == '__main__':
    main()
