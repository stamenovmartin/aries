"""Preserve observed voice tradeoffs without declaring the unmet10-minute test passed."""
import json
from pathlib import Path
D=Path(__file__).parent
ROOT=D.parents[2]
r=json.loads((D/'replay_final.json').read_text());c=json.loads((D/'cost_final.json').read_text())
rows=['# Voice evidence supplied by the reviewing agent — 2026-10-03','',
 '| Measurement | Before (n) | After (n) |','|---|---:|---:|',
 f"| Synthetic spoken commands passing the wake/filter gates | {c['runs']['before']['accepted']}/{c['n']} | {c['runs']['after']['accepted']}/{c['n']} |",
 f"| False wake candidates in fixed playback replay | {r['runs']['before']['accepted']}/{r['utterances']} | {r['runs']['after']['accepted']}/{r['utterances']} |",'',
 f"Replay duration: {r['seconds']} seconds. Synthetic command mixture SNR: {c['snr_db']} dB.",'',
 'Wake/filter acceptance is not accurate transcription or successful execution. One synthetic speaker and one SNR do not establish live microphone reliability. No WER measured.',
 'False wakes increased; this measure did not improve. There is no completed probe_after.json for the required10-minute live acceptance run. A silent or unavailable microphone cannot prove rejection reliability. Item2.2 remains open.',
 'Artifacts were copied unchanged from the reviewing agent scratchpad; manifest.json records hashes. Source ownership was released in COORDINATION.md.','']
text='\n'.join(rows);(D/'REPORT.md').write_text(text)
p=ROOT/'docs/ARIES_REPORT.md';s=p.read_text();start='<!-- VOICE-20261003:START -->';end='<!-- VOICE-20261003:END -->';block=start+'\n'+text+'\n'+end
if start in s:s=s[:s.index(start)]+block+s[s.index(end)+len(end):]
else:s+='\n\n'+block+'\n'
p.write_text(s)
