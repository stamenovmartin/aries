# Speech — ARIES answering out loud

`experiments/voice/voice.py` turns speech into a command. `aries/speech/` turns the
outcome back into speech. One call:

```python
from aries import speech
speech.speak("Го отворив Фајерфокс.")           # detected as Macedonian
speech.speak("Volume is now thirty percent.")    # detected as English
```

`speak(text, *, language=None, blocking=False, engine=None)`, plus `stop()`,
`speaking()`, `warm()`, `available()` and `detect()`. Language is decided by
script: one Cyrillic letter means Macedonian. The rule is asymmetric because the
evidence is — a Macedonian reply always contains Cyrillic, an English reply never
does, and "Го отворив Firefox" is a Macedonian sentence with a product name in it.

## The Macedonian problem, and why it took three attempts

**No neural text-to-speech model has ever been published that was trained on
Macedonian speech.** Checked rather than assumed:

* Piper publishes 177 voices in 58 languages. No `mk`. Its one `sr_RS` voice was
  trained on the Serbski institut **Lower Sorbian** corpus — a different language,
  mislabelled upstream.
* Meta's MMS-TTS covers 1143 languages, from its own file manifest. `mkd` is not
  among them, nor `srp`, `hrv` or `slv`; `bul` and `rus` are.
* XTTS-v2 (17 languages), Kokoro, Coqui's zoo and sherpa-onnx all exclude it.
* `goran/speecht5-tts.mk` and `goran/parler-tts-large-v1.mk` on Hugging Face look
  exactly like what you want and contain only `.gitattributes`. Empty placeholders.

What does exist is **RHVoice**, written for blind users and packaged in Ubuntu,
with two voices recorded from Macedonian speakers. It was found only after the
user insisted the first search had been too shallow, and they were right.

| voice | who | licence |
|---|---|---|
| **Kiko** (default) | male, © 2021 Government of North Macedonia, LouderPages | CC BY-NC-SA 4.0 |
| Suze | female, recorded 2022 from Suzana Todorovska at the FEEIT speech studio, UKIM Skopje, with the Institute of Macedonian Language and UNICEF funding | CC BY-NC-ND 4.0 |

Both are **NonCommercial**, which is why Debian files them under `non-free`. Fine
for one person's own assistant; a blocker for anything sold, and NoDerivatives
means Suze may not be fine-tuned.

## The four engines, measured

Numbers and method in `experiments/speech/`; regenerate with
`.venv/bin/python experiments/speech/bench.py --language mk [--transcribe]`.

| engine | first sound | load | RAM | WER | network |
|---|---|---|---|---|---|
| **rhvoice Kiko** (mk default) | 68 ms | 1.1 ms | +1.8 MB | **0.387** | no |
| edge `mk-MK-AleksandarNeural` (mk fallback) | 410–1600 ms | — | 0 | 0.421 | **yes** |
| piper `en_US-ryan-medium` (en default) | 78 ms | 1096 ms | +91 MB | — | no |
| espeak-ng `mk+m3` | 7 ms | 28 ms | +20 MB | 0.863 | no |

`WER` is a **proxy for a listener, not a listener**: each clip is fed back to the
same Whisper large-v3 ARIES listens with and compared to the input text. It is
inflated equally for every engine because Whisper writes "30%" where the text says
"триесет проценти", which scores as two errors. Read the ranking, not the number.

Kiko won on both the user's ear and the measurement, which was not expected — HTS
parametric synthesis is audibly a synthesizer while the Microsoft voice sounds
human. It is more *recoverable*, and 6–20x faster because it does not travel.

### Bulgarian was built, measured and deleted

`bg_BG-dimitar` driven by espeak-ng's **Macedonian** front end instead of its own
scored WER 0.578 and worked, in the sense that every phoneme the `mk` front end
emits has an id in the Bulgarian voice's symbol table. It was refused outright —
*"нејќам на бугарски"* — so the model is off the disk and `engines.engine('mk',
'piper')` raises by name rather than quietly speaking another language.

The finding is kept in `engines.py` because it is worth knowing: using the
Bulgarian voice with its **own** `bg` front end is not merely worse, it is broken.
Bulgarian's alphabet has no ј, ѓ, ќ, ѕ, љ, њ or џ, and espeak-ng `bg` responds to
them by spelling their Unicode names aloud — "Ѓорѓи ќе ѕвони" came back as
"флорин о рə флорин … буква четири пет".

## Choosing an engine

```
ARIES_SPEECH_MK=edge      the natural network voice instead of Kiko
ARIES_SPEECH_MK=espeak    the robot
ARIES_SPEECH_EN=edge      Microsoft for English too
ARIES_SPEECH_MK_FALLBACK  what speaks when the default cannot
```

`available()` reports, per language, which engine is in force, whether it is
ready, its licence and what the alternatives are — all from each engine's own live
`check()`, never from a written list.

## Installing the voices

```
./scripts/aries-fetch-voice en_US-ryan-medium     Piper, parallel ranges (63 MB in ~17 s)
sudo apt install rhvoice-macedonian librhvoice5   RHVoice, the ordinary way
./scripts/aries-fetch-rhvoice                     RHVoice without root
```

ARIES prefers a system RHVoice install and falls back to a copy in
`var/models/rhvoice`. The rootless script exists because there is no C++ toolchain
on this machine — `apt-get download` plus `dpkg-deb -x` needs no privileges, and
building from source would need a compiler that is not here. RHVoice is reached by
ctypes over `libRHVoice.so.5`, with dependencies dlopen'd `RTLD_GLOBAL` rather
than through `LD_LIBRARY_PATH`, because the voice daemon's wrapper already owns
that variable for CUDA.

## Wiring it into the voice daemon

In `serve()`, on the branch that already passed the wake gate and acted:

```python
from aries import speech
speech.speak(result.get('message') or ('Готово.' if lang == 'mk' else 'Done.'),
             language=lang, blocking=True)
```

and once at startup, beside the model load: `speech.warm()`.

**Speak only when spoken to.** The user's rule, in their words: *"ако не го
повикам Ари, нека не се јавува"* — sometimes they are on the phone in the same
room, or watching a film, and a machine that answers the television is worse than
one that says nothing. Nothing in `aries/speech/` can tell whether ARIES was
addressed; only the wake gate can. So `speak()` belongs on that branch and nowhere
else — not on a dropped utterance, not on a low-confidence transcription, not on a
refusal nobody asked for.

**`blocking=True` is the right first wiring.** `serve()` is sequential, so
blocking means ARIES is not listening while it talks. That is what stops it
transcribing itself: a feedback loop of exactly that shape ran 44 times on
2026-09-29. For barge-in later, use `blocking=False` and call `stop()` when a new
utterance begins; `speaking()` is there to gate on.

## Streaming

Per sentence there is nothing to stream: VITS is not autoregressive, so a sentence
is one forward pass that produces all of its audio at once. Across sentences there
is — a four-sentence Macedonian reply through Piper emits four chunks, the first at
81 ms carrying 0.57 s of audio while the remaining 393 ms of synthesis finishes
underneath it. The Microsoft voice genuinely streams mid-sentence (16–33 MP3
chunks per sentence), which is what cut its first sound from 1.7 s to under one.

Playback is `pw-play` reading from a pipe. `pactl` does not exist on this machine;
PipeWire's own tools do.

## Honest limits

* **Nobody has heard these voices but the user.** The quality ranking is their ear
  plus the WER proxy, not an authored judgement.
* **No test plays audio**, so playback itself has no regression guard. The 46
  checks in `tests/test_speech.py` stop at the samples.
* `speak()` has not run inside the live `aries-voice.service` process. What is
  verified: `pw-play` works from a systemd user unit, and the module loads and
  synthesizes in a process that already holds `faster_whisper`.
* Latin product names inside Macedonian text are handled by a 20-entry
  transliteration table for the local engines, so a name outside it is
  mispronounced. The Microsoft voice does not need the table.
* **The licence-clean answer does not exist yet**: a Piper `mk_MK` voice trained
  on the 24 CC0 hours in Common Voice mk would be ~60 MB, run at Piper latency,
  and be free of the NonCommercial restriction. Nobody has attempted it.
