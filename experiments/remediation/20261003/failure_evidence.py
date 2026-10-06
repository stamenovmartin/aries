"""Generate the fixed refusal-subset comparison; no replacement of the full60 score."""
import json,urllib.request
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[3]
D=Path(__file__).parent
B=ROOT/'experiments/assistant-benchmark/20261003T113052Z-after-file-parser/results.json'
A=ROOT/'experiments/assistant-benchmark/20261003T114058Z-after-failure-evidence-subset/results.json'
b=json.loads(B.read_text());a=json.loads(A.read_text())
before=[r for r in b['cases'] if r['category']=='refusal'];after=a['cases']
assert [r['id'] for r in before]==[r['id'] for r in after]
assert a['finished_at'] and b['finished_at'] and not a['runtime_changed'] and not b['runtime_changed']
result={'before_artifact':str(B.relative_to(ROOT)),'after_artifact':str(A.relative_to(ROOT)),
        'before_started_at':b['started_at'],'after_started_at':a['started_at'],
        'before_passed_n':sum(r['passed'] for r in before),'after_passed_n':sum(r['passed'] for r in after),'n_each':len(before),
        'full60_after_pending':False,'full60_after_artifact':'experiments/assistant-benchmark/20261003T131001Z-clarification-final/results.json','observed_errors':{}}
for label,cases in [('before',before),('after',after)]:
    errors=Counter();typed=0;steps_n=0;verified=0
    for case in cases:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/aries/workspace/'+case['goal_id'],timeout=10) as response:goal=json.load(response)
        for step in goal['steps']:
            steps_n+=1;error=step.get('error') or {};typed+=isinstance(error,dict) and bool(error.get('code'))
            errors[error.get('code','not_recorded') if isinstance(error,dict) else 'untyped']+=1
            verified+=step.get('verification_status')=='verified'
    result['observed_errors'][label]={'steps_n':steps_n,'typed_error_n':typed,'error_codes':dict(errors),'claimed_verified_n':verified}
result['limitations']=['Same frozen8 subset, unchanged predicates. Full60 rerun completed; linked artifact retains all60 cases and separate clarification changes.',
    'Six policy-blocked reads were blocked before and after; improvement is durable typed evidence, not broader access.',
    'Two targets are missing files rather than explicit policy exclusions; kept as unmet refusal predicates. No metric relabeling.']
(D/'failure-evidence.json').write_text(json.dumps(result,indent=2)+'\n')
rows=['# Typed capability-failure evidence', '',f"Before: {b['started_at']}; after: {a['started_at']}.", '',
 '| Item | Before (n) | After (n) |', '|---|---:|---:|',
 f"| Frozen refusal predicate | {result['before_passed_n']}/{len(before)} | {result['after_passed_n']}/{len(after)} |",
 f"| Stored typed step error | {result['observed_errors']['before']['typed_error_n']}/{result['observed_errors']['before']['steps_n']} | {result['observed_errors']['after']['typed_error_n']}/{result['observed_errors']['after']['steps_n']} |",
 '',*result['limitations'],'']
rendered='\n'.join(rows);(D/'FAILURE_EVIDENCE.md').write_text(rendered)
p=ROOT/'docs/ARIES_REPORT.md';previous=p.read_text();start='<!-- FAILURE-EVIDENCE:START -->';end='<!-- FAILURE-EVIDENCE:END -->';block=start+'\n'+rendered+'\n'+end
if start in previous:previous=previous[:previous.index(start)]+block+previous[previous.index(end)+len(end):]
else:previous+='\n\n'+block+'\n'
p.write_text(previous)
print(json.dumps(result))
