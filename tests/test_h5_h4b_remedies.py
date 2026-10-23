"""The remedies designed after H5 and H4b, each behind its own flag (default off).

ARIES_CONTRACT_FILENAME_JOIN    contracts.paraphrased(): "read notes.txt in ~/x" is the file, not the folder.
ARIES_TYPED_CONTRACT_CODE_PATH  typed_contract: the model gives the type and a name; code gives the path.
ARIES_RESOLVER_CODE_SELECT      clarify_resolver: code selects on a request word; no decision call.

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
from aries.workspace import clarify_resolver as R
from aries.workspace import contracts


def compiled(goal, join=True):
    return contracts.compile_goal(goal, '/demo', paraphrase=True, filename_join=join)


def test_filename_join_targets_the_file():
    check('read a bare name in a folder: the file',
          compiled('Read notes.txt in /h/p.')['requirements'] == [{'capability': 'file.read', 'path': '/h/p/notes.txt'}])
    check('a quoted name: the file',
          compiled("Show me what 'plan-v2.md' in /h/p says")['requirements'][0]['path'] == '/h/p/plan-v2.md')
    check('existence of a bare name: the file, not the folder',
          compiled('Is there a report.pdf in /h/p?')['requirements'] == [{'capability': 'file.exists', 'path': '/h/p/report.pdf'}])
    check('without the flag the folder is the target (the H5 behaviour)',
          compiled('Read notes.txt in /h/p.', join=False)['requirements'][0]['path'] == '/h/p')


def test_filename_join_fails_closed():
    check('two bare names: no contract', not compiled('Read a.txt and b.txt in /h/p')['supported'])
    check('a folder read with no file: no contract', not compiled('Read the notes in /h/p')['supported'])
    check('"show me" a file path is a read, not a listing',
          compiled('Show me /h/p/notes.txt')['requirements'] == [{'capability': 'file.read', 'path': '/h/p/notes.txt'}])
    check('"list" a folder is still a listing',
          compiled('List /h/p')['requirements'] == [{'capability': 'file.list', 'path': '/h/p'}])
    check('an exact file path is unchanged',
          compiled('Read /h/p/a.md.')['requirements'] == [{'capability': 'file.read', 'path': '/h/p/a.md'}])
    check('"called" still names the file',
          compiled('Am I right that there is nothing called tax-2025.pdf in /h/p?')['requirements'][0]['path']
          == '/h/p/tax-2025.pdf')
    check('a compound read keeps both parts',
          [r['capability'] for r in compiled('List /h/p and read /h/p/minutes.txt.')['requirements']]
          == ['file.list', 'file.read'])


def test_flag_off_compiler_unchanged():
    from tests.test_completion_read_paraphrase import fixture_goals
    goals = fixture_goals() + ['Read notes.txt in /h/p.', 'Is there a report.pdf in /h/p?']
    check('filename_join=False is the compiler as it was',
          all(contracts.compile_goal(g, '/demo', paraphrase=True) ==
              contracts.compile_goal(g, '/demo', paraphrase=True, filename_join=False) for g in goals))


def test_typed_code_path():
    from aries.workspace import typed_contract as T
    g = 'Could you pull up notes.txt? It lives in /h/p.'
    c, why = T.validate_code_path({'goal_type': 'read', 'name': 'notes.txt'}, g)
    check('code supplies the path, the name is joined', c and c['requirements'] ==
          [{'capability': 'file.read', 'path': '/h/p/notes.txt'}])
    c, _ = T.validate_code_path({'goal_type': 'read', 'name': '/h/p/notes.txt'}, g)
    check('a model that prefixed the folder still gives the file', c and c['requirements'][0]['path'] == '/h/p/notes.txt')
    c, why = T.validate_code_path({'goal_type': 'read', 'name': ''}, g)
    check('a read of the folder itself is rejected', c is None and 'folder' in why)
    c, _ = T.validate_code_path({'goal_type': 'read', 'name': ''}, 'What does /h/p/a.md say?')
    check('a read of a named file with no name is accepted', c and c['requirements'][0]['path'] == '/h/p/a.md')
    c, why = T.validate_code_path({'goal_type': 'exists', 'name': 'secret.key'}, g)
    check('an invented name is rejected', c is None and 'verbatim' in why)
    c, _ = T.validate_code_path({'goal_type': 'list', 'name': ''}, 'What is in /h/p/trip?')
    check('a listing of the one path', c and c['requirements'] == [{'capability': 'file.list', 'path': '/h/p/trip'}])
    c, why = T.validate_code_path({'goal_type': 'read', 'path': '/h/p', 'name': ''}, g)
    check('the old shape is not accepted in code-path mode', c is None)
    check('the code-path schema has no path field', 'path' not in T.CODE_PATH_SCHEMA['properties'])


async def test_typed_code_path_flag_reaches_the_call():
    await m14.setup()
    calls = []

    async def fake(db, messages, schema, **kwargs):
        calls.append(schema)
        return json.dumps({'goal_type': 'read', 'name': 'minutes.md'}), {}
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        (Path(d) / 'minutes.md').write_text('Friday.')
        env = {'ARIES_COMPLETION_TYPED_CONTRACT': '1', 'ARIES_TYPED_CONTRACT_CODE_PATH': '1',
               'ARIES_COMPLETION_READ_PARAPHRASE': '0'}
        with patch.dict(os.environ, env), patch('aries.intelligence.structured', side_effect=fake):
            result = await m14.run_goal(f'Could you look at minutes.md for me? It is somewhere in {d}, I think.',
                                        [m14.execute('file.read', path=f'{d}/minutes.md'), m14.finish])
    contract = result['agent']['contract']
    check('the call used the code-path schema', calls and 'path' not in calls[0]['properties'])
    check('the contract is the file in the folder', contract.get('requirements') ==
          [{'capability': 'file.read', 'path': f'{d}/minutes.md'}])
    check('the verified read ends done', result['state'] == 'done')


def cands(*names, mtimes=None):
    return [{'path': f'/h/p/{n}', 'name': n, 'mtime': (mtimes or [0] * len(names))[i], 'size': 0}
            for i, n in enumerate(names)]


def test_code_select():
    pair = cands('budget-report.txt', 'travel-report.txt')
    picked = R.code_select('Read me the budget report in /h/p.', '/h/p', pair)
    check('a word only one candidate has selects it', picked and picked[0]['name'] == 'budget-report.txt'
          and picked[1] == 'budget')
    check('a word both have selects nothing', R.code_select('Read me the report in /h/p.', '/h/p', pair) is None)
    by_type = cands('notes.md', 'notes.pdf')
    check('a type word selects by extension', R.code_select('Open the notes pdf in /h/p.', '/h/p', by_type)[0]['name'] == 'notes.pdf')
    dated = cands('report-a.txt', 'report-b.txt', mtimes=[1, 2])
    check('an order word selects on the observed mtime',
          R.code_select('Read the latest report in /h/p.', '/h/p', dated)[0]['name'] == 'report-b.txt')
    check('two words pointing at two candidates select nothing',
          R.code_select('Read the budget and the travel report in /h/p.', '/h/p', pair) is None)
    check('a folder word is not evidence', R.code_select('Read the budget report in /h/budget.', '/h/budget',
          cands('budget-a.txt', 'budget-b.txt')) is None)


async def run(goal, sequence, env):
    calls = []

    async def fake(db, messages, schema, **kwargs):
        calls.append(kwargs.get('purpose'))
        return json.dumps({'decision': 'ask', 'selected_index': -1, 'evidence_span': ''}), {}
    with patch.dict(os.environ, env), patch('aries.intelligence.structured', side_effect=fake):
        result = await m14.run_goal(goal, sequence)
    return result, calls


async def test_code_select_in_the_loop():
    env = {'ARIES_CLARIFY_RESOLVER': '1', 'ARIES_RESOLVER_CODE_SELECT': '1'}
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        a, b = Path(d) / 'budget-report.txt', Path(d) / 'travel-report.txt'
        a.write_text('A'); b.write_text('B')
        result, calls = await run(f'Read me the budget report in {d}.',
                                  [m14.execute('file.read', path=str(a)), m14.finish], env)
        state = result['agent']['resolver']
        check('unambiguous twin: selected in code, no resolver call',
              state.get('selected') == str(a) and 'workspace.clarify-resolver' not in calls)
        check('the planner continues instead of asking', result['state'] != 'needs_clarification')
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        (Path(d) / 'budget-report.txt').write_text('A'); (Path(d) / 'travel-report.txt').write_text('B')
        result, calls = await run(f'Read me the report in {d}.', [m14.finish], env)
        check('ambiguous twin: asks from the template, no resolver call',
              result['state'] == 'needs_clarification' and 'workspace.clarify-resolver' not in calls)
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        (Path(d) / 'budget-report.txt').write_text('A'); (Path(d) / 'travel-report.txt').write_text('B')
        result, calls = await run(f'Read me the budget report in {d}.', [m14.finish],
                                  {'ARIES_CLARIFY_RESOLVER': '1', 'ARIES_RESOLVER_CODE_SELECT': '0'})
        check('flag off: the decision call runs and its ask stands (the H4b behaviour)',
              'workspace.clarify-resolver' in calls and result['state'] == 'needs_clarification')


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
