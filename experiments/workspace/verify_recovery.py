"""Installed-system recovery of a real file workflow; no original action is replayed."""
import json,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.workspace.live_evaluate import api
root=Path.home()/'Documents'/('ARIES-Recovery-'+uuid.uuid4().hex[:10])
def wait(id):
 end=time.monotonic()+90
 while time.monotonic()<end:
  data=api('GET','/workspace?goal_id='+id)
  g=next(g for g in data['goals'] if g['id']==id)
  if g['state'] not in {'queued','running'}:return g
  time.sleep(1)
 raise TimeoutError('Task did not finish')
parent=api('POST','/workspace',{'request':f'create folder {root} then read file {root}/followup.txt'})
original=wait(parent['id'])
assert original['state'] in {'failed','partial'} and root.is_dir(), original
with (root/'followup.txt').open('x') as stream:stream.write('Dependency now available')
identity=root.stat().st_ino
child=api('POST','/workspace/'+parent['id']+'/recover',{})
duplicate=api('POST','/workspace/'+parent['id']+'/recover',{})
result=wait(child['id'])
parent_after=wait(parent['id'])
checks={'original_failure_preserved':parent_after['state']==original['state'],
 'child_completed':result['state']=='done','duplicate_returns_same_child':duplicate['id']==child['id'],
 'folder_inherited_not_executed':result['steps'][0].get('inherited') is True,
 'folder_identity_unchanged':root.stat().st_ino==identity,
 'fresh_read_verified':any('Dependency now available' in c.get('text','') for c in result.get('cards',[]))}
Path(__file__).with_suffix('.json').write_text(json.dumps({'checks':checks,'folder':str(root),'parent':original,'child':result},ensure_ascii=False,indent=2))
print(json.dumps(checks),flush=True)
sys.exit(0 if all(checks.values()) else 1)
