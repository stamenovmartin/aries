"""Fresh read-only live census; raw user requests and result text are not exported."""
import json,sqlite3,sys,subprocess
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'vendor'),str(ROOT/'vendor/agentic-core')]
from aries.workspace.capabilities import CATALOGUE
from aries.workspace.registry import registry
sys.path.insert(0,str(ROOT/'experiments/verification'))
from surface import owners,TWIN,DELEGATES_VERIFY,VSRC
from probe import bucket,recoverable
now=datetime.now(timezone.utc); cutoff=(now-timedelta(days=14)).replace(tzinfo=None).isoformat(' ')
c=sqlite3.connect(f'file:{ROOT}/var/aries.db?mode=ro',uri=True,isolation_level=None)
upper=now.replace(tzinfo=None).isoformat(' ')
future_n=c.execute('SELECT COUNT(*) FROM aries_workspace_goals WHERE created_at>?',(upper,)).fetchone()[0]
rows=c.execute('SELECT id,state,created_at,result_json FROM aries_workspace_goals WHERE created_at>=? AND created_at<=? ORDER BY created_at',(cutoff,upper)).fetchall()
wal=c.execute('PRAGMA journal_mode').fetchone()[0];c.close()
counts=Counter();caps=defaultdict(Counter);failed=Counter();classified=[]
for gid,state,created,raw in rows:
 counts[state]+=1
 try:d=json.loads(raw or '{}')
 except ValueError:d={}
 for s in d.get('steps',[]):
  k=s.get('capability','(none)');b=bucket(s);caps[k][b]+=1
  if recoverable(s):caps[k]['nested_positive_verdict']+=1
 if state in {'failed','partial','interrupted','unconfirmed','empty'}:
  # Attribution only to recorded failure fields, not user wording or guesses.
  errors=[d.get('error'),d.get('gaps'),(d.get('agent') or {}).get('error')]
  errors += [s.get('error') for s in d.get('steps',[])]+[(s.get('result') or {}).get('summary') for s in d.get('steps',[]) if s.get('state') in {'failed','unconfirmed'}]
  e=json.dumps(errors).lower()
  reason='other'
  if 'timeout' in e or 'timed out' in e or 'deadline' in e:reason='timeout'
  elif any(s.get('verification_status')=='verification_failed' for s in d.get('steps',[])) or 'verification failed' in e:reason='verification'
  elif any(s.get('state')=='failed' or s.get('execution_status')=='failed' for s in d.get('steps',[])) or any(t in e for t in ('database is locked','permission','not found','does not exist','filenotfounderror','locked desktop','unlock the desktop')):reason='capability'
  elif any(t in e for t in ('planner output remained invalid','planner decision retry','invalid json','max_steps','step budget')):reason='planner'
  elif any(t in e for t in ('routing','unknown intent','unsupported request')):reason='routing'
  elif any(t in e for t in ('asr','transcription failed','whisper')):reason='ASR'
  failed[reason]+=1;classified.append({'id':gid,'state':state,'reason':reason})
owned=owners();matrix=[]
for name,title,_ in CATALOGUE:
 source='\n'.join(owned.get(name,[]));twin=TWIN.get(name);verifier=registry.get(twin).verifier if twin else None
 invoked=('"verification"' in source or "'verification'" in source or name in DELEGATES_VERIFY)
 from aries.workspace.capabilities import WRITES
 invoked |= name in WRITES
 b=dict(caps[name]);n=sum(v for k,v in b.items() if k!='nested_positive_verdict')
 matrix.append({'capability':name,'registry_twin':twin,'registry_verifier':verifier.__name__ if verifier else None,'executor_records_verification_static':invoked,'steps_n':n,'unverified_steps':n-b.get('verified',0),'buckets':b})
start=now-timedelta(hours=48)
j=subprocess.run(['journalctl','--user','-u','aries-core','--since','@'+str(int(start.timestamp())),'--until','@'+str(int(now.timestamp())),'--output=json','--no-pager'],capture_output=True,text=True,check=True)
messages=[json.loads(l) for l in j.stdout.splitlines() if l.strip()]
times=[int(r['__REALTIME_TIMESTAMP'])/1e6 for r in messages]
locks=[r for r in messages if 'database is locked' in str(r.get('MESSAGE',''))]
out={'measured_at':now.isoformat(),'window_days':14,'goal_scan_cap':None,'goal_n':len(rows),'future_dated_goals_excluded_n':future_n,'goal_states':dict(counts),'unsuccessful_n':len(classified),'reason_counts':{k:failed[k] for k in ['ASR','routing','planner','capability','verification','timeout','other']},'classification':'Rule-based from stored failure fields; other includes insufficient evidence. No attribution of ASR errors without recorded ASR evidence. Partial/interrupted/unconfirmed/empty included; cancelled excluded.','classified_goals':classified,'registry_n':len(registry._items),'registry_capabilities':[{'name':n,'verifier':cap.verifier.__name__ if cap.verifier else None} for n,cap in sorted(registry._items.items())],'catalogue_n':len(matrix),'capabilities':matrix,'locking':{'window_start':start.isoformat(),'window_end':now.isoformat(),'requested_hours':48,'continuous_coverage_proven':False,'coverage_note':'First/last log timestamps do not prove continuous service operation. Clock changes and unavailable journal intervals prevent a 48-hour acceptance claim.','journal_records_n':len(messages),'matching_records_n':len(locks),'count_unit':'journal records containing database is locked; not distinct incidents','journal_mode':wal,'first_available_record_at':datetime.fromtimestamp(min(times),timezone.utc).isoformat() if messages else None,'last_available_record_at':datetime.fromtimestamp(max(times),timezone.utc).isoformat() if messages else None}}
known=set()
for evidence_path in (ROOT/'experiments/assistant-benchmark').glob('*/results.json'):
 try:
  known.update(r['goal_id'] for r in json.loads(evidence_path.read_text()).get('cases',[]) if r.get('goal_id'))
 except (ValueError,KeyError):pass
out['known_assistant_fixture_goals_n']=sum(gid in known for gid,_,_,_ in rows)
out['known_assistant_fixture_unsuccessful_n']=sum(r['id'] in known for r in classified)
out['non_fixture_classification_caveat']='Only this frozen60 fixture IDs identified; other synthetic trials may remain.'
out['reason_counts_excluding_known_assistant_fixture']=dict(Counter(r['reason'] for r in classified if r['id'] not in known))
p=Path(sys.argv[1]);p.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k not in {'capabilities','classified_goals','registry_capabilities'}}))
