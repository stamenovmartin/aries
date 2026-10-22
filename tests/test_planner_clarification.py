"""The planner may ask which observed target is meant, and only about observed targets.

Motivated by the independent acceptance run of 2026-10-06: 0 of 5 ambiguous-target
goals produced a question, because the planner's only verbs were execute, finish,
fail and ask_approval. Every case failed safely (nothing changed), but none asked.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_agent_execution as m14
from tests._bootstrap import check, run_module
from aries.workspace import agent_planner
from aries.workspace.clarification import grounded_choices


def ask(*choices, question='Which notes file do you mean?'):
    return {'action': 'ask_clarification', 'question': question, 'choices': list(choices),
            'reason': 'Two observed files fit the goal'}


def rejected(payload):
    try:
        agent_planner.Decision.model_validate(payload)
    except Exception:
        return True
    return False


def test_decision_shape():
    check('valid question accepted', not rejected(ask('/a/one.md', '/a/two.md')))
    check('one choice rejected', rejected(ask('/a/one.md')))
    check('six choices rejected', rejected(ask(*[f'/a/{i}.md' for i in range(6)])))
    check('duplicate choices rejected', rejected(ask('/a/one.md', '/A/ONE.md')))
    check('empty question rejected', rejected(ask('/a/one.md', '/a/two.md', question='  ')))
    check('question cannot carry a capability',
          rejected({**ask('/a/one.md', '/a/two.md'), 'capability': 'file.read', 'arguments': {'path': '/a/one.md'}}))
    check('execute cannot carry a question',
          rejected({'action': 'execute', 'capability': 'system.status', 'arguments': {}, 'question': 'which?'}))


def test_grammar_unchanged_when_not_offered():
    off = agent_planner.generation_schema(allow_finish=True, allow_fail=True)
    on = agent_planner.generation_schema(allow_finish=True, allow_fail=True, allow_ask=True)
    check('option absent when not offered', 'ask_clarification' not in off['properties']['action']['enum']
          and 'question' not in off['properties'] and 'choices' not in off['properties'])
    check('option present when offered', 'ask_clarification' in on['properties']['action']['enum']
          and on['properties']['choices']['type'] == 'array')
    check('offered strings stay grammar-bounded',
          on['properties']['question'].get('maxLength') and on['properties']['choices']['items'].get('maxLength'))


def test_grounding_rule():
    steps = [{'verification_status': 'verified', 'execution_result': {'path': '/h/p', 'entries': [
        {'name': 'notes-a.md', 'path': '/h/p/notes-a.md'}, {'name': 'notes-b.md', 'path': '/h/p/notes-b.md'}]}}]
    check('observed paths accepted', grounded_choices(['/h/p/notes-a.md', '/h/p/notes-b.md'], steps)[0])
    check('observed names plus one free choice accepted', grounded_choices(['notes-a.md', 'notes-b.md', 'Cancel'], steps)[0])
    check('invented files under a listed folder rejected', not grounded_choices(['/h/p/x.md', '/h/p/y.md'], steps)[0])
    check('two free choices rejected', not grounded_choices(['notes-a.md', 'notes-b.md', 'x', 'y'], steps)[0])
    typed = [{'verification_status': 'verified', 'execution_result': {'path': '/h/p', 'entries': [
        {'name': 'notes-a.md', 'path': '/h/p/notes-a.md', 'type': 'file'},
        {'name': 'notes-b.md', 'path': '/h/p/notes-b.md', 'type': 'file'}], 'summary': 'Listed directory entries'}}]
    check('field values and free text do not ground a choice',
          not grounded_choices(['some other file', 'a different file', 'notes-a.md'], typed)[0]
          and not grounded_choices(['Listed directory entries', 'notes-a.md'], typed)[0])
    unverified = [{**steps[0], 'verification_status': 'failed'}]
    check('unverified observation does not ground a question', not grounded_choices(['notes-a.md', 'notes-b.md'], unverified)[0])


async def test_ambiguous_goal_asks_and_touches_nothing():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        a, b = Path(directory) / 'thesis-notes.md', Path(directory) / 'thesis-notes-old.md'
        a.write_text('A'); b.write_text('B')
        before = {p: p.stat().st_mtime_ns for p in (a, b)}
        result = await m14.run_goal(f'Read me the thesis notes in {directory}.',
                                    [m14.execute('file.list', path=directory), ask(str(a), str(b))])
        check('goal stops as a question', result['state'] == 'needs_clarification')
        clarification = result.get('clarification') or {}
        check('structured question with observed choices',
              isinstance(clarification.get('question'), str) and sorted(clarification.get('choices', [])) == sorted([str(a), str(b)]))
        check('no candidate was read', [s['capability'] for s in result['steps']] == ['file.list'])
        check('files untouched', {p: p.stat().st_mtime_ns for p in (a, b)} == before)
        check('not reported as finished', result['agent'].get('finished') is False)


async def test_invented_choices_are_rejected_then_bounded():
    await m14.setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        (Path(directory) / 'one.md').write_text('1')
        result = await m14.run_goal(f'Read me the notes in {directory}.', [
            m14.execute('file.list', path=directory),
            ask(f'{directory}/invented-a.md', f'{directory}/invented-b.md'),
            {'action': 'fail', 'summary': 'stopped'}])
        check('ungrounded question does not become the answer', result['state'] != 'needs_clarification')
        check('rejection is counted', result['agent']['metrics'].get('ungrounded_clarifications') == 1)


async def test_question_before_any_observation_is_rejected():
    await m14.setup()
    result = await m14.run_goal('Show system status', [ask('/x/a', '/x/b'), m14.execute('system.status'),
                                                        {'action': 'fail', 'summary': 'stopped'}])
    check('no question without an observation', result['state'] != 'needs_clarification')


async def test_flag_off_rejects_the_option():
    await m14.setup()
    with patch.dict(os.environ, {'ARIES_PLANNER_CLARIFY': '0'}), \
            tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        a, b = Path(directory) / 'a.md', Path(directory) / 'b.md'
        a.write_text('A'); b.write_text('B')
        result = await m14.run_goal(f'Read me the notes in {directory}.', [
            m14.execute('file.list', path=directory), ask(str(a), str(b)), {'action': 'fail', 'summary': 'stopped'}])
        check('flag off: no planner question', result['state'] != 'needs_clarification')
        check('flag off: option not offered to the model',
              not agent_planner.clarification_offered({'steps': [{'verification_status': 'verified'}]}))


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
