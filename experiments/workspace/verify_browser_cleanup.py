"""Real public navigation must leave evidence and close its own temporary browser."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.workspace.live_evaluate import api
row=api('POST','/workspace',{'capability':'agent_task','args':{'task':'Open https://www.kernel.org and report the page title.'}})
print('Submitted',row['id'],flush=True)
end=time.monotonic()+180
while time.monotonic()<end:
 data=api('GET','/workspace?goal_id='+row['id'])
 goal=next(g for g in data['goals'] if g['id']==row['id'])
 if goal['state'] not in {'queued','running'} and (goal.get('window_cleanup') or goal['state']!='done'):
  break
 time.sleep(1)
else:raise TimeoutError('Goal did not finish and clean up')
closed=goal.get('window_cleanup',[])
checks={'goal_done':goal['state']=='done','observed_title':any('Linux Kernel Archives' in c.get('title','') or 'Linux Kernel Archives' in c.get('text','') for c in goal.get('cards',[])),
        'closed_owned_browser':bool(closed) and all(r['closed'] for r in closed),
        'no_live_owned_session':not any(r.get('owner')==row['id'] and r['open'] for r in data['runtime']['browsers']),
        'result_retained':bool(goal.get('cards'))}
Path(__file__).with_suffix('.json').write_text(json.dumps({'checks':checks,'goal':goal},ensure_ascii=False,indent=2))
print(json.dumps(checks),flush=True)
sys.exit(0 if all(checks.values()) else 1)
