"""Core-side lifecycle boundary for the system AT-SPI worker."""
import asyncio
import json
from pathlib import Path


async def inspect_app(app, *, activation=None):
    if not isinstance(app, str) or not app.strip() or len(app) > 160 or "\x00" in app:
        raise ValueError("Choose an application name of at most 160 characters")
    worker = Path(__file__).with_name("accessibility_bridge.py")
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/python3", "-I", str(worker), app.strip(), *(['activate'] if activation else []),
        stdin=asyncio.subprocess.PIPE if activation else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        if activation:
            output, _ = await asyncio.wait_for(proc.communicate(json.dumps(activation).encode()), 7)
        else:
            output, _ = await asyncio.wait_for(proc.communicate(), 7)
    except asyncio.TimeoutError:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        return {"available": False, "nodes": [], "error": "Accessibility observation timed out"}
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise
    if proc.returncode or len(output) > 64000:
        return {"available": False, "nodes": [], "error": "Accessibility worker failed"}
    try:
        return json.loads(output)
    except (ValueError, UnicodeError):
        return {"available": False, "nodes": [], "error": "Invalid accessibility response"}
