"""ARIES answering out loud. Nothing here plays a sound.

Synthesis is arithmetic and can be checked; playback needs speakers, a session
and a person not to be annoyed, so the tests stop at the samples. What they do
guard is the claim the Macedonian voice rests on — that espeak-ng's Macedonian
front end and a Bulgarian Piper voice share an alphabet — because that is the
part that would break silently, by mispronouncing rather than by failing.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-speech')
import numpy as np
from aries import speech
from aries.speech import engines
from aries.workspace import capabilities as cap

MACEDONIAN = "Готово. Го отворив Firefox и го намалив звукот на триесет проценти."


async def test_language_is_decided_by_script_not_by_word_count():
    check('Cyrillic is Macedonian', speech.detect('Готово.') == 'mk')
    check('Latin is English', speech.detect('Opening Firefox.') == 'en')
    # The case this rule exists for: a Macedonian sentence naming an English
    # product is Macedonian, however many Latin letters it happens to contain.
    check('a product name does not make it English', speech.detect('Го отворив Firefox.') == 'mk')
    check('empty text is not Macedonian', speech.detect('') == 'en')


async def test_latin_names_are_rewritten_before_a_cyrillic_front_end_sees_them():
    said = engines.cyrillize('Го отворив Firefox и YouTube.')
    check('Firefox is spelled for a Macedonian reader', 'Фајерфокс' in said)
    check('YouTube is spelled for a Macedonian reader', 'Јутјуб' in said)
    check('the Macedonian around it is untouched', said.startswith('Го отворив '))
    check('an unknown name is left alone rather than guessed at',
          'Inkscape' in engines.cyrillize('Го отворив Inkscape.'))


async def test_macedonian_never_comes_out_of_a_bulgarian_voice():
    """The user's rule, enforced rather than documented: "нејќам на бугарски".

    Piper has no Macedonian voice. Driving its Bulgarian one with espeak-ng's
    Macedonian front end works and was measured, and was refused anyway. So
    asking Piper for Macedonian must fail loudly instead of quietly speaking
    another language, and nothing may reach it by falling back.
    """
    try:
        engines.engine('mk', 'piper')
        check('Piper refuses to speak Macedonian', False)
    except ValueError as exc:
        check('Piper refuses to speak Macedonian, by name', 'Bulgarian' in str(exc))
    # What Bulgarian was replaced by: a voice recorded from a Macedonian, and it is
    # the DEFAULT, not the fallback. These two assertions were written while `edge`
    # was still the default and were not updated when the user picked Kiko by ear —
    # "гласот Kiko земи го". Kiko also won on measurement: 68 ms to first sound
    # against 410-1600 ms, WER 0.387 against 0.421, and it needs no network.
    # Asserting `edge` here would have quietly defended sending every Macedonian
    # reply to a remote service in a system whose whole claim is that it runs local.
    check('Macedonian speaks with RHVoice by default', engines.DEFAULTS['mk'] == 'rhvoice')
    check('and edge is only the fallback', engines.fallback('mk') == 'edge')
    check('and English needs none', engines.fallback('en') is None)
    check('no engine offers Macedonian that cannot speak it',
          all('mk' in langs or kind == 'piper' for kind, langs in engines.KINDS.items()))
    check('Piper is registered for English only', engines.KINDS['piper'] == ('en',))
    os.environ['ARIES_SPEECH_MK_FALLBACK'] = 'espeak'
    try:
        check('the fallback is overridable', engines.fallback('mk') == 'espeak')
    finally:
        del os.environ['ARIES_SPEECH_MK_FALLBACK']


async def test_the_macedonian_front_end_is_still_the_right_one():
    """espeak-ng `mk` is what pronounces Macedonian for every engine that needs
    phonemes. Pinned because the tempting "simplification" — letting a Cyrillic
    voice use its own language's front end — is not worse, it is broken."""
    from piper.phonemize_espeak import EspeakPhonemizer
    phonemizer = EspeakPhonemizer()
    text = engines.cyrillize(MACEDONIAN) + ' Ѓорѓи ќе ѕвони на Љупчо и Њам, џамија, ѕвезда.'
    produced = [c for sentence in phonemizer.phonemize('mk', text) for c in sentence]
    check('the Macedonian front end keeps ј', 'j' in produced)
    check('and produces the palatals Bulgarian does not have', 'ʎ' in produced and 'ɲ' in produced)
    # Bulgarian's alphabet has no ј/ѓ/ќ/ѕ/љ/њ/џ, and espeak-ng `bg` answers by
    # reading their Unicode names out loud. Pinned so nobody "simplifies" the
    # front end back to the voice's own language.
    letters = 'Ѓорѓи ќе ѕвони на Љупчо.'
    native = [c for s in phonemizer.phonemize('mk', letters) for c in s]
    foreign = [c for s in phonemizer.phonemize('bg', letters) for c in s]
    check('the Bulgarian front end does not read Macedonian letters, it spells them out '
          f'({len(native)} phonemes become {len(foreign)})', len(foreign) > 1.8 * len(native))


async def test_every_engine_makes_audio_without_a_network_or_a_speaker():
    for kind, text in (('rhvoice', MACEDONIAN), ('espeak', MACEDONIAN),
                       ('espeak', 'Opening Firefox.'), ('piper', 'Opening Firefox.')):
        language = speech.detect(text)
        voice = engines.engine(language, kind)
        if not voice.check()['ready']:
            check(f'skipped — {voice.name} is not on this machine', True)
            continue
        chunks = list(voice.stream(text))
        samples = np.frombuffer(b''.join(payload for payload, _ in chunks), dtype='<i2')
        seconds = sum(length for _, length in chunks)
        check(f'{voice.name} produces audible {language} samples',
              len(chunks) >= 1 and seconds > 0.5 and int(np.abs(samples.astype(np.int32)).max()) > 4000)
        # Trimming is what keeps the answer from starting a quarter second late.
        head = np.abs(samples[:voice.sample_rate // 10].astype(np.int32)).max()
        check(f'{voice.name} does not open with silence', head > engines.SILENCE)


async def test_trim_keeps_the_speech_and_drops_the_padding():
    rate = 22050
    quiet = np.zeros(rate // 2, dtype=np.int16)
    loud = (np.sin(np.arange(rate) / 8) * 20000).astype(np.int16)
    trimmed = engines.trim(np.concatenate((quiet, loud, quiet)), rate)
    check('padding is gone', abs(len(trimmed) - rate) < rate // 10)
    check('silence alone survives as silence', not len(engines.trim(quiet, rate)))


async def test_the_engine_for_a_language_is_selectable():
    check('Macedonian defaults to the voice the user chose', engines.DEFAULTS['mk'] == 'rhvoice')
    check('English defaults to the local voice', engines.DEFAULTS['en'] == 'piper')
    os.environ['ARIES_SPEECH_MK'] = 'espeak'
    try:
        check('the environment overrides the default', engines.chosen('mk') == 'espeak')
        check('and produces a different engine', engines.engine('mk').kind == 'espeak')
    finally:
        del os.environ['ARIES_SPEECH_MK']
    check('the default comes back', engines.chosen('mk') == 'rhvoice')
    try:
        engines.engine('mk', 'festival')
        check('an unknown engine is refused', False)
    except ValueError as exc:
        check('an unknown engine is refused by name', 'festival' in str(exc))


async def test_nothing_is_reported_that_was_not_observed():
    empty = speech.speak('')
    check('silence is not an answer', empty['state'] == 'failed' and empty['detail'] == 'nothing to say')
    check('nothing is claimed about it', not empty['ok'] and not empty['verified'])
    unknown = speech.speak('Hola', language='es')
    check('a language with no voice is refused', unknown['state'] == 'failed' and 'es' in unknown['detail'])
    state = speech.available()
    check('health reports the player it needs', state['player'] == 'pw-play')
    check('health reports a decision per language', set(state['languages']) == {'mk', 'en'})
    for code, entry in state['languages'].items():
        # Derived from engines.KINDS, not a literal set. The literal was written
        # before `rhvoice` existed and then quietly failed the language it was
        # meant to protect — the same staleness this project fixed in
        # docs/CAPABILITIES.md by generating it. A test that hard-codes a list the
        # code owns is a test that goes wrong the moment the code improves.
        check(f'{code} names its engine and its licence',
              entry['kind'] in engines.KINDS and bool(entry.get('detail')))
        check(f'{code} declares the engine it names can serve it',
              code in engines.KINDS[entry['kind']])
    check('nothing is speaking before anything was said', not speech.speaking())
    check('stopping nothing reports nothing', not speech.stop())


async def test_the_capability_is_wired_in_both_languages():
    check('Macedonian', cap.recognize('кажи Готово') == {'capability': 'say', 'args': {'text': 'Готово'}})
    check('transliterated', cap.recognize('kazi Gotovo')['capability'] == 'say')
    check('English', cap.recognize('say volume is at thirty')['capability'] == 'say')
    # "кажи ми …" is "tell me …" — a question, not a thing to read aloud.
    told = cap.recognize('кажи ми колку е часот')
    check('a question is not an utterance', told is None or told['capability'] != 'say')
    check('the catalogue example parses', cap.recognize('say Готово')['capability'] == 'say')
    check('the argument contract exists', cap.ARGUMENTS['say'] == ('text',))
    check('speaking is not a destructive capability', 'say' not in cap.WRITES and 'say' not in cap.SENSITIVE)
    action, request = cap.validate_action('say', {'text': 'Готово'})
    check('it validates into a capability step', action['capability'] == 'say' and 'Готово' in request)


if __name__ == '__main__':
    run_module(sys.modules[__name__])
