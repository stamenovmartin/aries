"""Read-only journal coverage and lock-count collector. Never claims an empty log passed."""
import argparse,collections,hashlib,json,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
UNITS=['aries-core.service','aries-voice.service','aries-local-model.service']
def stamp():return datetime.now(timezone.utc).isoformat()
def journal(*args):
 command=['journalctl','--user','--no-pager','--output=json']
 for unit in UNITS:command+=['-u',unit]
 p=subprocess.run(command+list(args),capture_output=True,text=True,timeout=25,check=True)
 return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
def source_hashes():
 paths=['vendor/agentic-core/agentic_core/database/base.py','aries/intelligence/generation.py','aries/workspace/orchestration.py']
 return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
def write(path,data):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2)+'\n');temp.replace(path)
def counts(rows):
 return {'records_n':len(rows),'locked_records_n':sum('database is locked' in str(r.get('MESSAGE','')).lower() for r in rows),
         'by_unit':dict(collections.Counter(r.get('_SYSTEMD_USER_UNIT','unknown') for r in rows))}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--hours',type=float,default=48);ap.add_argument('--interval',type=float,default=60);a=ap.parse_args()
 a.output.mkdir(parents=True,exist_ok=True);summary=a.output/'summary.json'
 if summary.exists():raise SystemExit('Use a new output directory; never overwrite an earlier window')
 start=time.monotonic();first=stamp();latest=journal('-n','1');cursor=latest[-1]['__CURSOR'] if latest else None
 historical=journal('--since','48 hours ago');times=[int(r['__REALTIME_TIMESTAMP'])/1e6 for r in historical]
 write(a.output/'historical.json',{'measured_at':first,'requested_hours':48,**counts(historical),'available_span_hours':(max(times)-min(times))/3600 if len(times)>1 else 0,'continuous_coverage_proven':False,'note':'Historical journal availability is not a complete before window. No raw messages retained.'})
 state={'started_at':first,'requested_hours':a.hours,'completed':False,'records_n':0,'locked_records_n':0,'polls_n':0,'errors_n':0,'gaps_n':0,'max_poll_gap_seconds':0,'source_hashes_start':source_hashes(),'source_change_polls_n':0,'core_inactive_polls_n':0,'core_invocation_changes_n':0,'coverage_complete':False,'lock_free_acceptance':False,'limitations':['Counts matching journal records, not distinct incidents or SQL write attempts.','48-hour collection is not a repair before/after pair. Zero records, gaps or downtime cannot prove stability.','Only listed service journals observed; no intentionally induced production lock.','Collector must stay running; a new run is required after interruption.']}
 last=start;last_wall=time.time();prior_core=None
 write(summary,state)
 while True:
  t=time.monotonic();wall=time.time();gap=max(t-last,abs(wall-last_wall));last=t;last_wall=wall
  state['max_poll_gap_seconds']=max(state['max_poll_gap_seconds'],gap)
  if gap>a.interval*2.5:state['gaps_n']+=1
  try:
   rows=journal('--after-cursor',cursor) if cursor else journal('--since',first)
   if rows:cursor=rows[-1]['__CURSOR']
   c=counts(rows);state['records_n']+=c['records_n'];state['locked_records_n']+=c['locked_records_n']
   info=subprocess.run(['systemctl','--user','show','aries-core.service','-p','ActiveState','-p','InvocationID'],capture_output=True,text=True,timeout=10,check=True).stdout
   fields=dict(line.split('=',1) for line in info.splitlines() if '=' in line)
   if fields.get('ActiveState')!='active':state['core_inactive_polls_n']+=1
   if prior_core and fields.get('InvocationID')!=prior_core:state['core_invocation_changes_n']+=1
   prior_core=fields.get('InvocationID')
   if source_hashes()!=state['source_hashes_start']:state['source_change_polls_n']+=1
   sample={'at':stamp(),'gap_seconds':round(gap,3),**c,'core_active':fields.get('ActiveState')=='active'}
   with (a.output/'samples.jsonl').open('a') as f:f.write(json.dumps(sample)+'\n')
  except Exception as exc:
   state['errors_n']+=1;state['last_error_type']=type(exc).__name__
  state['polls_n']+=1;state['last_poll_at']=stamp();state['elapsed_seconds']=round(time.monotonic()-start,3);write(summary,state)
  if time.monotonic()-start>=a.hours*3600:break
  time.sleep(min(a.interval,max(0,a.hours*3600-(time.monotonic()-start))))
 state['completed']=True;state['finished_at']=stamp();state['elapsed_seconds']=round(time.monotonic()-start,3)
 state['source_hashes_end']=source_hashes()
 state['coverage_complete']=state['records_n']>0 and not any(state[k] for k in ['errors_n','gaps_n','core_inactive_polls_n','core_invocation_changes_n','source_change_polls_n'])
 # No false48h acceptance from a short smoke run.
 state['lock_free_acceptance']=a.hours>=48 and state['coverage_complete'] and state['locked_records_n']==0
 write(summary,state)
if __name__=='__main__':main()
