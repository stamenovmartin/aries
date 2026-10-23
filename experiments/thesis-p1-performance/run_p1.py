#!/usr/bin/env python3
"""P1 runner (docs/preregistration/P1-performance.md). Called by run-p1.sh inside one measurement window.

    run_p1.py decision --model M                     cold load, idle, then the decision workload with model M
    run_p1.py workload --model M --set S             (internal) R1b's treatment pipeline on the first 100 items of S
    run_p1.py phase NAME start|end                   (internal) a phase marker in raw/phases.jsonl

The decision workload is R1b's treatment (configuration C1: router, capability gate, planner; nothing is
executed) on the first 100 items, in manifest order, of the NL2Bash r1b and the CLINC150 r1b samples. Raw files
go to raw/ (not committed: they carry the item texts); phases.jsonl and the resource samples join on wall time."""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = HERE / 'raw'
OLLAMA = 'http://127.0.0.1:11434'
MODELS = ('qwen2.5:1.5b', 'qwen2.5:7b', 'llama3.1:8b', 'qwen2.5:14b')
N_ITEMS = 100
IDLE_S = 20


def phase(name, edge, **extra):
    RAW.mkdir(exist_ok=True)
    with (RAW / 'phases.jsonl').open('a') as f:
        f.write(json.dumps({'phase': name, 'edge': edge, 't': round(time.time(), 3), **extra}) + '\n')


def ollama(path, body=None, timeout=600):
    req = urllib.request.Request(OLLAMA + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b'{}')


def unload_all():
    for m in ollama('/api/ps').get('models', []):
        ollama('/api/generate', {'model': m['name'], 'keep_alive': 0})
    for _ in range(60):
        if not ollama('/api/ps').get('models'):
            return
        time.sleep(1)
    raise SystemExit('REFUSED: a model is still loaded after 60 s')


def decision(model):
    unload_all()
    phase(f'idle-unloaded:{model}', 'start'); time.sleep(IDLE_S); phase(f'idle-unloaded:{model}', 'end')
    phase(f'load:{model}', 'start')
    t0 = time.monotonic()
    ollama('/api/generate', {'model': model, 'prompt': '', 'keep_alive': '30m'})
    load_s = round(time.monotonic() - t0, 3)
    ps = ollama('/api/ps').get('models', [])
    phase(f'load:{model}', 'end', load_seconds=load_s,
          size_vram=[m.get('size_vram') for m in ps], size=[m.get('size') for m in ps])
    phase(f'idle-loaded:{model}', 'start'); time.sleep(IDLE_S); phase(f'idle-loaded:{model}', 'end')
    for s in ('nl2bash-r1b', 'clinc-r1b'):
        phase(f'workload:{model}:{s}', 'start')
        rc = subprocess.run([sys.executable, __file__, 'workload', '--model', model, '--set', s], cwd=ROOT).returncode
        phase(f'workload:{model}:{s}', 'end', returncode=rc)
        if rc:
            return rc
    unload_all()
    return 0


def workload(model, set_name):
    sys.path.insert(0, str(ROOT / 'experiments/thesis-r1b'))
    import asyncio
    import run_r1b
    full = run_r1b.items
    run_r1b.items = lambda name: full(name)[:N_ITEMS]
    run_r1b.RAW = RAW
    env = run_r1b.current_env
    run_r1b.current_env = lambda work, flags: env(HERE / 'storage' / work.name, flags)   # a fresh database per run
    treatment = json.loads((ROOT / 'experiments/thesis-r1b/configs.json').read_text())['treatment']
    args = argparse.Namespace(stage='aries', config=treatment, model=model, set=set_name, allow_dirty=False)
    asyncio.run(run_r1b.aries_stage(args))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['decision', 'workload', 'phase'])
    ap.add_argument('rest', nargs='*')
    ap.add_argument('--model', choices=MODELS)
    ap.add_argument('--set', choices=['nl2bash-r1b', 'clinc-r1b'])
    a = ap.parse_args()
    if a.stage == 'phase':
        phase(a.rest[0], a.rest[1])
        return 0
    if a.stage == 'decision':
        return decision(a.model)
    return workload(a.model, a.set)


if __name__ == '__main__':
    sys.exit(main())
