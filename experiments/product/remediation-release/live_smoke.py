"""Synthetic live reads; inspect durable evidence against independently hashed bytes."""
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import uuid

BASE=Path(__file__).resolve().parent


def request(path,body=None):
    req=urllib.request.Request('http://127.0.0.1:8000/api/aries'+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)


def goal(text,name):
    started=time.monotonic()
    row=request('/workspace',{'request':text})
    (BASE/(name+'-submitted.json')).write_text(json.dumps(row,indent=2))
    print(name,row['id'],'submitted',flush=True)
    while row['state'] in {'queued','running'} and time.monotonic()-started<240:
        time.sleep(1)
        row=request('/workspace/'+row['id'])
    (BASE/(name+'-result.json')).write_text(json.dumps(row,indent=2))
    return row,round(time.monotonic()-started,2)


def main():
    token=uuid.uuid4().hex
    fixture=BASE/'live-fixture'/token
    fixture.mkdir(parents=True)
    a,b=fixture/'a.txt',fixture/'b.txt'
    a.write_text('Synthetic ARIES release smoke alpha '+token)
    b.write_text('Synthetic ARIES release smoke beta '+token)
    expected={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (a,b)}
    (BASE/'live-oracle.json').write_text(json.dumps(expected,indent=2))
    row,seconds=goal(f'Read {a} and read {b}','positive')
    proofs={e['evidence_id']:e for e in row.get('evidence',[])}
    refs=row.get('final_evidence_refs',[])
    delivered={proofs[r].get('data',{}).get('path'):proofs[r].get('data',{}).get('sha256')
               for r in refs if r in proofs and proofs[r].get('verified') is True}
    positive={'id':row['id'],'state':row['state'],'seconds':seconds,
              'passed':row['state']=='done' and all(delivered.get(p)==h for p,h in expected.items()),
              'expected':expected,'delivered':delivered,'metrics':(row.get('agent') or {}).get('metrics',{})}
    missing=fixture/'missing.txt'
    negative,seconds=goal(f'Read {missing}','negative')
    negative_check={'id':negative['id'],'state':negative['state'],'seconds':seconds,
                    'passed':negative['state']=='failed' and not missing.exists()
                    and not negative.get('final_evidence_refs') and bool(negative.get('steps')),
                    'metrics':(negative.get('agent') or {}).get('metrics',{})}
    analytics=request('/analytics?days=365&goal_scan=1')
    integrity={k:analytics['metrics'][k] for k in ('verification_honesty','verification_contradictions')}
    checked=all(m.get('truncated') is True and m.get('goals_scanned')==1
                and m.get('goals_in_window',0)>1 for m in integrity.values())
    result={'positive':positive,'negative':negative_check,'integrity':integrity,
            'analytics_passed':checked,'maintenance':request('/maintenance'),
            'scope':'Two synthetic live file goals; not general assistant or held-out acceptance'}
    (BASE/'live-smoke.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'positive':positive['passed'],'negative':negative_check['passed'],'analytics':checked}),flush=True)
    return 0 if positive['passed'] and negative_check['passed'] and checked else 1


if __name__=='__main__':raise SystemExit(main())
