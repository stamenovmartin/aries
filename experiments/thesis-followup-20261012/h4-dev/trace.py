"""Per-case action trace of an H4 run folder (read-only)."""
import json, sys
from pathlib import Path
run = Path(sys.argv[1])
res = json.loads((run / 'results.json').read_text())['results']
for r in res:
    rec = json.loads((run / 'records' / f"{r['id']}.json").read_text())
    a = rec.get('agent', {})
    seq = []
    for s in rec.get('steps', []):
        p = str((s.get('args') or {}).get('path', '')).split('ARIES-CIA-01/')[-1]
        code = (s.get('error') or {}).get('code') or ''
        seq.append(f"{s.get('capability')}({p}){'✓' if s.get('verification_status') == 'verified' else '✗' + code[:12]}")
    inval = [((d.get('error') or {}).get('code') or (d.get('error') or {}).get('type')) for d in a.get('decisions', []) if not d.get('valid', True)]
    print(f"{r['id']:9} {r['verdict']:5} state={rec.get('state'):20} calls={a.get('metrics',{}).get('planner_calls')} "
          f"invalid={inval[:3]} | {' → '.join(seq[:6])}")
