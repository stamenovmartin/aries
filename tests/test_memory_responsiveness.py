"""Slow background inference must not monopolise the API event loop."""
import asyncio
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-memory-responsiveness')
import numpy as np
from agentic_core.database.base import async_session
from aries.workspace.memory import store, extraction


class SlowEmbedder:
    dim = 2
    name = 'test-slow'
    def __init__(self):
        self.threads = []
    def passages(self, texts):
        self.threads.append(threading.get_ident())
        time.sleep(.08)
        return np.array([[1., 0.]] * len(texts), dtype=np.float32)
    def query(self, text):
        return self.passages([text])[0]


class SlowCascade:
    def __init__(self):
        self.threads = []
    def run(self, *args, **kwargs):
        self.threads.append(threading.get_ident())
        time.sleep(.08)
        return extraction.Verdict('ABORT', 'test', 'No memory write in this responsiveness check')


async def test_background_memory_yields():
    await reset_db()
    store.reset_cache()
    embedder, cascade = SlowEmbedder(), SlowCascade()
    ticks = []
    async def heartbeat():
        while True:
            ticks.append(time.monotonic())
            await asyncio.sleep(.01)
    pulse = asyncio.create_task(heartbeat())
    try:
        async with async_session() as db:
            cache = await store.warm(db, embedder=embedder)
            out = await store.observe(db, 'I prefer tea in the morning.', cascade=cascade)
            check('background decision is still honoured', out['stored'] is None)
            await store.record(db, 'I prefer tea.', cache=cache)
            await store.relevant(db, 'What drink do I prefer?', version='semantic-v3')
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
    main = threading.get_ident()
    check('embedding and retrieval run outside the event-loop thread',
          len(embedder.threads) >= 3 and all(t != main for t in embedder.threads))
    check('slow model classification runs outside the event-loop thread',
          cascade.threads and all(t != main for t in cascade.threads))
    check('unrelated API work can progress throughout memory inference', len(ticks) >= 10)


async def test_model_loading_yields():
    store.reset_cache()
    seen = []
    def load(name):
        seen.append(threading.get_ident())
        return SlowEmbedder()
    async with async_session() as db:
        with patch.object(store.embedding, 'get', load):
            await store.warm(db, name='test-slow')
    check('cold model loading does not run on the event loop', seen == [seen[0]] and seen[0] != threading.get_ident())


async def test_new_utterance_is_drained_during_inference():
    store._pending.clear()
    store._flusher = None
    started, release = asyncio.Event(), asyncio.Event()
    heard = []
    async def observe(db, text, **kwargs):
        heard.append(text)
        if len(heard) == 1:
            started.set()
            await release.wait()
    with patch.object(store, 'observe', observe):
        store.observe_later('first sentence', delay=0)
        await asyncio.wait_for(started.wait(), 2)
        store.observe_later('second sentence', delay=0)
        release.set()
        await asyncio.wait_for(store._flusher, 2)
    check('speech arriving during inference is processed without another wakeup',
          heard == ['first sentence', 'second sentence'] and not store._pending)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
