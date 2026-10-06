"""Paired replay: one recording, two versions of the decision chain.

Two live runs cannot be compared honestly — the room is not the same twice, and
on this machine the acoustic path turned out to be silent anyway. So the same
recorded audio is segmented once, by the same endpointer the daemon uses, and
every segment is then decoded by BOTH modules. Identical input, identical
segmentation, one difference: the code. That is the only way this particular
fix can be shown to do anything.
"""
import importlib.util, json, sys, types, wave
from unittest.mock import patch
import numpy as np

RECORDING, OUT = sys.argv[1], sys.argv[2]
SAMPLE_RATE, WINDOW = 16000, 512


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def segments(audio, endpointer, silence_ms=400, min_speech_frames=3, max_seconds=15.0):
    """Cut the recording where listen() would have cut it."""
    need_silent = max(1, int(silence_ms / (WINDOW / SAMPLE_RATE * 1000)))
    out, buf, speech, silent, started = [], [], 0, 0, False
    for i in range(0, len(audio) - WINDOW, WINDOW):
        frame = audio[i:i + WINDOW]
        p = endpointer.speech_probability(frame)
        if p >= endpointer.threshold:
            speech += 1; silent = 0; started = True
        elif started:
            silent += 1
        if started:
            buf.append(frame)
        if started and silent >= need_silent:
            if speech >= min_speech_frames:
                out.append(np.concatenate(buf))
            buf, speech, silent, started = [], 0, 0, False
            endpointer.reset()
        elif started and len(buf) * WINDOW >= max_seconds * SAMPLE_RATE:
            out.append(np.concatenate(buf))
            buf, speech, silent, started = [], 0, 0, False
            endpointer.reset()
    if started and speech >= min_speech_frames:
        out.append(np.concatenate(buf))
    return out


with wave.open(RECORDING) as w:
    assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768

fixed = load('experiments/voice/voice.py', 'voice_fixed')
original = load(sys.argv[3], 'voice_original')

ep = fixed.Endpointer('var/models/silero_vad.onnx', threshold=0.5)
cuts = segments(audio, ep)
rms = float(np.sqrt((audio ** 2).mean()))
print(f'{len(audio)/SAMPLE_RATE:.0f} s of recording at {20*np.log10(rms):.1f} dBFS '
      f'-> {len(cuts)} utterances the endpointer would have handed to Whisper', flush=True)

model, _ = fixed.load_model('var/models/faster-whisper-large-v3', 'cuda', 'float16')
args = types.SimpleNamespace(languages=['mk', 'en'], language=None)
report = {'recording': RECORDING, 'seconds': len(audio) / SAMPLE_RATE,
          'dbfs': round(20 * float(np.log10(rms)), 1), 'utterances': len(cuts), 'runs': {}}

for name, module, playing in (('before', original, False), ('after', fixed, True)):
    # `playing` is True for the fixed chain because it WAS true when this was
    # recorded; the original chain has no such parameter at all, which is the point.
    tally = {'accepted': 0, 'not_addressed': 0, 'dropped': 0, 'accepted_texts': []}
    for i, cut in enumerate(cuts):
        module.DROPPED.clear()
        with patch.object(module, 'audio_is_playing', return_value=playing):
            try:
                text, _, _, lang, lang_p = module.decode_command(model, cut, args)
            except Exception as exc:
                print(f'  [{name}] utterance {i} failed: {exc}', flush=True)
                continue
        if not text:
            tally['dropped'] += 1
            continue
        command = module.wake_match(text)
        if command is None:
            tally['not_addressed'] += 1
            continue
        tally['accepted'] += 1
        tally['accepted_texts'].append(text[:110])
    report['runs'][name] = tally
    print(f'  {name:6s} accepted {tally["accepted"]:3d}  not addressed {tally["not_addressed"]:3d}  '
          f'dropped {tally["dropped"]:3d}', flush=True)

with open(OUT, 'w') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
b, a = report['runs']['before']['accepted'], report['runs']['after']['accepted']
print(f'\nfalse wakes on identical audio: {b} -> {a}  (n = {len(cuts)} utterances)', flush=True)
