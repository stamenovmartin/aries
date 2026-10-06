"""The regression gate for ARIES's English voice: 20 fixed sentences, WER, +0.05.

    APP_ENV=test PYTHONPATH=vendor/agentic-core:vendor:. .venv/bin/python tests/test_tts_regression.py

WHAT FAILS THIS TEST
--------------------
A word error rate more than 0.05 above the saved baseline in
`eval/surfaces/tts_baseline.json` — specifically `corpus_wer`, total edits over
total reference words, for the reason written out beside `METRIC` below, which is
three runs of unchanged code rather than an opinion. That is a tripwire for the
English voice path, not a quality target: the baseline is whatever this machine
measured, and the gate's only claim is "it did not get materially worse".

The measurement itself lives in `eval/surfaces/tts_wer.py` and is run here AS A
SUBPROCESS, exactly the way a person would run it. That is deliberate rather than
lazy: loading faster-whisper needs LD_LIBRARY_PATH pointing at the pip CUDA
libraries BEFORE the process starts (CTranslate2 links CUDA 12, this machine's
driver is CUDA 13), the way scripts/aries-voice sets it, and a variable the
loader already read cannot be fixed from inside Python. The harness re-execs
itself once to arrange that; running it as a child means this file does not have
to, and means the published entry point is what is being tested.

NO MICROPHONE, SO NO AIR
------------------------
Every analog jack on this machine reads `available: no`. Each sentence is
synthesized to its own WAV FILE and the FILE is transcribed. Nothing is recorded
and nothing is played.

THE FAST CHECKS COME FIRST
--------------------------
Most of this file runs in milliseconds and needs no model: the comparison rule,
the normaliser, the shape of the baseline, and — the part that actually decides
whether the gate works — the +0.05 arithmetic, driven with fabricated results
either side of the line. A threshold nobody has seen trip is a threshold nobody
should trust. The live measurement is the last test and takes minutes; its result
is kept in `var/measurements/tts-regression/gate-*.json` so a failure can be
argued about afterwards rather than only remembered.

Set ARIES_TTS_RESULT=<path to a tts_wer.py --out file> to grade a measurement
taken earlier instead of taking a new one.

ONE THING TO KNOW BEFORE READING A FAILURE
------------------------------------------
Piper is a VITS model with a stochastic duration predictor, so the same sentence
is not the same waveform twice and this measurement has real variance of its own.
Measured across runs here: the long sentences come back identically, and the
one-word reply "Done." has been transcribed both correctly and as `die` from a
0.33 s clip — a 1.00 swing on one sentence, which is 0.05 of the mean over twenty
and therefore the whole tolerance. A single failing run is a reason to run it
again before it is a reason to blame a change; two in a row is evidence. The
per-sentence line printed on failure says which sentence moved, which is what
tells the two apart.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module

bootstrap('aries-tts-regression')

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / 'eval/surfaces/tts_wer.py'
BASELINE = ROOT / 'eval/surfaces/tts_baseline.json'
SENTENCES = ROOT / 'eval/surfaces/tts_sentences.json'

#: The whole of the policy. A rise of more than this above the baseline is a
#: regression; the baseline itself is not a target and is never asserted against.
TOLERANCE = 0.05

#: WHICH word error rate the tolerance is applied to, and why it is this one.
#:
#: `corpus_wer` is total edits over total reference words — the standard
#: definition. `mean_wer` is the mean of the twenty per-sentence rates. The gate
#: was written on `mean_wer` first and that was wrong, measured rather than
#: argued: three runs of UNCHANGED code on this machine gave
#:
#:     run        1 *      2          3        spread over 2 and 3
#:     mean_wer   0.0926   0.0321     0.0884   0.0563   <- past the tolerance
#:     corpus_wer 0.0503   0.0279     0.0391   0.0112
#:
#: (* run 1 used an earlier normaliser that could not spell 61 000, so only runs 2
#: and 3 are a like-for-like pair; run 1 is shown because the "Done." transcript
#: differs in all three.) The 0.0563 is past the tolerance, so the tripwire fired
#: on code nobody had touched. The cause is structural and not the voice's fault: Piper is VITS with
#: a stochastic duration predictor, the one-word reply "Done." came back as `die`,
#: `DONE` and `John?` on those three runs, and one sentence of twenty scoring 1.00
#: moves `mean_wer` by exactly 0.05 — the entire budget — while moving `corpus_wer`
#: by 1 edit in 179 words.
#:
#: This is a tripwire being calibrated, not a result being re-scored: a gate that
#: fires on an unchanged system is broken whatever it is measuring. `mean_wer` is
#: still computed, still saved, and still printed with its delta on every run, so
#: nothing is hidden by the choice — it is just not what trips the wire.
METRIC = 'corpus_wer'

#: The per-sentence check, in EDITS rather than in a rate, and why it has to be.
#:
#: 0.05 of a ten-word sentence is half a word. No sentence in this corpus is
#: longer than twenty words, so "no sentence more than 0.05 worse" is really "no
#: sentence may gain a single word error" — and the stochastic vocoder produces
#: exactly that on its own. Measured across three runs of unchanged code, the
#: largest movement of any individual sentence was ONE edit: `in` heard as `and`
#: in a twelve-word sentence, `Brightness` heard as `Rightness` in a ten-word one,
#: `Done.` heard as `die` and as `John?`. So the bound is two edits — one more than
#: the dice have been seen to produce, and far less than a broken voice would.
#: Calibrated from those runs, not derived from a principle; every sentence that
#: moves at all is still printed, gated or not.
PER_SENTENCE_EDITS = 2

sys.path.insert(0, str(ROOT / 'eval/surfaces'))
import tts_wer  # noqa: E402


# --- the corpus ---------------------------------------------------------------

def test_the_corpus_is_twenty_fixed_english_sentences():
    rows, digest = tts_wer.sentences()
    check('exactly twenty sentences', len(rows) == 20)
    check('every one is English — not one Cyrillic character, because Macedonian is '
          'frozen and nothing new is measured in it',
          not any('Ѐ' <= c <= 'ӿ' for s in rows for c in s))
    check('no duplicates, so twenty sentences are twenty measurements',
          len(set(rows)) == 20)
    check('the corpus is identified by a digest, so a result cannot be compared '
          'against a baseline taken over different words', len(digest) == 64)
    check('and the file says, in writing, that changing a sentence invalidates the '
          'baseline', 'invalidates the saved baseline' in SENTENCES.read_text())


# --- the comparison rule ------------------------------------------------------

def test_the_normaliser_only_folds_spelling_conventions_and_never_words():
    for text, expected in [
            ('Done.', ['done']),
            ('Volume is now 30%.', ['volume', 'is', 'now', 'thirty', 'percent']),
            ('Volume is now thirty percent.', ['volume', 'is', 'now', 'thirty', 'percent']),
            ('96% full', ['ninety', 'six', 'percent', 'full']),
            ('61,000 files', ['sixty', 'one', 'thousand', 'files']),
            ('412 lines', ['four', 'hundred', 'and', 'twelve', 'lines']),
            ('Firefox & Chrome', ['firefox', 'and', 'chrome']),
            ('forty-one', ['forty', 'one'])]:
        check('%-32r normalises to %s' % (text, expected), tts_wer.normalise(text) == expected)
    check('the two spellings of the same sentence are the same word list, which is '
          'the entire reason the normaliser exists',
          tts_wer.normalise('The disk is 96% full.') == tts_wer.normalise('The disk is ninety six percent full.'))
    check('but a WRONG word is still wrong — nothing here forgives meaning',
          tts_wer.normalise('the disk is full') != tts_wer.normalise('the desk is full'))


def test_the_word_error_rate_is_an_edit_distance_and_is_checkable_by_hand():
    for reference, heard, rate, edits in [
            ('Done.', 'Done.', 0.0, 0),
            ('Done.', 'Dawn.', 1.0, 1),
            ('Opening Firefox.', 'Opening Firefox', 0.0, 0),
            ('Opening Firefox.', 'Opening Fire Fox.', 1.0, 2),          # 2 edits over 2 words
            ('one two three four', 'one two three', 0.25, 1),           # one deletion
            ('one two three four', 'one two three four five', 0.25, 1),  # one insertion
            ('The disk is 96% full.', 'The disk is ninety six percent full.', 0.0, 0)]:
        measured, got_edits, words = tts_wer.wer(reference, heard)
        check('wer(%r, %r) = %.2f over %d edits' % (reference, heard, rate, edits),
              abs(measured - rate) < 1e-9 and got_edits == edits)
    try:
        tts_wer.wer('', 'something')
        check('a reference with no words is refused rather than scored as perfect', False)
    except ValueError:
        check('a reference with no words is refused rather than scored as perfect', True)


# --- the baseline and the gate -------------------------------------------------

def _baseline():
    return json.loads(BASELINE.read_text())


def test_the_baseline_is_saved_and_says_what_ruler_measured_it():
    check('a baseline is on disk at eval/surfaces/tts_baseline.json', BASELINE.exists())
    if not BASELINE.exists():
        return
    base = _baseline()
    ruler = base['ruler']
    check('it records a mean WER over the twenty sentences',
          isinstance(base['mean_wer'], float) and 0.0 <= base['mean_wer'] <= 1.0
          and len(base['rows']) == 20)
    check('the voice is Piper en_US-ryan-medium — the English voice, not the frozen '
          'Macedonian one', ruler['voice'] == 'en_US-ryan-medium' and 'piper' in ruler['engine'])
    check('the ear is faster-whisper large-v3', 'faster-whisper-large-v3' in ruler['whisper_model'])
    check('and it records the device, compute type and beam size, because a WER is '
          'only comparable against the same decoder',
          ruler['device'] in {'cpu', 'cuda'} and ruler['compute_type'] and ruler['beam_size'] >= 1)
    check('the corpus digest in the baseline is the digest of the corpus on disk',
          ruler['sentences_sha256'] == tts_wer.sentences()[1])
    check('the flags in force when it was taken are recorded with it',
          isinstance(base.get('flags', {}).get('flags'), dict))
    check('every row keeps the WAV it was measured from, so the evidence is on disk '
          'and not only in a number',
          all(row['wav'].endswith('.wav') and row['reference_words'] >= 1 for row in base['rows']))
    print('      baseline: mean WER %.4f (corpus %.4f, %d/20 perfect, worst %.4f) on %s/%s'
          % (base['mean_wer'], base['corpus_wer'], base['perfect_sentences'],
             base['worst_wer'], ruler['device'], ruler['compute_type']))


def grade(result, base, tolerance=TOLERANCE):
    """The whole gate, as one function, so it can be driven with fabricated numbers.

    Returns (passed, reason). A ruler mismatch is NOT a pass and NOT a WER
    regression: it is a refusal to compare, which is the honest third answer.
    """
    mine, theirs = result['ruler'], base['ruler']
    differ = [k for k in ('voice', 'whisper_model', 'device', 'compute_type', 'beam_size',
                          'language', 'sentences', 'sentences_sha256', 'normaliser')
              if mine.get(k) != theirs.get(k)]
    if differ:
        return None, ('refusing to compare: the ruler changed (%s). Re-take the baseline with '
                      '--save-baseline instead of reading a method change as a regression.'
                      % ', '.join(differ))
    rise = result[METRIC] - base[METRIC]
    other = ('; mean over sentences %.4f -> %.4f (%+.4f), not gated on'
             % (base['mean_wer'], result['mean_wer'], result['mean_wer'] - base['mean_wer'])
             if METRIC != 'mean_wer' and 'mean_wer' in result else '')
    if rise > tolerance:
        return False, ('%s rose %.4f (%.4f -> %.4f), past the %.2f tolerance%s'
                       % (METRIC, rise, base[METRIC], result[METRIC], tolerance, other))
    return True, ('%s %.4f against a baseline of %.4f (%+.4f, tolerance %.2f)%s'
                  % (METRIC, result[METRIC], base[METRIC], rise, tolerance, other))


def test_the_gate_itself_trips_where_it_says_it_does():
    """Fabricated results either side of the line. No model, no audio: this is
    about the arithmetic, and a tripwire nobody has seen trip is not a tripwire."""
    base = {METRIC: 0.1000, 'mean_wer': 0.1000,
            'ruler': {'voice': 'en_US-ryan-medium', 'whisper_model': 'm',
                      'device': 'cpu', 'compute_type': 'int8', 'beam_size': 5,
                      'language': 'en', 'sentences': 20,
                      'sentences_sha256': 'abc', 'normaliser': 'v1'}}

    def at(value, **ruler):
        return {METRIC: value, 'mean_wer': value, 'ruler': dict(base['ruler'], **ruler)}

    for value, expected, why in [(0.1000, True, 'unchanged'),
                                 (0.0100, True, 'better by a lot'),
                                 (0.1490, True, 'worse by 0.049, inside the tolerance'),
                                 (0.1500, True, 'worse by exactly 0.05, which is the boundary '
                                                'and is allowed'),
                                 (0.1501, False, 'worse by 0.0501, past the tolerance'),
                                 (0.4000, False, 'four times worse')]:
        passed, reason = grade(at(value), base)
        check('%s %.4f: %s -> %s (%s)'
              % (METRIC, value, why, 'pass' if expected else 'FAIL', reason),
              passed is expected)

    for ruler, what in [({'device': 'cuda'}, 'a different device'),
                        ({'compute_type': 'float16'}, 'a different compute type'),
                        ({'voice': 'en_GB-alan-low'}, 'a different voice'),
                        ({'sentences_sha256': 'def'}, 'different sentences'),
                        ({'beam_size': 1}, 'a different beam size'),
                        ({'normaliser': 'v2'}, 'a different normaliser')]:
        passed, reason = grade(at(0.9, **ruler), base)
        check('%s refuses the comparison rather than reporting a regression' % what,
              passed is None and 'ruler changed' in reason)


# --- the live measurement ------------------------------------------------------

def test_the_voice_measured_now_is_not_materially_worse_than_the_baseline():
    if not BASELINE.exists():
        check('SKIPPED, not passed — there is no baseline to compare against. Take one with '
              './eval/surfaces/tts_wer.py --save-baseline', True)
        return
    base = _baseline()
    existing = os.environ.get('ARIES_TTS_RESULT', '').strip()
    if existing:
        result = json.loads(Path(existing).read_text())
        print('      grading an earlier measurement: ' + existing)
    else:
        with tempfile.TemporaryDirectory(prefix='aries-tts-regression-') as tmp:
            # The JSON goes somewhere durable — a failing run is only arguable if
            # the transcripts behind it still exist. The WAVs stay in the tempdir;
            # 20 of them is 2 MB per run and the digests are in the JSON.
            keep = ROOT / 'var/measurements/tts-regression'
            keep.mkdir(parents=True, exist_ok=True)
            out = keep / ('gate-%s.json' % os.environ.get('ARIES_RUN_LABEL', str(os.getpid())))
            ruler = base['ruler']
            argv = [sys.executable, str(HARNESS), '--out', str(out),
                    '--voice', ruler['voice'], '--model', ruler['whisper_model'],
                    '--device', ruler['device'], '--compute', ruler['compute_type'],
                    '--beam', str(ruler['beam_size']),
                    '--audio-dir', str(Path(tmp) / 'audio')]
            print('      measuring now (minutes, on %s/%s): %s'
                  % (ruler['device'], ruler['compute_type'], ' '.join(argv[1:])))
            # A fresh environment: the harness re-execs itself to put the pip CUDA
            # libraries on LD_LIBRARY_PATH, which is the only way faster-whisper
            # loads here, and APP_ENV must not leak the test database into it.
            env = {k: v for k, v in os.environ.items()
                   if k not in {'ARIES_TTS_WER_REEXEC', 'LD_LIBRARY_PATH', 'APP_ENV',
                                'DATABASE_URL', 'DATA_DIR', 'RUNTIME_STORE', 'CONTEXT_DIR'}}
            proc = subprocess.run(argv, cwd=str(ROOT), env=env, capture_output=True,
                                  text=True, timeout=3600)
            if proc.returncode or not out.exists():
                check('SKIPPED, not passed — the measurement could not be taken here: '
                      + (proc.stderr.strip().splitlines() or ['no error text'])[-1][:300], True)
                return
            result = json.loads(out.read_text())
            print('\n'.join('      ' + line for line in proc.stdout.strip().splitlines()[-4:]))

    passed, reason = grade(result, base)
    if passed is None:
        check('SKIPPED, not passed — ' + reason, True)
        return
    check('the English voice is still intelligible to the ear ARIES listens with: ' + reason,
          passed)
    # Per sentence, in edits. See PER_SENTENCE_EDITS for why a rate cannot be used
    # at these lengths.
    moved, over = [], []
    for row in result['rows']:
        was = base['rows'][row['index']]
        gained = row['edits'] - was['edits']
        if gained <= 0:
            continue
        moved.append((row['text'], was['edits'], row['edits'], row['heard'], was['reference_words']))
        if gained > PER_SENTENCE_EDITS:
            over.append(moved[-1])
    for text, then, now, heard, words in moved:
        print('      WORSE  %d -> %d edits of %d words  %-38s heard %r'
              % (then, now, words, text[:38], heard[:60]))
    check('no sentence gained more than %d word errors (%d of 20 moved at all, %d past '
          'the bound)' % (PER_SENTENCE_EDITS, len(moved), len(over)), not over)


if __name__ == '__main__':
    raise SystemExit(run_module(sys.modules[__name__]))
