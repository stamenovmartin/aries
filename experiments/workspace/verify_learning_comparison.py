"""Exercise the installed comparison queue; do not switch user retrieval settings."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.workspace.live_evaluate import api
before=api('GET','/settings/workspace.review_retrieval')['value']
goal=api('POST','/workspace',{'capability':'learning_eval','args':{}})
end=time.monotonic()+90
while time.monotonic()<end:
    data=api('GET','/workspace?goal_id='+goal['id'])
    result=next(g for g in data['goals'] if g['id']==goal['id'])
    if result['state'] not in {'queued','running'}:break
    time.sleep(1)
else:raise TimeoutError('Comparison did not finish')
comparison=result['steps'][0]['result'].get('comparison',{})
after=api('GET','/settings/workspace.review_retrieval')['value']
checks={'completed':result['state']=='done','active_version_unchanged':before==after,
        'both_versions_recorded':len(comparison.get('versions',{}))==2,
        'all_cases_recorded':all(len(v['cases'])==20 for v in comparison.get('versions',{}).values()),
        'not_promoted':comparison.get('promoted') is False}
Path(__file__).with_suffix('.json').write_text(json.dumps({'goal_id':goal['id'],'checks':checks,'result':result},ensure_ascii=False,indent=2))
print(json.dumps(checks),flush=True)
print('Goal:',goal['id'],flush=True)
sys.exit(0 if all(checks.values()) else 1)
