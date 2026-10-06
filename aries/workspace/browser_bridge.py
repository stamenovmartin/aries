"""Private Unix-socket bridge to the owned user browser service."""
import asyncio
import json
import os
from pathlib import Path


def socket_path():
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'aries-browser.sock'


async def request(method, *args):
    path = socket_path()
    if method == 'open_page':
        if len(args) == 1:
            args = (*args, '')
        from aries.workspace.capabilities import command
        root = Path(__file__).resolve().parents[2]
        code, _, error = await command(['systemd-run', '--user', '--collect', '--quiet', '--unit=aries-browser-worker',
            '--property=RuntimeMaxSec=7200', '--property=MemoryMax=1G', '--property=TasksMax=128',
            '--working-directory='+str(root), '--setenv=PYTHONPATH='+str(root/'vendor/agentic-core')+':'+str(root/'vendor')+':'+str(root),
            '--', str(root/'.venv/bin/python'), '-m', 'aries.workspace.browser_worker'], timeout=10)
        if code and not path.exists():
            raise ValueError('Browser worker could not start: '+error[:200])
        for _ in range(30):
            if path.exists():
                break
            await asyncio.sleep(0.1)
    try:
        reader, writer = await asyncio.open_unix_connection(str(path), limit=128000)
    except (OSError, asyncio.TimeoutError):
        if method == 'inventory':
            return []
        if method == 'close_all':
            return None
        raise ValueError('The owned browser session is unavailable; open its website again') from None
    try:
        writer.write(json.dumps({'method':method,'args':args}).encode()+b'\n')
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), 100)
        result = json.loads(raw)
        if result.get('error'):
            raise ValueError(result['error'])
        return result.get('result')
    finally:
        writer.close()
        await writer.wait_closed()
