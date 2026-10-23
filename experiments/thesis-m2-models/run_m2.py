#!/usr/bin/env python3
"""M2 runner (docs/preregistration/M2-local-models.md): R1b's systems with another local model.

    run_m2.py aries|frozen|frozen-planner --model llama3.1:8b --set nl2bash-r1b|clinc-r1b
    run_m2.py zeroshot                    --model llama3.1:8b --set nl2bash-r1b|clinc-r1b

T and F are R1b's stages, called with --model (T is the R1b treatment configuration). The zero-shot stage is
R1's request (same instruction, schema and options) with the model named instead of qwen2.5:7b. Raw files go to
experiments/thesis-r1b/raw/ and carry the model in their names; nothing is overwritten."""
import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
R1B = ROOT / 'experiments/thesis-r1b'
sys.path.insert(0, str(R1B))
sys.path.insert(0, str(ROOT / 'experiments/thesis-r1-real-data'))
import run_r1  # noqa: E402

MODELS = ('llama3.1:8b', 'qwen2.5:1.5b', 'qwen2.5:14b')


async def zeroshot(args):
    import httpx
    import run_r1b
    run_r1.items, run_r1.RAW = run_r1b.items, run_r1b.RAW
    path = run_r1.dest('zeroshot', args)
    schema = {'type': 'object', 'properties': {'label': {'type': 'string', 'enum': run_r1.LABELS}}, 'required': ['label']}
    meta = await run_r1.model_meta(args.model)
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        with path.open('x') as out:
            run_r1.header(out, 'zeroshot', args, {'model_before': meta, 'runner': 'thesis-m2-models/run_m2.py',
                                                  'runner_sha256': run_r1.sha(__file__),
                                                  'system_sha256': hashlib.sha256(run_r1.ZEROSHOT_SYSTEM.encode()).hexdigest()})
            for key, text in run_r1.items(args.set):
                row, t0 = {'id': key, 'started_at': run_r1.stamp()}, time.monotonic()
                try:
                    r = await client.post(run_r1.OLLAMA + '/api/chat', json={
                        'model': args.model, 'stream': False, 'format': schema,
                        'options': {'temperature': 0.1, 'top_p': 0.9, 'num_ctx': 8192, 'num_predict': 60},
                        'messages': [{'role': 'system', 'content': run_r1.ZEROSHOT_SYSTEM}, {'role': 'user', 'content': text}]})
                    r.raise_for_status()
                    content = r.json()['message']['content']
                    row.update(raw=content, label=json.loads(content)['label'])
                except Exception as exc:
                    row['error'] = type(exc).__name__ + ': ' + str(exc)[:300]
                row['seconds'] = round(time.monotonic() - t0, 4)
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
                out.flush()
            out.write(json.dumps({'footer': True, 'finished_at': run_r1.stamp(),
                                  'model_after': await run_r1.model_meta(args.model)}) + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['aries', 'frozen', 'frozen-planner', 'zeroshot'])
    ap.add_argument('--model', required=True, choices=MODELS)
    ap.add_argument('--set', required=True, choices=['nl2bash-r1b', 'clinc-r1b'])
    args = ap.parse_args()
    if args.stage == 'zeroshot':
        asyncio.run(zeroshot(args))
        return 0
    treatment = json.loads((R1B / 'configs.json').read_text())['treatment']
    extra = ['--config', treatment] if args.stage == 'aries' else []
    return subprocess.run([sys.executable, str(R1B / 'run_r1b.py'), args.stage, *extra, '--model', args.model,
                           '--set', args.set], cwd=ROOT).returncode


if __name__ == '__main__':
    sys.exit(main())
