"""Bridge compatibility and exact-state negative controls; no live claims."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-m15-desktop')
from aries.operator import desktop
from aries.workspace import desktop_capabilities as caps
from aries.workspace.registry import registry


def bridge(methods):
    return SimpleNamespace(returncode=0,stdout='<node><interface name="org.aries.Shell">'+''.join('<method name="'+m+'"/>' for m in methods)+'</interface></node>')


async def test_protocol():
    with patch.object(desktop.subprocess,'run',return_value=bridge(['Ping','Windows'])):
        state=desktop.capabilities()
        check('old bridge explicitly legacy',state['compatibility']=='legacy' and 'FocusWindow' in state['missing'])
    methods=['Ping','Windows','FocusWindow','WindowAction','Capabilities']
    with patch.object(desktop.subprocess,'run',return_value=bridge(methods)), patch.object(desktop,'_call_shell',return_value=(json.dumps({'protocol_version':3,'capabilities':methods,'window_actions':['focus','move']}),'')):
        check('v3 handshake',desktop.capabilities()['compatibility']=='compatible')
    with patch.object(desktop.subprocess,'run',return_value=bridge(methods)), patch.object(desktop,'_call_shell',return_value=(json.dumps({'protocol_version':99,'capabilities':methods,'window_actions':['focus']}),'')):
        check('future version fails closed',desktop.capabilities()['compatibility']=='incompatible')


async def test_observation_and_state():
    with patch.object(desktop,'_call_shell',return_value=(json.dumps({'error':'observer failed'}),'')):
        check('observer exception is not an empty desktop',desktop.read_windows()[0] is None)
    row={'id':'42','app_id':'editor.desktop','focused':False,'minimised':False,'geometry':{'x':0,'y':32,'width':960,'height':700},'maximized':False}
    with patch.object(desktop,'_call_shell',return_value=(json.dumps({'windows':[row]}),'')):
        window=desktop.read_windows()[0][0]
        check('geometry comes from observation',window.geometry['height']==700)
    args={'window_id':'42','app_id':'editor.desktop'}
    with patch.object(caps,'observe',return_value={'windows':[{**row,'window_id':'42','minimized':False}]}),patch.object(caps.asyncio,'sleep'):
        check('accepted focus is not proof',not (await caps.verifier('focus')(args,{'accepted':True},{}))['met'])
    with patch.object(caps,'observe',return_value={'windows':[]}),patch.object(caps.asyncio,'sleep'):
        check('missing focus target cannot pass',not (await caps.verifier('focus')(args,{},{}))['met'])
        check('closed target independently absent',(await caps.verifier('close')(args,{},{}))['met'])
    check('close requires approval',registry.get('desktop.close').requires_approval)
    with patch.object(desktop,'capabilities',return_value={'compatibility':'legacy'}):
        try: await caps.executor('move')({**args,'x':10,'y':10},{})
        except caps.DesktopCapabilityError as exc: check('unsupported typed error',exc.code=='CAPABILITY_UNAVAILABLE')
        else: check('unsupported rejected',False)


if __name__=='__main__':run_module(sys.modules[__name__])
