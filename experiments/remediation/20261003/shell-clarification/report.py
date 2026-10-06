"""Render saved live API measurements; no new requests or acoustic claims."""
import json
from pathlib import Path
D=Path(__file__).parent
root=D.parents[3]
b=json.loads((D/'before.json').read_text());a=json.loads((D/'after.json').read_text())
assert b['n']==a['n']==2
text='\n'.join(['# Clarification reaches the voice API envelope','',f"Before: {b['measured_at']}; after: {a['measured_at']}.",'','| Measurement | Before (n) | After (n) |','|---|---:|---:|',f"| API message is the actual clarification question, with zero steps | {b['passed_n']}/{b['n']} | {a['passed_n']}/{a['n']} |",'', 'The spoken-reply formatter also returns the question in scoped tests. No acoustic speech playback or ASR quality is measured here.', 'An earlier batch received429; no result is credited for that interrupted batch. The600-second pause expired naturally before both paired requests; no reset or source switch.', ''])
(D/'REPORT.md').write_text(text)
p=root/'docs/ARIES_REPORT.md';s=p.read_text();start='<!-- SHELL-CLARIFICATION:START -->';end='<!-- SHELL-CLARIFICATION:END -->';block=start+'\n'+text+'\n'+end
if start in s:s=s[:s.index(start)]+block+s[s.index(end)+len(end):]
else:s+='\n\n'+block+'\n'
p.write_text(s)
