"""Paired live API probe. Read-only capabilities, fixed owned file, no approvals."""
import json,sys,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone
root=Path.home()/'Documents/ARIES-Verification-20261001'
root.mkdir(exist_ok=True);file=root/'fixture.txt'
if not file.exists():file.write_text('ARIES verification fixture 20261001.\n')
cases=[('read_file',{'path':str(file)}),('list_folder',{'path':str(root)}),('package_info',{'package':'bash'}),('services',{}),('disk',{}),('abilities',{}),('research',{'query':'OpenAI artificial intelligence'})]
def api(method,path,body=None):
 r=urllib.request.Request('http://127.0.0.1:8000/api/aries'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(r,timeout=30) as f:return json.load(f)
out={'started_at':datetime.now(timezone.utc).isoformat(),'repetitions':3,'cases':[],'scope':'Fixed 21 read-only live API goals. Not representative field traffic; 18 verifier-eligible, 3 research cannot verify claims.'}
path=Path(sys.argv[1])
for rep in range(3):
 for cap,args in cases:
  start=time.monotonic();gid=api('POST','/workspace',{'capability':cap,'args':args})['id'];deadline=start+180
  while True:
   row=next(g for g in api('GET','/workspace?goal_id='+gid)['goals'] if g['id']==gid)
   if row['state'] not in {'queued','running'}:break
   if time.monotonic()>deadline:
    api('POST','/workspace/'+gid+'/cancel',{});break
   time.sleep(.5)
  steps=row.get('steps',[])
  record={'rep':rep,'capability':cap,'goal_id':gid,'goal_state':row['state'],'elapsed_s':round(time.monotonic()-start,3),'steps':[{'state':s.get('state'),'verification_status':s.get('verification_status'),'met':(s.get('result',{}).get('verification') or {}).get('met'),'verification_recorded':isinstance(s.get('result',{}).get('verification'),dict)} for s in steps]}
  out['cases'].append(record);path.write_text(json.dumps(out,indent=2)+'\n');print(cap,record['goal_state'],flush=True)
out['finished_at']=datetime.now(timezone.utc).isoformat();path.write_text(json.dumps(out,indent=2)+'\n')
