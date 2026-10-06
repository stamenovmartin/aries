"""Speech in, ARIES action out — the VOICE -.-> CMD edge from JARVIS_ARCHITECTURE.md.

Deliberately a measurement instrument first and a feature second. The end goal is a
desktop driven by speaking, and for that the only number that decides whether the idea
works is how long a person waits between finishing a sentence and the machine acting.
So every path here reports its own latency, split into the parts you can actually
attack: capture, transcription, routing.

ARIES already owns the meaning of a command — /api/aries/command is the single router
both command bars use. This adds no second interpretation of intent; it only turns
sound into the text that router already accepts.
"""
import argparse, json, math, os, re, sys, tempfile, time, urllib.request, urllib.error
from pathlib import Path

import numpy as np

# The live signal the shell's mark moves on. Optional on purpose: a desktop with
# no session bus, or a shell that is not listening, must not stop the microphone
# working. If it cannot be imported the loop runs exactly as before, silently.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from pulse import (Pulse, IDLE as PHASE_IDLE, LISTENING as PHASE_LISTENING,
                       THINKING as PHASE_THINKING, ACTING as PHASE_ACTING,
                       SETTLED as PHASE_SETTLED, REFUSED as PHASE_REFUSED)
except Exception:                                    # noqa: BLE001 - drawing is never load-bearing
    PHASE_IDLE = PHASE_LISTENING = PHASE_THINKING = 'idle'
    PHASE_ACTING = PHASE_SETTLED = PHASE_REFUSED = 'idle'

    class Pulse:                                     # a no-op with the same shape
        def emit(self, level, phase, confidence=-1.0): pass
        def close(self): pass

# Answering out loud. Guarded for the same reason the pulse is: speaking is the
# part a person notices, but listening is the part that must not stop. If the
# module cannot import, ARIES goes back to being silent and keeps working.
try:
    from aries import speech
except Exception:                                    # noqa: BLE001
    speech = None

SAMPLE_RATE = 16000          # what Whisper wants; resampling later costs latency
BASE = 'http://127.0.0.1:8000/api/aries'


def load_model(size, device, compute):
    from faster_whisper import WhisperModel
    t0 = time.monotonic()
    model = WhisperModel(size, device=device, compute_type=compute)
    return model, time.monotonic() - t0


# Whisper decodes a short command with almost no context, which is why it
# returned Italian and Romanian for Macedonian speech. Naming the wake word and
# the verbs that actually get said pulls the decoder toward them. The research
# on this is blunt: for a small closed command vocabulary, biasing beats a
# bigger model.
#
# But the prompt must never contain a whole "Ari, <command>" sentence. On music
# or noise Whisper regurgitates its prompt, and on 2026-09-29 it produced
# "Ari, play some music." from a song ARIES had started — which passed the wake
# gate, started another song, and looped 44 times. A bare word list still
# biases the vocabulary, and regurgitated it does not start with the name.
PROMPTS = {
    'mk': 'Речник: YouTube, Spotify, Firefox, вести, статус, екран, поставки, музика, песна, звук.',
    'en': 'Vocabulary: YouTube, Spotify, Firefox, news, status, screen, settings, music, song, volume.',
}
_PROMPT_WORDS = {w.casefold() for p in PROMPTS.values() for w in re.findall(r'\w+', p)}

# The usual Whisper hallucination thresholds (the reference implementation uses
# the same three): a segment that is probably not speech, that the model was
# unsure of, or that repeats itself is not a command.
NO_SPEECH_MAX = 0.6
AVG_LOGPROB_MIN = -1.0
COMPRESSION_MAX = 2.4
LANGUAGE_CONFIDENCE_MIN = 0.10
# A STRICTER BAR WHILE AUDIO PLAYS WAS TRIED AND REMOVED, 2026-10-03.
#
# The idea was that a wake word hallucinated out of music scores worse than a
# spoken one, so the same six gates held higher (no_speech 0.30, logprob -0.55)
# exactly while the speakers are on would catch the 2026-09-29 loop. Measured
# both directions on this machine, it did neither:
#
#   false wakes, one 155 s recording through both versions, 12 utterances:  2 -> 2
#   real commands over music at +10 dB SNR, n=10:         7/10 without, 5/10 with
#
# It caught nothing and cost two commands in ten. The premise was simply wrong:
# the passage really does say "Ари, пушти нешто" in clean speech, and no
# confidence threshold can reject that — nor should one. What DOES fix it is not
# listening to the loudspeakers at all; see capture_target() below. Echo
# rejection against our own last sentence stays, because it identifies the one
# case by content rather than by confidence.
_LAST_SPOKEN = ['']                  # what ARIES itself said last, for echo rejection

DROPPED = []                 # why the last transcription discarded what it did


def pick_language(model, audio, allowed):
    """Choose between a few known languages instead of all ninety-nine.

    Left to itself Whisper picked Italian, Romanian and Urdu on consecutive
    Macedonian commands — a two-second utterance simply does not carry enough
    evidence to identify a language from scratch. But forcing one language is
    wrong too when the speaker uses two. So detection still runs; it just only
    gets to choose among the languages this person actually speaks.
    """
    _, _, all_probs = model.detect_language(audio)
    ranked = [(l, p) for l, p in all_probs if l in allowed]
    if not ranked:
        return None, 0.0
    # A near-zero winner is weak evidence — but letting the decoder resolve the
    # utterance instead is worse, and measurably so. On 2026-10-03, ten real
    # Macedonian commands mixed over music at +10 dB SNR: the unconstrained
    # decoder returned Portuguese, Bulgarian, Romanian, Croatian and Polish, and
    # seven of the ten were then discarded as "unsupported detected language".
    # This person speaks two languages. The weak winner between those two still
    # decides which; what weak evidence forfeits is the vocabulary prompt, which
    # is where a wrong guess does real damage (it regurgitates its own wordlist).
    language, probability = max(ranked, key=lambda lp: lp[1])
    return language, probability


def transcribe(model, audio, language, prompt=None):
    t0 = time.monotonic()
    segments, info = model.transcribe(
        audio, language=language, beam_size=1,           # beam 1: latency over the last % of accuracy
        vad_filter=True,                                 # drop leading/trailing silence before decoding
        initial_prompt=prompt,
        condition_on_previous_text=False)                # a command is not a continuation of the last one
    kept, DROPPED[:] = [], []
    for s in segments:
        nsp_max = NO_SPEECH_MAX
        lp_min = AVG_LOGPROB_MIN
        if s.no_speech_prob <= nsp_max and s.avg_logprob >= lp_min \
                and s.compression_ratio <= COMPRESSION_MAX:
            kept.append(s)
        else:
            # Logged by serve(): if a real command is ever dropped, these numbers
            # are what the thresholds get tuned against.
            DROPPED.append(f'{s.text.strip()[:50]!r} nsp={s.no_speech_prob:.2f} '
                           f'lp={s.avg_logprob:.2f} cr={s.compression_ratio:.2f}'
                           )
    text = ' '.join(s.text.strip() for s in kept).strip()
    words = [w.casefold() for w in re.findall(r'\w+', text)]
    if words and all(w in _PROMPT_WORDS for w in words):
        DROPPED.append(f'{text[:50]!r} prompt echo')
        text = ''                                        # the prompt echoed back, not speech
    if caption_hallucination(text):
        DROPPED.append(f'{text[:70]!r} caption hallucination')
        text = ''
    return text, time.monotonic() - t0, info


def route(text):
    """Hand the text to the router ARIES already uses. Never a second intent model."""
    req = urllib.request.Request(
        BASE + '/command', data=json.dumps({'text': text}).encode(),
        headers={'Content-Type': 'application/json'})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r), time.monotonic() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.monotonic() - t0, f'HTTP {e.code}: {e.read()[:200].decode(errors="replace")}'
    except Exception as e:
        return None, time.monotonic() - t0, f'{type(e).__name__}: {e}'


def record(seconds, device=None):
    """Capture through PipeWire directly.

    Not sounddevice: that binds PortAudio, which is a system library needing root to
    install, and this machine already runs PipeWire with a chosen default source.
    Shelling out to pw-record keeps the prototype installable by the user who wants
    to run it, and honours whatever input they picked in Settings.
    """
    import subprocess
    argv = ['pw-record', '--rate', str(SAMPLE_RATE), '--channels', '1',
            '--format', 's16', '--latency', '20ms']
    target = capture_target(device)
    if target:
        argv += ['--target', str(target)]
    argv += ['-']
    t0 = time.monotonic()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    want = int(seconds * SAMPLE_RATE) * 2          # s16 = 2 bytes per frame
    buf = b''
    try:
        while len(buf) < want:
            chunk = proc.stdout.read(min(8192, want - len(buf)))
            if not chunk:
                break
            buf += chunk
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    if len(buf) < SAMPLE_RATE:                      # under 0.5 s of audio came back
        err = proc.stderr.read()[:200].decode(errors='replace')
        raise RuntimeError(f'pw-record returned {len(buf)} bytes; {err or "is a source selected?"}')
    audio = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, time.monotonic() - t0


class Endpointer:
    """Decide when the person stopped talking. This, not the model, is the wait.

    Whisper pads every input to a 30 s mel spectrogram, so decoding a 4 s command
    costs the same as decoding a 1 s one — measured at 57-111 ms on this GPU. A
    silence threshold of 800 ms therefore costs seven to fourteen times more than
    the transcription does. It is the only latency here worth tuning.

    Silero over onnxruntime rather than the torch build: the ONNX graph is 2.3 MB
    and runs in ~0.1 ms per frame, against roughly 900 MB of PyTorch for the same
    decision. faster-whisper's own VadOptions are NOT used for this — their
    min_silence_duration_ms default is 2000, which would silently impose a
    two-second wait on every command.
    """

    WINDOW, CONTEXT = 512, 64      # the v5/v6 graph wants 576 = 512 new + 64 carried

    def __init__(self, path, threshold=0.5):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = opts.intra_op_num_threads = 1
        self.sess = ort.InferenceSession(path, opts, providers=['CPUExecutionProvider'])
        self.threshold = threshold
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros(self.CONTEXT, dtype=np.float32)

    def speech_probability(self, frame):
        """frame: exactly WINDOW samples. Feeding a bare 512 returns 0.0 forever."""
        x = np.concatenate([self.context, frame]).astype(np.float32)[None, :]
        out, self.state = self.sess.run(None, {'input': x, 'state': self.state,
                                               'sr': np.array(SAMPLE_RATE, dtype=np.int64)})
        self.context = frame[-self.CONTEXT:]
        return float(out[0][0])


def listen(endpointer, silence_ms=400, max_seconds=15.0, start_timeout=8.0, device=None, pulse=None):
    """Record until the speaker stops, and report where the time actually went.

    `pulse`, when given, receives the live speech probability for every 32 ms
    frame. It is the same number the endpointer decides on — the shell's mark
    moves because a person is actually speaking, not because a timer says so.
    """
    import subprocess
    argv = ['pw-record', '--rate', str(SAMPLE_RATE), '--channels', '1',
            '--format', 's16', '--latency', '20ms']
    target = capture_target(device)
    if target:
        argv += ['--target', str(target)]
    argv += ['-']
    hop = Endpointer.WINDOW * 2                      # s16 bytes per VAD frame
    need_silent = max(1, int(silence_ms / (Endpointer.WINDOW / SAMPLE_RATE * 1000)))
    endpointer.reset()

    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames, silent_run, started_at = [], 0, None
    t0 = time.monotonic()
    try:
        while True:
            buf = proc.stdout.read(hop)
            if not buf or len(buf) < hop:
                break
            frame = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
            p = endpointer.speech_probability(frame)
            if pulse is not None:
                pulse.emit(p, PHASE_LISTENING)
            now = time.monotonic()
            if started_at is None:
                if p >= endpointer.threshold:
                    started_at = now
                    frames.append(frame)
                elif now - t0 > start_timeout:
                    return None, {'reason': 'no speech started', 'waited': now - t0}
                continue
            frames.append(frame)
            silent_run = silent_run + 1 if p < endpointer.threshold else 0
            if silent_run >= need_silent or now - started_at > max_seconds:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    if started_at is None or not frames:
        return None, {'reason': 'no speech captured'}
    ended = time.monotonic()
    audio = np.concatenate(frames)
    # The endpoint fires silence_ms AFTER the last word, so the honest "how long
    # did the machine make me wait" starts there, not at the end of the buffer.
    return audio, {'to_speech': started_at - t0,
                   'spoke_for': (ended - started_at) - silence_ms / 1000,
                   'endpoint_wait': silence_ms / 1000,
                   'samples': len(audio)}


def bench(model, durations):
    """Compute cost only: silence of a known length, so the number is the decode path.

    Silence is not speech and this is NOT an accuracy measurement — it bounds how much
    of the wait is the model rather than the person still talking.
    """
    rows = []
    for d in durations:
        audio = np.zeros(int(d * SAMPLE_RATE), dtype=np.float32)
        _, secs, _ = transcribe(model, audio, 'en')
        rows.append((d, secs))
    return rows


# The name it answers to, the way Siri answers to "Siri". An always-listening
# microphone that acted on everything it heard would act on the television, on a
# phone call, on the other person in the room.
#
# The gate is on the TRANSCRIPT rather than a separate wake-word model: the audio
# is being transcribed anyway, so this costs nothing and adds no second thing
# that can be wrong. Whisper spells a short name several ways depending on which
# language it decided it was hearing, and Macedonian speech comes back in
# Cyrillic, so both alphabets are listed.
# Measured against what Whisper actually returned, not what it ought to: a
# leading H appears on the name constantly ("Хари", "Hari"), because a bare
# two-syllable name at the very start of an utterance has no context to anchor
# it. Listing the mishearings is cheaper and more honest than pretending the
# model will stop making them.
WAKE = ('ari', 'ари', 'hari', 'хари', 'arie', 'арие', 'aries', 'ариес',
        'арес', 'арис', 'harry', 'ari̇')

# Do not admit ara/ара (an ordinary interjection) or the ambiguous ary alias.
# Transcription variants must not turn ordinary room speech into authority.
# The name must be a whole word. "ari" as a bare prefix would fire on Ariana, on
# аригато, on arithmetic — a false wake is worse than a missed one here, because
# a false wake executes something.
_WAKE_RE = __import__('re').compile(
    r'^[\s.,!?\-—"\'«»]*(' + '|'.join(WAKE) + r')[\s.,!?\-—:;"\'«»]+(.*)$',
    __import__('re').IGNORECASE | __import__('re').DOTALL)


def audio_is_playing():
    """Is sound coming out of this machine right now? Cached for two seconds.

    PipeWire's own graph, not MPRIS. MPRIS only knows applications that register as
    media players — it does not know `pw-play`, which is what ARIES's own speech
    uses, so an MPRIS-only check would have missed the very source it exists to
    guard against. A running `Stream/Output/Audio` node is the honest signal: it
    catches a browser, a music app, and ARIES itself, with no allowlist to maintain.

    Unknown is not evidence: if the graph cannot be read, this returns False and the
    ordinary thresholds apply, because silently tightening the bar on every utterance
    would drop real commands for a reason nobody could see.
    """
    # A test must not decide differently because the developer happens to have
    # music on: that would make the thresholds depend on the room.
    if os.environ.get('APP_ENV', '').strip().lower() == 'test':
        return False
    now = time.monotonic()
    if now - _PLAYING[1] < 2.0:
        return _PLAYING[0]
    playing = False
    try:
        import subprocess
        out = subprocess.run(['pw-dump'], capture_output=True, text=True, timeout=4)
        if out.returncode == 0:
            for node in json.loads(out.stdout):
                info = node.get('info') or {}
                props = info.get('props') or {}
                if (info.get('state') == 'running'
                        and props.get('media.class') == 'Stream/Output/Audio'):
                    playing = True
                    break
    except Exception:                                     # noqa: BLE001
        playing = False
    _PLAYING[0], _PLAYING[1] = playing, now
    return playing


_PLAYING = [False, 0.0]


# WHICH NODE DOES pw-record READ?  This is not a detail.
#
# On 2026-10-03 this machine's `default.audio.source` was the OUTPUT sink
# (alsa_output.pci-0000_00_1f.3.iec958-stereo), so every capture came from that
# sink's MONITOR: ARIES was listening to its own loudspeaker feed, digitally,
# rather than to the microphone. Measured here on the same 12 s passage at
# volume 0.40, six seconds per cell:
#
#     default source (sink monitor)   silence -120.0 dBFS   playing -21.6 dBFS
#     real microphone                 silence  -83.4 dBFS   playing -55.6 dBFS
#
# A monitor hands ARIES its own speech 34 dB louder than the room does, and its
# silence is exact digital zero, which no microphone has ever produced. No
# threshold on the transcript can repair that — the input itself is wrong. So the
# source is resolved here, and a sink monitor is never chosen.
_TARGET = [False, 0.0, None]         # resolved name, when, the last note printed


def _pw_nodes():
    import subprocess
    try:
        out = subprocess.run(['pw-dump'], capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    try:
        return json.loads(out.stdout)
    except ValueError:
        return []


def real_sources(nodes=None):
    """Genuine audio inputs on this machine. A sink monitor is not an input."""
    found = []
    for node in (_pw_nodes() if nodes is None else nodes):
        props = ((node.get('info') or {}).get('props') or {})
        name = props.get('node.name') or ''
        if props.get('media.class') == 'Audio/Source' and '.monitor' not in name:
            found.append(name)
    return found


def default_source_name():
    """What the session calls its default input — which may be a sink."""
    import subprocess
    try:
        out = subprocess.run(['pw-metadata', '-n', 'default'],
                             capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"key:'default\.audio\.source' value:'(.*?)' type", out.stdout or '')
    if not m:
        return None
    try:
        return (json.loads(m.group(1)) or {}).get('name')
    except ValueError:
        return None


def source_is_connected(name, nodes=None):
    """Does anything appear to be plugged into this input? None when unknowable.

    The ALC887 codec exposes `alsa_input...analog-stereo` whether or not a
    microphone is in the jack, and recording from an empty jack returns a clean
    -83 dBFS of nothing. On 2026-10-03 every analog route on this machine read
    `available: no` — there was no microphone attached at all, which is a very
    different thing from ARIES mishearing, and worth saying in those words.
    """
    nodes = _pw_nodes() if nodes is None else nodes
    device_id = None
    for node in nodes:
        props = ((node.get('info') or {}).get('props') or {})
        if props.get('node.name') == name:
            device_id = props.get('device.id')
            break
    if device_id is None:
        return None
    for node in nodes:
        info = node.get('info') or {}
        props = info.get('props') or {}
        if props.get('media.class') != 'Audio/Device' or node.get('id') != device_id:
            continue
        routes = (info.get('params') or {}).get('EnumRoute') or []
        inputs = [r for r in routes if r.get('direction') == 'Input']
        if not inputs:
            return None
        if any(r.get('available') != 'no' for r in inputs):
            return True
        return False
    return None


def capture_target(explicit=None, cache_seconds=30.0):
    """The `pw-record --target` to use. An explicit --input is always honoured.

    Returns None only when the machine really has no input: pw-record's own
    default then applies and record() reports the silence instead of pretending.
    The reason is printed once per change, never per utterance.
    """
    if explicit:
        return explicit
    now = time.monotonic()
    if _TARGET[0] is not False and now - _TARGET[1] < cache_seconds:
        return _TARGET[0]
    sources = real_sources()
    wanted = default_source_name()
    chosen = wanted if wanted in sources else (sources[0] if sources else None)
    # Ordered by what a person needs to know first. An empty jack outranks a
    # misconfigured default, because no setting repairs a missing microphone.
    if not sources:
        note = 'no real audio input exists; recording from whatever PipeWire defaults to'
    elif source_is_connected(chosen) is False:
        note = (f'{chosen!r} is the only input on this machine and NOTHING IS PLUGGED '
                f'INTO IT — every analog jack on its card reads unavailable, so capture '
                f'is silence until a microphone or headset is connected')
    elif wanted is None:
        note = f'the session has no default input at all; capturing from {chosen!r}'
    elif wanted != chosen:
        note = (f'the session default source is {wanted!r}, which is not a microphone '
                f'— capturing from {chosen!r} instead')
    else:
        note = f'microphone {chosen!r}'
    if note != _TARGET[2]:
        print(f'· input: {note}', flush=True)
    _TARGET[0], _TARGET[1], _TARGET[2] = chosen, now, note
    return chosen


def echoes_own_speech(text, spoken):
    """True when the transcript is mostly words ARIES just said out loud."""
    if not spoken or not text:
        return False
    said = {w for w in re.findall(r'\w+', spoken.casefold()) if len(w) > 2}
    heard = [w for w in re.findall(r'\w+', text.casefold()) if len(w) > 2]
    if not said or len(heard) < 2:
        return False
    return sum(w in said for w in heard) / len(heard) >= 0.6


def speak_and_remember(sentence, language):
    """Say it, and keep it, so the next transcription can recognise an echo.

    Every spoken reply goes through here. A sentence ARIES never remembers
    saying is a sentence echoes_own_speech() cannot recognise, and the 44-goal
    loop of 2026-09-29 started with exactly one unremembered sentence.
    """
    _LAST_SPOKEN[0] = sentence or ''
    speech.speak(sentence, language=language, blocking=True)


def wake_match(text):
    """Return the command with the name removed, or None if it was not addressed."""
    if text.strip().casefold() in WAKE:
        return ''
    m = _WAKE_RE.match(text.strip())
    return m.group(2).strip() if m else None


def caption_hallucination(text):
    """Known standalone caption echoes; quoted phrases inside commands remain text."""
    command = wake_match(text)
    normalized = ' '.join(re.findall(r'\w+', command if command is not None else text)).casefold()
    return bool(re.fullmatch(
        r'(?:thank(?:s| you) for watching(?: subscribe(?: for more videos)?)?'
        r'|captions by gettranscribed com|subtitles by amara org'
        r'|благодарам (?:што гледавте|за гледањето))', normalized))


def decode_command(model, audio, args):
    language, probability = (pick_language(model, audio, args.languages)
                             if args.languages else (args.language, 1.0))
    # The echo check only means anything if something is actually coming out of
    # the speakers; asking costs one cached pw-dump.
    playing = audio_is_playing()
    prompt = PROMPTS.get(language) if probability >= LANGUAGE_CONFIDENCE_MIN else None
    text, seconds, info = transcribe(model, audio, language, prompt)
    if language is None:
        language = getattr(info, 'language', None)
        probability = getattr(info, 'language_probability', 0.0)
        if args.languages and language not in args.languages:
            DROPPED.append(f'unsupported detected language: {language}')
            text = ''
    # Hearing our own last sentence back is not a command, however confidently
    # Whisper transcribed it — it transcribed it well precisely because it was
    # clean synthetic speech. Only while audio is out, so a person who repeats
    # what ARIES said is still heard.
    if text and playing and echoes_own_speech(text, _LAST_SPOKEN[0]):
        DROPPED.append(f'echo of our own reply: {text[:60]!r}')
        text = ''
    return text, seconds, info, language, probability


def await_outcome(result, *, timeout=8.0):
    """Read this goal's durable result; submitting a task is not completing it."""
    if result.get('ok') is False:
        return {'state': 'refused', 'error': result.get('message') or result.get('error') or ''}
    outcome = result.get('result') if isinstance(result.get('result'), dict) else result
    goal_id = outcome.get('id')
    if not goal_id or outcome.get('state') not in {'queued', 'running'}:
        return outcome
    # IDs come from our API, but never allow one to turn a status read into a
    # different endpoint. No shell command, external URL or retry of the action.
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(goal_id)):
        return {'state': 'unknown', 'error': 'Invalid task identifier'}
    deadline = time.monotonic() + max(0.0, timeout)
    while outcome.get('state') in {'queued', 'running'}:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with urllib.request.urlopen(BASE + '/workspace/' + goal_id,
                                        timeout=min(2.0, remaining)) as response:
                observed = json.load(response)
            if not isinstance(observed, dict) or observed.get('id') != goal_id:
                return {'state': 'unknown', 'error': 'Task response did not match the submitted goal'}
            outcome = observed
        except Exception as exc:
            return {'state': 'unknown', 'error': f'{type(exc).__name__}: {exc}'}
        if outcome.get('state') in {'queued', 'running'}:
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
    return outcome


def spoken_outcome(outcome, language):
    from aries.speech.replies import sentence
    state = outcome.get('state')
    if state in {'queued', 'running'}:
        return ('Сè уште работам на задачата. Резултатот ќе биде во прегледот на задачите.'
                if language == 'mk' else 'I am still working on it. The result will appear in your tasks.')
    if state == 'unknown':
        return ('Не можам да проверам дали задачата заврши.' if language == 'mk'
                else 'I cannot confirm whether the task finished.')
    if state in {'failed', 'refused', 'cancelled', 'interrupted'}:
        # Earlier successful readings are not the outcome of a failed goal.
        detail = outcome.get('summary') or '; '.join(str(g) for g in outcome.get('gaps', [])[:2])
        return sentence({'state': 'failed', 'error': str(detail or outcome.get('error') or '')[:240]},
                        language=language)
    agent = outcome.get('agent') or {}
    if state in {'done', 'partial'} and (outcome.get('orchestration') or {}).get('role') == 'parent':
        answer = next((card.get('text') for card in outcome.get('cards', [])
                       if card.get('title') == 'Answer'), None)
        if answer:
            # Parent roll-up already builds this from each independently
            # verified child's answer, including any missing sub-goal. The
            # neighbouring audit card is useful on screen, not speech.
            return sentence({'summary': answer}, language=language)
    contract = agent.get('contract') or {}
    requirements = contract.get('requirements') or []
    if state in {'done', 'answered'} and agent.get('finished') and requirements \
            and requirements[-1].get('capability') == 'file.read':
        refs = {ref.strip() for card in outcome.get('cards', [])
                if card.get('title') in {'Answer', 'Verified goal result'}
                for ref in str(card.get('evidence') or '').split(',')}
        wanted = requirements[-1].get('path')
        for proof in reversed(outcome.get('evidence', [])):
            data = proof.get('data') or {}
            if proof.get('verified') is True and proof.get('evidence_id') in refs \
                    and proof.get('source') == 'file.read' and isinstance(data, dict) \
                    and data.get('path') == wanted and isinstance(data.get('text'), str):
                content = data['text'].strip()
                if not content:
                    return 'Датотеката е празна.' if language == 'mk' else 'The file is empty.'
                if len(content) > 800:
                    prefix = 'Почетокот на датотеката е: ' if language == 'mk' else 'The file begins: '
                    return prefix + content[:800].rsplit(' ', 1)[0] + '…'
                return ('Во датотеката пишува: ' if language == 'mk' else 'The file says: ') + content
    if state == 'answered' and agent.get('finished') and contract.get('answer') == 'measurements':
        # The Answer card references the final independent recheck. Older
        # execution readings may differ, and include metrics not asked about.
        from aries.workspace.contracts import measured_readings
        refs = {ref.strip() for card in outcome.get('cards', []) if card.get('title') == 'Answer'
                for ref in str(card.get('evidence') or '').split(',')}
        readings = [reading for proof in outcome.get('evidence', [])
                    if proof.get('verified') is True and proof.get('evidence_id') in refs
                    for requirement in contract.get('requirements', [])
                    for reading in measured_readings(proof.get('data'), requirement)]
        if readings:
            return sentence({'readings': readings}, language=language)
    return sentence(outcome, language=language)


def spoken_error(error, language):
    """A rejected command needs an audible next step, not a silent log line."""
    mk = language == 'mk'
    match = re.fullmatch(r'HTTP (\d{3}): (.*)', str(error), re.S)
    code = int(match[1]) if match else None
    if code == 429:
        return ('Добив премногу повторени команди. Почекај малку пред следната команда.' if mk
                else 'I received too many repeated commands. Please wait before trying again.')
    if code in {400, 409}:
        try:
            detail = json.loads(match[2]).get('detail')
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str) and detail.startswith('AMBIGUOUS:'):
            return detail.partition(':')[2].strip()[:300]
        return ('Не можам да ја извршам така зададената команда. Кажи ја поконкретно.' if mk
                else 'I cannot carry out that command as given. Please be more specific.')
    if code in {401, 403}:
        return ('Немам дозвола за таа команда.' if mk else 'I do not have permission for that command.')
    return ('Не можам да добијам одговор од системот во моментов.' if mk
            else 'I cannot get a response from the system right now.')


class PendingReplies:
    """Bounded status reads between captures; never a second execution path."""
    def __init__(self, state_path=None):
        self.goals = {}
        self.state_path = Path(state_path) if state_path else None
        if self.state_path and self.state_path.exists():
            try:
                if self.state_path.stat().st_size > 16384:
                    raise ValueError('Pending reply state is too large')
                saved = json.loads(self.state_path.read_text())
                if not isinstance(saved, dict) or saved.get('version') != 1:
                    raise ValueError('Unknown pending reply state')
                for row in saved.get('goals', [])[:16]:
                    if not isinstance(row, dict):
                        continue
                    goal_id, language = row.get('id'), row.get('language')
                    expires = row.get('expires')
                    if not isinstance(goal_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', goal_id):
                        continue
                    if language not in {'mk', 'en'} or not isinstance(expires, (int, float)):
                        continue
                    remaining = expires - time.time()
                    if math.isfinite(remaining) and 0 < remaining <= 1800:
                        self.goals[goal_id] = (language, time.monotonic() + remaining)
            except (OSError, ValueError, TypeError):
                print('Could not restore pending voice replies; task results remain in the dashboard.', flush=True)

    def _save(self):
        if not self.state_path:
            return
        temporary = None
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            # IDs and expiry only: never persist transcripts or file contents.
            now, wall = time.monotonic(), time.time()
            saved = {'version': 1, 'goals': [
                {'id': gid, 'language': lang, 'expires': wall + expires - now}
                for gid, (lang, expires) in self.goals.items() if expires > now]}
            with tempfile.NamedTemporaryFile(mode='w', dir=self.state_path.parent,
                                             prefix='.voice-pending-', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(saved, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.state_path)
        except OSError:
            print('Could not save pending voice replies; task results remain in the dashboard.', flush=True)
        finally:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def add(self, outcome, language):
        goal_id = outcome.get('id')
        if outcome.get('state') not in {'queued', 'running'} or \
                not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(goal_id or '')):
            return False
        if goal_id not in self.goals and len(self.goals) >= 16:
            return False  # Its durable answer remains in the task dashboard.
        self.goals[goal_id] = (language, time.monotonic() + 1800)
        self._save()
        return True

    def discard(self, goal_id):
        if goal_id in self.goals:
            del self.goals[goal_id]
            self._save()

    def ready(self):
        # At most 0.6 s of status I/O per capture cycle, rotating fairly.
        for goal_id, (language, expires) in list(self.goals.items())[:2]:
            if time.monotonic() >= expires:
                del self.goals[goal_id]
                self._save()
                continue
            self.goals.pop(goal_id)
            self.goals[goal_id] = (language, expires)
            try:
                with urllib.request.urlopen(BASE + '/workspace/' + goal_id, timeout=.3) as response:
                    outcome = json.load(response)
            except Exception:                         # transient read failure; no re-execution
                continue
            if not isinstance(outcome, dict) or outcome.get('id') != goal_id:
                continue
            if outcome.get('state') in {'done', 'answered', 'partial', 'failed', 'refused',
                                        'cancelled', 'interrupted', 'proposed'}:
                del self.goals[goal_id]
                self._save()
                return outcome, language
        return None


def act(text):
    """Hand the sentence to ARIES the same way the command bar does.

    kind=workspace is the catch-all the shell already posts for anything the
    intent table did not match: the workspace planner recognises it, plans it and
    executes it through the permission-checked, audited path. Deliberately NOT a
    second interpretation of meaning, and deliberately not a privileged desktop
    route into ARIES — voice gets exactly the authority the command bar has.
    """
    req = urllib.request.Request(
        BASE + '/shell/act', data=json.dumps({'kind': 'workspace', 'text': text, 'source': 'voice'}).encode(),
        headers={'Content-Type': 'application/json'})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r), time.monotonic() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.monotonic() - t0, f'HTTP {e.code}: {e.read(4096).decode(errors="replace")}'
    except Exception as e:
        return None, time.monotonic() - t0, f'{type(e).__name__}: {e}'


def serve(model, endpointer, args):
    """Listen forever. One utterance at a time, acting only when addressed."""
    log = lambda m: print(m, flush=True)   # journald is the window; stdout is the log
    pulse = Pulse()
    if speech is not None and not args.mute:
        try:
            warm = speech.warm()
            log(f'voice ready — {warm}' if warm else 'voice ready')
        except Exception as exc:                     # noqa: BLE001
            log(f'speech unavailable, continuing silently: {type(exc).__name__}: {exc}')
    log(f'aries-voice ready — wake word required, one of {WAKE}')
    heard = acted = 0
    pending = PendingReplies(getattr(args, 'pending_state', None))
    while True:
        # Capturing has not started yet. Blocking speech here cannot feed the
        # microphone loop, and reading a finished goal cannot replay its action.
        ready = pending.ready()
        if ready:
            completed, reply_language = ready
            log(f'· delayed result {completed["id"]} — {completed["state"]}')
            if speech is not None and not args.mute:
                try:
                    speak_and_remember(spoken_outcome(completed, reply_language),
                                       reply_language)
                except Exception as exc:             # noqa: BLE001
                    log(f'  (could not speak delayed result: {type(exc).__name__}: {exc})')
        try:
            audio, timing = listen(endpointer, args.silence_ms, args.max_seconds,
                                   start_timeout=min(args.start_timeout, 1.0) if pending.goals else args.start_timeout,
                                   device=args.input, pulse=pulse)
        except Exception as exc:                       # a device disappearing must not end the service
            log(f'capture failed: {type(exc).__name__}: {exc}')
            time.sleep(2)
            continue
        if audio is None:
            continue                                   # nobody spoke; go round again
        heard += 1
        pulse.emit(1.0, PHASE_THINKING)
        try:
            text, stt_s, info, lang, lang_p = decode_command(model, audio, args)
        except Exception as exc:
            log(f'transcription failed: {type(exc).__name__}: {exc}')
            continue
        if not text:
            if DROPPED:
                log('· dropped ' + '; '.join(DROPPED))
            continue
        command = wake_match(text)
        if command is None:
            # Heard, understood, and not for us. That is a distinct state from
            # failure, and the mark should show the difference.
            pulse.emit(0.0, PHASE_IDLE)
            log(f'· not addressed [{lang} {lang_p:.2f}] ({stt_s*1000:.0f}ms): {text[:70]!r}')
            continue
        if not command:
            # The name alone. People pause after a wake word — "Ari… open
            # YouTube" is one intention spoken with a breath in the middle, and
            # treating the pause as the end of the utterance threw away the half
            # that said what to do. So keep the microphone open and take the
            # next thing said as the command, with no second wake word.
            log('· woken — listening for the command')
            pulse.emit(0.0, PHASE_LISTENING)
            follow, ftiming = listen(endpointer, args.follow_silence_ms, args.max_seconds,
                                     start_timeout=args.follow_timeout, device=args.input, pulse=pulse)
            if follow is None:
                log('· nothing followed the name')
                continue
            try:
                command, stt_s, info, lang, lang_p = decode_command(model, follow, args)
            except Exception as exc:
                log(f'transcription failed: {type(exc).__name__}: {exc}')
                continue
            command = (command or '').strip()
            # It may have repeated the name; strip it rather than search for it.
            again = wake_match(command)
            if again is not None:
                command = again
            if not command:
                log('· nothing followed the name')
                continue
            timing = ftiming
        acted += 1
        pulse.emit(1.0, PHASE_ACTING)
        result, act_s, err = act(command)
        wait = (timing['endpoint_wait'] + stt_s) * 1000
        if err:
            pulse.emit(0.0, PHASE_REFUSED)
            log(f'✗ {command[:60]!r} — {err}')
            if speech is not None and not args.mute:
                try:
                    speak_and_remember(spoken_error(err, lang), lang)
                except Exception as exc:             # noqa: BLE001
                    log(f'  (could not speak: {type(exc).__name__}: {exc})')
        else:
            receipt = result.get('result') if isinstance(result.get('result'), dict) else result
            pending.add(receipt, lang)
            outcome = await_outcome(result, timeout=args.reply_wait)
            state = outcome.get('state')
            pending.add(outcome, lang)
            if state in {'done', 'answered', 'partial', 'failed', 'refused',
                         'cancelled', 'interrupted', 'proposed'}:
                pending.discard(outcome.get('id'))
            phase = PHASE_ACTING if state in {'queued', 'running'} else (
                PHASE_REFUSED if state in {'failed', 'refused', 'cancelled', 'interrupted', 'unknown'}
                else PHASE_SETTLED)
            pulse.emit(0.0, phase)
            log(f'· {command[:60]!r} — {state or "response received"} '
                f'(heard in {wait:.0f}ms, acted in {act_s*1000:.0f}ms)')
            # blocking, deliberately: serve() records one utterance at a time, so
            # speaking while the microphone is open means transcribing ourselves.
            # That loop actually happened, 44 times, on 2026-09-29.
            if speech is not None and not args.mute:
                try:
                    speak_and_remember(spoken_outcome(outcome, lang), lang)
                except Exception as exc:             # noqa: BLE001
                    log(f'  (could not speak: {type(exc).__name__}: {exc})')
        log(f'  [{acted} acted / {heard} utterances]')


def main():
    p = argparse.ArgumentParser(description='ARIES voice prototype: speech -> /api/aries/command')
    p.add_argument('mode', choices=['bench', 'listen', 'say', 'serve'], help='bench: decode latency; listen: one utterance; serve: listen forever behind a wake word; say: route text without a microphone')
    p.add_argument('--model', default='small', help='faster-whisper size: tiny/base/small/medium/large-v3')
    p.add_argument('--device', default='auto', choices=['auto', 'cuda', 'cpu'])
    p.add_argument('--compute', default='', help='float16 (GPU) / int8 (CPU); blank picks per device')
    p.add_argument('--language', default=None, help="ISO code, e.g. en or mk; omit to auto-detect")
    p.add_argument('--seconds', type=float, default=4.0, help='listen: how long to record')
    p.add_argument('--input', default=None, help='listen: pw-record --target (omit for the default source)')
    p.add_argument('--text', default=None, help='say: the sentence to route')
    p.add_argument('--no-route', action='store_true', help='transcribe only; do not call ARIES')
    p.add_argument('--fixed', action='store_true', help='listen: record --seconds flat instead of endpointing')
    p.add_argument('--silence-ms', type=int, default=400, help='listen: silence that ends the utterance (300-500 is the useful range)')
    p.add_argument('--max-seconds', type=float, default=15.0, help='listen: hard cap on one utterance')
    p.add_argument('--vad-model', default='var/models/silero_vad.onnx')
    p.add_argument('--vad-threshold', type=float, default=0.5)
    p.add_argument('--start-timeout', type=float, default=8.0, help='how long one listen waits for speech to begin')
    p.add_argument('--mute', action='store_true', help='serve: act, but never answer out loud')
    p.add_argument('--pending-state', default=str(Path(__file__).resolve().parents[2] / 'var/voice-pending.json'),
                   help='serve: retain pending result IDs across restarts')
    p.add_argument('--reply-wait', type=float, default=8.0,
                   help='serve: seconds to wait for a real task result before reporting that it is still running')
    p.add_argument('--languages', default='', help='serve: comma list to choose BETWEEN, e.g. en,mk. Omit to take aries.flags.listen_languages(), which is the single place that decides.')
    p.add_argument('--follow-silence-ms', type=int, default=900, help='serve: silence ending the command after the name — longer, because a command is a sentence')
    p.add_argument('--follow-timeout', type=float, default=6.0, help='serve: how long to wait for a command after hearing only the name')
    args = p.parse_args()

    if args.mode == 'say':
        if not args.text:
            p.error('say needs --text')
        action, secs, err = route(args.text)
        print(f'route   {secs*1000:7.0f} ms')
        print(json.dumps(action, ensure_ascii=False, indent=1) if action else f'  ERROR {err}')
        return

    device = args.device
    if device == 'auto':
        try:
            import ctranslate2
            device = 'cuda' if ctranslate2.get_cuda_device_count() > 0 else 'cpu'
        except Exception:
            device = 'cpu'
    compute = args.compute or ('float16' if device == 'cuda' else 'int8')

    print(f'model={args.model} device={device} compute={compute}', flush=True)
    model, load_s = load_model(args.model, device, compute)
    print(f'load    {load_s*1000:7.0f} ms', flush=True)

    args.languages = tuple(x.strip() for x in args.languages.split(',') if x.strip())
    if not args.languages and not args.language:
        # English became primary on 2026-10-03 and Macedonian was frozen. With one
        # language there is nothing to misdetect, which matters here more than it
        # sounds: unconstrained detection answered Macedonian speech with pt, bg,
        # ro, hr and pl, and our own filter then discarded seven of ten real
        # commands. `aries.flags` is the only place that decides this.
        try:
            from aries import flags as _flags
            args.languages = _flags.listen_languages()
            if len(args.languages) == 1:
                args.language, args.languages = args.languages[0], ()
        except Exception as exc:                          # noqa: BLE001
            print(f'· language policy unavailable ({type(exc).__name__}); detecting freely', flush=True)
    if args.mode == 'serve':
        serve(model, Endpointer(args.vad_model, threshold=args.vad_threshold), args)
        return

    if args.mode == 'bench':
        transcribe(model, np.zeros(SAMPLE_RATE, dtype=np.float32), 'en')   # warm the kernels
        print('\n audio_s   decode_ms   xRT')
        for d, secs in bench(model, [1, 2, 4, 8]):
            print(f'{d:7.1f}   {secs*1000:9.0f}   {d/secs:5.1f}x')
        return

    if args.fixed:
        audio, cap_s = record(args.seconds, args.input)
        timing = {'spoke_for': args.seconds, 'endpoint_wait': 0.0}
        print(f'capture {cap_s*1000:7.0f} ms   (fixed {args.seconds}s, no endpointer)')
    else:
        ep = Endpointer(args.vad_model, threshold=args.vad_threshold)
        print(f'listening — speak, then stop (endpoint at {args.silence_ms} ms of silence)', flush=True)
        audio, timing = listen(ep, args.silence_ms, args.max_seconds, device=args.input)
        if audio is None:
            print(f'  nothing heard: {timing.get("reason")}')
            return
        print(f'speech  {timing["spoke_for"]*1000:7.0f} ms spoken, '
              f'endpoint fired {timing["endpoint_wait"]*1000:.0f} ms after you stopped')

    peak = float(np.abs(audio).max())
    text, stt_s, info = transcribe(model, audio, args.language)
    if peak < 0.01:
        print(f'        peak_amplitude={peak:.3f}   <- silent: wrong input device?')
    print(f'stt     {stt_s*1000:7.0f} ms   lang={getattr(info, "language", "?")}')
    print(f'heard: {text!r}')
    if not text or args.no_route:
        return
    action, r_s, err = route(text)
    print(f'route   {r_s*1000:7.0f} ms')
    print(json.dumps(action, ensure_ascii=False, indent=1) if action else f'  ERROR {err}')
    # What the person actually experiences: everything after their last word.
    print(f'\nWAIT AFTER YOUR LAST WORD: {(timing["endpoint_wait"] + stt_s + r_s)*1000:.0f} ms')


if __name__ == '__main__':
    main()
