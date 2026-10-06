#!/usr/bin/env python3
"""Read-only publication consistency checks, no model/network required."""
from pathlib import Path
import hashlib,json,re
root=Path(__file__).resolve().parent;repo=root.parent.parent
manifest=json.loads((root/'evidence-manifest.json').read_text())
for item in manifest['artifacts']:
 assert hashlib.sha256((repo/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
rows=[json.loads(x) for x in (repo/'experiments/operator/results.jsonl').read_text().splitlines()]
summary=json.loads((repo/'experiments/operator/summary.json').read_text())
assert len(rows)==372
assert sum(r['class']=='control' for r in rows)==60
assert summary['verifier_integrity']['checkable']==52
assert summary['verifier_integrity']['wrongly_met']==0
for variant in ('A','B2'):
 assert summary['variants'][variant]['verified_success']==60
 assert summary['variants'][variant]['checkable']==67
 assert summary['variants'][variant]['false_successes']==4
paper=(root/'paper.md').read_text()
for i,source in enumerate(re.findall(r'```mermaid\n(.*?)```',paper,re.S),1):
 assert source==(root/'diagrams'/f'figure-{i}.mmd').read_text()
 assert '<svg' in (root/'diagrams'/f'figure-{i}.svg').read_text()
for filename in ('paper.md','slides.md','README.md','m14-results.md'):
 for target in re.findall(r'\]\(([^)]+)\)',(root/filename).read_text()):
  if not target.startswith(('http:','https:','#')):
   assert (root/target.split('#')[0]).exists(),(filename,target)
run=json.loads((repo/'experiments/agent/20260917T204354Z-fb8722/result.json').read_text())
assert run['passed']==run['total']==4
assert sum(c['metrics']['total_tokens'] for c in run['cases'])==36039
assert sum(c['planner_calls'] for c in run['cases'])==10
assert all(c['local_model_observed'] and c['metrics']['token_measurement_complete'] for c in run['cases'])
negative=next(c for c in run['cases'] if c['scenario']=='negative-control')
assert negative['task_state']=='failed' and negative['passed']
for c in run['cases']:
 task=json.loads((repo/'experiments/agent/20260917T204354Z-fb8722/tasks'/f"{c['scenario']}.json").read_text())
 evidence={e['evidence_id']:e for e in task['evidence']}
 assert all(evidence[ref]['verified'] for ref in task['final_evidence_refs'])
 if c['scenario']=='negative-control':
  assert task['steps'][0]['error']['error_type']=='FileNotFoundError'
replication=json.loads((repo/'experiments/agent/20260917T204843Z-1ae7a7/result.json').read_text())
assert replication['passed']==replication['total']==4
html=(root/'presentation.html').read_text()
assert len(re.findall('<section id=',html))==18
assert not re.search(r'<(?:script|link)[^>]+(?:src|href)=["\']https?://',html)
print('Publication checks passed: artifact digests, 372 rows/60 controls/52 eligible, A/B2 counts, four Mermaid sources/SVGs, local links, 18 offline slides, M14 4/4 and native tokens/final evidence refs.')
