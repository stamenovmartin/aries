"""Owned browser lifecycle outside the core service's namespace restrictions."""
import asyncio
import json
import os
import signal
os.environ['ARIES_BROWSER_WORKER'] = '1'
from aries.workspace import browser
from aries.workspace.browser_bridge import socket_path


async def main():
    path = socket_path()
    if path.exists():
        path.unlink()
    stop = asyncio.Event()
    methods = {'open_page':2, 'observe':1, 'follow':2, 'fill':3, 'close':1, 'close_all':0, 'inventory':0, 'elements':1, 'click_element':2, 'type_element':3, 'element_value':2, 'navigate_page':2, 'history_page':2, 'scroll_page':2, 'wait_page':2}
    async def handle(reader, writer):
        task = disconnected = None
        try:
            payload = json.loads(await asyncio.wait_for(reader.readline(), 5))
            method, args = payload['method'], payload['args']
            if method not in methods or len(args) != methods[method] or any(not isinstance(a,str) or len(a)>4000 for a in args):
                raise ValueError('Invalid browser operation')
            task = asyncio.create_task(getattr(browser, method)(*args))
            disconnected = asyncio.create_task(reader.read(1))
            done, _ = await asyncio.wait([task, disconnected], return_when=asyncio.FIRST_COMPLETED)
            if task not in done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return
            result = await task
            writer.write(json.dumps({'result':result}).encode()+b'\n')
            await writer.drain()
            if method == 'close_all':
                stop.set()
        except Exception as exc:
            writer.write(json.dumps({'error':str(exc)[:600]}).encode()+b'\n')
            await writer.drain()
        finally:
            if disconnected:
                disconnected.cancel()
                await asyncio.gather(disconnected, return_exceptions=True)
            writer.close()
            await writer.wait_closed()
    old = os.umask(0o077)
    try:
        server = await asyncio.start_unix_server(handle, path=str(path), limit=16000)
    finally:
        os.umask(old)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        async with server:
            await stop.wait()
    finally:
        await browser.close_all()
        path.unlink(missing_ok=True)


if __name__ == '__main__':
    asyncio.run(main())
