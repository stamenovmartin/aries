"""Count how often ARIES *would* accept a command while music with 'Ari' plays.

It calls voice.py's own listen / decode_command / wake_match, so the decision
chain under test is the shipped one. It never calls act(), because the point is
to count false wakes, not to let forty-four of them start forty-four songs.
"""
import argparse, json, sys, time, types
sys.path.insert(0, '/home/stamenovmartin/aries/experiments/voice')
import voice

ap = argparse.ArgumentParser()
ap.add_argument('--minutes', type=float, default=10.0)
ap.add_argument('--input', default=None)
ap.add_argument('--label', default='run')
ap.add_argument('--out', required=True)
cli = ap.parse_args()

args = types.SimpleNamespace(
    languages=['mk', 'en'], language=None,
    silence_ms=400, max_seconds=15.0, start_timeout=8.0,
    follow_silence_ms=900, follow_timeout=2.5, input=cli.input,
)
model, load_s = voice.load_model('var/models/faster-whisper-large-v3', 'cuda', 'float16')
ep = voice.Endpointer('var/models/silero_vad.onnx', threshold=0.5)
print(f'[{cli.label}] model loaded in {load_s*1000:.0f} ms · input={cli.input or "default source"}', flush=True)

tally = {'label': cli.label, 'input': cli.input or 'default-source',
         'heard': 0, 'dropped': 0, 'not_addressed': 0, 'accepted': 0,
         'accepted_texts': [], 'dropped_reasons': [], 'playing_seen': 0}
deadline = time.monotonic() + cli.minutes * 60
while time.monotonic() < deadline:
    try:
        audio, timing = voice.listen(ep, args.silence_ms, args.max_seconds,
                                     start_timeout=4.0, device=args.input)
    except Exception as exc:
        print(f'capture failed: {exc}', flush=True); time.sleep(2); continue
    if audio is None:
        continue
    tally['heard'] += 1
    if voice.audio_is_playing():
        tally['playing_seen'] += 1
    try:
        text, stt_s, info, lang, lang_p = voice.decode_command(model, audio, args)
    except Exception as exc:
        print(f'decode failed: {exc}', flush=True); continue
    if not text:
        tally['dropped'] += 1
        if voice.DROPPED:
            tally['dropped_reasons'].append('; '.join(voice.DROPPED)[:160])
        continue
    command = voice.wake_match(text)
    if command is None:
        tally['not_addressed'] += 1
        print(f'  not addressed [{lang} {lang_p:.2f}]: {text[:70]!r}', flush=True)
        continue
    tally['accepted'] += 1
    tally['accepted_texts'].append(text[:120])
    print(f'  ACCEPTED [{lang} {lang_p:.2f}]: {text[:100]!r}', flush=True)

with open(cli.out, 'w') as f:
    json.dump(tally, f, ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in tally.items() if k != 'accepted_texts'}, ensure_ascii=False), flush=True)
