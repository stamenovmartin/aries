"""Exercise real arbitration on the live SQLite DB; fixture writes always roll back."""
import asyncio,hashlib,json,os,sys,uuid
from pathlib import Path
from datetime import datetime,timedelta,timezone
ROOT=Path(__file__).resolve().parents[2];D=Path(__file__).parent
sys.path[:0]=[str(ROOT),str(ROOT/'vendor'),str(ROOT/'vendor/agentic-core')]
os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+str(ROOT/'var/aries.db')
import aries
from agentic_core.database.base import async_session
from aries.workspace.memory import store
from aries.workspace.models import WorkspaceMemory,WorkspaceConclusion
from sqlalchemy import select
cases=[{'id':f'p{i:02d}','ground_truth':'valid_update' if i<15 else 'false_update',
        'old':f'ARIES TEST {i}: the synthetic token is alpha.',
        'new':f'ARIES TEST {i}: the synthetic token is beta.',
        'confirmation':False} for i in range(30)]
p=D/'fixture.json'
if not p.exists():p.write_text(json.dumps(cases,indent=2)+'\n')
assert json.loads(p.read_text())==cases
async def main():
 report={'measured_at':datetime.now(timezone.utc).isoformat(),'fixture_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
         'source_sha256':hashlib.sha256((ROOT/'aries/workspace/memory/store.py').read_bytes()).hexdigest(),
         'scope':'Live DB and real arbitration function in independent process; controlled SUPERSEDE decisions, no model accuracy or live API approval claim. Each fixture transaction rolled back; no genuine USER facts modified. Both true and false changes require explicit confirmation.', 'rows':[]}
 all_ids=[]
 for case in cases:
  async with async_session() as db:
   try:
    now=datetime.utcnow();src=await store.record(db,case['old'],source='user',commit=False)
    old=await store.conclude(db,text=case['old'],sources=[src.id],decision='APPEND',confidence=1.,rationale='rollback-only fixture',stage='fixture',valid_at=now-timedelta(days=1),commit=False)
    fresh=await store.record(db,case['new'],source='user',commit=False)
    new=await store.conclude(db,text=case['new'],sources=[fresh.id],decision='SUPERSEDE',confidence=1.,rationale='rollback-only fixture',stage='fixture',valid_at=now,commit=False)
    all_ids.extend([src.id,fresh.id,old.id,new.id])
    await db.flush()
    loser,reason=await store.arbitrate(db,new,'c:'+old.id,commit=False)
    await db.flush()
    hidden=await store.withdrawn_sources(db)
    report['rows'].append({'id':case['id'],'ground_truth':case['ground_truth'],'old_fact_replaced':old.expired_at is not None,'USER_hidden':src.id in hidden,'USER_expired':src.expired_at is not None,'reason':reason})
   finally:await db.rollback()
 async with async_session() as db:
  remaining=0
  for model in [WorkspaceMemory,WorkspaceConclusion]:remaining+=len((await db.execute(select(model.id).where(model.id.in_(all_ids)))).all())
 report['fixture_rows_persisted_n']=remaining;assert remaining==0
 report['summary']={'n':30,'false_pairs_n':15,'false_replacements_n':sum(r['old_fact_replaced'] for r in report['rows'] if r['ground_truth']=='false_update'),'unconfirmed_replacements_n':sum(r['old_fact_replaced'] for r in report['rows']),'USER_hidden_n':sum(r['USER_hidden'] for r in report['rows']),'USER_expired_n':sum(r['USER_expired'] for r in report['rows'])}
 out=D/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+sys.argv[1]+'.json');out.write_text(json.dumps(report,indent=2)+'\n');print(out,report['summary'])
asyncio.run(main())
