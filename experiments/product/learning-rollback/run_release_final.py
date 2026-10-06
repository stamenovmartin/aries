import subprocess,json,hashlib,re,datetime
from pathlib import Path
root=Path('/tmp/aries-learning-rollback-k6qragg0')
out=Path('/home/stamenovmartin/aries/experiments/product/learning-rollback')
def hashes():return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('aries','aries_ui') for p in (root/folder).rglob('*.py')}
before=hashes();results=[]
for suite in ['test_learning_controls','test_learning_evidence_reuse','test_learning','test_reversal','test_goal_origin','test_agent_execution','test_agent_replay','test_orchestration_integration','test_workspace_recovery','test_memory_responsiveness','test_ui_render','test_security','test_workspace']:
    with (out/(suite+'-release-final.log')).open('w') as log:
        result=subprocess.run(['/home/stamenovmartin/aries/.venv/bin/python','tests/'+suite+'.py'],cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=240)
    content=(out/(suite+'-release-final.log')).read_text()
    row=dict(suite=suite,exit_code=result.returncode,passed=len(re.findall(r'^PASS  ',content,re.M)),failed=len(re.findall(r'^FAIL  ',content,re.M)));results.append(row);print(row,flush=True)
after=hashes();result=dict(date=datetime.datetime.now(datetime.timezone.utc).isoformat(),scratch=str(root),results=results,source_before=before,source_after=after,source_stable=before==after)
(out/'release-final-checks.json').write_text(json.dumps(result,indent=2)+'\n')
raise SystemExit(0 if before==after and all(r['exit_code']==0 and r['failed']==0 for r in results) else 1)
