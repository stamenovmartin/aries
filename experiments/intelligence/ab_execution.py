"""Matched real execution arms. No fabricated cloud baseline or silent fallback."""
import json,time,uuid,statistics
from pathlib import Path
from datetime import datetime,timezone
from evaluate import call,ready

def main():
    out=Path('experiments/intelligence')/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-ab-'+uuid.uuid4().hex[:6]);out.mkdir(parents=True)
    # Read-only paired goals avoid contaminated file/window resets. A known
    # missing-file task is correct iff it fails after a real read attempt.
    goals=[('system','Show system status'),('storage','Check disk usage and report which filesystem has the highest percentage used.'),
           ('negative','Read /this/path/does/not/exist/aries.txt')]
    ready()
    results=[]
    for index,(name,goal) in enumerate(goals):
        for arch in (['A','B'] if index%2==0 else ['B','A']):
            start=time.monotonic();r={'scenario':name,'architecture':arch,'goal':goal}
            try:
                task=call('/intelligence/ab-task',{'text':goal,'architecture':arch})
                deadline=time.monotonic()+600
                while time.monotonic()<deadline:
                    task=call('/workspace/'+task['id'])
                    if task['state'] in {'done','failed','partial','proposed','cancelled'}:break
                    time.sleep(1)
                steps=task.get('steps',[]);evidence=task.get('evidence',[])
                if name=='system':
                    passed=task['state']=='done' and (any(e.get('verified') and e.get('source')=='system.status' for e in evidence) or any(c.get('evidence')=='Live system probe' for c in task.get('cards',[])))
                elif name=='storage':
                    passed=task['state']=='done' and any(e.get('verified') and e.get('source')=='system.storage' for e in evidence)
                else:
                    passed=task['state']!='done' and any(s.get('capability')=='file.read' and s.get('execution_status')=='failed' for s in steps)
                r.update(task_id=task['id'],task_state=task['state'],passed=passed,
                    tool_execution_success=sum(s.get('execution_status') in {'observed','verified'} for s in steps),
                    verified_steps=sum(s.get('verification_status')=='verified' for s in steps),steps=len(steps),
                    metrics=task.get('agent',{}).get('metrics',{}))
                calls=[d.get('usage',{}).get('native',{}) for d in task.get('agent',{}).get('decisions',[])]
                r['cloud_requests']=sum(c.get('execution_level')=='cloud' for c in calls)
                r['local_requests']=sum(c.get('execution_level')=='local' for c in calls)
                r['cloud_tokens']=sum((c.get('prompt_eval_count') or 0)+(c.get('eval_count') or 0) for c in calls if c.get('execution_level')=='cloud')
                cloud_calls=[c for c in calls if c.get('execution_level')=='cloud']
                r['estimated_cost_usd']=sum(c['estimated_cost_usd'] for c in cloud_calls) if cloud_calls and all(c.get('estimated_cost_usd') is not None for c in cloud_calls) else None
                # Exclude retrieved memories/reviews from portable benchmark artifacts.
                task.pop('context',None);task.pop('related',None)
                task.get('agent',{}).pop('context',None)
                (out/(name+'-'+arch+'.json')).write_text(json.dumps(task,indent=2)+'\n')
            except Exception as exc:r.update(passed=False,unavailable=type(exc).__name__,detail=str(exc)[:160])
            r['seconds']=round(time.monotonic()-start,3);results.append(r)
            print(json.dumps(r),flush=True)
    available=all('unavailable' not in r for r in results)
    summary={arch:{'trials':sum(r['architecture']==arch for r in results),
                  'passed':sum(r['architecture']==arch and r['passed'] for r in results),
                  'mean_seconds':statistics.mean(r['seconds'] for r in results if r['architecture']==arch),
                  'cloud_requests':sum(r.get('cloud_requests',0) for r in results if r['architecture']==arch),
                  'local_requests':sum(r.get('local_requests',0) for r in results if r['architecture']==arch),
                  'cloud_tokens':sum(r.get('cloud_tokens',0) for r in results if r['architecture']==arch)} for arch in ('A','B')}
    payload={'scope':'Three read-only development controls; not evidence of general task equivalence. Alternating arm order.',
             'paired_available':available,'results':results,'summary':summary,
             'cloud_token_savings':summary['A']['cloud_tokens']-summary['B']['cloud_tokens'] if available else None,
             'success_rate_delta':(summary['B']['passed']-summary['A']['passed'])/len(goals) if available else None}
    (out/'result.json').write_text(json.dumps(payload,indent=2)+'\n')
    print('Artifacts: '+str(out),flush=True)
    return 0 if available and all(r['passed'] for r in results) else 1
if __name__=='__main__':raise SystemExit(main())
