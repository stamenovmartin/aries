"""Reproduce isolated transport checks and save raw logs/source fingerprints."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
FILES=['aries/workspace/memory/'+f+'.py' for f in ['embedding','calibration','local_transport']]
FILES+=['tests/test_memory_egress.py','tests/test_memory.py','tests/test_memory_privacy.py']
def hashes():return {f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES}
before=hashes();runs=[]
selected="import sys,types; import tests.test_memory as m; s=types.ModuleType('calibration_regression'); s.test_label=m.test_the_label_is_recovered_even_when_the_model_explains_itself; sys.exit(m.run_module(s))"
for name,args in [('transport',['-m','unittest','tests.test_memory_egress','-v']),
                  ('calibration',['-c',selected]),('privacy',['tests/test_memory_privacy.py'])]:
    command=[str(ROOT/'.venv/bin/python'),'-B',*args]
    run=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (OUT/(name+'.log')).write_text(run.stdout)
    runs.append({'suite':name,'exit_code':run.returncode,'command':command,'log':name+'.log',
                 'passing_assertions':sum(line.startswith('PASS ') for line in run.stdout.splitlines())})
after=hashes();passed=before==after and all(r['exit_code']==0 for r in runs)
(OUT/'results.json').write_text(json.dumps({'date':datetime.now(timezone.utc).isoformat(),
    'passed':passed,'runs':runs,'source_before':before,'source_after':after,'source_stable':before==after,
    'runtime_deployed':False,'real_model_calls':0,
    'scope':'Synthetic loopback servers, adversarial URL inputs, isolated calibration/privacy regression',
    'limitations':['No live service restart','Not a system-wide privacy leakage measurement',
                   'Trusted local server can itself relay data; this is client transport enforcement']},indent=2)+'\n')
sys.exit(0 if passed else 1)
