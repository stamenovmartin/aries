"""Generate dated live planner comparison without changing routing policy."""
import json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
d=Path(sys.argv[1]);data=json.loads((d/'results.json').read_text())
assert data['finished_at'] and not data['source_changed']
lines=['# Live planner comparison', '', 'Measured: '+data['started_at'], '',
'| Backend | Plausible next decision (n) | Valid JSON (n) | Valid schema (n) | Median seconds |', '|---|---:|---:|---:|---:|']
for name,r in data['summary'].items():
 lines.append(f"| {name} | {r['usable_n']}/{r['n']} | {r['valid_json_n']}/{r['n']} | {r['valid_schema_n']}/{r['n']} | {r['median_latency_s']} |")
lines += ['', 'Identical frozen23 payloads; fallback disabled; actual local/cloud backends called. No actions executed. This scores plausible next capability/action and schema, not end-to-end goal completion or fully correct arguments. Continuation fixtures contain seeded observations.', '', 'Unusable decisions: '+ '; '.join(r['requested_level']+':'+r['id']+' chose '+str(r.get('chose')) for r in data['rows'] if not r['usable']), '', 'Routing policy remains unchanged; the user decides after reviewing evidence. One daily sample, not a longitudinal accuracy estimate.', '']
if len(sys.argv)>2:
 before_path=Path(sys.argv[2]);before=json.loads((before_path/'results.json').read_text())
 assert before['fixture_sha256']==data['fixture_sha256'] and not before['source_changed']
 assert before['started_at'][:10]==data['started_at'][:10]
 lines += ['## Same-day instruction change', '', 'Before artifact: '+str(before_path), '', '| Backend | Before plausible (n) | After plausible (n) | Before median s | After median s |', '|---|---:|---:|---:|---:|']
 for name,a in data['summary'].items():
  b=before['summary'][name]
  lines.append(f"| {name} | {b['usable_n']}/{b['n']} | {a['usable_n']}/{a['n']} | {b['median_latency_s']} | {a['median_latency_s']} |")
 lines += ['', 'One sample per case/backend before and after. Prompt wording separates desktop windows from browser tabs. Model nondeterminism and shared load remain; no causal latency or held-out generalization claim.', '']
if (d/'decision.json').exists():
 decision=json.loads((d/'decision.json').read_text());lines += ['Candidate accepted: '+str(decision['accepted']), decision['reason'], 'Candidate never deployed to core; own instruction change reverted to measured baseline hash.', '']
rendered='\n'.join(lines);(d/'REPORT.md').write_text(rendered)
p=root/'docs/ARIES_REPORT.md';s=p.read_text();start='<!-- PLANNER-DAILY:START -->';end='<!-- PLANNER-DAILY:END -->';block=start+'\n'+rendered+'\n'+end
if start in s:s=s[:s.index(start)]+block+s[s.index(end)+len(end):]
else:s+='\n\n'+block+'\n'
p.write_text(s)
