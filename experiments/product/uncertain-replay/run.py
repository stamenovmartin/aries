"""Isolated execution-loop regression checks; deterministic planner, no model."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
FILES=['aries/workspace/agent.py','tests/test_agent_replay.py','tests/test_agent_execution.py','tests/test_finish_proposal.py']
def hashes():return {f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES}
before=hashes();runs=[]
names=['test_file_workflow_and_persistent_api','test_policy_and_approval_are_before_execution',
       'test_restart_keeps_history_and_never_replays_uncertain_write','test_user_write_target_and_confirmation_policy',
       'test_verification_failure_and_later_recovery']
selected="import sys,types; import tests.test_agent_execution as m; s=types.ModuleType('execution_regressions'); "+'; '.join(
    's.'+n+'=m.'+n for n in names)+"; sys.exit(m.run_module(s))"
for name,args in [('replay',['tests/test_agent_replay.py']),('execution',['-c',selected]),
                  ('finish',['tests/test_finish_proposal.py'])]:
    command=[str(ROOT/'.venv/bin/python'),'-B',*args]
    run=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (OUT/(name+'.log')).write_text(run.stdout)
    runs.append({'suite':name,'exit_code':run.returncode,'command':command,'log':name+'.log',
        'passing_assertions':sum(line.startswith('PASS ') for line in run.stdout.splitlines())})
after=hashes();passed=before==after and all(r['exit_code']==0 for r in runs)
(OUT/'results.json').write_text(json.dumps({'date':datetime.now(timezone.utc).isoformat(),'passed':passed,
    'runs':runs,'source_before':before,'source_after':after,'source_stable':before==after,
    'baseline':'before-corrected-fixture.log: duplicate mutation executes again after timeout',
    'fixture_correction':'before.log used unsupported creation wording; corrected to supported create/read contract before production edit',
    'runtime_deployed':False,'real_model_calls':0,
    'limitations':['Identical capability and arguments within one goal only',
        'Not cross-goal idempotency or equivalence detection for altered arguments',
        'No live service restart or desktop action']},indent=2)+'\n')
sys.exit(0 if passed else 1)
