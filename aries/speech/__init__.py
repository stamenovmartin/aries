"""ARIES answering out loud — the missing half of the voice loop.

experiments/voice/voice.py turns speech into a command. This turns the outcome
back into speech, so that the person who spoke gets an answer instead of
silence. One call:

    from aries import speech
    speech.speak("Го отворив Фајерфокс.")          # detected as Macedonian
    speech.speak("Volume is now thirty percent.")   # detected as English

MACEDONIAN
----------
No NEURAL text-to-speech model has ever been published that was trained on
Macedonian speech — verified against Piper's 177 voices, Meta MMS's 1143
languages, XTTS-v2, Kokoro, Coqui's zoo and sherpa-onnx, all listed in
engines.py. But a real Macedonian voice does exist, and the user was right to
insist on it: RHVoice, written for blind users and packaged in Ubuntu, has two
voices recorded from Macedonian speakers. Measurements in experiments/speech/:

    rhvoice     (default)  Kiko — male, © Government of North Macedonia.
                Offline, 93 ms for a four-second sentence, 24 kHz, nothing
                leaves the machine. HTS parametric: audibly a synthesizer, but
                a Macedonian one. Chosen by ear: "гласот Kiko земи го".
    edge        Microsoft's mk-MK-AleksandarNeural, a native speaker and the
                most natural of all of them, but 0.4-1.6 s to first sound and
                the sentence goes to Microsoft. Kept as the fallback for a
                machine with no RHVoice.
    espeak-ng   offline and instant (~5 ms), genuinely Macedonian, and robotic
                enough that the user rejected it on hearing it. Selectable.

Piper's Bulgarian voice driven by a Macedonian front end was built and measured
(WER 0.58 against Kiko's own local alternative) and then refused outright —
"нејќам на бугарски". It is not in the Macedonian chain at any position.

    ARIES_SPEECH_MK=edge      the natural network voice instead
    ARIES_SPEECH_MK=espeak    the robot

English has no such problem: Piper's en_US-ryan-medium, local, ~78 ms to first
sound, against roughly 930 ms already spent getting the words out of Whisper.

WHAT THE DAEMON MUST DO WITH THIS
---------------------------------
Speak only when spoken to. The user's rule, in their words: "ако не го повикам
Ари, нека не се јавува" — sometimes they are on the phone in the same room, or
watching a film, and a machine that answers the television is worse than one
that says nothing. Nothing in this module can tell whether ARIES was addressed;
the wake gate in experiments/voice/voice.py can. So speak() belongs on the
branch that already passed that gate and acted, and nowhere else — not on a
dropped utterance, not on a low-confidence transcription, not on a refusal the
person never asked for.

Then: ARIES holds the microphone open. If it speaks into its own microphone,
Whisper transcribes ARIES, the router acts on it, and it answers itself — which
is not hypothetical, a feedback loop of exactly that shape ran 44 times on
2026-09-29. `speaking()` exists to be gated on, and `stop()` exists so that a
person who starts talking cuts ARIES off mid-word, as they would a person.

Nothing here reports success it did not observe. A non-blocking speak() returns
`state: "speaking"` and no measurements, because at that moment none have been
made; only a blocking one can say `state: "spoken"`, and it says so because it
watched the player exit cleanly.
"""
import threading
import time

from aries import flags
from . import engines, playback, replies

__all__ = ["speak", "answer", "stop", "speaking", "available", "warm", "detect", "replies"]

MAX_CHARS = 1000      # a spoken answer, not a read-aloud document

_lock = threading.Lock()
_current = None       # the live utterance: (Sink or Popen, cancel flag)
_thread = None


def detect(text):
    """Which language is ARIES speaking?

    One Cyrillic letter decides it. The rule is asymmetric because the evidence
    is: a Macedonian reply always contains Cyrillic, an English reply never
    does, and the ambiguous middle ("Го отворив Firefox") is a Macedonian
    sentence with a product name in it, not an English one.
    """
    return "mk" if any("Ѐ" <= c <= "ӿ" for c in text or "") else "en"


def answer(outcome, *, language=None, blocking=False):
    """Say what an outcome MEANS, which is not what an outcome says about itself.

    The one call the voice daemon wants. `/shell/act` returns "Task queued" before
    the goal finishes, and on 2026-09-30 that is what ARIES said out loud while
    the result already held the disk figures — every layer working and none of it
    reaching the person in words. replies.sentence() builds the sentence from the
    measurements instead; this wraps it so the daemon has one line to call.
    """
    # The caller usually knows the language of the request. When it does not, the
    # project's primary language decides — not a literal, which is what this was
    # until 2026-10-03 and which is how a frozen language keeps answering first.
    said = replies.sentence(outcome, language=language or flags.primary_language())
    spoken = speak(said, language=language, blocking=blocking)
    spoken["said"] = said
    return spoken


def speaking():
    """Is a sentence in the air right now?"""
    with _lock:
        return _current is not None and _current.running()


def stop():
    """Cut the current utterance off. True if there was one to cut off."""
    global _current
    with _lock:
        live, _current = _current, None
    if live is None:
        return False
    live.cancel()
    return True


def warm(language=None):
    """Pay the model load now instead of in front of the person.

    Worth calling once at daemon start: Piper costs ~0.7 s the first time and
    nothing afterwards, and that 0.7 s would otherwise land on the first answer
    of the day.
    """
    report = {}
    for code in ([language] if language else list(engines.DEFAULTS)):
        # Any fallback is warmed too. It only ever runs when the default has
        # already failed, which is the worst moment to then wait for a model.
        for kind in dict.fromkeys(k for k in (engines.chosen(code), engines.fallback(code)) if k):
            try:
                chosen = engines.engine(code, kind)
                report[f"{code}:{kind}"] = {"engine": chosen.name, "load_ms": chosen.warm()}
            except Exception as exc:                 # noqa: BLE001 - a health report never raises
                report[f"{code}:{kind}"] = {"engine": kind, "error": f"{type(exc).__name__}: {exc}"}
    return report


def available():
    """Can ARIES speak, and with what? Evidence, not a boolean."""
    player = playback.available()
    languages = {}
    for code in engines.DEFAULTS:
        kind = engines.chosen(code)
        try:
            chosen = engines.engine(code, kind)
            state = dict(chosen.check(), engine=chosen.name, kind=kind)
        except Exception as exc:                     # noqa: BLE001 - reported, never raised
            state = {"ready": False, "kind": kind, "detail": f"{type(exc).__name__}: {exc}"}
        state["alternatives"] = [k for k, langs in engines.KINDS.items() if code in langs and k != kind]
        state["fallback"] = engines.fallback(code)
        languages[code] = state
    ok = player and all(s.get("ready") for s in languages.values())
    return {"ok": ok, "player": playback.PLAYER, "player_present": player,
            "languages": languages,
            "detail": "ready" if ok else
                      f"{playback.PLAYER} is not installed" if not player else
                      "; ".join(f"{c}: {s.get('detail')}" for c, s in languages.items() if not s.get("ready"))}


def _utter(chosen, text, result):
    """Start the player empty and feed it, so the person hears the first sentence
    while the second is still being made."""
    global _current
    # Loading happens here rather than in speak(), because speak() must be able
    # to return before the model does. Charged to first_audio_ms, where it
    # belongs: to the person waiting it is not a load, it is silence.
    result["load_ms"] = chosen.warm()
    sink = playback.Sink(chosen.sample_rate)
    with _lock:
        _current = sink
    # Only the time spent inside the generator counts as synthesis. Writing to
    # the player blocks once its buffer is full, which is playback waiting to
    # happen, not work — charging it to the synthesizer made espeak-ng look
    # 150x slower than it is.
    chunks = chosen.stream(text)
    synthesis = 0.0
    while not sink.cancelled:
        at = time.monotonic()
        chunk = next(chunks, None)
        synthesis += time.monotonic() - at
        if chunk is None:
            break
        if result["first_audio_ms"] is None:
            result["first_audio_ms"] = (time.monotonic() - result["_started"]) * 1000
        if not sink.write(*chunk):
            break
    result["synthesis_ms"] = synthesis * 1000
    return sink


def _utterance(chosen, text, result, *, language=None):
    global _current
    sink = None
    try:
        sink = _utter(chosen, text, result)
        code, error = sink.close()
        played = sink.seconds
        result["audio_seconds"] = round(played, 3) if played is not None else None
        heard = f"{played:.2f} s" if played is not None else "the answer"
        if sink.cancelled:
            result.update(state="interrupted", ok=True, verified=False,
                          detail="stopped part way through, as requested")
        elif code == 0:
            result.update(state="spoken", ok=True, verified=True,
                          detail=f"{playback.PLAYER} played {heard} and exited cleanly")
        else:
            result.update(state="failed", ok=False, verified=False,
                          detail=error or f"{playback.PLAYER} exited {code}")
    except Exception as exc:                         # noqa: BLE001 - a failed answer is reported, not raised
        result.update(state="failed", ok=False, verified=False,
                      detail=f"{type(exc).__name__}: {exc}")
        if sink is not None:
            sink.cancel()
    finally:
        with _lock:
            if _current is sink:
                _current = None
        result.pop("_started", None)
    # A dropped connection is the one thing that can take ARIES's Macedonian
    # voice away, and for Macedonian there is deliberately nothing to fall back
    # to: the local alternatives were a Bulgarian voice and a robotic one, and
    # both were refused. So it fails, says why, and stays quiet rather than
    # answering in a language nobody asked for. ARIES_SPEECH_MK_FALLBACK=espeak
    # buys the robot back for anyone who prefers it to silence.
    spare = engines.fallback(language) if language else None
    if result["state"] == "failed" and spare and chosen.kind != spare:
        local = engines.engine(language, spare)
        retry = dict(result, engine=local.name, fell_back_from=chosen.name,
                     _started=time.monotonic(), first_audio_ms=None)
        spoken = _utterance(local, text, retry)
        spoken["detail"] = f"{chosen.name} failed ({result['detail']}); {spoken['detail']}"
        return spoken
    return result


def speak(text, *, language=None, blocking=False, engine=None):
    """Say something out loud. Returns what was actually observed.

    language  "mk", "en", or None to decide from the text.
    blocking  True waits for the last sample to be heard and can therefore
              report that it was; False returns as soon as playback is under
              way and reports only that it started.
    engine    "espeak", "piper" or "edge" to override this one utterance.

    A new utterance replaces any utterance still in the air. Latest wins on
    purpose: if the person has asked something else, the previous answer is
    already stale, and two voices over each other is worse than either.
    """
    text = " ".join((text or "").split())
    result = {"text": text, "state": "failed", "ok": False, "verified": False,
              "language": None, "engine": None, "truncated": False,
              "load_ms": None, "first_audio_ms": None, "synthesis_ms": None,
              "audio_seconds": None, "fell_back_from": None, "detail": ""}
    if not text:
        result["detail"] = "nothing to say"
        return result
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
        result.update(text=text, truncated=True)
    result["language"] = code = language or detect(text)
    if code not in engines.DEFAULTS:
        result["detail"] = f"no voice for language {code!r}"
        return result

    stop()
    try:
        chosen = engines.engine(code, engine)
        result["engine"] = chosen.name
    except (ValueError, KeyError) as exc:            # an engine name nobody can honour
        result["detail"] = f"{type(exc).__name__}: {exc}"
        return result

    result["_started"] = time.monotonic()
    if blocking:
        return _utterance(chosen, text, result, language=code)
    threading.Thread(target=_utterance, args=(chosen, text, result), kwargs={"language": code},
                     name="aries-speech", daemon=True).start()
    started = {k: v for k, v in result.items() if k != "_started"}
    started.update(state="speaking", ok=True, verified=False,
                   detail="playback started; nothing has been observed yet")
    return started
