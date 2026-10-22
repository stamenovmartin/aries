#!/usr/bin/env python3
"""R1 runs (docs/preregistration/R1-real-data-benchmarks.md, Amendments 1-2). Written before any run.

One stage per process, each writing raw/<stage>.jsonl (refuses to overwrite):

    run_r1.py router   --model qwen2.5:7b --arm A1 --set nl2bash-test|clinc
    run_r1.py planner  --model qwen2.5:7b --set nl2bash-test        (only the items the router acts on)
    run_r1.py zeroshot --set nl2bash-test|clinc                     (qwen2.5:7b, no ARIES structure)
    run_r1.py embedding --set nl2bash|clinc-val|clinc               (e5-base-int8 scores for every label)
    run_r1.py bm25 --set nl2bash                                    (BM25 scores over the 58 descriptions)

The router and planner stages run the frozen ARIES-FINAL-20261006 source (verified against its
source-manifest.json), configured like H6 (router) and the frozen planner evaluation (planner). Nothing is
executed: the router classifies and the planner proposes one next action. Request texts are read from the
local sample files; raw outputs carry ids, decisions and timings.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import CAPABILITIES, DATA, LABELS, LOCAL, OOS, check_data, jsonl  # noqa: E402

FINAL = HERE.parent / 'thesis-final-20261006'
FROZEN = FINAL / 'frozen'
H6 = HERE.parent / 'thesis-followup-20261012' / 'h6-run'
RAW = HERE / 'raw'
OLLAMA = 'http://127.0.0.1:11434'
ROUTER_SETTINGS = {
    'intelligence.location': 'local', 'intelligence.local_url': OLLAMA, 'intelligence.gateway_enabled': False,
    'intelligence.cloud_enabled': False, 'intelligence.local_confidence_threshold': 0.82,
    'workspace.controlled_browser': False, 'ai.temperature': 0.1, 'ai.top_p': 0.9, 'ai.context_tokens': 8192,
    'ai.max_output_tokens': 450,
}
PRECONDITION = 'No action has run; no current observation is available.'
ZEROSHOT_SYSTEM = (
    'You choose which capability an assistant should call first. The assistant can act only through the '
    'capabilities below. Choose the one capability the assistant would use as the first step to fulfil the '
    'request completely, using only listed capabilities. If the listed capabilities cannot fulfil the request '
    f'completely, choose {OOS}. Answer with JSON {{"label": "<label>"}}.\n\nCapabilities:\n'
    + '\n'.join(f'- {k}: {v}' for k, v in CAPABILITIES.items())
    + f'\n- {OOS}: the listed capabilities cannot fulfil the request completely')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def items(name):
    """(id, text) for a set. nl2bash-* from the NL2Bash sample; clinc from the frozen CLINC sample; clinc-val
    from CLINC val + oos_val (threshold only)."""
    if name.startswith('nl2bash'):
        rows = jsonl(LOCAL / 'nl2bash_sample.jsonl')
        split = name.split('-', 1)[1] if '-' in name else None
        return [(r['id'], r['text']) for r in rows if split in (None, r['split'])]
    if name == 'clinc':
        return [(r['id'], r['text']) for r in jsonl(LOCAL / 'clinc_sample.jsonl')]
    if name == 'clinc-val':
        data = json.loads((DATA / 'clinc150/data_full.json').read_text())
        return [(f'cv-{i:05d}', t) for i, (t, _) in enumerate(data['val'] + data['oos_val'])]
    raise SystemExit(f'unknown set {name}')


def dest(stage, args):
    parts = [stage] + [str(x) for x in (getattr(args, 'model', None), getattr(args, 'arm', None)) if x] + [args.set]
    path = RAW / (re.sub(r'[^A-Za-z0-9-]+', '_', '-'.join(parts)) + '.jsonl')
    if path.exists():
        raise SystemExit(f'REFUSED: {path} exists')
    RAW.mkdir(exist_ok=True)
    return path


def verify_frozen():
    manifest = json.loads((FINAL / 'source-manifest.json').read_text())
    bad = [n for n, d in manifest['files'].items() if sha(FROZEN / n) != d]
    if bad:
        raise SystemExit(f'REFUSED: frozen source differs: {bad[:5]}')
    return {'files': len(manifest['files']), 'manifest_sha256': sha(FINAL / 'source-manifest.json')}


def frozen_env(work, flag_file, extra=None):
    work.mkdir(parents=True, exist_ok=True)
    os.environ.update(APP_ENV='test', DATABASE_URL='sqlite+aiosqlite:///' + str(work / 'r1.sqlite3'),
                      DATA_DIR=str(work / 'runtime'), RUNTIME_STORE=str(work / 'runtime/state.json'),
                      CONTEXT_DIR=str(work / 'context'), API_KEY='', CREDENTIALS_KEY='', OPENAI_API_KEY='',
                      ANTHROPIC_API_KEY='', ARIES_CLOUD_API_KEY='', AI_PROVIDER='ollama', DRY_RUN='true',
                      LIVE_TOOLS='', ARIES_FLAG_FILE=str(flag_file), SCHEDULER_ENABLED='false',
                      LEARNING_NIGHTLY_ENABLED='false', **(extra or {}))
    sys.dont_write_bytecode = True
    os.chdir(FROZEN)
    sys.path[:0] = [str(FROZEN), str(FROZEN / 'vendor'), str(FROZEN / 'vendor/agentic-core')]


async def model_meta(model):
    import httpx
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        tags = (await client.get(OLLAMA + '/api/tags')).json()
        version = (await client.get(OLLAMA + '/api/version')).json().get('version')
    m = next(m for m in tags['models'] if m['name'] == model)
    return {'model': model, 'digest': m['digest'], 'ollama': version}


def header(out, stage, args, extra):
    out.write(json.dumps({'header': True, 'stage': stage, 'args': vars(args), 'started_at': stamp(),
                          'runner_sha256': sha(__file__), 'common_sha256': sha(HERE / 'common.py'),
                          'capabilities_sha256': sha(HERE / 'capabilities.json'), **extra}) + '\n')


async def router_stage(args):
    source = verify_frozen()
    frozen_hashes = json.loads((FINAL / 'protocol.json').read_text())['hashes']
    prompt = (H6 / 'prompts' / f'{args.arm}.txt').read_text()
    if hashlib.sha256(prompt.encode()).hexdigest() != frozen_hashes[args.arm]:
        raise SystemExit('REFUSED: the router prompt differs from the frozen protocol')
    path = dest('router', args)
    frozen_env(LOCAL / 'storage' / path.stem, FINAL / 'frozen-flags.env')
    from agentic_core.database.base import Base, async_session, engine
    from aries.settings import SettingsService
    from aries.intelligence import local_structured, router
    from aries.intelligence.schemas import Decision
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        s = SettingsService(db)
        for k, v in {**ROUTER_SETTINGS, 'intelligence.local_model': args.model}.items():
            await s.set(k, v, set_by='user')
        await db.commit()

    class FrozenProvider(router.LocalLLMDecisionProvider):
        def instruction(self):
            return prompt

        async def decide(self, db, text):
            self.raw, self.usage = await local_structured(
                db, [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': text}],
                Decision.model_json_schema(), purpose='intelligence.route', max_tokens=450)
            return Decision.model_validate_json(self.raw)

    meta = await model_meta(args.model)
    with path.open('x') as out:
        header(out, 'router', args, {'source': source, 'model_before': meta, 'prompt_sha256': frozen_hashes[args.arm]})
        for i, (key, text) in enumerate(items(args.set), 1):
            provider, t0 = FrozenProvider(), time.monotonic()
            row = {'id': key, 'started_at': stamp()}
            async with async_session() as db:
                try:
                    row.update((await router.route(db, text, provider=provider, allow_contract=True)).model_dump())
                except Exception as exc:
                    row['error'] = type(exc).__name__ + ': ' + str(exc)[:500]
            row.update(seconds=round(time.monotonic() - t0, 4), provider_raw=getattr(provider, 'raw', None))
            out.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
            out.flush()
            if i % 50 == 0:
                print(f'{stamp()} router {args.model} {args.arm} {args.set} {i}', flush=True)
        out.write(json.dumps({'footer': True, 'finished_at': stamp(), 'model_after': await model_meta(args.model),
                              'source_after': verify_frozen()}) + '\n')
    await engine.dispose()


async def planner_stage(args):
    source = verify_frozen()
    protocol = json.loads((FINAL / 'planner' / 'protocol.json').read_text())
    acts = [json.loads(l) for l in Path(args.router_file).read_text().splitlines()]
    acts = {r['id'] for r in acts if 'id' in r and router_acts(r)}
    path = dest('planner', args)
    work = LOCAL / 'storage' / path.stem
    work.mkdir(parents=True, exist_ok=True)
    (work / 'flags.env').write_text('# Private R1 planner evaluation; no shared overrides.\n')
    frozen_env(work, work / 'flags.env', {'ARIES_PRIMARY_LANG': 'en', **protocol['flags']})
    from agentic_core.database.base import Base, async_session, engine
    from aries.api.app import app  # noqa: F401  (registers the 58 capabilities; no server starts)
    from aries.settings import SettingsService
    from aries.workspace import agent_planner
    if len(agent_planner.scoped_capabilities()) != 58:
        raise SystemExit('REFUSED: the frozen planner scope is not 58 capabilities')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        s = SettingsService(db)
        for k, v in {**protocol['settings'], 'intelligence.local_model': args.model}.items():
            await s.set(k, v, set_by='user')
        await db.commit()
    data = {'routing': {'execution_level': 'local', 'reason': 'Prespecified offline planner evaluation',
                        'no_fallback': True}, 'steps': [], 'evidence': [],
            'agent': {'contract': {'supported': False, 'requirements': [],
                                   'reason': 'Offline next-action evaluation; no completion-contract hints supplied.'},
                      'context': {}, 'environment': {'fixture_precondition': PRECONDITION,
                                                     'source': 'R1 offline evaluation; not current OS observations'}}}
    meta = await model_meta(args.model)
    with path.open('x') as out:
        header(out, 'planner', args, {'source': source, 'model_before': meta,
                                      'planner_protocol_sha256': sha(FINAL / 'planner' / 'protocol.json'),
                                      'router_file_sha256': sha(args.router_file)})
        for key, text in items(args.set):
            if key not in acts:
                continue
            row, t0 = {'id': key, 'started_at': stamp()}, time.monotonic()
            async with async_session() as db:
                try:
                    raw, usage = await agent_planner.plan(db, text, json.loads(json.dumps(data)), 8)
                    row.update(raw_output=raw, decision=agent_planner.parse(raw).model_dump())
                except Exception as exc:
                    row['error'] = type(exc).__name__ + ': ' + str(exc)[:500]
            row['seconds'] = round(time.monotonic() - t0, 4)
            out.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
            out.flush()
        out.write(json.dumps({'footer': True, 'finished_at': stamp(), 'model_after': await model_meta(args.model),
                              'source_after': verify_frozen()}) + '\n')
    await engine.dispose()


def router_acts(r):
    """The frozen act rule (thesis-final-20261006/analyze_router.py: valid and not ASK/OUT_OF_SCOPE/UNKNOWN)."""
    valid = not r.get('error') and r.get('source') != 'fallback' and bool(r.get('intent'))
    return valid and r.get('intent') not in {'ASK', 'OUT_OF_SCOPE', 'UNKNOWN'}


async def zeroshot_stage(args):
    import httpx
    path = dest('zeroshot', args)
    model = 'qwen2.5:7b'
    schema = {'type': 'object', 'properties': {'label': {'type': 'string', 'enum': LABELS}}, 'required': ['label']}
    meta = await model_meta(model)
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        with path.open('x') as out:
            header(out, 'zeroshot', args, {'model_before': meta,
                                           'system_sha256': hashlib.sha256(ZEROSHOT_SYSTEM.encode()).hexdigest()})
            for key, text in items(args.set):
                row, t0 = {'id': key, 'started_at': stamp()}, time.monotonic()
                try:
                    r = await client.post(OLLAMA + '/api/chat', json={
                        'model': model, 'stream': False, 'format': schema,
                        'options': {'temperature': 0.1, 'top_p': 0.9, 'num_ctx': 8192, 'num_predict': 60},
                        'messages': [{'role': 'system', 'content': ZEROSHOT_SYSTEM}, {'role': 'user', 'content': text}]})
                    r.raise_for_status()
                    content = r.json()['message']['content']
                    row.update(raw=content, label=json.loads(content)['label'])
                except Exception as exc:
                    row['error'] = type(exc).__name__ + ': ' + str(exc)[:300]
                row['seconds'] = round(time.monotonic() - t0, 4)
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
                out.flush()
            out.write(json.dumps({'footer': True, 'finished_at': stamp(), 'model_after': await model_meta(model)}) + '\n')


def passages():
    return [f'{k}: {v}' for k, v in CAPABILITIES.items()]


def embedding_stage(args):
    sys.path[:0] = [str(HERE.parents[1]), str(HERE.parents[1] / 'vendor'), str(HERE.parents[1] / 'vendor/agentic-core')]
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    import numpy as np
    from aries.workspace.memory import embedding
    path = dest('embedding', args)
    emb = embedding.get('e5-base-int8')
    caps = np.asarray(emb.passages(passages()), dtype=np.float32)
    caps /= np.linalg.norm(caps, axis=1, keepdims=True)
    with path.open('x') as out:
        header(out, 'embedding', args, {'embedder': 'e5-base-int8'})
        for key, text in items(args.set):
            q = np.asarray(emb.query(text), dtype=np.float32)
            sims = caps @ (q / np.linalg.norm(q))
            out.write(json.dumps({'id': key, 'scores': [round(float(x), 6) for x in sims]}) + '\n')
        out.write(json.dumps({'footer': True, 'finished_at': stamp()}) + '\n')


def tokens(text):
    return re.findall(r'[a-z0-9]+', text.lower())


def bm25_scores(query, docs, k1=1.5, b=0.75):
    toks = [tokens(d) for d in docs]
    avg = sum(map(len, toks)) / len(toks)
    df = Counter(t for d in toks for t in set(d))
    n = len(docs)
    out = []
    for d in toks:
        tf = Counter(d)
        s = 0.0
        for t in set(tokens(query)):
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        out.append(s)
    return out


def bm25_stage(args):
    path = dest('bm25', args)
    docs = passages()
    with path.open('x') as out:
        header(out, 'bm25', args, {'k1': 1.5, 'b': 0.75})
        for key, text in items(args.set):
            out.write(json.dumps({'id': key, 'scores': [round(x, 6) for x in bm25_scores(text, docs)]}) + '\n')
        out.write(json.dumps({'footer': True, 'finished_at': stamp()}) + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['router', 'planner', 'zeroshot', 'embedding', 'bm25'])
    ap.add_argument('--set', required=True)
    ap.add_argument('--model')
    ap.add_argument('--arm', choices=['A0', 'A1'])
    ap.add_argument('--router-file')
    args = ap.parse_args()
    if args.router_file:  # router and planner stages chdir into the frozen source
        args.router_file = str(Path(args.router_file).resolve())
    check_data()
    if args.stage == 'router':
        asyncio.run(router_stage(args))
    elif args.stage == 'planner':
        asyncio.run(planner_stage(args))
    elif args.stage == 'zeroshot':
        asyncio.run(zeroshot_stage(args))
    elif args.stage == 'embedding':
        embedding_stage(args)
    else:
        bm25_stage(args)


if __name__ == '__main__':
    main()
