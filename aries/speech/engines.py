"""The three ways ARIES can make a sound, and what each of them costs.

Each engine turns text into (int16 bytes, seconds) chunks at a known sample
rate. Nothing above this file knows which one is speaking, which is the point:
Macedonian and English do not have to be served by the same technology, and on
this machine they should not be.

    espeak  local, offline, GPL-3.0, +20 MB, real MACEDONIAN phonology, formant
            synthesis — correct and robotic. Whisper recovers 14% of its words.
    piper   local, offline, MIT model weights, 63 MB and +91 MB per voice, a
            recorded human voice. ENGLISH ONLY here: Piper has no Macedonian
            voice, and answering Macedonian with its Bulgarian one was tried,
            measured (42% of words recovered) and refused by the user.
    edge    Microsoft's neural voices over the network, including two native
            Macedonian ones. Natural AND correct — 58% recovered, the best of
            the three — and the only option here that sends the sentence off
            this machine.

WHY THERE IS NO SINGLE RIGHT ANSWER FOR MACEDONIAN
--------------------------------------------------
Checked, not assumed:
  * Piper publishes 177 voices in 58 languages. No Macedonian. Its one
    "sr_RS" voice was trained on the Serbski institut LOWER SORBIAN corpus —
    a different language, mislabelled upstream.
  * Meta's MMS-TTS covers 1143 languages, listed in its own file manifest.
    Macedonian is not one of them (nor Serbian, Croatian or Slovenian;
    Bulgarian and Russian are). Licence there is CC-BY-NC-4.0 regardless.
  * XTTS-v2 and Kokoro list their languages explicitly; neither includes mk.
  * A Hugging Face search for Macedonian models returns ASR, OCR and LLMs
    only — no speech synthesis.
So no downloadable neural model has ever been trained on Macedonian speech.
What remains is a rule-based synthesizer that knows the language (espeak-ng),
a natural voice that does not (Piper Bulgarian), and a cloud service that is
both (Microsoft). The user heard all three and ruled: the Microsoft voice, and
no Bulgarian at any price — not as a default, not as a fallback. So Piper is
English-only in this file and Macedonian has no local engine wired up.

There is one more, found by looking harder after the user insisted a real
Macedonian voice must exist. They were right: `rhvoice-macedonian` is an
official Ubuntu package (resolute/multiverse, RHVoice 1.14) holding a voice
recorded from a Macedonian speaker — offline, GPL, statistical-parametric, so
clearer than espeak and less natural than neural. It needs root to install, so
it is named here and not yet implemented. That is the gap to close next.
"""
import os
import queue as queue_module
import re
import threading
import time
from pathlib import Path

import numpy as np

MODELS = Path(__file__).resolve().parents[2] / "var/models/piper"
SILENCE = 328          # int16 amplitude under which 10 ms of samples is nothing
SENTENCE_GAP_MS = 120  # what replaces the half-second of padding VITS emits


def trim(samples, sample_rate):
    """Drop the silence a synthesizer pads each sentence with.

    Measured on the Piper voices: ~250 ms of nothing before the first consonant
    and ~300 ms after the last. Spoken back to someone waiting for an answer
    that quarter second is the difference between a reply and a pause, and at
    the end it is a quarter second before the microphone can safely reopen.
    """
    frame = max(1, sample_rate // 100)
    whole = len(samples) // frame * frame
    if not whole:
        return samples
    peaks = np.abs(samples[:whole].astype(np.int32)).reshape(-1, frame).max(axis=1)
    loud = np.flatnonzero(peaks > SILENCE)
    if not len(loud):
        return samples[:0]
    return samples[loud[0] * frame: min(len(samples), (loud[-1] + 2) * frame)]


# --------------------------------------------------------------------------
# espeak-ng — the only local synthesizer that knows Macedonian
# --------------------------------------------------------------------------
# Not installed on this machine and not installable without root, but it is
# already here: piper-tts statically links the whole of libespeak-ng into
# espeakbridge.so and exports its C symbols, and ships espeak-ng-data including
# the compiled mk_dict. So this is ctypes over a library that is already loaded
# in this process for phonemization — no package, no download, no apt.
#
# espeak-ng is not thread-safe and keeps one global voice and one global
# callback, which piper's phonemizer also uses. _ESPEAK_LOCK is what keeps the
# two off each other; every entry point re-asserts the voice it wants.
_ESPEAK_LOCK = threading.RLock()
_espeak_lib = None
_espeak_rate = 0

AUDIO_OUTPUT_RETRIEVAL = 1
ESPEAK_CHARS_UTF8 = 1
ESPEAK_RATE, ESPEAK_VOLUME, ESPEAK_PITCH, ESPEAK_RANGE = 1, 2, 3, 4


def _espeak():
    """Initialize the bundled libespeak-ng for audio retrieval. Returns (lib, rate)."""
    global _espeak_lib, _espeak_rate
    with _ESPEAK_LOCK:
        if _espeak_lib is not None:
            return _espeak_lib, _espeak_rate
        import ctypes
        import piper
        here = Path(piper.__file__).parent
        lib = ctypes.CDLL(str(here / "espeakbridge.so"))
        lib.espeak_Initialize.restype = ctypes.c_int
        lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        lib.espeak_Synth.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int,
                                     ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        rate = lib.espeak_Initialize(AUDIO_OUTPUT_RETRIEVAL, 0, str(here / "espeak-ng-data").encode(), 0)
        if rate <= 0:
            raise RuntimeError("espeak-ng refused to initialize for audio retrieval")
        _espeak_lib, _espeak_rate = lib, rate
        return lib, rate


class Espeak:
    """Formant synthesis. Correct Macedonian, and it sounds like 1995.

    Kept as the offline default for Macedonian because the alternative offline
    option pronounces a different language. Rate and pitch are moved off the
    defaults (175 wpm, shrill) towards something a person can listen to for a
    whole sentence; `+m3` is one of espeak's male formant variants, which is
    lower and less buzzy than the bare voice.
    """
    kind = "espeak"
    licence = "GPL-3.0 (espeak-ng, linked inside the piper-tts wheel)"

    def __init__(self, voice="mk+m3", *, words_per_minute=150, pitch=42):
        self.voice = voice
        self.words_per_minute = words_per_minute
        self.pitch = pitch
        self._rate = None

    @property
    def name(self):
        return "espeak-ng " + self.voice

    def warm(self):
        if self._rate is not None:
            return None
        started = time.monotonic()
        _, self._rate = _espeak()
        return (time.monotonic() - started) * 1000

    @property
    def sample_rate(self):
        if self._rate is None:
            self.warm()
        return self._rate

    def check(self):
        try:
            lib, _ = _espeak()
        except Exception as exc:                     # noqa: BLE001 - reported, never raised at a caller
            return {"ready": False, "detail": f"{type(exc).__name__}: {exc}"}
        with _ESPEAK_LOCK:
            known = lib.espeak_SetVoiceByName(self.voice.encode()) == 0
        return {"ready": known, "voice": self.voice, "licence": self.licence,
                "detail": "voice accepted by espeak-ng" if known else f"espeak-ng has no voice {self.voice!r}"}

    def stream(self, text):
        """One chunk. espeak synthesizes 2.5 s of speech in 9 ms — there is
        nothing to gain from splitting it, and a generator keeps the interface
        the same as Piper's, which genuinely does stream."""
        import ctypes
        lib, rate = _espeak()
        collected = []

        def on_audio(wav, count, _events):
            if wav and count > 0:
                collected.append(np.ctypeslib.as_array(wav, (count,)).copy())
            return 0

        callback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short),
                                    ctypes.c_int, ctypes.c_void_p)(on_audio)
        payload = text.encode()
        with _ESPEAK_LOCK:
            if lib.espeak_SetVoiceByName(self.voice.encode()) != 0:
                raise RuntimeError(f"espeak-ng has no voice {self.voice!r}")
            lib.espeak_SetParameter(ESPEAK_RATE, self.words_per_minute, 0)
            lib.espeak_SetParameter(ESPEAK_PITCH, self.pitch, 0)
            lib.espeak_SetSynthCallback(callback)
            code = lib.espeak_Synth(payload, len(payload) + 1, 0, 0, 0, ESPEAK_CHARS_UTF8, None, None)
            lib.espeak_Synchronize()
            lib.espeak_SetSynthCallback(None)
        if code != 0:
            raise RuntimeError(f"espeak_Synth returned {code}")
        if not collected:
            return
        audio = trim(np.concatenate(collected), rate)
        if len(audio):
            yield audio.tobytes(), len(audio) / rate


# --------------------------------------------------------------------------
# Piper — a recorded human voice, for the language that has one
# --------------------------------------------------------------------------
# espeak-ng's Macedonian front end does not switch languages for Latin words and
# has no idea what to do with them: "Firefox" became "фиреф-оикс" and "YouTube"
# was spelled out letter by letter. These are the names ARIES says while
# reporting what it just did, written the way a Macedonian speaker writes them.
# Anything not in this table is left alone rather than guessed at.
LATIN_IN_CYRILLIC = {
    "ARIES": "Ариес", "Firefox": "Фајерфокс", "YouTube": "Јутјуб", "Spotify": "Спотифај",
    "Google": "Гугл", "Gmail": "Гмаил", "GitHub": "Гитхаб", "VS Code": "Вижуал студио код",
    "VLC": "Ви Ел Си", "GIMP": "Гимп", "PyCharm": "Пајчарм", "Ubuntu": "Убунту",
    "GNOME": "Гном", "Linux": "Линукс", "Python": "Пајтон", "Telegram": "Телеграм",
    "Chrome": "Хром", "Slack": "Слек", "Discord": "Дискорд", "Netflix": "Нетфликс",
}
_LATIN_RE = re.compile("|".join(re.escape(k) for k in sorted(LATIN_IN_CYRILLIC, key=len, reverse=True)), re.I)
_CASEFOLDED = {k.casefold(): v for k, v in LATIN_IN_CYRILLIC.items()}

_piper_loaded = {}
_piper_lock = threading.Lock()


def cyrillize(text):
    """Rewrite the Latin names a Cyrillic front end would otherwise mangle."""
    return _LATIN_RE.sub(lambda m: _CASEFOLDED[m.group(0).casefold()], text)


class Piper:
    """A VITS voice model. Fast, natural, and only as right as its language.

    `phonemizer` is named separately from `voice` because for Macedonian they
    deliberately disagree: espeak-ng `mk` supplies Macedonian pronunciation and
    bg_BG-dimitar supplies a Slavic Cyrillic-language speaker. Every phoneme the
    `mk` front end emits exists in the Bulgarian voice's symbol table — Piper
    voices all carry the same 256-symbol generic espeak alphabet — so nothing is
    dropped. Present in the table is not the same as seen during training, which
    is why ќ /c/, written `k^` by espeak and never produced by Bulgarian, comes
    out closer to к. The result is Macedonian words in a Bulgarian accent.
    """
    kind = "piper"
    licence = "MIT (piper voice weights); piper-tts runtime is GPL-3.0"

    def __init__(self, voice, phonemizer, *, length_scale=1.0, cyrillic_names=False):
        self.voice = voice
        self.phonemizer = phonemizer
        self.length_scale = length_scale
        self.cyrillic_names = cyrillic_names
        self._voice = None

    @property
    def name(self):
        return f"piper {self.voice}" + (f" + espeak {self.phonemizer}"
                                        if not self.voice.startswith(self.phonemizer[:2]) else "")

    @property
    def model(self):
        return MODELS / self.voice / (self.voice + ".onnx")

    def check(self):
        config = self.model.with_suffix(".onnx.json")
        ready = self.model.is_file() and config.is_file()
        return {"ready": ready, "voice": self.voice, "phonemizer": self.phonemizer,
                "licence": self.licence, "path": str(self.model),
                "bytes": self.model.stat().st_size if ready else 0,
                "detail": "model and config on disk" if ready
                          else f"missing; run ./scripts/aries-fetch-voice {self.voice}"}

    def warm(self):
        """Load once and keep. Returns milliseconds, or None if already resident."""
        if self._voice is not None:
            return None
        with _piper_lock:
            if self.voice in _piper_loaded:
                self._voice = _piper_loaded[self.voice]
                return None
            from piper import PiperVoice
            if not self.model.is_file():
                raise FileNotFoundError(
                    f"{self.voice} is not in {MODELS}; run ./scripts/aries-fetch-voice {self.voice}")
            started = time.monotonic()
            # CPU on purpose. Whisper large-v3 holds ~3 GB of this machine's
            # VRAM and the local model server holds ~5 GB; a 63 MB VITS runs 30x
            # faster than real time on the i7 anyway, so the GPU buys nothing
            # and risks the thing that cannot be moved.
            loaded = PiperVoice.load(str(self.model), use_cuda=False)
            _piper_loaded[self.voice] = loaded
            self._voice = loaded
            return (time.monotonic() - started) * 1000

    @property
    def sample_rate(self):
        self.warm()
        return self._voice.config.sample_rate

    def stream(self, text):
        """Yield one sentence at a time.

        Sentence-at-a-time is the finest grain that exists, and it is a property
        of the model rather than of this code: VITS is not autoregressive, so a
        sentence is a single forward pass that produces all of its audio at
        once. What this does buy is sentence two being synthesized while
        sentence one is still being heard.
        """
        from piper.config import SynthesisConfig
        self.warm()
        voice = self._voice
        rate = voice.config.sample_rate
        config = SynthesisConfig(length_scale=self.length_scale)
        gap = np.zeros(rate * SENTENCE_GAP_MS // 1000, dtype=np.int16)
        if self.cyrillic_names:
            text = cyrillize(text)
        # Phonemize under the lock and infer outside it. espeak-ng is one global
        # object with one current voice; the ONNX session is neither.
        with _ESPEAK_LOCK:
            voice.config.espeak_voice = self.phonemizer
            sentences = [s for s in voice.phonemize(text) if s]
        first = True
        for phonemes in sentences:
            audio = voice.phoneme_ids_to_audio(voice.phonemes_to_ids(phonemes), config)
            if isinstance(audio, tuple):
                audio = audio[0]
            peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
            if peak < 1e-8:
                continue
            samples = trim((np.clip(audio / peak, -1.0, 1.0) * 32767).astype(np.int16), rate)
            if not len(samples):
                continue
            if not first:
                samples = np.concatenate((gap, samples))
            first = False
            yield samples.tobytes(), len(samples) / rate


# --------------------------------------------------------------------------
# RHVoice — a Macedonian voice recorded from Macedonians
# --------------------------------------------------------------------------
class RHVoice:
    """The offline Macedonian answer. See aries/speech/rhvoice.py for the whole
    story: two voices from UKIM Skopje and the North Macedonian government,
    shipped in Ubuntu, reached through ctypes, NonCommercial licence.

    Kiko by default rather than Suze because he is the faster of the two
    (measured RTF 0.026 against 0.069) and male, which keeps one voice for
    Macedonian whether the network is there or not.
    """
    kind = "rhvoice"
    licence = "engine LGPL-2.1; voices CC BY-NC-SA 4.0 (Kiko) / CC BY-NC-ND 4.0 (Suze) — NonCommercial"

    def __init__(self, voice="Kiko"):
        self.voice = voice
        self._rate = None

    @property
    def name(self):
        return "rhvoice " + self.voice

    def check(self):
        from aries.speech import rhvoice as binding
        found = binding.where()
        if not found:
            return {"ready": False, "voice": self.voice, "licence": self.licence,
                    "detail": "not installed: sudo apt install rhvoice-macedonian librhvoice5, "
                              "or ./scripts/aries-fetch-rhvoice for a copy needing no root"}
        libs, data, _ = found
        try:
            known = self.voice in binding.engine().voices
        except Exception as exc:                     # noqa: BLE001 - reported, never raised
            return {"ready": False, "voice": self.voice, "licence": self.licence,
                    "detail": f"{type(exc).__name__}: {exc}"}
        return {"ready": known, "voice": self.voice, "licence": self.licence, "path": str(data),
                "detail": f"loaded from {libs}" if known
                          else f"RHVoice has no voice {self.voice!r} here"}

    def warm(self):
        if self._rate is not None:
            return None
        from aries.speech import rhvoice as binding
        started = time.time()
        binding.engine()
        return (time.time() - started) * 1000

    @property
    def sample_rate(self):
        if self._rate is None:
            from aries.speech import rhvoice as binding
            # The rate is only known once something has been synthesized: RHVoice
            # reports it through a callback rather than a getter. One short word
            # is the cheapest honest way to ask, and it costs about 10 ms.
            _, self._rate = binding.engine().render("а", self.voice)
        return self._rate

    def stream(self, text):
        """One chunk. RHVoice hands back audio through ~50 callbacks during a
        synchronous call, so it could stream, but at RTF 0.026 the whole reply is
        ready in a tenth of the time it takes to say the first word of it."""
        from aries.speech import rhvoice as binding
        samples, rate = binding.engine().render(text, self.voice)
        self._rate = rate
        audio = trim(samples, rate)
        if len(audio):
            yield audio.tobytes(), len(audio) / rate


# --------------------------------------------------------------------------
# Microsoft Edge neural voices — the only natural, native Macedonian there is
# --------------------------------------------------------------------------
class Edge:
    """mk-MK-AleksandarNeural and mk-MK-MarijaNeural: real Macedonian speakers.

    ARIES's Macedonian voice, chosen by ear, and the one thing in this project
    that does not run on this machine. What ARIES is about to say goes to an
    endpoint Microsoft publishes no contract for, so the local voice stays
    installed and takes over whenever this one cannot answer.

    It is also the slowest to open its mouth — 0.4 to 1.6 s before the first
    byte of audio exists, against ~0.1 s for Piper and ~0.005 s for espeak-ng,
    because that time is a round trip rather than arithmetic. Streaming the MP3
    instead of waiting for the finished file is what keeps it under a second;
    the service starts sending roughly 0.3 s before it stops.

        ARIES_SPEECH_MK=piper     back to the local voice
    """
    kind = "edge"
    licence = "Microsoft service terms; no local model, no redistribution"
    sample_rate = None                     # MP3: the stream carries its own header

    def __init__(self, voice="mk-MK-AleksandarNeural"):
        self.voice = voice

    @property
    def name(self):
        return "edge " + self.voice

    def check(self):
        try:
            import edge_tts                # noqa: F401
        except ImportError:
            return {"ready": False, "voice": self.voice, "licence": self.licence,
                    "detail": "edge-tts is not installed: uv pip install --python .venv/bin/python edge-tts"}
        return {"ready": True, "voice": self.voice, "licence": self.licence,
                "detail": "installed; needs the network at the moment of speaking"}

    def warm(self):
        return None                        # nothing to load; the cost is per sentence

    def stream(self, text):
        """Yield MP3 as the service produces it, not after it has finished.

        Worth the awkwardness of an async generator drained from a thread: the
        service starts sending audio roughly a second before it stops, and
        waiting for the whole file doubled the silence the person sits through.
        pw-play decodes MP3 from a pipe, so nothing has to be decoded here.
        """
        import asyncio
        import edge_tts

        queue = queue_module.Queue(maxsize=64)
        sentinel = object()

        async def pump():
            try:
                async for chunk in edge_tts.Communicate(text, self.voice).stream():
                    if chunk["type"] == "audio" and chunk.get("data"):
                        queue.put(chunk["data"])
            except BaseException as exc:                 # noqa: BLE001 - handed to the caller below
                queue.put(exc)
            finally:
                queue.put(sentinel)

        worker = threading.Thread(target=lambda: asyncio.run(pump()),
                                  name="aries-speech-edge", daemon=True)
        worker.start()
        heard = False
        while True:
            item = queue.get()
            if item is sentinel:
                break
            if isinstance(item, BaseException):
                raise RuntimeError(f"the speech service failed: {type(item).__name__}: {item}")
            heard = True
            yield item, 0.0          # MP3: duration is the decoder's business
        if not heard:
            raise RuntimeError("the speech service returned no audio")


# --------------------------------------------------------------------------
# Which engine speaks which language
# --------------------------------------------------------------------------
def _build(kind, language):
    if kind == "espeak":
        return Espeak("mk+m3" if language == "mk" else "en-us+m3")
    if kind == "rhvoice":
        if language != "mk":
            raise ValueError("RHVoice is installed here for Macedonian only; English uses piper")
        return RHVoice("Kiko")
    if kind == "edge":
        return Edge("mk-MK-AleksandarNeural" if language == "mk" else "en-US-GuyNeural")
    if kind == "piper":
        # Macedonian is deliberately absent. Driving bg_BG-dimitar with the
        # Macedonian front end works and is documented in this file because the
        # finding is worth keeping, but the user's instruction was explicit:
        # "нејќам на бугарски" — rather no Macedonian voice than a Bulgarian
        # one. Piper serves English, where its voice is the right language.
        if language == "mk":
            raise ValueError("Piper has no Macedonian voice and its Bulgarian one is not wanted; "
                             "use edge (native Macedonian) or espeak (Macedonian, robotic)")
        # Chosen by ear on 2026-10-04, by the person who has to listen to it. Four
        # English voices were synthesized on the same sentence and played in order —
        # ryan-medium (the previous default), lessac-high, ryan-high and
        # libritts_r-medium — and the instruction was "последниов voice одбери го",
        # the last one played. LibriTTS-R is the restored release of LibriTTS, which
        # is why it sounds cleaner than the tier number suggests: 75 MB against
        # ryan-medium's 61 MB and lessac-high's 109 MB, on CPU, offline.
        return Piper("en_US-libritts_r-medium", "en-us")
    raise ValueError(f"unknown speech engine {kind!r}; choose edge, rhvoice, piper or espeak")


# Chosen by the person who has to listen to it, on 2026-09-29, in two rounds.
# First, of the three engines that existed at the time: "глас број 2 е добар" —
# the Microsoft one. Then RHVoice turned up, the search having been pushed harder
# on the user's insistence that a real Macedonian voice must exist somewhere, and
# after hearing Kiko and Suze: "гласот Kiko земи го". So Macedonian is Kiko:
# recorded from a Macedonian speaker, offline, 100 ms to a whole sentence, and
# nothing leaves the machine. Microsoft stays as the fallback for a machine where
# RHVoice is not installed, and as ARIES_SPEECH_MK=edge for anyone who wants the
# extra naturalness and does not mind the network.
DEFAULTS = {"mk": "rhvoice", "en": "piper"}
# Every engine that exists, and which languages each can honestly serve. Piper
# has no Macedonian voice and its Bulgarian one is refused; RHVoice was installed
# here for Macedonian only.
KINDS = {"edge": ("mk", "en"), "rhvoice": ("mk",), "espeak": ("mk", "en"), "piper": ("en",)}

# What speaks when the default cannot. Macedonian falls back to the Microsoft
# voice, which is the other real Macedonian: it needs the network, but it is only
# reached if the local RHVoice install has gone missing. A Bulgarian stand-in was
# built, measured and refused — "нејќам на бугарски" — and is not in this chain
# at any position.
FALLBACK = {"mk": "edge", "en": None}


def fallback(language):
    chosen = os.environ.get("ARIES_SPEECH_" + language.upper() + "_FALLBACK",
                            FALLBACK.get(language) or "").strip().casefold()
    return chosen or None
_engines = {}
_engine_lock = threading.Lock()


def chosen(language):
    """The engine name in force for a language, environment override included."""
    return os.environ.get("ARIES_SPEECH_" + language.upper(), DEFAULTS[language]).strip().casefold()


def engine(language, kind=None):
    kind = kind or chosen(language)
    with _engine_lock:
        if (language, kind) not in _engines:
            _engines[(language, kind)] = _build(kind, language)
        return _engines[(language, kind)]
