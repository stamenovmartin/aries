"""Save repeatable isolated checks without calling a model or live API."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
FILES=['aries/workspace/policy_artifacts.py','aries/workspace/policy_evaluation.py',
       'tests/test_policy_artifacts.py','tests/test_policy_evaluation.py']
def hashes():
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}

before=hashes()
runs=[]
for name,args in [('registry',['-m','unittest','tests.test_policy_artifacts','-v']),
                  ('evaluator',['tests/test_policy_evaluation.py'])]:
    command=[str(ROOT/'.venv/bin/python'),'-B',*args]
    run=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (OUT/(name+'.log')).write_text(run.stdout)
    runs.append({'suite':name,'command':command,'exit_code':run.returncode,'log':name+'.log'})
after=hashes()
passed=all(run['exit_code']==0 for run in runs) and before==after
(OUT/'results.json').write_text(json.dumps({'date':datetime.now(timezone.utc).isoformat(),
    'passed':passed,'runs':runs,'source_before':before,'source_after':after,'source_stable':before==after,
    'scope':'Synthetic isolated offline-registry acceptance and numerical evaluator regression checks',
    'runtime_deployed':False,'model_calls':0,'model_policy_performance_measured':False,
    'limitations':['Trusted producer; no authenticated raw observations',
                   'No held-out model-policy experiment or statistical efficiency claim',
                   'Offline pointer rollback only, no live state restoration']},indent=2)+'\n')
sys.exit(0 if passed else 1)
