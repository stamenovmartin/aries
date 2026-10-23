import json,time,urllib.request,sys
from datetime import datetime,timezone
from pathlib import Path
out={'started_at':datetime.now(timezone.utc).isoformat(),'goal_id':'a8a6d2732b68440db294fe169782866e','trials':[],'timeout_seconds':8}
for i in range(5):
 t=time.monotonic()
 try:
  with urllib.request.urlopen('http://127.0.0.1:8000/api/aries/workspace?goal_id='+out['goal_id'],timeout=8) as f:b=f.read()
  d=json.loads(b);r={'ok':True,'bytes':len(b),'goals_n':len(d['goals']),'selected_present':any(g['id']==out['goal_id'] for g in d['goals'])}
 except Exception as e:r={'ok':False,'error':type(e).__name__}
 r['seconds']=round(time.monotonic()-t,4);out['trials'].append(r)
 Path(sys.argv[1]).write_text(json.dumps(out,indent=2)+'\n')
 print(r,flush=True)
