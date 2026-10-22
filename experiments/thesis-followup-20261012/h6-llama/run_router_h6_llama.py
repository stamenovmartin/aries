#!/usr/bin/env python3
"""H6 exploratory secondary: the same protocol as h6-run/run_router_h6.py with llama3.1:8b (outside Holm).

A copy of ../h6-run/run_router_h6.py in which only the model and the output folder (this folder) change, as
Task 6 did for the original fixture (docs/preregistration/H6-abstention-replication.md, Secondary outcomes).
Prompts were written for qwen2.5:7b and are not re-tuned. The H6 runner's own description follows.


A copy of experiments/thesis-final-20261006/run_router.py in which only the fixture path, the arm list and the
output folder change (docs/preregistration/H6-abstention-replication.md, Procedure). The frozen source,
prompts (regenerated from it and hash-checked against the frozen protocol), settings, schema, seeds and scorer
are the originals. Classification never executes requests."""
import argparse, asyncio, hashlib, json, os, random, subprocess, sys, time
from pathlib import Path
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parents[1] / 'thesis-final-20261006'
FROZEN = ORIGINAL / 'frozen'
FIXTURE = HERE.parent / 'h6-items' / 'h6_requests.jsonl'
ARMS = ['A0', 'A1']
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

SETTINGS = {
    'intelligence.location':'local', 'intelligence.local_model':MODEL,
    'intelligence.local_url':'http://127.0.0.1:11434', 'intelligence.gateway_enabled':False,
    'intelligence.cloud_enabled':False, 'intelligence.local_confidence_threshold':0.82,
    'workspace.agent_demo_directory':str(Path.home()/'Documents/ARIES-Thesis-Evaluation'),
    'workspace.controlled_browser':False, 'ai.temperature':0.1, 'ai.top_p':0.9,
    'ai.context_tokens':8192, 'ai.max_output_tokens':450,
}

async def initialize():
    import aries
    from agentic_core.database import models
    from agentic_core.database.base import Base, engine, async_session
    from aries.settings import SettingsService
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        s=SettingsService(db)
        for k,v in SETTINGS.items(): await s.set(k,v,set_by='user')
        await db.commit()
        return {k:await s.explain(k) for k in SETTINGS}

async def prepare():
    configure('preflight')
    resolved=await initialize()
    import httpx
    from aries import flags
    from aries.intelligence.router import LocalLLMDecisionProvider, capability_surface, machine_limits
    from aries.intelligence.schemas import Decision
    full=LocalLLMDecisionProvider().abstention()
    base,tail=full.split('This machine can do the following, so none of these is ever OUT_OF_SCOPE: ',1)
    surface,tail=tail.split('But these are measured limits of THIS machine and are always OUT_OF_SCOPE even if a ',1)
    limits,unsupported=tail.split('Anything outside that list IS out of scope: ',1)
    # Explicit unsupported examples are invariant across abstention arms. A1 cannot
    # refer to a missing list, so the shared clause uses the same neutral wording.
    examples='These requests are out of scope: '+unsupported
    surface='This machine can do the following, so none of these is ever OUT_OF_SCOPE: '+surface
    limits='But these are measured limits of THIS machine and are always OUT_OF_SCOPE even if a '+limits
    middles={'A0':LocalLLMDecisionProvider.GUESS,'A1':base+examples,
             'A2':base+surface+examples,'A3':base+surface+limits+examples}
    prompts={a:LocalLLMDecisionProvider.SHARED+m+LocalLLMDecisionProvider.TRAILER for a,m in middles.items()}
    for a,p in prompts.items(): (HERE/'prompts'/f'{a}.txt').write_text(p)
    frozen_hashes=read(ORIGINAL/'protocol.json')['hashes']
    assert all(hashlib.sha256(prompts[a].encode()).hexdigest()==frozen_hashes[a] for a in ARMS), 'prompts differ from the frozen protocol'
    async with httpx.AsyncClient(timeout=20) as client:
        tags=(await client.get('http://127.0.0.1:11434/api/tags')).json()
        ps=(await client.get('http://127.0.0.1:11434/api/ps')).json()
    model=next(m for m in tags['models'] if m['name']==MODEL)
    rows=[json.loads(l) for l in (FIXTURE).read_text().splitlines() if l]
    order=[]
    for rep in range(1,4):
        arms=list(ARMS); random.Random(26061006+rep).shuffle(arms)
        ids=[r['id'] for r in rows]; random.Random(26100000+rep).shuffle(ids)
        for arm in arms: order.append({'rep':rep,'arm':arm,'ids':ids})
    protocol={'version':1,'preregistered_at':stamp(),'status':'frozen before first model inference',
      'question':'Does capability and machine context improve act/hold routing without degrading semantic intent correctness?',
      'design':'Four nested prompt variants; identical current rules, schema and contract path in all arms. Not a rerun of the historical source-changing ablation.',
      'arms':{'A0':'No explicit abstention instruction; full schema unchanged','A1':'Explicit ASK/OUT_OF_SCOPE instruction and unsupported examples','A2':'A1 plus fixed capability catalogue text','A3':'A2 plus measured machine limits text'},
      'fixture_n':len(rows),'repetitions':3,'planned_decisions':len(rows)*len(ARMS)*3,'sampling_seed':None,
      'seed_note':'Ollama production adapter does not expose seed. Three fresh calls at temperature 0.1; case/arm order seeds are fixed separately.',
      'order':order,'settings':SETTINGS,'resolved_settings':resolved,'flags':flags.describe(),
      'model':model,'loaded_models_before':ps,'surface':capability_surface(),'limits':machine_limits(),
      'allow_contract':True,'schema':Decision.model_json_schema(),
      'hashes':{'fixture':digest(FIXTURE),'semantic_labels':digest(ORIGINAL/'semantic_labels.json'),
        'source_manifest':digest(ORIGINAL/'source-manifest.json'),'runner':digest(__file__),
        **{a:hashlib.sha256(p.encode()).hexdigest() for a,p in prompts.items()}},
      'metrics':{
        'binary_accuracy':'Fixed 225. actionable correct iff valid nonfallback intent not ASK/OUT_OF_SCOPE/UNKNOWN; other classes correct iff valid nonfallback intent ASK/OUT_OF_SCOPE/UNKNOWN. UNKNOWN is nonaction, not deliberate refusal. Errors always wrong.',
        'explicit_abstention':'ASK or OUT_OF_SCOPE only; precision = justified nonaction-class abstentions / all explicit abstentions; recall on 125 nonaction cases.',
        'ood_recall':'OUT_OF_SCOPE intent on the fixed 40 out_of_scope cases; also report any nonaction separately.',
        'semantic_coarse':'Exact allowed intent/tool pair on 82 prelabelled actionable cases; implementation proxy, not capability correctness.',
        'semantic_native':'Exact native semantic intent/tool pair on 56 prelabelled actionable cases.',
        'infrastructure':'Missing/schema error/fallback counted incorrect in every fixed-denominator accuracy, reported separately.'},
      'primary_comparison':'A3 minus A1, averaged over repetitions within each case; paired case bootstrap 2000 samples seed 61006; interval descriptive on reused fixture.',
      'predeclared_success':'A3 mean binary accuracy > A1, A3 native semantic accuracy no more than 2 percentage points below A1, and A3 out_of_scope false-action rate < A1. Failure remains reported; no post-result tuning.',
      'limitations':['Author-created reused fixture, not held-out generalization.','Labels annotated by second AI agent, not human reviewer.',
        'Only three repeats; 675 observations per arm are 225 repeated cases, not 675 independent cases.',
        'Rule decisions bypass LLM and are reported separately. No actions, speech, GUI or deployment reliability measured.',
        'Some actionable labels presume context absent from input; prelabelled sensitivity/exclusion notes preserved.',
        'Prompt assembly is an experimental adapter; production route/rules/schema unchanged, sampling settings held constant.',
        'Machine limitations frozen once; model computation uses shared local Ollama service; concurrent load cannot be fully excluded.']}
    protocol.update(
      question='H6 exploratory secondary (outside Holm): on new requests, A1 vs A0 per-request binary accuracy with llama3.1:8b',
      arms={a:protocol['arms'][a] for a in ARMS},
      primary_comparison='Per request, majority of 3 repetitions correct; one-sided exact McNemar A1 vs A0 (H1: b > c), '
                         'exploratory, reported separately and outside the Holm family (docs/preregistration/H6-abstention-replication.md).',
      predeclared_success='See the H6 preregistration; the frozen A3-vs-A1 criterion does not apply.',
      limitations=['Requests written by OpenAI Codex (gpt-6-astra), not a person (H6 Amendments 1-2).']+protocol['limitations'][2:],
      derived_from={'runner':'experiments/thesis-final-20261006/run_router.py','runner_sha256':digest(ORIGINAL/'run_router.py'),
                    'protocol_sha256':digest(ORIGINAL/'protocol.json')})
    save(HERE/'protocol.json',protocol)
    print('PREREGISTERED '+str(HERE/'protocol.json'),flush=True)

async def cell(rep,arm):
    configure(f'r{rep}-{arm}')
    protocol=read(HERE/'protocol.json')
    assert digest(__file__)==protocol['hashes']['runner']
    assert digest(ORIGINAL/'semantic_labels.json')==protocol['hashes']['semantic_labels']
    assert digest(FIXTURE)==protocol['hashes']['fixture']
    await initialize()
    from agentic_core.database.base import async_session, engine
    from aries.intelligence import router, local_structured
    from aries.intelligence.schemas import Decision
    class FrozenProvider(router.LocalLLMDecisionProvider):
        def instruction(self): return (HERE/'prompts'/f'{arm}.txt').read_text()
        async def decide(self,db,text):
            self.raw,self.usage=await local_structured(db,[{'role':'system','content':self.instruction()},
              {'role':'user','content':text}],Decision.model_json_schema(),purpose='intelligence.route',max_tokens=450)
            return Decision.model_validate_json(self.raw)
    rows={r['id']:r for r in [json.loads(l) for l in (FIXTURE).read_text().splitlines() if l]}
    entry=next(e for e in protocol['order'] if e['rep']==rep and e['arm']==arm)
    dest=HERE/'raw'/f'r{rep}-{arm}.jsonl'
    with dest.open('x') as output:
        for i,key in enumerate(entry['ids'],1):
            provider=FrozenProvider(); start=time.monotonic()
            row={**rows[key],'rep':rep,'arm':arm,'started_at':stamp()}
            async with async_session() as db:
                try: row.update((await router.route(db,row['utterance'],provider=provider,allow_contract=True)).model_dump())
                except Exception as exc: row['error']=type(exc).__name__+': '+str(exc)
            row.update(seconds=round(time.monotonic()-start,4),provider_raw=getattr(provider,'raw',None),
                       provider_usage=getattr(provider,'usage',None))
            output.write(json.dumps(row,ensure_ascii=False,default=str)+'\n');output.flush()
            if i%25==0 or i==len(rows): print(f'{stamp()} r{rep}-{arm} {i}/{len(rows)}',flush=True)
    await engine.dispose()

def run_all():
    protocol=read(HERE/'protocol.json')
    save(HERE/'run-status.json',{'started_at':stamp(),'status':'running','protocol_sha256':digest(HERE/'protocol.json')})
    for e in protocol['order']:
        print(f"START r{e['rep']}-{e['arm']}",flush=True)
        subprocess.run([sys.executable,str(Path(__file__).resolve()),'--cell',str(e['rep']),e['arm']],check=True)
    manifest=read(ORIGINAL/'source-manifest.json')
    stable=all(digest(FROZEN/p)==s for p,s in manifest['files'].items())
    save(HERE/'run-status.json',{'completed_at':stamp(),'status':'complete','frozen_source_stable':stable,
                               'protocol_sha256':digest(HERE/'protocol.json')})
    assert stable

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prepare',action='store_true');ap.add_argument('--run',action='store_true');ap.add_argument('--cell',nargs=2)
    a=ap.parse_args()
    if a.prepare:
        (HERE/'prompts').mkdir(exist_ok=True);(HERE/'raw').mkdir(exist_ok=True)
        (HERE/'frozen-flags.env').write_text('# Frozen experiment: source defaults, no production override file.\n')
        asyncio.run(prepare())
    elif a.cell: asyncio.run(cell(int(a.cell[0]),a.cell[1]))
    elif a.run: run_all()
