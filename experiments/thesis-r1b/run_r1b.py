#!/usr/bin/env python3
"""R1b runs (docs/preregistration/R1b-improved-router-planner.md): the R1 protocol on new samples, with the
current ARIES source and a named flag configuration.

    run_r1b.py aries     --config C1 --set nl2bash-dev|nl2bash-r1b|clinc-r1b [--model qwen2.5:7b]
    run_r1b.py frozen    --set nl2bash-r1b|clinc-r1b [--arm A1]     (R1's frozen ARIES router)
    run_r1b.py frozen-planner --set nl2bash-r1b                     (R1's frozen planner on the router's acts)
    run_r1b.py zeroshot  --set nl2bash-r1b|clinc-r1b
    run_r1b.py embedding --set nl2bash-r1b|clinc-r1b
    run_r1b.py bm25      --set nl2bash-r1b

One process per stage, each writing raw/<stage>-<config>-<set>.jsonl (refuses to overwrite). The `aries` stage
routes each request with the current router (the A1 abstention instruction plus the configuration's flags) and,
when the frozen act rule says the router acts, asks the planner for one next action, exactly as R1 did in two
stages. Nothing is executed. The configurations are in configs.json; the zero-shot, embedding and BM25 stages are
R1's own functions (thesis-r1-real-data/run_r1.py), pointed at the new samples. Request texts are read from
~/data-ext/r1b (local, never committed); raw outputs carry ids, decisions and timings.
"""
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
R1 = REPO / 'experiments' / 'thesis-r1-real-data'
sys.path.insert(0, str(R1))
import run_r1  # noqa: E402
from common import DATA, check_data, jsonl  # noqa: E402

LOCAL = DATA / 'r1b'
RAW = HERE / 'raw'
CONFIGS = json.loads((HERE / 'configs.json').read_text())
# The frozen planner protocol of ARIES-FINAL-20261006 (settings and context flags); R1 used the same.
PLANNER_PROTOCOL = Path.home() / 'aries/experiments/thesis-final-20261006/planner/protocol.json'


def items(name):
    if name == 'nl2bash-dev':
        return [(r['id'], r['text']) for r in jsonl(DATA / 'r1' / 'nl2bash_sample.jsonl') if r['split'] == 'dev']
    if name == 'clinc-dev':
        # 150 CLINC val + oos_val utterances (seed 20261101), for development only; R1 used val for its threshold.
        import random
        data = json.loads((DATA / 'clinc150/data_full.json').read_text())
        pool = [(f'cv-{i:05d}', t) for i, (t, _) in enumerate(data['val'] + data['oos_val'])]
        return random.Random(20261101).sample(pool, 150)
    if name == 'nl2bash-r1b':
        return [(r['id'], r['text']) for r in jsonl(LOCAL / 'nl2bash_sample.jsonl')]
    if name == 'clinc-r1b':
        return [(r['id'], r['text']) for r in jsonl(LOCAL / 'clinc_sample.jsonl')]
    raise SystemExit(f'unknown set {name}')


def dest(stage, args):
    parts = [stage] + [str(x) for x in (getattr(args, 'config', None), getattr(args, 'model', None)) if x] + [args.set]
    path = RAW / ('-'.join(p.replace(':', '_').replace('.', '_') for p in parts) + '.jsonl')
    if path.exists():
        raise SystemExit(f'REFUSED: {path} exists')
    RAW.mkdir(exist_ok=True)
    return path


def git_state():
    head = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', str(REPO), 'status', '--porcelain', '--', 'aries', 'vendor'],
                           capture_output=True, text=True).stdout.strip()
    return {'commit': head, 'aries_source_clean': not dirty}


def current_env(work, flags):
    work.mkdir(parents=True, exist_ok=True)
    (work / 'flags.env').write_text('# Private R1b evaluation; flags come from the environment.\n')
    os.environ.update(APP_ENV='test', DATABASE_URL='sqlite+aiosqlite:///' + str(work / 'r1b.sqlite3'),
                      DATA_DIR=str(work / 'runtime'), RUNTIME_STORE=str(work / 'runtime/state.json'),
                      CONTEXT_DIR=str(work / 'context'), API_KEY='', CREDENTIALS_KEY='', OPENAI_API_KEY='',
                      ANTHROPIC_API_KEY='', ARIES_CLOUD_API_KEY='', AI_PROVIDER='ollama', DRY_RUN='true',
                      LIVE_TOOLS='', ARIES_FLAG_FILE=str(work / 'flags.env'), SCHEDULER_ENABLED='false',
                      LEARNING_NIGHTLY_ENABLED='false', ARIES_PRIMARY_LANG='en', **flags)
    sys.dont_write_bytecode = True
    os.chdir(REPO)
    sys.path[:0] = [str(REPO), str(REPO / 'vendor'), str(REPO / 'vendor/agentic-core')]


async def aries_stage(args):
    config = CONFIGS['configs'][args.config]
    protocol = json.loads(PLANNER_PROTOCOL.read_text())
    flags = {**protocol['flags'], **config['flags']}
    path = dest('aries', args)
    source = git_state()
    if not source['aries_source_clean'] and not args.allow_dirty:
        raise SystemExit('REFUSED: aries/ or vendor/ has uncommitted changes')
    current_env(LOCAL / 'storage' / path.stem, flags)
    from agentic_core.database.base import Base, async_session, engine
    from aries.api.app import app  # noqa: F401  (registers the capabilities; no server starts)
    from aries import flags as aries_flags
    from aries.settings import SettingsService
    from aries.intelligence import router
    from aries.workspace import agent_planner
    n_caps = len(agent_planner.scoped_capabilities())
    if n_caps != 58:
        raise SystemExit(f'REFUSED: the planner scope is {n_caps} capabilities, not 58')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        s = SettingsService(db)
        for k, v in {**run_r1.ROUTER_SETTINGS, 'intelligence.local_model': args.model}.items():
            await s.set(k, v, set_by='user')
        for k, v in protocol['settings'].items():
            if k not in ('intelligence.local_model', 'ai.temperature', 'ai.max_output_tokens'):
                await s.set(k, v, set_by='user')
        await db.commit()
    prompt = router.LocalLLMDecisionProvider().instruction()
    base = {'routing': {'execution_level': 'local', 'reason': 'Prespecified offline planner evaluation',
                        'no_fallback': True}, 'steps': [], 'evidence': [],
            'agent': {'contract': {'supported': False, 'requirements': [],
                                   'reason': 'Offline next-action evaluation; no completion-contract hints supplied.'},
                      'context': {}, 'environment': {'fixture_precondition': run_r1.PRECONDITION,
                                                     'source': 'R1b offline evaluation; not current OS observations'}}}
    planner_settings = {'ai.temperature': protocol['settings']['ai.temperature'],
                        'ai.max_output_tokens': protocol['settings']['ai.max_output_tokens']}
    router_settings = {'ai.temperature': run_r1.ROUTER_SETTINGS['ai.temperature'],
                       'ai.max_output_tokens': run_r1.ROUTER_SETTINGS['ai.max_output_tokens']}

    async def use(values):
        async with async_session() as db:
            s = SettingsService(db)
            for k, v in values.items():
                await s.set(k, v, set_by='user')
            await db.commit()

    meta = await run_r1.model_meta(args.model)
    with path.open('x') as out:
        out.write(json.dumps({'header': True, 'stage': 'aries', 'args': vars(args), 'started_at': run_r1.stamp(),
                              'runner_sha256': run_r1.sha(__file__), 'configs_sha256': run_r1.sha(HERE / 'configs.json'),
                              'config': config, 'source': source, 'model_before': meta,
                              'router_prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                              'flags': aries_flags.describe() if hasattr(aries_flags, 'describe') else None},
                             default=str) + '\n')
        for i, (key, text) in enumerate(items(args.set), 1):
            row, t0 = {'id': key, 'started_at': run_r1.stamp()}, time.monotonic()
            await use(router_settings)
            async with async_session() as db:
                try:
                    row['route'] = (await router.route(db, text, allow_contract=True)).model_dump()
                except Exception as exc:
                    row['route'] = {'error': type(exc).__name__ + ': ' + str(exc)[:500]}
            row['router_seconds'] = round(time.monotonic() - t0, 4)
            row['acts'] = run_r1.router_acts(row['route'])
            if row['acts']:
                data = json.loads(json.dumps(base))
                data['routing']['gate_capability'] = row['route'].get('gate_capability')
                await use(planner_settings)
                t1 = time.monotonic()
                async with async_session() as db:
                    try:
                        raw, usage = await agent_planner.plan(db, text, data, 8)
                        row['raw_output'] = raw
                        row['decision'] = agent_planner.parse(raw).model_dump()
                    except Exception as exc:
                        row['planner_error'] = type(exc).__name__ + ': ' + str(exc)[:500]
                row['planner_seconds'] = round(time.monotonic() - t1, 4)
            out.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
            out.flush()
            if i % 50 == 0:
                print(f'{run_r1.stamp()} aries {args.config} {args.set} {i}', flush=True)
        out.write(json.dumps({'footer': True, 'finished_at': run_r1.stamp(),
                              'model_after': await run_r1.model_meta(args.model), 'source_after': git_state()}) + '\n')
    await engine.dispose()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['aries', 'frozen', 'frozen-planner', 'zeroshot', 'embedding', 'bm25'])
    ap.add_argument('--arm', choices=['A0', 'A1'])
    ap.add_argument('--set', required=True)
    ap.add_argument('--config')
    ap.add_argument('--model', default='qwen2.5:7b')
    ap.add_argument('--allow-dirty', action='store_true', help='development runs on nl2bash-dev only')
    args = ap.parse_args()
    check_data()
    if args.allow_dirty and args.set not in ('nl2bash-dev', 'clinc-dev'):
        raise SystemExit('REFUSED: --allow-dirty is for the development sets only')
    if args.stage == 'aries':
        if args.config not in CONFIGS['configs']:
            raise SystemExit(f'unknown config {args.config}')
        asyncio.run(aries_stage(args))
        return
    # R1's own stages, pointed at the new samples and at this folder's raw/.
    run_r1.items, run_r1.RAW = items, RAW
    if args.stage in ('frozen', 'frozen-planner'):
        # The frozen ARIES-FINAL-20261006 source and protocol live in the thesis-followup checkout. Router and
        # planner run in separate processes, as in R1 (each stage builds its own isolated database).
        run_r1.FINAL = Path.home() / 'aries/experiments/thesis-final-20261006'
        run_r1.FROZEN = run_r1.FINAL / 'frozen'
        args.arm = args.arm or 'A1'
        if args.stage == 'frozen':
            asyncio.run(run_r1.router_stage(args))
        else:
            args.arm = None
            args.router_file = str(RAW / f"router-{args.model.replace(':', '_').replace('.', '_')}-A1-{args.set}.jsonl")
            asyncio.run(run_r1.planner_stage(args))
        return
    args.model = None                      # R1 names baseline files without a model (zero-shot is qwen2.5:7b)
    if args.stage == 'zeroshot':
        asyncio.run(run_r1.zeroshot_stage(args))
    elif args.stage == 'embedding':
        run_r1.embedding_stage(args)
    else:
        run_r1.bm25_stage(args)


if __name__ == '__main__':
    main()
