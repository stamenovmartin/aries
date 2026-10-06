"""Same frozen decision fixtures on live local/cloud backends; never execute plans."""
import asyncio,copy,hashlib,json,statistics,time,urllib.request,argparse
from datetime import datetime,timezone
from pathlib import Path
import measure as fixture  # creates an isolated tracking database before core imports
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser()
parser.add_argument('--fixture',type=Path)
cli_args=parser.parse_args()
OUT=Path(__file__).parent/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-daily-local-cloud')
OUT.mkdir()

def stamp():return datetime.now(timezone.utc).isoformat()
def hashes():
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
            ['aries/workspace/agent_planner.py','aries/intelligence/generation.py','aries/intelligence/cli.py','aries/intelligence/providers.py']}

async def main():
    from tests._bootstrap import reset_db
    from agentic_core.database.base import async_session
    from aries.settings import SettingsService
    from aries.workspace import agent_planner
    await reset_db()
    names=['location','local_backend','local_url','local_model','keep_alive','gateway_enabled','gateway_url',
           'cloud_provider','cloud_cli_timeout_seconds','cloud_enabled','cloud_url','cloud_model','cloud_local_fallback',
           'cloud_input_usd_per_million','cloud_output_usd_per_million']
    keys=['intelligence.'+k for k in names]+['ai.temperature','ai.top_p','ai.context_tokens','ai.max_output_tokens',
                                        'workspace.agent_max_steps','workspace.agent_demo_directory']
    cfg={}
    for key in keys:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/aries/settings/'+key,timeout=10) as response:
            cfg[key]=json.load(response)['value']
    async with async_session() as db:
        settings=SettingsService(db)
        for key,value in cfg.items():await settings.set(key,value,set_by='user')
        await db.commit()
    cases=[(k,l,t,e,None,None) for k,l,t,e in fixture.GOALS]
    cases += [(k,l,t,e,(cap,args,v,0),want) for k,l,t,want,e,cap,args,v in fixture.CONTINUATIONS]
    k,l,t,want,e,cap,args,v,pad=fixture.LONG;cases.append((k,l,t,e,(cap,args,v,pad),want))
    frozen=[]
    for key,lang,goal,expected,prior,want in cases:
        data=fixture.blank_task(goal,str(Path(cfg['workspace.agent_demo_directory']).expanduser()),cfg['workspace.agent_max_steps'])
        evidence_id=None
        if prior:data,evidence_id=fixture.with_verified_step(data,*prior)
        frozen.append({'id':key,'language':lang,'goal':goal,'expected':sorted(expected),
                       'want':want,'evidence_id':evidence_id,'data':data})
    if cli_args.fixture:frozen=json.loads(cli_args.fixture.read_text())
    serialized=json.dumps(frozen,ensure_ascii=False,sort_keys=True)
    (OUT/'fixture.json').write_text(serialized+'\n')
    report={'started_at':stamp(),'fixture_sha256':hashlib.sha256(serialized.encode()).hexdigest(),
            'source_hashes_start':hashes(),'config':cfg,'rows':[],
            'scope':'Live model calls with isolated tracking DB and synthetic prior observations. Measures valid/plausible next decisions, NOT executed goals or verification coverage. Identical payloads, no fallback, no production routing change.'}
    def save():
        report['summary']={}
        for level in ['local','cloud']:
            rows=[r for r in report['rows'] if r['requested_level']==level]
            report['summary'][level]={'n':len(rows),'usable_n':sum(r.get('usable',False) for r in rows),
                'valid_json_n':sum(r.get('json',False) for r in rows),'valid_schema_n':sum(r.get('parses',False) for r in rows),
                'median_latency_s':statistics.median(r['seconds'] for r in rows) if rows else None}
        (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    save();print(OUT,flush=True)
    for case in frozen:
        for level in ['local','cloud']:
            data=copy.deepcopy(case['data']);data['routing']={'execution_level':level,'no_fallback':True,'reason':'User-requested daily comparison; decision only'}
            start=time.monotonic();raw='';usage={};failure=None
            try:
                async with async_session() as db:
                    raw,usage=await asyncio.wait_for(agent_planner.plan(db,case['goal'],data,cfg['workspace.agent_max_steps']),210)
            except Exception as exc:failure=type(exc).__name__+': '+str(exc)[:250]
            try:
                row=(fixture.score_continuation(raw,case['want'],set(case['expected']),case['evidence_id']) if case['want'] else fixture.score(raw,set(case['expected'])))
                if not case['want'] and row.get('action')!='execute':row['usable']=False
            except Exception as exc:row={'usable':False,'json':False,'parses':False,'scoring_error':type(exc).__name__}
            native=usage.get('native',{});row.update(id=case['id'],language=case['language'],requested_level=level,
                actual_level=native.get('execution_level'),provider=native.get('provider'),model=native.get('model'),
                seconds=round(time.monotonic()-start,3),failure=failure,raw=raw,measured_at=stamp())
            if raw and native.get('execution_level')!=level:row['usable']=False;row['route_mismatch']=True
            report['rows'].append(row);save();print(level,case['id'],row.get('usable'),row['seconds'],failure or '',flush=True)
    report.update(finished_at=stamp(),source_hashes_end=hashes())
    report['source_changed']=report['source_hashes_start']!=report['source_hashes_end'];save()
    print(json.dumps(report['summary']),flush=True)

if __name__=='__main__':asyncio.run(main())
