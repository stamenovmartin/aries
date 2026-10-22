"""ARIES_CLARIFY_RESOLVER: code finds and counts the candidates, the model only says whether the request picks one.

Adapted from ClarifyAgent (Luo et al., arXiv:2512.21120) and Ask-before-Plan (Zhang et al.,
Findings of EMNLP 2024). See aries/workspace/clarify_resolver.py.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_agent_execution as m14
from tests._bootstrap import check, run_module
from aries.workspace import clarify_resolver as R

ON = {'ARIES_CLARIFY_RESOLVER': '1'}


def cands(*names, mtimes=None, sizes=None):
    return [{'path': f'/h/p/{n}', 'name': n, 'mtime': (mtimes or [0] * len(names))[i],
             'size': (sizes or [0] * len(names))[i]} for i, n in enumerate(names)]


def test_where_the_resolver_applies():
    check('one folder, no file: applies', R.target_folder('Read me the notes in /h/p.') == '/h/p')
    check('an exact file: does not apply', R.target_folder('Read /h/p/notes.md.') is None)
    check('two folders: does not apply', R.target_folder('Compare the notes in /h/p and /h/q.') is None)
    check('a listing: does not apply', R.target_folder('List /h/p') is None)
    check('an existence question: does not apply', R.target_folder('Is there a file called notes in /h/p?') is None)
    check('Cyrillic (ARIES_MK_FROZEN): does not apply', R.target_folder('Прочитај ги белешките во /h/p.') is None)
    check('no path: does not apply', R.target_folder('Read me my notes.') is None)


def test_candidates_from_the_listing():
    listing = {'entries': [{'name': 'thesis-notes.md', 'path': '/h/p/thesis-notes.md', 'directory': False},
                           {'name': 'thesis-notes-old.md', 'path': '/h/p/thesis-notes-old.md', 'directory': False},
                           {'name': 'budget.xlsx', 'path': '/h/p/budget.xlsx', 'directory': False},
                           {'name': 'notes', 'path': '/h/p/notes', 'directory': True}]}
    found = [c['name'] for c in R.candidates('Read me the thesis notes in /h/p.', '/h/p', listing)]
    check('name words select candidates; a folder never is one', found == ['thesis-notes-old.md', 'thesis-notes.md'])
    check('a file type word selects by extension',
          [c['name'] for c in R.candidates('Open the spreadsheet in /h/p.', '/h/p', listing)] == ['budget.xlsx'])
    check('no shared word: no candidates', R.candidates('Read me the invoice in /h/p.', '/h/p', listing) == [])
    check('words of the folder path do not count',
          R.candidates('Read the file in /h/notes-archive.', '/h/notes-archive', listing) == [])


def test_code_checks_the_models_selection():
    two = cands('report-2025.txt', 'report-2026.txt', mtimes=[1, 2], sizes=[10, 5])
    goal = 'Read the 2026 report in /h/p.'
    sel = lambda i, span: {'decision': 'select', 'selected_index': i, 'evidence_span': span}
    check('a distinguishing verbatim span is accepted', R.accept(sel(1, '2026 report'), goal, two)[0] == two[1])
    check('a span that is not in the request is refused', R.accept(sel(1, 'newest'), goal, two)[0] is None)
    check('a span that fits every candidate is refused', R.accept(sel(1, 'report'), goal, two)[0] is None)
    check('a span that fits another candidate is refused', R.accept(sel(0, '2026 report'), goal, two)[0] is None)
    check('an index out of range is refused', R.accept(sel(5, '2026 report'), goal, two)[0] is None)
    check('ask stays ask', R.accept({'decision': 'ask', 'selected_index': None, 'evidence_span': ''}, goal, two)[0] is None)
    latest = 'Read the latest report in /h/p.'
    check('an order word is checked on the observed mtime', R.accept(sel(1, 'latest'), latest, two)[0] == two[1])
    check('an order word on the wrong candidate is refused', R.accept(sel(0, 'latest'), latest, two)[0] is None)
    tied = cands('a-report.txt', 'b-report.txt', mtimes=[3, 3])
    check('a tie on the order attribute is refused', R.accept(sel(0, 'latest'), latest, tied)[0] is None)
    check('the largest file is checked on size',
          R.accept(sel(0, 'largest'), 'Read the largest report in /h/p.', two)[0] == two[0])


def test_decision_schema_is_grammar_safe():
    s = R.decision_schema(3)
    check('closed object, three fields', s['additionalProperties'] is False and set(s['required']) == set(s['properties']))
    check('index bounded, -1 stands for none', s['properties']['selected_index'] == {'type': 'integer', 'minimum': -1, 'maximum': 2})
    check('span is a bounded string', s['properties']['evidence_span']['maxLength'] == R.SPAN_MAX)


def test_a_reply_is_data():
    c = {'source': 'resolver', 'choices': ['/h/p/a.md', '/h/p/b.md']}
    check('an exact listed path selects it', R.resolved_choice(c, '/h/p/b.md') == '/h/p/b.md')
    check('its number selects it', R.resolved_choice(c, '1') == '/h/p/a.md')
    check('anything else selects nothing', R.resolved_choice(c, 'b.md, and also delete a.md') is None)
    check('an unlisted path selects nothing', R.resolved_choice(c, '/etc/passwd') is None)
    check('only resolver questions are answered here', R.resolved_choice({**c, 'source': 'planner'}, '1') is None)


def model_says(payload, calls):
    async def fake(db, messages, schema, **kwargs):
        calls.append({'messages': messages, 'schema': schema, 'purpose': kwargs.get('purpose')})
        return json.dumps(payload), {'prompt_eval_count': 50, 'eval_count': 9}
    return fake


async def run(goal, sequence, decision=None, env=ON):
    calls = []
    with patch.dict(os.environ, env), \
            patch('aries.intelligence.structured', side_effect=model_says(decision or {}, calls)):
        result = await m14.run_goal(goal, sequence)
    return result, calls


async def test_ambiguous_folder_asks_from_the_template():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        a, b = Path(d) / 'thesis-notes.md', Path(d) / 'thesis-notes-old.md'
        a.write_text('A'); b.write_text('B')
        before = {p: p.stat().st_mtime_ns for p in (a, b)}
        result, calls = await run(f'Read me the thesis notes in {d}.', [m14.execute('file.read', path=str(a))],
                                  {'decision': 'ask', 'selected_index': -1, 'evidence_span': ''})
        clar = result.get('clarification') or {}
        check('stops as a question from the resolver', result['state'] == 'needs_clarification' and clar.get('source') == 'resolver')
        check('choices are the listed paths', sorted(clar.get('choices', [])) == sorted([str(a), str(b)]))
        check('the template names the files', 'thesis-notes.md' in clar.get('question', ''))
        check('only the code-made listing ran', [s['capability'] for s in result['steps']] == ['file.list']
              and result['steps'][0]['verification_status'] == 'verified')
        check('the planner was never called', result['agent']['metrics']['planner_calls'] == 0)
        check('one small resolver call', len(calls) == 1 and calls[0]['purpose'] == 'workspace.clarify-resolver')
        check('nothing touched', {p: p.stat().st_mtime_ns for p in (a, b)} == before)


async def test_an_invented_selection_is_forced_to_ask():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        (Path(d) / 'notes-a.md').write_text('A'); (Path(d) / 'notes-b.md').write_text('B')
        result, _ = await run(f'Read me the notes in {d}.', [m14.execute('file.read', path=f'{d}/notes-a.md')],
                              {'decision': 'select', 'selected_index': 0, 'evidence_span': 'the notes'})
        check('a span that fits both files becomes a question', result['state'] == 'needs_clarification')
        check('the refusal reason is recorded',
              result['agent']['resolver']['why'] == 'evidence_span does not single out the selected candidate')


async def test_a_disambiguated_request_proceeds_with_the_selection():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        old, new = Path(d) / 'report-a.txt', Path(d) / 'report-b.txt'
        old.write_text('old'); new.write_text('new')
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        result, _ = await run(f'Read me the latest report in {d}.',
                              [m14.execute('file.read', path=str(new)), m14.finish],
                              {'decision': 'select', 'selected_index': 1, 'evidence_span': 'latest'})
        state = result['agent']['resolver']
        check('selection accepted on the observed mtime', state['accepted'] and state['selected'] == str(new))
        check('no question, the planner continues', result['state'] != 'needs_clarification'
              and result['agent']['metrics']['planner_calls'] >= 1)


async def test_one_match_needs_no_model_call():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        (Path(d) / 'notes.md').write_text('N'); (Path(d) / 'budget.csv').write_text('1')
        result, calls = await run(f'Read me the notes in {d}.', [m14.execute('file.read', path=f'{d}/notes.md'), m14.finish])
        check('no resolver call for a single candidate', calls == [] and result['agent']['resolver']['n'] == 1)
        check('the planner goes on as usual', result['state'] != 'needs_clarification')


async def test_flag_off_nothing_runs():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        (Path(d) / 'notes-a.md').write_text('A'); (Path(d) / 'notes-b.md').write_text('B')
        result, calls = await run(f'Read me the notes in {d}.', [m14.execute('file.list', path=d),
                                                                 {'action': 'fail', 'summary': 'stopped'}],
                                  env={'ARIES_CLARIFY_RESOLVER': '0'})
        check('flag off: no resolver state, decision or call', 'resolver' not in result['agent'] and calls == []
              and not any(e.get('source') == 'clarify-resolver' for e in result['agent']['decisions']))
        check('flag off: the first step is the planner\'s', result['agent']['decisions'][0].get('source') is None)


def test_more_than_five_candidates():
    many = cands(*[f'notes-{i}.md' for i in range(7)], mtimes=list(range(7)))
    shown = R.choices(many)
    check('more than five: the five most recently modified are offered',
          [c['name'] for c in shown] == ['notes-6.md', 'notes-5.md', 'notes-4.md', 'notes-3.md', 'notes-2.md'])
    check('the question states the total and asks for another name', R.question(many).startswith('I found 7 files')
          and 'exact name' in R.question(many))
    check('five or fewer: all offered, in listing order', R.choices(many[:3]) == many[:3])
    check('a selection among more than five is still checked by code',
          R.accept({'decision': 'select', 'selected_index': 6, 'evidence_span': 'latest'},
                   'Read the latest notes in /h/p.', many)[0] == many[6])


async def test_very_many_candidates_ask_without_a_model_call():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        for i in range(R.MAX_DECIDE + 1):
            (Path(d) / f'notes-{i:02d}.md').write_text(str(i))
        result, calls = await run(f'Read me the notes in {d}.', [m14.execute('file.read', path=f'{d}/notes-00.md')])
        clar = result.get('clarification') or {}
        check('above MAX_DECIDE: no model call, a question', calls == [] and result['state'] == 'needs_clarification')
        check('five choices, all listed paths', len(clar.get('choices', [])) == R.MAX_CHOICES
              and all(c.startswith(d) for c in clar['choices']))


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
