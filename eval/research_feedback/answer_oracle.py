"""Conservative answer adjudication against authored screen facts.

Exact structured answers and exact OCR transcripts are machine-checkable.
Other prose is unknown, never judged correct through substring matching or an LLM.
This scores answer content separately from obtaining the required observation.
"""
import json


def screen_answer(answer, *, frames):
    texts = [f'ARIES TEST FRAME {i}\nVALUE {17 if i == 1 else 29}' for i in frames]
    expected = {'texts': texts}
    if len(frames) == 2:
        expected['changed'] = True
    result = {'met': None, 'expected': expected, 'method': 'authored exact facts',
              'reason': 'Free-form answer requires independent human adjudication'}
    if not isinstance(answer, str) or not answer.strip():
        return {**result, 'met': False, 'reason': 'No answer supplied'}
    normalize = lambda text: ' '.join(text.split())
    if len(frames) == 1 and normalize(answer) == normalize(texts[0]):
        return {**result, 'met': True, 'reason': 'Exact authored transcript'}
    try:
        value = json.loads(answer)
    except (ValueError, TypeError):
        return result
    if not isinstance(value, dict) or set(value) != set(expected):
        return {**result, 'met': False, 'reason': 'Structured answer has missing or unexpected fields'}
    actual = value.get('texts')
    correct = (isinstance(actual, list) and len(actual) == len(texts)
               and all(isinstance(a, str) and normalize(a) == normalize(b) for a, b in zip(actual, texts)))
    if len(frames) == 2:
        correct = correct and value.get('changed') is True
    return {**result, 'met': bool(correct), 'reason': 'Structured answer compared with authored scene'}
