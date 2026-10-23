"""Read, listing and existence goals said in natural words get a completion contract.

Motivated by docs/analysis/terminal-state-diagnosis.md: on the held-out run of
2026-10-06, 39 of 49 goals had no completion contract, so no goal could reach done
however good its verified evidence was. Behind ARIES_COMPLETION_READ_PARAPHRASE.
Completion is not loosened: done still needs re-checked verified evidence.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_agent_execution as m14
from tests._bootstrap import check, run_module
from aries.workspace import contracts

ROOT = Path(__file__).resolve().parents[1]
FLAG = 'ARIES_COMPLETION_READ_PARAPHRASE'


# The frozen source archive is a local snapshot, not in the public repository; its aries/ tree is identical,
# file by file, to the tag thesis-final-20261006-snapshot, so a checkout without the archive reads the tag.
FROZEN_TAG = 'thesis-final-20261006-snapshot'


def frozen_contracts():
    path = ROOT / 'experiments/thesis-final-20261006/frozen/aries/workspace/contracts.py'
    if path.is_file():
        spec = importlib.util.spec_from_file_location('frozen_contracts', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    source = subprocess.run(['git', 'show', f'{FROZEN_TAG}:aries/workspace/contracts.py'], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
    module = types.ModuleType('frozen_contracts')
    exec(compile(source, f'{FROZEN_TAG}:aries/workspace/contracts.py', 'exec'), module.__dict__)
    return module


def fixture_goals():
    goals = []
    for name in ('experiments/product/independent-acceptance/fixtures.jsonl',
                 'eval/agent_suite/goals.jsonl', 'experiments/archive/aries100/goals.jsonl'):
        p = ROOT / name
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    goal = row.get('goal') or row.get('request') or row.get('text')
                    if isinstance(goal, str):
                        goals.append(goal)
    return goals


def test_flag_off_is_the_frozen_compiler():
    frozen = frozen_contracts()
    goals = fixture_goals() + ['Read /tmp/notes.txt.', 'List /tmp and read /tmp/a.txt.',
                               'Pull up /tmp/a.md and tell me what it says.']
    check('flag-off corpus is non-trivial', len(goals) >= 50)
    check('flag off: identical to ARIES-FINAL-20261006 on every corpus goal',
          all(contracts.compile_goal(g, '/demo') == frozen.compile_goal(g, '/demo') for g in goals))


def test_recogniser_is_closed():
    c = lambda g: contracts.compile_goal(g, '/demo', paraphrase=True)
    read = c('I can never keep track — pull up /h/p/minutes.md and tell me what it says.')
    check('natural read compiles to file.read', read['supported'] and read['requirements'] == [{'capability': 'file.read', 'path': '/h/p/minutes.md'}])
    check('trailing period stripped from an anchored read', c('Read /h/p/notes.txt.')['requirements'][0]['path'] == '/h/p/notes.txt')
    check('without the flag the period stays (frozen behaviour)',
          contracts.compile_goal('Read /h/p/notes.txt.', '/demo')['requirements'][0]['path'] == '/h/p/notes.txt.')
    exists = c('Am I right that there is nothing called tax-2025.pdf in /h/p? Double-check before you answer.')
    check('existence question compiles to file.exists on the named file',
          exists['supported'] and exists['requirements'] == [{'capability': 'file.exists', 'path': '/h/p/tax-2025.pdf'}])
    both = c('List /h/p and read /h/p/minutes.txt.')
    check('"list what is inside" is a listing, not a read',
          c('List what is inside /h/p/locked-dir.')['requirements'] == [{'capability': 'file.list', 'path': '/h/p/locked-dir'}])
    check('list-and-read compound compiles', both['supported'] and [r['capability'] for r in both['requirements']] == ['file.list', 'file.read'])
    for goal in ('Pull up /h/p/a.md and delete it.', 'Summarise /h/p/a.md for me.', 'Read /h/p/a.md and /h/p/b.md.',
                 'Show me /h/p/a.md and email it to my mentor.', 'Read me the notes from my thesis project.',
                 'Tell me if /h/p/a.md mentions the budget.', 'Print two copies of /h/p/report.txt on the office printer.', 'Read /h/p/a.md then move it to /h/q.'):
        check(f'stays unsupported: {goal}', not c(goal)['supported'])


async def test_correct_finish_is_accepted():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path = Path(directory) / 'minutes.md'
        path.write_text('We settled on Friday.')
        with patch.dict(os.environ, {FLAG: '1'}):
            result = await m14.run_goal(f'Pull up {path} and tell me what it says.',
                                        [m14.execute('file.read', path=str(path)), m14.finish])
        check('flag on: verified read of the requested file ends done', result['state'] == 'done')
        check('answer is built from verified evidence, not model prose',
              'We settled on Friday.' in result['agent']['summary'] and 'MODEL CLAIM' not in result['agent']['summary'])


async def test_incorrect_finish_is_still_rejected():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        wanted, other = Path(directory) / 'minutes.md', Path(directory) / 'other.md'
        wanted.write_text('A'); other.write_text('B')
        with patch.dict(os.environ, {FLAG: '1'}):
            wrong_file = await m14.run_goal(f'Pull up {wanted} and tell me what it says.',
                                            [m14.execute('file.read', path=str(other)), m14.finish,
                                             {'action': 'fail', 'summary': 'stopped'}])
            no_evidence = await m14.run_goal(f'Pull up {wanted} and tell me what it says.',
                                             [{'action': 'finish', 'evidence_refs': []},
                                              m14.execute('system.status'), {'action': 'fail', 'summary': 'stopped'}])
        check('finish on evidence for a different file is not done', wrong_file['state'] not in ('done', 'answered'))
        check('the rejection is recorded as a completion check',
              any(not x['met'] for x in wrong_file['agent'].get('completion_checks', [])))
        check('finish without evidence is not done', no_evidence['state'] not in ('done', 'answered'))
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        target = Path(directory) / 'notes.md'
        target.write_text('first')
        def change_then_finish(data):
            target.write_text('changed after the read')
            return m14.finish(data)
        # ARIES_CONTRACT_FINISH would propose finish without a planner call, so the
        # change below would never happen; switch it off to create a real stale read.
        with patch.dict(os.environ, {FLAG: '1', 'ARIES_CONTRACT_FINISH': '0'}):
            stale = await m14.run_goal(f'Pull up {target} and tell me what it says.',
                                       [m14.execute('file.read', path=str(target)), change_then_finish,
                                        {'action': 'fail', 'summary': 'stopped'}])
        check('the file really changed before the finish was checked', target.read_text() == 'changed after the read')
        check('a read made stale before finish is not done (recheck still applies)', stale['state'] not in ('done', 'answered'))


async def test_flag_off_keeps_the_old_behaviour():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path = Path(directory) / 'minutes.md'
        path.write_text('We settled on Friday.')
        with patch.dict(os.environ, {FLAG: '0'}):
            result = await m14.run_goal(f'Pull up {path} and tell me what it says.',
                                        [m14.execute('file.read', path=str(path)), m14.finish,
                                         {'action': 'fail', 'summary': 'stopped'}])
        check('flag off: same goal has no contract', result['agent']['contract']['supported'] is False)
        check('flag off: same goal does not reach done', result['state'] not in ('done', 'answered'))


async def test_existence_answer_is_verified():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        missing = Path(directory) / 'tax-2025.pdf'
        with patch.dict(os.environ, {FLAG: '1'}):
            result = await m14.run_goal(f'Am I right that there is nothing called tax-2025.pdf in {directory}?',
                                        [m14.execute('file.exists', path=str(missing)), m14.finish])
        check('existence goal ends done on a verified absence', result['state'] == 'done')
        check('existence answer states the re-checked fact', 'does not exist' in result['agent']['summary'])


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
