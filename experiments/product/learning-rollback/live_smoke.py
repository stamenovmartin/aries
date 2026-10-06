"""Non-destructive live checks for learning controls and origin enforcement."""
import json,time,uuid,hashlib,urllib.request
from pathlib import Path
BASE=Path(__file__).resolve().parent

def request(path,body=None):
    req=urllib.request.Request('http://127.0.0.1:8000/api/aries'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)

def wait(row,name):
    started=time.monotonic()
    while row['state'] in {'queued','running'} and time.monotonic()-started<180:
        time.sleep(1);row=request('/workspace/'+row['id'])
    (BASE/(name+'-live.json')).write_text(json.dumps(row,indent=2))
    return row

def main():
    controls=request('/learning/controls');(BASE/'controls-live.json').write_text(json.dumps(controls,indent=2))
    control_ok=all(k in controls for k in ('items','history','truncated','note'))
    fixture=BASE/'live-fixture'/uuid.uuid4().hex;fixture.mkdir(parents=True)
    target=fixture/'background-must-not-exist.txt'
    bg=request('/shell/act',{'kind':'workspace','source':'automation:release-smoke','text':f'create file {target} :: synthetic background guard'})['result']
    print('background',bg['id'],flush=True);bg=wait(bg,'background')
    background_ok=bg['state']=='proposed' and bg.get('origin')=='automation:release-smoke' and not target.exists() and not bg.get('presentation')
    if bg['state'] in {'proposed','queued','running'}:request('/workspace/'+bg['id']+'/cancel',{})
    a,b=fixture/'a.txt',fixture/'b.txt'
    for p in (a,b):p.write_text('Synthetic learning/origin release smoke '+p.name+' '+fixture.name)
    expected={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (a,b)}
    row=request('/workspace',{'request':f'Read {a} and read {b}'})
    print('read',row['id'],flush=True);row=wait(row,'read')
    proofs={e['evidence_id']:e for e in row.get('evidence',[])}
    delivered={proofs[r].get('data',{}).get('path'):proofs[r].get('data',{}).get('sha256') for r in row.get('final_evidence_refs',[]) if r in proofs and proofs[r].get('verified') is True}
    read_ok=row['state']=='done' and row.get('origin')=='ui' and all(delivered.get(p)==h for p,h in expected.items())
    if row['state'] in {'proposed','queued','running'}:request('/workspace/'+row['id']+'/cancel',{})
    result={'controls_get':control_ok,'background_proposed_without_effect':background_ok,'interactive_read_with_independent_hashes':read_ok,'background_id':bg['id'],'read_id':row['id'],'expected':expected,'delivered':delivered,'maintenance':request('/maintenance'),'scope':'Two synthetic goals and read-only controls API. No actual user reset/undo; no general acceptance claim.'}
    (BASE/'live-smoke.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    return 0 if control_ok and background_ok and read_ok else 1

if __name__=='__main__':raise SystemExit(main())
