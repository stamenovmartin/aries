#!/usr/bin/env python3
"""ARIES-FINAL-20261006 router protocol with a second local model (llama3.1:8b).

A copy of experiments/thesis-final-20261006/run_router.py in which ONLY the model
changes. Everything else is taken from the original protocol, not regenerated:

- frozen source: experiments/thesis-final-20261006/frozen (read-only);
- prompts, fixture, semantic labels and source manifest: byte copies, hashes checked
  against the original protocol.json before every cell;
- settings: the original SETTINGS with intelligence.local_model replaced;
- order: the original randomised rep/arm/id order, reused.

qwen2.5:7b remains the primary result. Prompt wording was written for qwen2.5:7b and
is not re-tuned for llama3.1:8b; that is part of the comparison, not a defect in it.

    --prepare   write protocol.json (no inference)
    --smoke N   N utterances of A1 into smoke/ (not part of the result)
    --run       all 12 cells
"""
import argparse, asyncio, hashlib, json, os, subprocess, sys, time
from pathlib import Path
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parents[1] / 'thesis-final-20261006'
FROZEN = ORIGINAL / 'frozen'
MODEL = 'llama3.1:8b'
def stamp(): return datetime.now(timezone.utc).isoformat()
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p, obj): Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')
def read(p): return json.loads(Path(p).read_text())

def configure(name):
    work = HERE/'storage'/name
    work.mkdir(parents=True, exist_ok=True)
    os.chdir(FROZEN)
    os.environ.update(APP_ENV='test', DATABASE_URL='sqlite+aiosqlite:///'+str(work/'router.sqlite3'),
        DATA_DIR=str(work/'runtime'), RUNTIME_STORE=str(work/'runtime/state.json'),
        CONTEXT_DIR=str(work/'context'), API_KEY='', CREDENTIALS_KEY='', OPENAI_API_KEY='',
        ARIES_CLOUD_API_KEY='', AI_PROVIDER='ollama', DRY_RUN='true', LIVE_TOOLS='',
        ARIES_FLAG_FILE=str(HERE/'frozen-flags.env'), SCHEDULER_ENABLED='false',
        LEARNING_NIGHTLY_ENABLED='false')
    sys.path[:0] = [str(FROZEN), str(FROZEN/'vendor'), str(FROZEN/'vendor/agentic-core')]
    return work

ORIGINAL_PROTOCOL = read(ORIGINAL/'protocol.json')
SETTINGS = {**ORIGINAL_PROTOCOL['settings'], 'intelligence.local_model': MODEL}

def check_inputs():
    h = ORIGINAL_PROTOCOL['hashes']
    ok = {'fixture': digest(HERE/'fixture.jsonl') == h['fixture'],
          'semantic_labels': digest(HERE/'semantic_labels.json') == h['semantic_labels'],
          'source_manifest': digest(HERE/'source-manifest.json') == h['source_manifest'],
          **{a: hashlib.sha256((HERE/'prompts'/f'{a}.txt').read_text().encode()).hexdigest() == h[a]
             for a in ('A0', 'A1', 'A2', 'A3')}}
    manifest = read(HERE/'source-manifest.json')
    ok['frozen_source'] = all(digest(FROZEN/p) == s for p, s in manifest['files'].items())
    assert all(ok.values()), ok
    return ok

async def initialize():
    import aries  # noqa: F401
    from agentic_core.database import models  # noqa: F401
    from agentic_core.database.base import Base, engine, async_session
    from aries.settings import SettingsService
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        s=SettingsService(db)
        for k,v in SETTINGS.items(): await s.set(k,v,set_by='user')
        await db.commit()
        return {k:await s.explain(k) for k in SETTINGS}

async def model_identity():
    import httpx
    async with httpx.AsyncClient(timeout=20) as client:
        tags=(await client.get('http://127.0.0.1:11434/api/tags')).json()
    return next(m for m in tags['models'] if m['name']==MODEL)

async def prepare():
    configure('preflight')
    resolved=await initialize()
    from aries import flags
    protocol={'version':1,'created_at':stamp(),'status':'frozen before first model inference',
      'derived_from':{'protocol':str((ORIGINAL/'protocol.json').relative_to(HERE.parents[2])),
                      'protocol_sha256':digest(ORIGINAL/'protocol.json'),
                      'runner':'experiments/thesis-final-20261006/run_router.py',
                      'runner_sha256':digest(ORIGINAL/'run_router.py')},
      'only_change':'intelligence.local_model qwen2.5:7b -> '+MODEL,
      'primary_result_remains':'qwen2.5:7b (ARIES-FINAL-20261006)',
      'model':await model_identity(),'settings':SETTINGS,'resolved_settings':resolved,'flags':flags.describe(),
      'order':ORIGINAL_PROTOCOL['order'],'input_checks':check_inputs(),
      'hashes':{**ORIGINAL_PROTOCOL['hashes'],'runner':digest(__file__)},
      'metrics':ORIGINAL_PROTOCOL['metrics'],'predeclared_success_original':ORIGINAL_PROTOCOL['predeclared_success'],
      'analysis':'Same metrics as final-evaluation.json via the frozen analyze_router.py scoring functions; '
                 'descriptive comparison with qwen2.5:7b, no new success criterion.',
      'limitations':ORIGINAL_PROTOCOL['limitations']+['Prompts were written and frozen for qwen2.5:7b; not re-tuned for '+MODEL+'.']}
    save(HERE/'protocol.json',protocol)
    print('PROTOCOL '+str(HERE/'protocol.json'),flush=True)

async def cell(rep, arm, dest, ids):
    configure(f'r{rep}-{arm}' if dest.parent.name=='raw' else 'smoke')
    protocol=read(HERE/'protocol.json')
    assert digest(__file__)==protocol['hashes']['runner']
    check_inputs()
    await initialize()
    from agentic_core.database.base import async_session, engine
    from aries.intelligence import router, local_structured
    class FrozenProvider(router.LocalLLMDecisionProvider):
        def instruction(self): return (HERE/'prompts'/f'{arm}.txt').read_text()
        async def decide(self,db,text):
            from aries.intelligence.schemas import Decision
            self.raw,self.usage=await local_structured(db,[{'role':'system','content':self.instruction()},
              {'role':'user','content':text}],Decision.model_json_schema(),purpose='intelligence.route',max_tokens=450)
            return Decision.model_validate_json(self.raw)
    rows={r['id']:r for r in [json.loads(l) for l in (HERE/'fixture.jsonl').read_text().splitlines() if l]}
    with dest.open('x') as output:
        for i,key in enumerate(ids,1):
            provider=FrozenProvider(); start=time.monotonic()
            row={**rows[key],'rep':rep,'arm':arm,'started_at':stamp()}
            async with async_session() as db:
                try: row.update((await router.route(db,row['utterance'],provider=provider,allow_contract=True)).model_dump())
                except Exception as exc: row['error']=type(exc).__name__+': '+str(exc)
            row.update(seconds=round(time.monotonic()-start,4),provider_raw=getattr(provider,'raw',None),
                       provider_usage=getattr(provider,'usage',None))
            output.write(json.dumps(row,ensure_ascii=False,default=str)+'\n');output.flush()
            if i%25==0 or i==len(ids): print(f'{stamp()} r{rep}-{arm} {i}/{len(ids)}',flush=True)
    await engine.dispose()

def run_all():
    protocol=read(HERE/'protocol.json')
    before=asyncio.run(model_identity())
    save(HERE/'run-status.json',{'started_at':stamp(),'status':'running','protocol_sha256':digest(HERE/'protocol.json'),
                                 'model_before':before})
    for e in protocol['order']:
        print(f"START r{e['rep']}-{e['arm']}",flush=True)
        subprocess.run([sys.executable,str(Path(__file__).resolve()),'--cell',str(e['rep']),e['arm']],check=True)
    after=asyncio.run(model_identity())
    manifest=read(HERE/'source-manifest.json')
    stable=all(digest(FROZEN/p)==s for p,s in manifest['files'].items())
    save(HERE/'run-status.json',{'completed_at':stamp(),'status':'complete','frozen_source_stable':stable,
        'protocol_sha256':digest(HERE/'protocol.json'),'model_before':before,'model_after':after,
        'model_stable':before['digest']==after['digest']})
    assert stable

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prepare',action='store_true');ap.add_argument('--run',action='store_true')
    ap.add_argument('--cell',nargs=2);ap.add_argument('--smoke',type=int)
    a=ap.parse_args()
    if a.prepare: asyncio.run(prepare())
    elif a.cell:
        e=next(e for e in read(HERE/'protocol.json')['order'] if e['rep']==int(a.cell[0]) and e['arm']==a.cell[1])
        asyncio.run(cell(e['rep'],e['arm'],HERE/'raw'/f"r{e['rep']}-{e['arm']}.jsonl",e['ids']))
    elif a.smoke:
        (HERE/'smoke').mkdir(exist_ok=True)
        e=next(e for e in read(HERE/'protocol.json')['order'] if e['rep']==1 and e['arm']=='A1')
        asyncio.run(cell(1,'A1',HERE/'smoke'/f'smoke-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl',e['ids'][:a.smoke]))
    elif a.run: run_all()
