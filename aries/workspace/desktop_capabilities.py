"""Exact-window M15 operations through the existing compositor bridge.

An accepted request is only an execution observation. Verifiers re-read Mutter.
"""
import asyncio
import json
from pydantic import Field
from aries import flags
from aries.operator import desktop
from aries.workspace.capability_types import Capability, Input
from datetime import datetime, timezone

class Empty(Input):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()


class WindowInput(Input):
    window_id: str = Field(min_length=1, max_length=80)
    app_id: str = Field(min_length=1, max_length=200)


class MoveInput(WindowInput):
    x: int = Field(ge=-32768, le=32768)
    y: int = Field(ge=-32768, le=32768)


class ResizeInput(WindowInput):
    width: int = Field(ge=64, le=16384)
    height: int = Field(ge=64, le=16384)


class TileInput(WindowInput):
    # A named side rather than a rectangle: the caller does not know the work
    # area, and a voice command never will. The shell owns that arithmetic
    # because only the compositor knows what the panel and dock are covering.
    side: str = Field(pattern=r'^(left|right|top|bottom|topleft|topright|bottomleft|bottomright|full)$')


class DesktopCapabilityError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.retryable = False


async def observe(args, ctx):
    windows, why, shell = await asyncio.to_thread(desktop.read_windows)
    if windows is None:
        raise DesktopCapabilityError('CAPABILITY_UNAVAILABLE', why)
    return {'windows': [{**w.as_dict(), 'window_id':w.id, 'application':w.app_id,
                         'minimized':w.minimised} for w in windows],
            'observed_at':now(), 'source':'GNOME/Mutter', 'shell':shell}


async def verify_observe(args, result, ctx):
    return {'met':True,'type':'desktop_state','data':await observe(args,ctx)}


def executor(action):
    async def execute(args, ctx):
        discovery = await asyncio.to_thread(desktop.capabilities)
        if discovery.get('compatibility') != 'compatible' or action not in discovery.get('window_actions', []):
            raise DesktopCapabilityError('CAPABILITY_UNAVAILABLE', 'Active GNOME bridge does not support '+action)
        before = await observe({},ctx)
        targets = [w for w in before['windows'] if w['window_id']==args['window_id'] and w['app_id']==args['app_id']]
        if len(targets) != 1:
            raise DesktopCapabilityError('TARGET_NOT_FOUND','Exact observed window identity is unavailable')
        payload, why = await asyncio.to_thread(desktop._call_shell, 'WindowAction', args=(json.dumps({**args,'id':args['window_id'],'action':action}),))
        if payload is None:
            raise DesktopCapabilityError('CAPABILITY_UNAVAILABLE', why)
        data = json.loads(payload)
        if data.get('accepted') is not True:
            raise DesktopCapabilityError(data.get('code','NON_RETRYABLE'),data.get('reason','Window request refused'))
        result = {'requested':action,'target':targets[0],'response':data}
        if action == 'tile' and flags.enabled('ARIES_TILE_HIDPI'):
            # The shell computes its rectangle from the work area at scale 1. On a
            # fractionally scaled monitor Mutter then places the window on whole
            # DEVICE pixels, so the rectangle it reports back and the rectangle
            # the window ends up at can differ by a pixel and a correct tile would
            # be verified as unconfirmed. Read the scale and say which rectangle
            # was expected, so the verifier below can accept the right one.
            # Never fatal: the tile already happened. A scale that cannot be read
            # leaves the verification exactly where it was before A10 rather than
            # turning a placed window into an error.
            try:
                result['scaling'] = await asyncio.to_thread(desktop.tile_expectation, targets[0], args['side'])
            except Exception as exc:                                  # noqa: BLE001
                result['scaling'] = {'side': args['side'], 'rect': None, 'scale': None,
                                     'why': 'the monitor scale could not be read (%s: %s)'
                                            % (type(exc).__name__, exc)}
        return result
    return execute


def verifier(action):
    async def verify(args, result, ctx):
        for attempt in range(10):
            state = await observe({},ctx)
            rows = [w for w in state['windows'] if w['window_id']==args['window_id']]
            target = next((w for w in rows if w['app_id']==args['app_id']),None)
            met = not rows if action=='close' else False
            if target:
                if action=='focus': met=target['focused'] and not target['minimized']
                if action=='minimize': met=target['minimized']
                if action=='maximize': met=target.get('maximized') is True
                if action=='unmaximize': met=target.get('maximized') is False
                if action in {'move','resize'}:
                    keys = ('x','y') if action=='move' else ('width','height')
                    met=all(target.get('geometry',{}).get(k)==args[k] for k in keys)
                if action=='tile':
                    # The shell reports the rectangle it computed; verification is
                    # that Mutter actually placed the window there. Trusting
                    # accepted=true would verify that we asked, not that it moved.
                    # Two EXACT candidates, never a tolerance: the rectangle the
                    # shell computed, and the device-pixel-aligned one for this
                    # monitor's scale factor. They are the same rectangle at every
                    # integer scale, so the second only ever matters on HiDPI.
                    wanted=[r for r in ((result or {}).get('response',{}).get('expected'),
                                        ((result or {}).get('scaling') or {}).get('rect')) if r]
                    met=any(all(target.get('geometry',{}).get(k)==r[k]
                                for k in ('x','y','width','height')) for r in wanted)
            if met or attempt==9:
                return {'met':met,'type':'desktop_state','data':{**state,'requested':action,'target':target}}
            await asyncio.sleep(.1)
    return verify


def register(registry):
    for name in ('windows','observe'):
        registry.register(Capability('desktop.'+name,'Observe authoritative GNOME windows; unavailable is an error',Empty,observe,verify_observe))
    for action, schema in [('close',WindowInput),('move',MoveInput),('resize',ResizeInput),('maximize',WindowInput),('unmaximize',WindowInput),('minimize',WindowInput),('tile',TileInput)]:
        registry.register(Capability('desktop.'+action,
            'Operate on an exact observed window ID and application identity'
            + ('. The rectangle is computed by the shell from the monitor work area and verified '
               'against the monitor scale factor, so a tile on a fractionally scaled display is '
               'not reported unconfirmed (ARIES_TILE_HIDPI)' if action=='tile' else ''),
            schema,executor(action),verifier(action),effect='desktop',requires_approval=action=='close'))
