"""Supplemental real submit-function comparison; isolated ledger and no worker."""
import asyncio,hashlib,json,sys,ast
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tests import test_workspace as harness
from agentic_core.database.base import async_session
from aries.workspace import service
D=Path(__file__).parent
INSERT='''        if clarification is None:
            from aries.workspace.capabilities import missing_reference
            from aries.workspace.clarification import reference_question
            missing = missing_reference(request)
            if missing:
                clarification = reference_question(request, missing)
'''
source=(ROOT/'aries/workspace/service.py').read_text();assert source.count(INSERT)==1
before=source.replace(INSERT,'')
live=json.loads(next(D.glob('*-before.json')).read_text())
assert hashlib.sha256(before.encode()).hexdigest()==live['source_start']['aries/workspace/service.py']
namespace=service.__dict__.copy()
node=next(n for n in ast.parse(before).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='submit')
exec(compile(ast.Module(body=[node],type_ignores=[]),'service_before_snapshot.py','exec'),namespace)
fixture=ROOT/'experiments/router-ood/fixture.jsonl'
cases=[json.loads(line) for line in fixture.read_text().splitlines()]
async def main():
 result={'scope':'Isolated actual service.submit; memory observation disabled, no queue worker, models or actions. Supplemental to live8; no end-to-end task claim.', 'fixture_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'rows':[]}
 for label,submit in [('before',namespace['submit']),('after',service.submit)]:
  for case in cases:
   await harness.setup()
   async with async_session() as db:
    goal=await submit(db,case['utterance'])
   result['rows'].append({'condition':label,'id':case['id'],'class':case['klass'],'state':goal['state'],'clarified':bool(goal.get('clarification')) and goal['steps']==[],'steps_n':len(goal['steps'])})
  (D/'submit225.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print({label:{kind:sum(r['clarified'] for r in result['rows'] if r['condition']==label and r['class']==kind) for kind in ['actionable','ambiguous','out_of_scope','unsafe']} for label in ['before','after']})
with patch('aries.workspace.memory.store.observe_later'):
 asyncio.run(main())
