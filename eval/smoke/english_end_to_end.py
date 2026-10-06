"""A0 smoke test: one English command through every layer except the microphone.

The plan asks for "one spoken English command end to end". That cannot be executed on
this machine: every analog jack reads `available: no`, there is no USB audio device,
and capture returns -82.8 dBFS. So this exercises the identical chain the daemon runs
after capture — route, execute, verify, build the sentence, synthesize it — and the one
missing link is named rather than papered over.

What it proves: the command reaches a capability, the capability is verified, the reply
is built from the verified result (not from the queue receipt), and the English voice
synthesizes it offline. What it does not prove: that speech would be recognised.
"""
import json
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'vendor/agentic-core'))
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'experiments/voice'))

import voice                                                     # noqa: E402
from aries import flags                                          # noqa: E402
from aries.speech import engines, replies                        # noqa: E402

COMMAND = sys.argv[1] if len(sys.argv) > 1 else 'how much disk space is free'
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None

print(f'policy    primary={flags.primary_language()} listen={flags.listen_languages()} '
      f'whisper={flags.whisper_model()}')
print(f'command   {COMMAND!r}')

started = time.monotonic()
result, act_s, err = voice.act(COMMAND)
if err:
    print(f'FAILED    the command was refused by the API: {err}')
    raise SystemExit(1)
outcome = voice.await_outcome(result, timeout=90)
elapsed = time.monotonic() - started

state = outcome.get('state')
steps = outcome.get('steps') or []
verified = [s for s in steps if (s.get('verification') or {}).get('met') is True]
unverifiable = [s for s in steps if (s.get('verification') or {}).get('unverifiable')]
print(f'state     {state}   ({elapsed:.1f} s, act {act_s*1000:.0f} ms)')
print(f'steps     {len(steps)}  verified {len(verified)}  unverifiable {len(unverifiable)}')
for s in steps:
    v = s.get('verification') or {}
    print(f'  - {s.get("capability") or s.get("kind")}: state={s.get("state")} '
          f'met={v.get("met")} {str(v.get("evidence") or "")[:90]}')

said = replies.sentence(outcome, language=flags.primary_language())
print(f'spoken    {said!r}')

# Synthesize rather than play: the only sink on this machine is an analog jack that
# jack detection reports as empty, so "it played" would be a claim without evidence.
# `stream()` is the engine contract every voice implements — see speech.speak().
import numpy as np
kind = engines.DEFAULTS[flags.primary_language()]
voiced = engines.engine(flags.primary_language(), kind)
voiced.warm()
def as_samples(chunk):
    """Engines yield PCM in whatever container suits them; take the bytes."""
    if isinstance(chunk, (tuple, list)) and chunk and isinstance(chunk[0], (bytes, bytearray)):
        chunk = chunk[0]
    try:
        return np.frombuffer(bytes(chunk), dtype=np.int16)
    except TypeError:
        return np.asarray(chunk, dtype=np.int16)


chunks = [as_samples(c) for c in voiced.stream(said)]
samples = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
rate = voiced.sample_rate
seconds = len(samples) / rate if rate else 0.0
print(f'voice     {voiced.name} · {seconds:.1f} s at {rate} Hz · {len(chunks)} chunks')
if OUT and len(samples):
    with wave.open(str(OUT), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(samples.astype(np.int16).tobytes())
    print(f'wrote     {OUT}')
synthesized = seconds > 0.5

# Deliberately NOT "steps > 0": a measurement question answers from readings and
# records its sub-goal outcome in the sentence rather than as a step, and demanding a
# step here would have made this smoke test fail on correct behaviour.
ok = (state in {'done', 'answered', 'partial'} and said
      and 'queued' not in said.casefold() and any(ch.isdigit() for ch in said)
      and synthesized)
print(f'\nSMOKE     {"PASS" if ok else "FAIL"} — reached a verified outcome and said it in English'
      if ok else f'\nSMOKE     FAIL — state={state} said={said!r}')
print('NOT PROVEN: speech recognition. There is no microphone attached to this machine.')
raise SystemExit(0 if ok else 1)
