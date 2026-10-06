"""Reproducible development routing benchmark; no fictional all-cloud baseline."""
import argparse,json,time,uuid,urllib.request,urllib.error,statistics
from datetime import datetime,timezone
from pathlib import Path

CASES=[
 ('open YouTube','code','OPEN_URL'),('open Gmail','code','OPEN_URL'),
 ('show system status','code','SYSTEM_ACTION'),('open Downloads','code','FILE_ACTION'),
 ('run system health','code','SYSTEM_ACTION'),
 ("show me something interesting from today's tech news",'local','SEARCH_WEB'),
 ('Classify this email priority: maintenance completed successfully.','local','CLASSIFY'),
 ('Decide whether to notify me about a routine backup completion.','local','CLASSIFY'),
 ('Extract dates from: the meeting is on 2026-10-05.','local','EXTRACT'),
 ('Compare three research papers and evaluate their conflicting methodologies.','cloud','RESEARCH'),
 ('Analyze the architecture of a large codebase and identify dependency cycles.','cloud','CODING'),
 ('Produce a research synthesis from conflicting experimental studies.','cloud','RESEARCH'),
 ('Solve a complex debugging problem involving an intermittent distributed race condition.','cloud','CODING'),
]
BASE='http://127.0.0.1:8000/api/aries'
def call(path,body=None):
    req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=210) as r:return json.load(r)

def ready():
    for attempt in range(20):
        try:call('/intelligence/stats');return
        except (urllib.error.URLError,TimeoutError):time.sleep(1)
    raise RuntimeError('Core API did not become ready within 20 seconds')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cloud-baseline',action='store_true',help='Spend actual configured cloud tokens; no local substitution allowed')
    parser.add_argument('--repeats',type=int,default=1);args=parser.parse_args()
    if not 1<=args.repeats<=10:parser.error('repeats must be 1..10')
    out=Path('experiments/intelligence')/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]);out.mkdir(parents=True)
    ready()
    rows=[];baseline=[]
    for repeat in range(args.repeats):
        for goal,expected,intent in CASES:
            start=time.monotonic();row={'goal':goal,'expected_level':expected,'expected_intent':intent,'repeat':repeat}
            try:
                r=call('/intelligence/route',{'text':goal});row.update(route=r,routing_correct=r['execution_level']==expected,intent_correct=r['intent']==intent)
            except Exception as exc:row.update(error=type(exc).__name__,routing_correct=False,intent_correct=False)
            row['seconds']=round(time.monotonic()-start,4);rows.append(row)
            print(('PASS' if row['routing_correct'] else 'FAIL')+' '+goal,flush=True)
            if args.cloud_baseline:
                t=time.monotonic();a={'goal':goal,'expected_intent':intent}
                try:
                    r=call('/intelligence/cloud-baseline',{'text':goal});a.update(response=r,intent_correct=r['decision']['intent']==intent)
                except Exception as exc:a.update(error=type(exc).__name__,intent_correct=False)
                a['seconds']=round(time.monotonic()-t,4);baseline.append(a)
            (out/'trials.json').write_text(json.dumps({'B':rows,'A':baseline},indent=2)+'\n')
    # Safe task execution is evaluated separately from classification correctness.
    task=call('/workspace',{'request':'show system status'});deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        task=call('/workspace/'+task['id'])
        if task['state'] in {'done','partial','failed','proposed','cancelled'}:break
        time.sleep(1)
    (out/'system-task.json').write_text(json.dumps(task,indent=2)+'\n')
    verified_system=task['state']=='done' and any(c.get('evidence')=='Live system probe' for c in task.get('cards',[]))
    bg=call('/intelligence/route',{'text':'health check','background':True})
    local=[r for r in rows if r['expected_level']=='local'];complex_rows=[r for r in rows if r['expected_level']=='cloud'];easy=[r for r in rows if r['expected_level']!='cloud']
    result={'scope':'Developer-labelled routing fixture. Not a held-out task-completion or energy benchmark.',
        'cases':len(rows),'routing_accuracy':sum(r['routing_correct'] for r in rows)/len(rows),
        'intent_accuracy':sum(r['intent_correct'] for r in rows)/len(rows),
        'local_intent_accuracy':sum(r['intent_correct'] for r in local)/len(local),
        'cloud_escalation_rate':sum(r.get('route',{}).get('execution_level')=='cloud' for r in rows)/len(rows),
        'false_escalation_rate':sum(r.get('route',{}).get('execution_level')=='cloud' for r in easy)/len(easy),
        'missed_escalation_rate':sum(r.get('route',{}).get('execution_level')!='cloud' for r in complex_rows)/len(complex_rows),
        'mean_routing_seconds':statistics.mean(r['seconds'] for r in rows),
        'native_local_input_tokens':sum(r.get('route',{}).get('input_tokens') or 0 for r in rows),
        'native_local_output_tokens':sum(r.get('route',{}).get('output_tokens') or 0 for r in rows),
        'B_scope':'Routing decision only; cloud recommendations do not execute cloud work in this fixture.',
        'A_scope':'Actual all-cloud classification only' if baseline else 'Not run: requires --cloud-baseline plus configured cloud access',
        'A':{'requests':len(baseline),'successful_responses':sum('response' in r for r in baseline),
             'native_input_tokens':sum(r.get('response',{}).get('usage',{}).get('prompt_eval_count') or 0 for r in baseline),
             'native_output_tokens':sum(r.get('response',{}).get('usage',{}).get('eval_count') or 0 for r in baseline)} if baseline else None,
        'paired_task_success_delta':None,'estimated_token_savings':None,'estimated_cost_savings':None,
        'task_completion_probe':{'task_id':task['id'],'state':task['state'],'verified_live_system_observation':verified_system},
        'all_task_completion_success_rate':None,'all_tool_execution_success_rate':None,'all_verification_success_rate':None,
        'completion_note':'Routing labels do not prove task completion. One real system probe is reported separately; use aries-agent-demo for four execution controls.',
        'background_probe':bg,'stats_snapshot':call('/intelligence/stats')}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'report.md').write_text('# Intelligence routing evaluation\n\n'+result['scope']+'\n\n'+
        '\n'.join(f'- {k}: {result[k]}' for k in ('routing_accuracy','intent_accuracy','local_intent_accuracy','cloud_escalation_rate','false_escalation_rate','missed_escalation_rate','mean_routing_seconds','native_local_input_tokens','native_local_output_tokens','A_scope'))+
        '\n\nSystem probe: '+str(verified_system)+'. A/B task-success and savings remain unmeasured.\n')
    print('Report: '+str(out/'report.md'),flush=True)
    return 0 if verified_system and not any('error' in r for r in rows) and not any('error' in r for r in baseline) else 1
if __name__=='__main__':raise SystemExit(main())
