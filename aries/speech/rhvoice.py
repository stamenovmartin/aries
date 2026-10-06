"""RHVoice: the only Macedonian voice on this machine recorded from a Macedonian.

WHY THIS FILE EXISTS
--------------------
Every neural text-to-speech project skips Macedonian — Piper's 177 voices, Meta
MMS's 1143 languages, XTTS-v2, Kokoro, Coqui's zoo, sherpa-onnx: none of them
has it. RHVoice, a synthesizer written for blind users and packaged in Debian
and Ubuntu, does. Two voices, both recorded from Macedonian speakers:

  Kiko   male,   © 2021 Government of North Macedonia, built by LouderPages.
                 CC BY-NC-SA 4.0.
  Suze   female, recorded 2022 from Suzana Todorovska at the FEEIT speech studio,
                 UKIM Skopje, with the Institute of Macedonian Language and
                 funding from UNICEF. CC BY-NC-ND 4.0.

Both licences are NonCommercial, which is why Debian files the package under
non-free. Fine for one person's own assistant; a blocker for anything sold, and
NoDerivatives means Suze cannot legally be fine-tuned.

It is HTS statistical-parametric synthesis, not neural — clearly a synthesizer,
but a Macedonian one, unlike Piper's Bulgarian voice, and far more natural than
espeak-ng's formants. It is also the fastest thing here: the engine initializes
in about 1 ms and Kiko synthesizes 4.7 s of speech in 120 ms, entirely offline.

HOW IT IS REACHED
-----------------
ctypes over the system `libRHVoice.so.5`, the same approach aries/workspace/
media.py takes to wpctl: use what the distribution already ships. Dependencies
are dlopen'd explicitly with RTLD_GLOBAL rather than through LD_LIBRARY_PATH,
because the loader reads that variable once before the process starts and
ARIES's voice daemon has its own reasons for what is in it.

If the packages are absent, a copy extracted into var/models/rhvoice by
./scripts/aries-fetch-rhvoice is used instead — same files, no root needed.
"""
import ctypes
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
# System install first, then the rootless copy. Each entry is (libraries, data, config).
LOCATIONS = (
    (Path("/usr/lib/x86_64-linux-gnu"), Path("/usr/share/RHVoice"), Path("/etc/RHVoice")),
    (ROOT / "var/models/rhvoice/usr/lib/x86_64-linux-gnu",
     ROOT / "var/models/rhvoice/usr/share/RHVoice",
     ROOT / "var/models/rhvoice/etc/RHVoice"),
)
# libRHVoice_audio is only needed for RHVoice's own playback, which ARIES does
# not use — it takes the samples and sends them to PipeWire itself. Absent on a
# minimal install, so it is optional here rather than required.
DEPENDENCIES = ("libRHVoice_core.so.10", "libRHVoice_audio.so.2", "libportaudio.so.2")

_SET_RATE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
_PLAY = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_uint, ctypes.c_void_p)
_TEXT_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
_SPAN_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p)
_DONE = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class _Callbacks(ctypes.Structure):
    _fields_ = [("set_sample_rate", _SET_RATE), ("play_speech", _PLAY), ("process_mark", _TEXT_CB),
                ("word_starts", _SPAN_CB), ("word_ends", _SPAN_CB), ("sentence_starts", _SPAN_CB),
                ("sentence_ends", _SPAN_CB), ("play_audio", _TEXT_CB), ("done", _DONE)]


class _InitParams(ctypes.Structure):
    _fields_ = [("data_path", ctypes.c_char_p), ("config_path", ctypes.c_char_p),
                ("resource_paths", ctypes.POINTER(ctypes.c_char_p)),
                ("callbacks", _Callbacks), ("options", ctypes.c_uint)]


class _SynthParams(ctypes.Structure):
    _fields_ = [("voice_profile", ctypes.c_char_p),
                ("absolute_rate", ctypes.c_double), ("absolute_pitch", ctypes.c_double),
                ("absolute_volume", ctypes.c_double), ("relative_rate", ctypes.c_double),
                ("relative_pitch", ctypes.c_double), ("relative_volume", ctypes.c_double),
                ("punctuation_mode", ctypes.c_int), ("punctuation_list", ctypes.c_char_p),
                ("capitals_mode", ctypes.c_int), ("flags", ctypes.c_int)]


class _VoiceInfo(ctypes.Structure):
    _fields_ = [("language", ctypes.c_char_p), ("name", ctypes.c_char_p),
                ("gender", ctypes.c_int), ("country", ctypes.c_char_p)]


def where():
    """The first location that has both the library and at least one voice."""
    for libs, data, config in LOCATIONS:
        if (libs / "libRHVoice.so.5").is_file() and (data / "voices").is_dir() \
                and any((data / "voices").iterdir()):
            return libs, data, config
    return None


_engine = None
_lock = threading.RLock()   # re-entrant: engine() holds it while building, render() re-takes it


class _Engine:
    """One process-wide RHVoice engine. Holds its own callback objects.

    Those references are load-bearing, not tidiness: ctypes callbacks are
    garbage collected like anything else, and a collected one leaves the C side
    calling freed memory. The crash is a segfault with no Python traceback.
    """

    def __init__(self):
        found = where()
        if not found:
            raise FileNotFoundError(
                "RHVoice is not installed. Either `sudo apt install rhvoice-macedonian librhvoice5` "
                "or, without root, ./scripts/aries-fetch-rhvoice")
        libs, data, config = found
        for name in DEPENDENCIES:
            if (libs / name).is_file():
                ctypes.CDLL(str(libs / name), mode=ctypes.RTLD_GLOBAL)
        lib = ctypes.CDLL(str(libs / "libRHVoice.so.5"))
        lib.RHVoice_new_tts_engine.restype = ctypes.c_void_p
        lib.RHVoice_new_tts_engine.argtypes = [ctypes.POINTER(_InitParams)]
        lib.RHVoice_get_number_of_voices.restype = ctypes.c_uint
        lib.RHVoice_get_number_of_voices.argtypes = [ctypes.c_void_p]
        lib.RHVoice_get_voices.restype = ctypes.POINTER(_VoiceInfo)
        lib.RHVoice_get_voices.argtypes = [ctypes.c_void_p]
        lib.RHVoice_new_message.restype = ctypes.c_void_p
        lib.RHVoice_new_message.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint,
                                            ctypes.c_int, ctypes.POINTER(_SynthParams), ctypes.c_void_p]
        lib.RHVoice_speak.argtypes = [ctypes.c_void_p]
        lib.RHVoice_delete_message.argtypes = [ctypes.c_void_p]

        self.lib = lib
        self.sample_rate = 0
        self._collected = []
        self._keep = (_SET_RATE(self._on_rate), _PLAY(self._on_audio),
                      _TEXT_CB(), _SPAN_CB(), _SPAN_CB(), _SPAN_CB(), _SPAN_CB(), _TEXT_CB(), _DONE())
        params = _InitParams(str(data).encode(), str(config).encode(), None,
                             _Callbacks(*self._keep), 0)
        self.handle = lib.RHVoice_new_tts_engine(ctypes.byref(params))
        if not self.handle:
            raise RuntimeError(f"RHVoice refused to start with data in {data}")
        self.data = data
        self.voices = {}
        for i in range(lib.RHVoice_get_number_of_voices(self.handle)):
            info = lib.RHVoice_get_voices(self.handle)[i]
            self.voices[info.name.decode()] = {
                "language": info.language.decode(),
                "gender": ("unknown", "male", "female")[info.gender]}

    def _on_rate(self, rate, _user_data):
        self.sample_rate = rate
        return 1

    def _on_audio(self, samples, count, _user_data):
        if samples and count:
            self._collected.append(np.ctypeslib.as_array(samples, (count,)).copy())
        return 1

    def render(self, text, voice, *, rate=0.0, pitch=0.0):
        """Synthesize to int16 samples. Returns (samples, sample rate).

        Serialized: one engine, one collection buffer, and RHVoice makes no
        thread-safety promise worth relying on. Nothing here needs concurrency —
        ARIES says one thing at a time on purpose.
        """
        payload = text.encode()
        params = _SynthParams(voice.encode(), rate, pitch, 0.0, 1.0, 1.0, 1.0, 0, None, 0, 0)
        with _lock:
            self._collected = []
            message = self.lib.RHVoice_new_message(self.handle, payload, len(payload), 0,
                                                   ctypes.byref(params), None)
            if not message:
                raise RuntimeError(f"RHVoice could not build a message for voice {voice!r}")
            try:
                self.lib.RHVoice_speak(message)
            finally:
                self.lib.RHVoice_delete_message(message)
            produced, self._collected = self._collected, []
        if not produced:
            return np.zeros(0, dtype=np.int16), self.sample_rate
        return np.concatenate(produced), self.sample_rate


def engine():
    global _engine
    with _lock:
        if _engine is None:
            _engine = _Engine()
        return _engine
