"""Macedonian goals retain the same independent proof requirements as English."""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module

bootstrap('aries-goal-contracts')
from aries.workspace.contracts import compile_goal, evidence_matches, answer


async def test_compound_reads_retain_every_requirement():
    contract=compile_goal('Read /tmp/a.txt and read /tmp/b.txt','/tmp/demo')
    check('two reads require two independent proofs',contract['supported'] and
          [r['path'] for r in contract['requirements']]==['/tmp/a.txt','/tmp/b.txt'])
    check('compound mutations do not enter read-only contract',not compile_goal(
        'Read /tmp/a.txt and delete /tmp/b.txt','/tmp/demo')['supported'])


async def test_macedonian_requests_have_the_same_completion_conditions():
    pairs = [
        ('Read file ~/Documents/a.txt', 'Прочитај датотека ~/Documents/a.txt'),
        ('Read ~/Documents/a.txt', 'Prochitaj ~/Documents/a.txt'),
        ('Show system status', 'Прикажи го статусот на системот'),
        ('Check system status', 'Proveri statusot na sistemot'),
        ('List running processes', 'Прикажи активни процеси'),
        ('Show processes', 'Listaj procesi'),
        ('Open application Firefox', 'Отвори апликацијата Firefox'),
        ('Launch Firefox', 'Otvori Firefox'),
        ('Write file ~/Documents/a.txt with content: Здраво',
         'Напиши датотека ~/Documents/a.txt со содржина: Здраво'),
        ('Save ~/Documents/a.txt containing: Здраво',
         'Zachuvaj ~/Documents/a.txt so sodrzhina: Здраво'),
        ('Create file a.txt in ~/Documents containing: Здраво Then read it back.',
         'Создај датотека a.txt во ~/Documents со содржина: Здраво Потоа прочитај ја.'),
        ('Create file a.txt in ~/Documents containing: Здраво Then read it back.',
         'Napravi datoteka a.txt vo ~/Documents so sodrzhina: Здраво Potoa prochitaj ja.'),
    ]
    for english, macedonian in pairs:
        expected = compile_goal(english, '/tmp/demo')
        actual = compile_goal(macedonian, '/tmp/demo')
        check(macedonian, expected['supported'] and actual == expected)


async def test_macedonian_compound_goal_cannot_be_silently_truncated():
    for request in ('Отвори Firefox и избриши датотека',
                    'Otvori Firefox potoa instaliraj program',
                    'Прикажи активни процеси и запреј ги',
                    'Прочитај ~/Documents/a.txt и избриши ја'):
        check('does not discard extra instructions: ' + request,
              not compile_goal(request, '/tmp/demo')['supported'])


async def test_macedonian_write_requires_the_exact_requested_bytes():
    contract = compile_goal('Напиши датотека ~/Documents/a.txt со содржина: Здраво', '/tmp/demo')
    requirement = contract['requirements'][0]
    correct = {'met': True, 'data': {'path': str(Path.home() / 'Documents/a.txt'),
                                   'sha256': hashlib.sha256('Здраво'.encode()).hexdigest()}}
    check('correct Macedonian bytes satisfy the independent proof',
          evidence_matches(requirement, correct))
    wrong = {'met': True, 'data': {**correct['data'], 'sha256': hashlib.sha256(b'Hello').hexdigest()}}
    check('a translation cannot substitute for the requested content',
          not evidence_matches(requirement, wrong))


async def test_measurement_questions_require_the_requested_numeric_observation():
    examples = [('колку место има на дискот?', 'disk.used_pct'),
                ('Kolku slobodno mesto imam?', 'disk.used_pct'),
                ('How much disk space do I have?', 'disk.used_pct'),
                ('Колку меморија се користи?', 'memory.used_pct'),
                ('What is the CPU usage?', 'cpu.used_pct')]
    for text, metric in examples:
        contract = compile_goal(text, '/tmp/demo')
        check('measurement question: ' + text,
              contract['supported'] and contract['requirements'][0]['metric'] == metric)
    contract = compile_goal('колку место има на дискот?', '/tmp/demo')
    requirement = contract['requirements'][0]
    reading = {'metric': 'disk.used_pct', 'subject': '/', 'value': 8.5,
               'detail': {'free_gib': 396.28, 'size_gib': 433.09}}
    verified = {'met': True, 'data': {'filesystems': [reading]}}
    check('a freshly verified disk measurement is a completion oracle',
          evidence_matches(requirement, verified))
    for bad in ({**reading, 'metric': 'cpu.used_pct'}, {**reading, 'value': None},
                {**reading, 'value': float('nan')}, {**reading, 'detail': {}},
                {'summary': 'There is plenty of disk space'}):
        check('unrelated or missing evidence cannot answer disk space',
              not evidence_matches(requirement, {'met': True, 'data': {'filesystems': [bad]}}))
    check('an unverified observation cannot satisfy the question',
          not evidence_matches(requirement, {**verified, 'met': False}))
    text = answer(contract, [{'data': verified['data']}])
    check('the answer is computed from the measured values in Macedonian',
          '396' in text and 'Дискот' in text)
    check('an added destructive clause cannot hide inside a measurement question',
          not compile_goal('колку место има на дискот и избриши ги датотеките', '/tmp/demo')['supported'])


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
