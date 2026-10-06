"""Render live response evidence and explicitly separate isolated broader checks."""
import json,sys
from pathlib import Path
D=Path(__file__).parent;ROOT=D.parents[1]
b=json.loads(Path(sys.argv[1]).read_text());a=json.loads(Path(sys.argv[2]).read_text())
assert b['fixture_sha256']==a['fixture_sha256'] and b['n']==a['n']==8
assert not b['runtime_changed'] and not a['runtime_changed']
assert b['started_at'][:10]==a['started_at'][:10]
s=json.loads((D/'submit225.json').read_text());counts={}
for label in ['before','after']:
 counts[label]={}
 for kind in ['actionable','ambiguous','out_of_scope','unsafe']:
  rows=[r for r in s['rows'] if r['condition']==label and r['class']==kind]
  counts[label][kind]={'n':len(rows),'clarified':sum(r['clarified'] for r in rows)}
text='\n'.join(['# Unresolved references ask before planning','',f"Live before: {b['started_at']}; after: {a['started_at']}.",'','| Measurement | Before (n) | After (n) |','|---|---:|---:|',f"| Live API response: structured question and zero queued steps | {b['passed_n']}/{b['n']} | {a['passed_n']}/{a['n']} |",f"| Isolated submit: ambiguous requests clarified | {counts['before']['ambiguous']['clarified']}/55 | {counts['after']['ambiguous']['clarified']}/55 |",f"| Isolated submit: actionable requests wrongly questioned | {counts['before']['actionable']['clarified']}/100 | {counts['after']['actionable']['clarified']}/100 |",'', 'Live trials use eight read-only utterances; only owned queued probes cancelled. This measures immediate clarification, not completed actions or acoustic speech.', 'Supplemental225 calls execute the actual submit function against an isolated ledger without a worker; memory observation disabled. Baseline submit source reconstructed by removing the exact insertion and checked against the saved live-baseline hash. No model or action acceptance claim.', '41/55 wider ambiguous cases remain uncovered. No generic OOD, unsafe-request or short-answer conversation resolution claim. Declining a recognizer match alone is not clarification.', ''])
(D/'REPORT.md').write_text(text)
p=ROOT/'docs/ARIES_REPORT.md';old=p.read_text();start='<!-- REFERENCE-CLARIFICATION:START -->';end='<!-- REFERENCE-CLARIFICATION:END -->';block=start+'\n'+text+'\n'+end
if start in old:old=old[:old.index(start)]+block+old[old.index(end)+len(end):]
else:old+='\n\n'+block+'\n'
p.write_text(old)
