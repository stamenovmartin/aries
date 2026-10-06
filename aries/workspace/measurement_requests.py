"""Complete spoken measurement requests, mapped to existing verified contracts.

Every clause must be understood. An unknown suffix never disappears behind a
successful first measurement, and a noun alias never authorises a mutation.
"""
import re
from aries.workspace.contracts import compile_goal

QUESTIONS = {
    'mk': ('колку место има на дискот?', 'колку меморија се користи?',
           'колку е оптоварен процесорот?'),
    'en': ('How much disk space do I have?', 'How much memory is used?',
           'What is the CPU usage?'),
}
SUBJECTS = {
    'disk': (0, 'en'), 'disk space': (0, 'en'), 'disk usage': (0, 'en'), 'storage': (0, 'en'),
    'диск': (0, 'mk'), 'дискот': (0, 'mk'), 'diskot': (0, 'mk'),
    'memory': (1, 'en'), 'memory usage': (1, 'en'), 'ram': (1, 'en'), 'меморијата': (1, 'mk'),
    'меморија': (1, 'mk'), 'рам': (1, 'mk'), 'memorijata': (1, 'mk'),
    'memorija': (1, 'mk'), 'cpu': (2, 'en'), 'cpu usage': (2, 'en'), 'processor': (2, 'en'),
    'процесорот': (2, 'mk'), 'процесор': (2, 'mk'),
    'procesorot': (2, 'mk'), 'procesor': (2, 'mk'),
}
SEPARATOR = r'\s*(?:;|,|\b(?i:and)\b|\bи\b|\bi\b)\s*'


def _measured(text):
    return compile_goal(text, '').get('answer') == 'measurements'


def _alias(text, language=None):
    key = text.strip().rstrip('.?!').strip().casefold()
    selected = SUBJECTS.get(key)
    if selected is None:
        return None
    index, inferred = selected
    return QUESTIONS[language or inferred][index]


def questions(text):
    """Return canonical full questions, or None if ANY part is unsupported."""
    text = text.strip()
    if not text or len(text) > 2000:
        return None
    if _measured(text):
        return [text]
    # A named follow-up carries its own subject; it does not reuse stale values.
    follow = re.fullmatch(r'(?i:(а|a|and|what about))\s+(.+)', text)
    if follow:
        language = 'mk' if follow[1].casefold() in {'а', 'a'} else 'en'
        answer = _alias(follow[2], language)
        return [answer] if answer else None
    short = re.fullmatch(r'(?i:(провери|прикажи|proveri|prikazhi|check|show))\s+(?:(?:ги|ми|gi|mi|the)\s+)?(.+)', text)
    if short:
        language = 'en' if short[1].casefold() in {'check', 'show'} else 'mk'
        parts = re.split(SEPARATOR, short[2])
        answers = [_alias(part, language) for part in parts]
    else:
        parts = re.split(SEPARATOR, text)
        if len(parts) < 2:
            return None
        # A bare trailing noun is meaningful only after a full measurement
        # question; e.g. "show CPU usage and memory".
        if not _measured(parts[0]):
            return None
        language = compile_goal(parts[0], '')['language']
        answers = [part if _measured(part) else _alias(part, language) for part in parts]
    if not 1 <= len(answers) <= 6 or not all(answers):
        return None
    return list(dict.fromkeys(answers))
