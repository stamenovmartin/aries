"""ARIES_COMPLETION_TYPED_CONTRACT (H5): the model only proposes a typed claim; code decides the contract.

See aries/workspace/typed_contract.py and docs/preregistration/H5-completion-paraphrase.md (The treatment, 2).
The model is mocked; no inference runs.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_agent_execution as m14
from tests._bootstrap import check, run_module
from aries.workspace import contracts

OFF = {'ARIES_COMPLETION_TYPED_CONTRACT': '0', 'ARIES_COMPLETION_READ_PARAPHRASE': '0'}
ON = {'ARIES_COMPLETION_TYPED_CONTRACT': '1', 'ARIES_COMPLETION_READ_PARAPHRASE': '0'}


def typed(kind, path, name=''):
    return {'goal_type': kind, 'path': path, 'name': name}


def test_code_validates_the_claim():
    from aries.workspace import typed_contract as T
    g = 'Could you tell me what my packing notes say? They are at /h/p/packing.txt.'
    c, why = T.validate(typed('read', '/h/p/packing.txt'), g)
    check('a read on the one verbatim path is accepted', c == {'supported': True, 'requirements': [
        {'capability': 'file.read', 'path': '/h/p/packing.txt'}], 'recognised_by': 'typed'})
    g = 'What is inside the folder /h/p/trip, please?'
    c, _ = T.validate(typed('list', '/h/p/trip,'), g)
    check('a listing strips sentence punctuation like the fast path', c and c['requirements'] ==
          [{'capability': 'file.list', 'path': '/h/p/trip'}] and c['answer'] == 'listing')
    g = 'Is there anything called budget.xlsx in /h/p/work?'
    c, _ = T.validate(typed('exists', '/h/p/work', 'budget.xlsx'), g)
    check('an existence claim joins the verbatim name to the path', c and c['requirements'] ==
          [{'capability': 'file.exists', 'path': '/h/p/work/budget.xlsx'}] and c['answer'] == 'existence')
    rejected = {
        'none': (typed('none', '/h/p/work'), g),
        'path not verbatim': (typed('read', '/h/p/work/budget.xlsx'), g),
        'not the one path': (typed('read', '/h/p'), g),
        'two paths in the request': (typed('read', '/h/a'), 'Read /h/a and compare it with /h/b'),
        'no path in the request': (typed('read', 'notes'), 'Read my notes'),
        'name not verbatim': (typed('exists', '/h/p/work', 'budget.csv'), g),
        'name with a slash': (typed('exists', '/h/p/work', 'x/budget.xlsx'), g + ' x/budget.xlsx'),
        'a listing with a name': (typed('list', '/h/p/work', 'budget.xlsx'), g),
        'unknown type': ({'goal_type': 'write', 'path': '/h/p/work', 'name': ''}, g),
        'extra field': ({**typed('read', '/h/p/work'), 'done': True}, g),
    }
    for label, (parsed, goal) in rejected.items():
        check('rejected: ' + label, T.validate(parsed, goal)[0] is None)


def test_shapes_are_the_existing_ones():
    from aries.workspace import typed_contract as T
    for goal, parsed in [('Read /h/p/a.txt', typed('read', '/h/p/a.txt')),
                         ('List /h/p', typed('list', '/h/p')),
                         ('Is there a file called a.txt in /h/p?', typed('exists', '/h/p', 'a.txt'))]:
        mine = T.validate(parsed, goal)[0]
        fast = contracts.paraphrased(goal) or contracts.compile_goal(goal, '/x')
        check('same requirement shape as the compiler: ' + goal,
              mine['requirements'] == fast['requirements'] and mine.get('answer') == fast.get('answer'))


def model_says(payload, calls):
    async def fake(db, messages, schema, **kwargs):
        calls.append({'purpose': kwargs.get('purpose'), 'schema': schema})
        if isinstance(payload, Exception):
            raise payload
        return json.dumps(payload), {'prompt_eval_count': 40, 'eval_count': 12}
    return fake


async def run(goal, sequence, payload, env):
    calls = []
    with patch.dict(os.environ, env), patch('aries.intelligence.structured', side_effect=model_says(payload, calls)):
        result = await m14.run_goal(goal, sequence)
    return result, calls


async def test_typed_contract_reaches_done_only_through_verified_evidence():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        f = Path(d) / 'packing.txt'
        f.write_text('passport\ncharger\n')
        goal = f'Could you tell me what my packing notes say? They are at {f}.'
        check('the fast path has no contract for this wording', not contracts.compile_goal(goal, d)['supported'])
        result, calls = await run(goal, [m14.execute('file.read', path=str(f)), m14.finish], typed('read', str(f)), ON)
        contract = result['agent']['contract']
        check('one typed call, and the typed contract is used', len(calls) == 1 and calls[0]['purpose'] ==
              'workspace.typed-contract' and contract['recognised_by'] == 'typed' and contract['typed']['accepted'])
        check('done after the verified, re-checked read', result['state'] == 'done')
        result, _ = await run(goal, [{'action': 'finish', 'evidence_refs': [], 'summary': 'It says passport.'},
                                     {'action': 'fail', 'summary': 'stopped'}], typed('read', str(f)), ON)
        check('a finish without verified evidence is still rejected', result['state'] != 'done')


async def test_rejected_claim_leaves_the_goal_unsupported():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        f = Path(d) / 'packing.txt'
        f.write_text('x')
        goal = f'Could you tell me what my packing notes say? They are in {d}.'
        seq = [m14.execute('file.read', path=str(f)), m14.finish, {'action': 'fail', 'summary': 'stopped'}]
        result, _ = await run(goal, seq, typed('read', str(f)), ON)
        c = result['agent']['contract']
        check('a path that is not verbatim in the request is rejected; goal not done',
              not c['supported'] and c['typed']['accepted'] is False and result['state'] != 'done')
        result, _ = await run(goal, seq, RuntimeError('model down'), ON)
        check('a failed call leaves the goal unsupported', not result['agent']['contract']['supported']
              and 'error' in result['agent']['contract']['typed'])


async def test_cyrillic_is_not_sent():
    await m14.setup()
    result, calls = await run('Прочитај ми ги белешките во /tmp/нема.', [{'action': 'fail', 'summary': 'stopped'}],
                              typed('read', '/tmp/нема'), ON)
    check('a Cyrillic request makes no typed call', calls == [] and not result['agent']['contract']['supported'])


async def test_flag_off_is_the_previous_behaviour():
    await m14.setup()
    sys.modules.pop('aries.workspace.typed_contract', None)
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        f = Path(d) / 'packing.txt'
        f.write_text('x')
        goal = f'Could you tell me what my packing notes say? They are at {f}.'
        seq = [m14.execute('file.read', path=str(f)), m14.finish, {'action': 'fail', 'summary': 'stopped'}]
        result, calls = await run(goal, seq, typed('read', str(f)), OFF)
        check('flag off: no typed call, module never imported',
              calls == [] and 'aries.workspace.typed_contract' not in sys.modules)
        check('flag off: the contract is exactly compile_goal\'s', result['agent']['contract'] ==
              contracts.compile_goal(goal, result['agent']['environment']['demo_directory']))
        check('flag off: unsupported goal does not reach done', result['state'] != 'done')


def test_contract_compiler_untouched():
    # Until the H5 measurement ended this checked that contracts.py was byte-identical to the tag. The
    # remedy designed after H5 (ARIES_CONTRACT_FILENAME_JOIN) changes the file, so the check is now on
    # behaviour: with the new flag off, the compiler gives exactly what the tagged one gives.
    import importlib.util
    import subprocess
    import tempfile as tf
    from tests.test_completion_read_paraphrase import fixture_goals
    root = Path(__file__).resolve().parents[1]
    frozen = subprocess.run(['git', 'show', 'h4b-frozen-20261018:aries/workspace/contracts.py'], cwd=root,
                            capture_output=True).stdout
    check('the tagged contracts.py is available', bool(frozen))
    with tf.NamedTemporaryFile('wb', suffix='.py', delete=False) as fh:
        fh.write(frozen)
    spec = importlib.util.spec_from_file_location('contracts_h4b_frozen', fh.name)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    Path(fh.name).unlink()
    goals = fixture_goals() + ['Read notes.txt in /h/p.', 'Is there a report.pdf in /h/p?', 'Show me /h/p/a.txt',
                               'Read the notes in /h/p', 'Pull up /h/p/a.md and tell me what it says.']
    check('with ARIES_CONTRACT_FILENAME_JOIN off the compiler equals the tag (h4b-frozen-20261018)',
          all(contracts.compile_goal(g, '/d', paraphrase=p) == old.compile_goal(g, '/d', paraphrase=p)
              for g in goals for p in (False, True)))


async def test_fast_path_contract_is_never_replaced():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        f = Path(d) / 'a.txt'
        f.write_text('x')
        result, calls = await run(f'Read {f}', [m14.execute('file.read', path=str(f)), m14.finish],
                                  typed('list', d), ON)
        check('a goal the fast path already supports makes no typed call', calls == []
              and 'typed' not in result['agent']['contract'] and result['state'] == 'done')


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
