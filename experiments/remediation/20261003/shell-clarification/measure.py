"""Two voice API cases, only after the existing guard has naturally resumed."""
import json,sys,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path
D=Path(__file__).parent
BASE='http://127.0.0.1:8000/api/aries'
with urllib.request.urlopen(BASE+'/shell/guard',timeout=5) as f:guard=json.load(f)
if guard.get('paused',{}).get('voice'):raise SystemExit('Voice guard still paused; no requests issued')
out={'measured_at':datetime.now(timezone.utc).isoformat(),'cases':[]}
for text in ['пушти нешто','play something']:
 req=urllib.request.Request(BASE+'/shell/act',data=json.dumps({'kind':'workspace','text':text,'source':'voice'}).encode(),headers={'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=10) as f:r=json.load(f)
  goal=r['result'];out['cases'].append({'goal_id':goal['id'],'state':goal['state'],'steps_n':len(goal['steps']),'message':r.get('message'),'question':goal.get('clarification',{}).get('question'),'passed':r.get('message')==goal.get('clarification',{}).get('question') and len(goal['steps'])==0})
 except urllib.error.HTTPError as e:
  out['error']={'http_status':e.code};break
 finally:
  out.update(n=len(out['cases']),passed_n=sum(r['passed'] for r in out['cases']))
  (D/(sys.argv[1]+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(out,ensure_ascii=False))
