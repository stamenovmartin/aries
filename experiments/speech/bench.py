"""What each voice costs, and whether a person can understand it.

Two numbers decide whether a spoken assistant works, and they pull against each
other. Time to first sound is what makes it feel alive. Intelligibility is
whether the answer arrived at all. This measures both for every engine ARIES
can use, so the choice between them is made on evidence rather than on which
one was implemented first.

    .venv/bin/python experiments/speech/bench.py              latency and memory
    .venv/bin/python experiments/speech/bench.py --transcribe adds the round trip

THE ROUND TRIP, AND WHAT IT IS NOT
----------------------------------
--transcribe synthesizes each sentence, feeds the samples back to the same
Whisper large-v3 that ARIES listens with, and compares the transcript to the
text that went in. It is a proxy for a listener, not a listener: Whisper's
Macedonian is itself imperfect, and a voice can be intelligible to a machine
and unpleasant to a person — which is exactly what happened here, where the
engine with the best round trip was rejected by ear for sounding robotic. Read
it as "were the words recoverable", never as "was it good".

It also overstates the damage in a way that hits every engine equally: Whisper
writes "триесет проценти" as "30%", and comparing word for word scores that as
two errors. The ranking is the measurement; the absolute number is not.

No sound is played. Everything is measured on the samples.
"""
import argparse
import json
import re
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

# Replies ARIES actually produces, not tongue twisters. The last two carry the
# letters Bulgarian does not have (ѓ ќ ѕ љ њ џ ј), which is where a voice
# borrowed from another language is most likely to fall over.
MACEDONIAN = [
    "Готово.",
    "Го отворив Firefox.",
    "Го намалив звукот на триесет проценти.",
    "Најдов дванаесет вести за вештачка интелигенција.",
    "Не разбрав, повтори го тоа.",
    "Ѓорѓи ќе ѕвони, а Љупчо и Њам чекаат во џипот.",
    "Ја пуштив песната на Јутјуб и ја зголемив јачината.",
]
ENGLISH = [
    "Done.",
    "Opening Firefox.",
    "Volume is now thirty percent.",
    "I found twelve stories about artificial intelligence.",
]


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def measure(engine, sentences):
    """Synthesis only: no player, so nothing here is waiting on a speaker."""
    before = rss_mb()
    load_ms = engine.warm()
    after_load = rss_mb()
    rows = []
    for text in sentences:
        started = time.monotonic()
        first_ms, total, chunks = None, [], 0
        for payload, seconds in engine.stream(text):
            if first_ms is None:
                first_ms = (time.monotonic() - started) * 1000
            chunks += 1
            total.append((payload, seconds))
        elapsed = (time.monotonic() - started) * 1000
        audio = sum(s for _, s in total)
        rows.append({"text": text, "chunks": chunks, "first_chunk_ms": round(first_ms or 0, 1),
                     "synthesis_ms": round(elapsed, 1), "audio_s": round(audio, 2),
                     "realtime_factor": round(elapsed / 1000 / audio, 4) if audio else None,
                     "samples": b"".join(p for p, _ in total)})
    return {"engine": engine.name, "kind": engine.kind, "licence": engine.licence,
            "load_ms": round(load_ms, 1) if load_ms else 0.0,
            "rss_before_mb": round(before, 1), "rss_after_load_mb": round(after_load, 1),
            "rss_cost_mb": round(after_load - before, 1), "rows": rows}


_WORD = re.compile(r"\w+", re.UNICODE)


def wer(reference, hypothesis):
    """Word error rate by edit distance. Case and punctuation are not speech."""
    a = [w.casefold() for w in _WORD.findall(reference)]
    b = [w.casefold() for w in _WORD.findall(hypothesis)]
    if not a:
        return None
    previous = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        current = [i]
        for j, wb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (wa != wb)))
        previous = current
    return previous[-1] / len(a)


def decode_mp3(payload):
    """MP3 bytes to mono float samples and their rate, through PyAV's ffmpeg.

    Only needed for the network voice, which is the one that matters most, so
    "we could not decode it" was not an acceptable gap in the comparison.
    """
    import io
    import av
    with av.open(io.BytesIO(payload)) as container:
        stream = container.streams.audio[0]
        rate = stream.rate
        frames = [f.to_ndarray().reshape(f.to_ndarray().shape[0], -1).mean(axis=0)
                  for f in container.decode(stream)]
    return np.concatenate(frames).astype(np.float32), rate


def transcribe_all(reports, language, model_dir):
    """Feed every synthesized clip back to the ear ARIES already listens with."""
    from faster_whisper import WhisperModel
    # CPU int8: aries-voice.service is normally holding large-v3 on the GPU, and
    # a benchmark has no business competing with the live microphone for VRAM.
    model = WhisperModel(str(model_dir), device="cpu", compute_type="int8")
    for report in reports:
        errors = []
        for row in report["rows"]:
            payload = row.pop("samples")
            if report["kind"] == "edge":
                samples, report["sample_rate"] = decode_mp3(payload)
            else:
                samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768
            if report["sample_rate"] != 16000:
                # Whisper wants 16 kHz. Linear resampling is enough to ask
                # "were the words there"; it is not enough to judge a voice.
                target = int(len(samples) * 16000 / report["sample_rate"])
                samples = np.interp(np.linspace(0, len(samples) - 1, target),
                                    np.arange(len(samples)), samples).astype(np.float32)
            segments, _ = model.transcribe(samples, language=language, beam_size=5)
            heard = " ".join(s.text for s in segments).strip()
            row["heard"] = heard
            row["wer"] = round(wer(row["text"], heard), 3)
            errors.append(row["wer"])
        report["mean_wer"] = round(sum(errors) / len(errors), 3) if errors else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcribe", action="store_true", help="round-trip through Whisper")
    parser.add_argument("--engines", default="rhvoice,espeak,edge", help="which engines to measure")
    parser.add_argument("--language", default="mk", choices=("mk", "en"))
    parser.add_argument("--model", default="var/models/faster-whisper-large-v3")
    parser.add_argument("--out", default="experiments/speech/results-mk-latency.json")
    args = parser.parse_args()

    from aries.speech import engines
    sentences = MACEDONIAN if args.language == "mk" else ENGLISH
    reports = []
    for kind in args.engines.split(","):
        engine = engines.engine(args.language, kind)
        try:
            # measure() before check(): espeak-ng initializes itself on first
            # contact, and asking it whether it is ready is first contact, which
            # would charge its load time to the health check instead of here.
            report = measure(engine, sentences)
        except Exception as exc:                     # noqa: BLE001 - a missing voice is a result
            print(f"{kind}: skipped — {type(exc).__name__}: {exc}")
            continue
        report["sample_rate"] = engine.sample_rate or 24000    # edge returns 24 kHz MP3
        reports.append(report)
        rows = report["rows"]
        print(f"{report['engine']:38s} load {report['load_ms']:7.1f} ms  "
              f"+{report['rss_cost_mb']:6.1f} MB  first sound "
              f"{np.median([r['first_chunk_ms'] for r in rows]):7.1f} ms (median)  "
              + (f"RTF {np.median(known):.4f}" if (known := [r['realtime_factor'] for r in rows if r['realtime_factor']])
                 else "RTF n/a — the decoder knows the duration, this does not"))

    if args.transcribe:
        transcribe_all(reports, args.language, Path(args.model))
        for report in reports:
            print(f"{report['engine']:38s} mean WER {report.get('mean_wer')}")
    else:
        for report in reports:
            for row in report["rows"]:
                row.pop("samples", None)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(reports, indent=1, ensure_ascii=False))
    print("wrote " + args.out)


if __name__ == "__main__":
    main()
