"""ARIES_PLANNER_CLARIFY_GUARD: a question is only for choosing between observed targets.

Motivated by the 2026-10-12 follow-up planner test: on three unambiguous browser.read
goals the model chose ask_clarification as a request for confirmation and attached
capability arguments, 9 of 9 attempts, all rejected by Decision.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-clarify-guard')
from aries.workspace import agent_planner

GUARD = 'ARIES_PLANNER_CLARIFY_GUARD'


def test_flag_off_grammar_is_unchanged():
    plain = agent_planner.generation_schema(allow_finish=True, allow_fail=True, allow_ask=True)
    unguarded = agent_planner.generation_schema(allow_finish=True, allow_fail=True, allow_ask=True, guard=False)
    check('guard off: grammar byte-identical to the unguarded one', json.dumps(plain) == json.dumps(unguarded))
    not_offered = agent_planner.generation_schema(allow_finish=True, allow_fail=True, allow_ask=False, guard=True)
    check('guard has no effect when asking is not offered',
          json.dumps(not_offered) == json.dumps(agent_planner.generation_schema(allow_finish=True, allow_fail=True)))


def test_guarded_grammar_separates_asking_from_acting():
    s = agent_planner.generation_schema(allow_finish=True, allow_fail=True, allow_ask=True, guard=True)
    act, ask = s['anyOf']
    check('acting shape cannot ask', 'ask_clarification' not in act['properties']['action']['enum']
          and 'question' not in act['properties'] and 'choices' not in act['properties'])
    check('asking shape cannot carry capability or arguments',
          ask['properties']['action']['enum'] == ['ask_clarification'] and 'capability' not in ask['properties']
          and 'arguments' not in ask['properties'] and ask['additionalProperties'] is False)
    check('asking shape requires question and choices', set(ask['required']) == {'action', 'question', 'choices'})
    check('ask_approval stays available for confirmation', 'ask_approval' in act['properties']['action']['enum'])
    check('every string in the asking shape stays grammar-bounded',
          ask['properties']['question']['maxLength'] and ask['properties']['choices']['items']['maxLength']
          and ask['properties']['reason']['maxLength'])
    only_acting = agent_planner.generation_schema(allow_finish=False, allow_fail=False, allow_ask=True, guard=True)
    check('capability still mandatory when only acting verbs are left', 'capability' in only_acting['anyOf'][0]['required'])


def test_listed_but_unread_rule():
    listed = {'steps': [{'capability': 'file.list', 'args': {'path': '/h/p'}, 'verification_status': 'verified'}]}
    check('a listed, unread goal folder gets the decision step', agent_planner.listed_but_unread('Read me the notes in /h/p.', listed) == ['/h/p'])
    sub = {'steps': listed['steps'] + [{'capability': 'file.list', 'args': {'path': '/h/p/a'}, 'verification_status': 'verified'}]}
    check('the latest listing inside the folder is named', agent_planner.listed_but_unread('Read me the notes in /h/p.', sub) == ['/h/p/a'])
    done = {'steps': listed['steps'] + [{'capability': 'file.read', 'args': {'path': '/h/p/x.md'}, 'verification_status': 'verified'}]}
    check('once something inside was read, no decision step', agent_planner.listed_but_unread('Read me the notes in /h/p.', done) == [])
    check('a goal naming an exact file gets no decision step', agent_planner.listed_but_unread('Read /h/p/x.md.', listed) == [])


def test_unlisted_folder_rule():
    data = {'steps': []}
    check('folder without a file is flagged', agent_planner.unlisted_folders('Read me the notes in /h/p.', data) == ['/h/p'])
    check('a named file is not flagged', agent_planner.unlisted_folders('Read /h/p/a.md.', data) == [])
    check('no path, no hint', agent_planner.unlisted_folders('Read me my notes.', data) == [])
    listed = {'steps': [{'capability': 'file.list', 'args': {'path': '/h/p'}, 'verification_status': 'verified'}]}
    check('a verified listing ends the hint', agent_planner.unlisted_folders('Read me the notes in /h/p.', listed) == [])
    failed = {'steps': [{'capability': 'file.list', 'args': {'path': '/h/p'}, 'verification_status': 'verification_failed'}]}
    check('an unverified listing does not', agent_planner.unlisted_folders('Read me the notes in /h/p.', failed) == ['/h/p'])


async def test_prompt_text_only_with_the_flag():
    from agentic_core.database.base import async_session
    await reset_db()
    captured = {}

    async def fake(db, messages, schema, **kwargs):
        captured['messages'], captured['schema'] = messages, schema
        return json.dumps({'action': 'execute', 'capability': 'file.list', 'arguments': {'path': '/h/p'}}), {}

    data = {'steps': [{'step_id': 's1', 'capability': 'file.list', 'args': {'path': '/h/q'}, 'verification_status': 'verified',
                       'execution_result': {'path': '/h/q', 'entries': []}, 'observation': {}, 'evidence_refs': []}],
            'evidence': [{'evidence_id': 'e1', 'verified': True}],
            'agent': {'contract': {'supported': False, 'requirements': []}, 'request': 'x', 'decisions': [],
                      'metrics': {}, 'context': {}, 'environment': {}}}
    seen = {}
    for value in ('0', '1'):
        captured.clear()
        with patch.dict(os.environ, {GUARD: value, 'ARIES_PLANNER_CLARIFY': '1'}), \
                patch('aries.intelligence.structured', side_effect=fake):
            async with async_session() as db:
                await agent_planner.plan(db, 'Read me the notes in /h/p.', json.loads(json.dumps(data)), 8)
        text = json.dumps(captured.get('messages', []))
        seen[value] = ('only for choosing between targets' in text and 'use ask_approval' in text,
                       'List that folder with file.list' in text, 'anyOf' in captured.get('schema', {}))
    check('guard off: no guard text and single-object grammar', seen['0'] == (False, False, False))
    check('guard on: confirmation/choice text, list-first hint and two-shape grammar', seen['1'] == (True, True, True))


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
