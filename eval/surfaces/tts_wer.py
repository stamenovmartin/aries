#!/usr/bin/env python3
"""Does ARIES's English voice still produce words a listener can recover?

    ./eval/surfaces/tts_wer.py                      measure, print, write a result
    ./eval/surfaces/tts_wer.py --save-baseline      and make it the baseline
    ./eval/surfaces/tts_wer.py --device cuda        if there is VRAM to spare

WHAT THIS MEASURES, AND WHAT IT CANNOT
--------------------------------------
Twenty fixed English sentences (eval/surfaces/tts_sentences.json) are synthesized
by Piper `en_US-ryan-medium` INTO WAV FILES, each file is transcribed back by the
same faster-whisper large-v3 that ARIES listens with, and the transcript is
compared word for word with the sentence that went in. The number is a word error
rate, and it answers exactly one question: WERE THE WORDS RECOVERABLE. It does not
say the voice is pleasant — the opposite case is already in this project's history,
where the engine with the best round trip was rejected by ear for sounding robotic.

Nothing is recorded and nothing is played. THIS MACHINE HAS NO MICROPHONE: every
analog jack reads `available: no`, so a measurement that went through air would be
a measurement of nothing. The files are the evidence; they are kept.

WHY WHISPER IS A FAIR JUDGE AND A BIASED ONE
--------------------------------------------
Fair, because it is the ear ARIES actually has: a reply this transcriber cannot
recover is a reply the voice loop cannot act on. Biased, because it normalises
as it writes — "thirty percent" comes back as "30%", which a word-for-word
comparison scores as two errors that no human listener would have made. So the
comparison normalises both sides first, and `normalise()` below is the whole of
it, written out rather than hidden in a library: digits nought to a hundred become
words, '%' becomes 'percent', '&' becomes 'and', punctuation and case are dropped.
Everything it does NOT fix stays in the number, which is why the baseline is a
baseline and not a target.

WHY cpu/int8 BY DEFAULT
-----------------------
LD_LIBRARY_PATH is exported below exactly as scripts/aries-voice does it, and for
the same reason: CTranslate2 links CUDA 12 while this machine's driver is CUDA 13,
so the runtime libraries come from the pip wheels in .venv, and the loader reads
that variable once BEFORE the process starts. Setting it from inside Python is too
late ("libcublas.so.12 is not found"), so this script re-execs itself once.
The default device is still `cpu`/`int8`, measured reason: of the RTX 3060's
12288 MiB, 2882 MiB were free while aries-voice.service held large-v3 (3720 MiB)
and ollama held a model (5028 MiB). A second large-v3 in float16 does not fit
beside them, and evicting the live microphone to measure a voice is the wrong
trade. `--device cuda` is there for a machine with the room.

THE SAME SENTENCE DOES NOT PRODUCE THE SAME AUDIO TWICE
-------------------------------------------------------
Piper is a VITS model and VITS has a STOCHASTIC duration predictor: the same text
synthesized twice is not the same waveform, so this measurement has real run to
run variance and it is not the recogniser's. Measured here across two runs of the
same twenty sentences: every long sentence was transcribed identically, and the
one-word reply "Done." came back as `die` in the first run and `DONE` in the
second — a swing of 1.00 on one sentence, which is 0.05 of the mean over twenty.
That is the whole of the tolerance, from one 0.33 s clip.

Two consequences, both of which the gate has to live with rather than hide:
the mean over sentences is sensitive to the shortest one, so `corpus_wer` (edits
over all reference words, where "Done." is 1 word of 194 instead of 1 sentence of
20) is reported beside it and is the steadier number; and a single failing run is
weak evidence on its own. Forcing determinism was considered and rejected —
`SynthesisConfig(noise_scale=0)` would measure a voice ARIES does not ship.

A BASELINE IS ONLY A BASELINE AGAINST THE SAME RULER
----------------------------------------------------
Device, compute type, model, voice, beam size and the digest of the twenty
sentences all go into the result, and tests/test_tts_regression.py refuses to
compare two runs whose rulers differ instead of reporting a change that is really
a change of method.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SENTENCES = HERE / "tts_sentences.json"
BASELINE = HERE / "tts_baseline.json"

# ---------------------------------------------------------------------------
# The loader path, before anything heavy is imported. scripts/aries-voice does
# exactly this; a CUDA load that happens after Python has started fails.
# ---------------------------------------------------------------------------
_SITE = ROOT / ".venv/lib/python3.12/site-packages/nvidia"
_WANT = f"{_SITE}/cublas/lib:{_SITE}/cudnn/lib"


def _reexec_with_cuda_libraries() -> None:
    if os.environ.get("ARIES_TTS_WER_REEXEC") == "1":
        return
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    env = dict(os.environ,
               ARIES_TTS_WER_REEXEC="1",
               LD_LIBRARY_PATH=_WANT + (":" + existing if existing else ""),
               PYTHONPATH=os.pathsep.join(
                   [str(ROOT / "vendor/agentic-core"), str(ROOT / "vendor"), str(ROOT)]
                   + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])))
    os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve())] + sys.argv[1:], env)


if __name__ == "__main__" and "--no-reexec" not in sys.argv:
    _reexec_with_cuda_libraries()

sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Normalisation: everything Whisper's own spelling conventions would otherwise
# charge to the voice. Written out, bounded, and applied to BOTH sides.
# ---------------------------------------------------------------------------
_UNITS = ["nought", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
          "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
          "seventeen", "eighteen", "nineteen"]
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty",
         70: "seventy", 80: "eighty", 90: "ninety"}
_WORD = re.compile(r"[\w%]+", re.UNICODE)


def _spell(number: int) -> list[str]:
    """0 to 999 999 in words, in the spelling ARIES itself uses ("four hundred and
    twelve", "sixty one thousand"). Past a million the digits are left alone and
    counted as errors, which is honest: nobody has agreed how to say 41237891
    either, and no ARIES reply contains one.
    """
    if number < 20:
        return [_UNITS[number]]
    if number < 100:
        tens, rest = divmod(number, 10)
        return [_TENS[tens * 10]] + ([_UNITS[rest]] if rest else [])
    if number < 1000:
        hundreds, rest = divmod(number, 100)
        out = [_UNITS[hundreds], "hundred"]
        return out + (["and"] + _spell(rest) if rest else [])
    if number < 1_000_000:
        thousands, rest = divmod(number, 1000)
        return _spell(thousands) + ["thousand"] + (_spell(rest) if rest else [])
    return [str(number)]


def normalise(text: str) -> list[str]:
    """One comparable word list. Case, punctuation and spelling conventions are
    not speech; a missing or wrong WORD is."""
    lowered = (text or "").casefold()
    lowered = lowered.replace("%", " percent ").replace("&", " and ")
    lowered = re.sub(r"(\d),(\d)", r"\1\2", lowered)          # 61,000 -> 61000
    words: list[str] = []
    for token in _WORD.findall(lowered):
        if token.isdigit():
            words.extend(_spell(int(token)))
        else:
            words.append(token)
    # "forty-one" and "forty one" are the same utterance; so are "ninety six
    # percent" and "96%" once the digits are spelled. Nothing else is folded.
    return words


def wer(reference: str, heard: str) -> tuple[float, int, int]:
    """Word error rate by Levenshtein distance over normalised words."""
    a, b = normalise(reference), normalise(heard)
    if not a:
        raise ValueError("a reference sentence with no words cannot be scored")
    previous = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        current = [i]
        for j, wb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (wa != wb)))
        previous = current
    return previous[-1] / len(a), previous[-1], len(a)


# ---------------------------------------------------------------------------
# Synthesis to files, then transcription of those files
# ---------------------------------------------------------------------------
def sentences() -> tuple[list[str], str]:
    data = json.loads(SENTENCES.read_text())
    rows = data["sentences"]
    if len(rows) != 20 or not all(isinstance(s, str) and s.strip() for s in rows):
        raise ValueError(f"{SENTENCES} must hold exactly 20 non-empty sentences, found {len(rows)}")
    digest = hashlib.sha256("\n".join(rows).encode()).hexdigest()
    return rows, digest


def _record(path: Path) -> str:
    """Repo-relative when it is in the repo, absolute otherwise. The audio dir is a
    caller's choice and may well be a temporary directory outside the tree."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _resolve(recorded: str) -> Path:
    path = Path(recorded)
    return path if path.is_absolute() else ROOT / path


def synthesize(rows: list[str], voice: str, audio_dir: Path) -> list[dict]:
    """Each sentence to its own WAV on disk. The file IS the measurement subject."""
    from aries.speech import engines
    engine = engines.Piper(voice, "en-us")
    health = engine.check()
    if not health.get("ready"):
        raise RuntimeError(f"{voice} is not usable here: {health.get('detail')}")
    load_ms = engine.warm() or 0.0
    rate = engine.sample_rate
    audio_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for index, text in enumerate(rows):
        started = time.monotonic()
        chunks = [payload for payload, _ in engine.stream(text)]
        synthesis_ms = (time.monotonic() - started) * 1000
        samples = b"".join(chunks)
        path = audio_dir / ("%02d.wav" % index)
        with wave.open(str(path), "wb") as sink:
            sink.setnchannels(1)
            sink.setsampwidth(2)
            sink.setframerate(rate)
            sink.writeframes(samples)
        out.append({"index": index, "text": text, "wav": _record(path),
                    "bytes": len(samples), "audio_seconds": round(len(samples) / 2 / rate, 3),
                    "synthesis_ms": round(synthesis_ms, 1)})
    return [{"engine": engine.name, "licence": engine.licence, "sample_rate": rate,
             "load_ms": round(load_ms, 1)}, out]


def transcribe(rows: list[dict], model_dir: Path, device: str, compute: str, beam: int) -> dict:
    from faster_whisper import WhisperModel
    started = time.monotonic()
    model = WhisperModel(str(model_dir), device=device, compute_type=compute)
    load_ms = (time.monotonic() - started) * 1000
    for row in rows:
        started = time.monotonic()
        # The PATH, not samples in memory: the sub-item is a file round trip, and
        # a decoder reading the written file is one more thing that has to work.
        segments, info = model.transcribe(str(_resolve(row["wav"])), language="en", beam_size=beam)
        heard = " ".join(s.text for s in segments).strip()
        row["heard"] = heard
        rate, edits, words = wer(row["text"], heard)
        row.update(wer=round(rate, 4), edits=edits, reference_words=words,
                   transcribe_ms=round((time.monotonic() - started) * 1000, 1),
                   language_probability=round(float(getattr(info, "language_probability", 0.0)), 3))
    return {"load_ms": round(load_ms, 1)}


def measure(args) -> dict:
    rows, digest = sentences()
    audio_dir = Path(args.audio_dir)
    if not audio_dir.is_absolute():
        audio_dir = ROOT / audio_dir
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    header, measured = synthesize(rows, args.voice, audio_dir / stamp)
    ear = transcribe(measured, ROOT / args.model, args.device, args.compute, args.beam)
    rates = [row["wer"] for row in measured]
    edits = sum(row["edits"] for row in measured)
    words = sum(row["reference_words"] for row in measured)
    from aries import flags
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        # The ruler. Two results are only comparable when all of this matches.
        "ruler": {"voice": args.voice, "engine": header["engine"], "sample_rate": header["sample_rate"],
                  "whisper_model": args.model, "device": args.device, "compute_type": args.compute,
                  "beam_size": args.beam, "language": "en", "sentences": len(rows),
                  "sentences_sha256": digest, "normaliser": "eval/surfaces/tts_wer.normalise v1"},
        "mean_wer": round(sum(rates) / len(rates), 4),
        "corpus_wer": round(edits / words, 4),
        "worst_wer": round(max(rates), 4),
        "perfect_sentences": sum(1 for r in rates if r == 0.0),
        "total_edits": edits, "total_reference_words": words,
        "piper_load_ms": header["load_ms"], "whisper_load_ms": ear["load_ms"],
        "audio_seconds": round(sum(row["audio_seconds"] for row in measured), 2),
        "licence": header["licence"],
        "flags": flags.describe(),
        "rows": measured,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="TTS regression: 20 English sentences, WER through Whisper")
    parser.add_argument("--voice", default="en_US-ryan-medium")
    parser.add_argument("--model", default="var/models/faster-whisper-large-v3")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--compute", default="int8")
    parser.add_argument("--beam", type=int, default=5)
    parser.add_argument("--audio-dir", default="var/measurements/tts-regression")
    parser.add_argument("--out", default="")
    parser.add_argument("--save-baseline", action="store_true",
                        help="write the result to eval/surfaces/tts_baseline.json as well")
    parser.add_argument("--no-reexec", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    result = measure(args)
    for row in result["rows"]:
        flag = "    " if row["wer"] == 0 else " !! "
        print("%s%4.2f  %-58s -> %s" % (flag, row["wer"], row["text"][:58], row["heard"][:70]))
    print("\nmean WER %.4f over %d sentences (corpus WER %.4f, %d/%d perfect, worst %.4f)"
          % (result["mean_wer"], len(result["rows"]), result["corpus_wer"],
             result["perfect_sentences"], len(result["rows"]), result["worst_wer"]))
    print("ruler: " + json.dumps(result["ruler"]))

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print("wrote " + str(path))
    if args.save_baseline:
        BASELINE.write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print("baseline written to " + str(BASELINE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
