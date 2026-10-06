"""Live submit response must clarify before queuing; cancel only owned read probes."""
import hashlib,json,sys,time,urllib.request,subprocess
from pathlib import Path
from datetime import datetime,timezone
D=Path(__file__).parent;ROOT=D.parents[1]
requests=['read file it','read file that one','read file this file','read file both','прочитај ми го','прочитај ги','прочитај таа датотека','прочитај тоа']
fixture=D/'fixture.json'
if not fixture.exists():fixture.write_text(json.dumps(requests,ensure_ascii=False,indent=2)+'\n')
assert json.loads(fixture.read_text())==requests
out=D/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+sys.argv[1]+'.json')
def api(method,path,body=None):
 req=urllib.request.Request('http://127.0.0.1:8000/api/aries'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
def invocation():return subprocess.check_output(['systemctl','--user','show','aries-core','-p','InvocationID','--value'],text=True).strip()
def hashes():return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['aries/workspace/service.py','aries/workspace/capabilities.py','aries/workspace/clarification.py']}
r={'started_at':datetime.now(timezone.utc).isoformat(),'fixture_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'source_start':hashes(),'core_start':invocation(),'rows':[],'scope':'Live submit-response clarification, not completed goals. Read-only ambiguous probes; cancel only own queued/running goals; no approvals.'}
def save():
 r['n']=len(r['rows']);r['passed_n']=sum(x['passed'] for x in r['rows']);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
for text in requests:
 goal=api('POST','/workspace',{'request':text});q=goal.get('clarification') or {}
 item={'request':text,'id':goal['id'],'response':goal,'passed':goal['state']=='needs_clarification' and bool(q.get('question')) and len(q.get('choices',[]))>=2 and goal['steps']==[]}
 r['rows'].append(item);save()
 if goal['state'] in {'queued','running'}:item['cancellation']=api('POST','/workspace/'+goal['id']+'/cancel',{})
 if goal['state'] in {'proposed','held'}:r['paused_for_approval']=goal['id'];save();raise SystemExit('Approval required; no further probes')
 save();time.sleep(.2)
r.update(finished_at=datetime.now(timezone.utc).isoformat(),source_end=hashes(),core_end=invocation());r['runtime_changed']=r['source_start']!=r['source_end'] or r['core_start']!=r['core_end'];save();print(out,r['passed_n'],r['n'])
