"""Installed M14 acceptance. Real local model, real capabilities, preserved failures."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error
import uuid

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get('ARIES_API','http://127.0.0.1:8000')+'/api/aries'


def api(method,path,body=None):
    request=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,
                                   headers={'Content-Type':'application/json'},method=method)
    try:
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read(2000).decode()}') from exc


def safe_export(task):
    # Relevant user reviews guide planning locally; do not copy them into reports.
    task=json.loads(json.dumps(task))
    task.pop('related',None);task.pop('context',None)
    task.get('agent',{}).pop('context',None)
    return task


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser',action='store_true',help='Explicitly exclude the network-dependent browser scenario')
    options=parser.parse_args()
    run=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
    out=ROOT/'experiments/agent'/run
    for child in ('tasks','evidence'):(out/child).mkdir(parents=True,exist_ok=True)
    demo=Path.home()/'Documents/ARIES-Demo'/run
    demo.mkdir(parents=True)
    path=demo/'aries-m14-test.txt'
    report={'run':run,'mode':'live local model','cases':[], 'excluded':['browser'] if options.no_browser else [],
            'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
            'source_sha256':hashlib.sha256(b''.join(str(p.relative_to(ROOT)).encode()+b'\0'+p.read_bytes() for p in sorted((ROOT/'aries').rglob('*.py')))).hexdigest(),
            'scope':'Engineering acceptance, not a held-out model benchmark; every attempt retained.'}
    # systemctl returns before Uvicorn binds its socket; poll only the read API.
    report['readiness_attempts'] = 0
    for attempt in range(60):
        report['readiness_attempts'] += 1
        try:
            api('GET','/workspace/capabilities')
            break
        except (OSError, RuntimeError):
            time.sleep(.25)

    def save():
        report['passed']=sum(c['passed'] for c in report['cases']);report['total']=len(report['cases'])
        (out/'result.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
        lines=['# M14 live agent execution', '', 'Run: '+run, '', report['scope'], '',
               '| Scenario | Task state | Check passed | Steps | Planner calls | Seconds |', '|---|---|---|---:|---:|---:|']
        lines += [f"| {c['scenario']} | {c.get('task_state','error')} | {c['passed']} | {c.get('steps','—')} | {c.get('planner_calls','—')} | {c['seconds']} |" for c in report['cases']]
        lines += ['',f"{report['passed']}/{report['total']} required checks passed.",'Excluded: '+(', '.join(report['excluded']) or 'none'),
                  '', 'Task snapshots and evidence are in tasks/ and evidence/. Negative control passes only when real failure is recorded.']
        for c in report['cases']:
            if c.get('error'):lines += ['',c['scenario']+': '+c['error']]
        (out/'report.md').write_text('\n'.join(lines)+'\n')

    def run_case(name,goal,verify):
        t0=time.monotonic();case={'scenario':name,'goal':goal,'passed':False}
        try:
            queued=api('POST','/workspace',{'request':goal})
            case['task_id']=queued['id']
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                task=api('GET','/workspace/'+queued['id'])
                if task['state'] == 'proposed':
                    pending=next((s for s in task.get('steps',[]) if s['state']=='proposed'),{})
                    arguments=pending.get('args',{})
                    # This command authorizes only its own fresh exact file and
                    # public Python navigation; all other proposals remain held.
                    owned_write=pending.get('capability')=='file.write' and arguments=={'path':str(path),'content':'ARIES M14 verified execution'}
                    public_page=pending.get('capability')=='browser.open' and arguments=={'url':'https://www.python.org'}
                    if owned_write or public_page:
                        case.setdefault('approvals',[]).append({'step_id':pending['step_id'],'capability':pending['capability'],'arguments':arguments})
                        api('POST','/workspace/'+queued['id']+'/approve',{})
                        continue
                if task['state'] not in {'queued','running'}:break
                time.sleep(0.5)
            else:
                api('POST','/workspace/'+queued['id']+'/cancel',{})
                task=api('GET','/workspace/'+queued['id'])
            task=safe_export(task)
            (out/'tasks'/(name+'.json')).write_text(json.dumps(task,indent=2,ensure_ascii=False))
            (out/'evidence'/(name+'.json')).write_text(json.dumps({'evidence':task.get('evidence',[]),'final_refs':task.get('final_evidence_refs',[])},indent=2,ensure_ascii=False))
            metrics=task.get('agent',{}).get('metrics',{})
            case.update(task_state=task['state'],steps=len(task.get('steps',[])),planner_calls=metrics.get('planner_calls'),metrics=metrics)
            # Prevent a legacy deterministic path from masquerading as a model E2E.
            native=any(d.get('usage',{}).get('native',{}).get('eval_count',0)>0 for d in task.get('agent',{}).get('decisions',[]))
            case['local_model_observed']=native
            case['passed']=bool(task.get('agent',{}).get('engine')=='m14' and native and verify(task))
            if not case['passed']:case['error']=task.get('agent',{}).get('summary') or '; '.join(task.get('gaps',[]))
        except Exception as exc:
            case['error']=f'{type(exc).__name__}: {exc}'
        case['seconds']=round(time.monotonic()-t0,3);report['cases'].append(case);save()
        print(f"{name}: {'PASS' if case['passed'] else 'FAIL'} · {case.get('task_state','error')} · {case['seconds']}s",flush=True)

    def verified(task):
        refs=set(task.get('final_evidence_refs',[]))
        actual={e['evidence_id'] for e in task.get('evidence',[]) if e['verified']}
        return task['state']=='done' and bool(refs) and refs<=actual

    run_case('file-workflow',f'Create a file called aries-m14-test.txt in {demo} containing:\nARIES M14 verified execution\nThen read it back.',
             lambda task:verified(task) and path.read_bytes()==b'ARIES M14 verified execution' and {'file.write','file.read'}<={s['capability'] for s in task['steps'] if s['verification_status']=='verified'})
    def check_storage(task):
        if not verified(task):return False
        evidence=next(e for e in task['evidence'] if e['evidence_id']==task['final_evidence_refs'][-1])
        top=max(evidence['data']['filesystems'],key=lambda r:r['value'])
        return evidence['data']['highest']==top and str(top['subject']) in task['agent']['summary'] and str(top['value']) in task['agent']['summary']
    run_case('system-inspection','Check disk usage and report which filesystem has the highest percentage used.',check_storage)
    run_case('negative-control','Read /this/path/does/not/exist/aries.txt',
             lambda task:task['state'] in {'failed','partial'} and any(s['capability']=='file.read' and s.get('error') for s in task['steps']) and not task.get('final_evidence_refs'))
    if not options.no_browser:
        run_case('browser','Open https://www.python.org and report the observed page title.',
                 lambda task:verified(task) and {'browser.open','browser.read'}<={s['capability'] for s in task['steps'] if s['verification_status']=='verified'})
    print('Report: '+str(out/'report.md'),flush=True)
    return 0 if report['cases'] and report['passed']==report['total'] else 1


if __name__=='__main__':raise SystemExit(main())
