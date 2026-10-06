"""Read-only, shared snapshots for the visible system monitor."""
import asyncio
import time
from datetime import datetime, timezone
from aries.health.probes import run_all
_lock = asyncio.Lock()
_cached = None
_at = 0.0

async def snapshot():
    global _cached, _at
    async with _lock:
        if _cached is None or time.monotonic() - _at > 3:
            probes = await run_all(['cpu','memory','disk','thermal','gpu'])
            _cached = {'measured_at':datetime.now(timezone.utc).isoformat(),
                       'probes':[p.as_dict() for p in probes]}
            _at = time.monotonic()
        return _cached
