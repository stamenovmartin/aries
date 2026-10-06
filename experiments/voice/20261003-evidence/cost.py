"""Does the stricter playback bar reject REAL commands while music plays?

A gate that drops false wakes by also dropping true ones is not a fix. There is
no microphone on this machine, so the commands are synthesized with the same
RHVoice/Piper voices ARIES uses and mixed over the recorded music bed at the
signal-to-noise ratio a person speaking near a microphone actually produces.
Both chains then decode exactly the same mixtures.
"""
import importlib.util, json, sys, types, wave
from unittest.mock import patch
import numpy as np

sys.path.insert(0, '/home/stamenovmartin/aries')
from aries.speech import rhvoice

SP, OUT, ORIG = sys.argv[1], sys.argv[2], sys.argv[3]
SR = 16000
SNR_DB = 10.0            # a person at the microphone against speakers across the room

COMMANDS = [
    ('mk', 'Ари, пушти ја музиката'),
    ('mk', 'Ари, намали го звукот'),
    ('mk', 'Ари, отвори го YouTube'),
    ('mk', 'Ари, колку диск ми е слободен'),
    ('mk', 'Ари, подели го екранот лево и десно'),
    ('mk', 'Ари, прикажи го статусот на системот'),
    ('mk', 'Ари, тивко'),
    ('mk', 'Ари, кои прозорци ми се отворени'),
    ('mk', 'Ари, зголеми го звукот'),
    ('mk', 'Ари, покажи ги вестите'),
]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resample(x, src, dst=SR):
    if src == dst:
        return x
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x)


with wave.open(f'{SP}/lyric_monitor.wav') as w:
    bed = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768

engine = rhvoice.engine()
fixed = load('/home/stamenovmartin/aries/experiments/voice/voice.py', 'voice_fixed')
original = load(ORIG, 'voice_original')
model, _ = fixed.load_model('var/models/faster-whisper-large-v3', 'cuda', 'float16')
args = types.SimpleNamespace(languages=['mk', 'en'], language=None)

report = {'snr_db': SNR_DB, 'n': len(COMMANDS), 'runs': {}, 'cases': []}
mixtures = []
for lang, text in COMMANDS:
    samples, sr = engine.render(text, 'kiko')
    voice_sig = resample(samples.astype(np.float32) / 32768, sr)
    # Place it over a random stretch of the music bed at the chosen SNR.
    start = np.random.default_rng(len(text)).integers(0, len(bed) - len(voice_sig) - SR)
    noise = bed[start:start + len(voice_sig)].copy()
    v_rms, n_rms = np.sqrt((voice_sig ** 2).mean()), np.sqrt((noise ** 2).mean())
    if n_rms > 0:
        noise *= v_rms / (n_rms * 10 ** (SNR_DB / 20))
    mix = np.clip(voice_sig + noise, -1.0, 1.0).astype(np.float32)
    mixtures.append((text, mix))

for name, module, playing in (('before', original, False), ('after', fixed, True)):
    tally = {'accepted': 0, 'dropped': 0, 'not_addressed': 0}
    for text, mix in mixtures:
        module.DROPPED.clear()
        with patch.object(module, 'audio_is_playing', return_value=playing):
            heard, _, _, _, _ = module.decode_command(model, mix, args)
        command = module.wake_match(heard) if heard else None
        if not heard:
            tally['dropped'] += 1
            verdict = 'dropped: ' + '; '.join(module.DROPPED)[:90]
        elif command is None:
            tally['not_addressed'] += 1
            verdict = f'not addressed: {heard[:60]!r}'
        else:
            tally['accepted'] += 1
            verdict = f'accepted: {command[:60]!r}'
        report['cases'].append({'run': name, 'said': text, 'verdict': verdict})
        print(f'  [{name:6s}] {text[:34]:34s} -> {verdict}', flush=True)
    report['runs'][name] = tally
    print(f'  {name:6s} accepted {tally["accepted"]}/{len(mixtures)}  '
          f'not addressed {tally["not_addressed"]}  dropped {tally["dropped"]}', flush=True)

with open(OUT, 'w') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
for name, tally in report['runs'].items():
    print(f"{name:22s} {tally['accepted']}/{len(mixtures)} accepted", flush=True)
print(f"\nshipped code, real commands over music: "
      f"{report['runs']['before']['accepted']}/{len(mixtures)} -> "
      f"{report['runs']['after']['accepted']}/{len(mixtures)}", flush=True)
