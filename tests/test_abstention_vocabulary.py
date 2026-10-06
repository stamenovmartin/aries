"""The decision vocabulary must be able to say "ask" and "I cannot".

Measured on 2026-10-03 over `experiments/router-ood/fixture.jsonl`, 225 utterances
in four classes: confidence separated "can act" from "must not act" with **AUC
0.642**. The best accuracy any threshold could reach was **60.9%**, against
**55.6%** for a system that simply never acts — the whole signal was worth five
points. The cause was not the model. With fourteen intents and no way to answer
"none of these", a classifier must choose a wrong one, and it did at confidence
1.00: `'јави се на Марија'` as SEND_EMAIL on a machine with no telephony,
`'испечати го овој документ'` as READ_EMAIL with no printer.

So these tests are about a vocabulary, not about accuracy: they fail if the two
words disappear, if the prompt goes back to demanding a guess, or if an abstention
can carry a tool.
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-abstention-vocabulary')
from agentic_core.database.base import async_session
from aries.intelligence import router
from aries.intelligence.schemas import Decision, Intent
from aries.intelligence.router import route, learn_verified
from typing import get_args


async def test_the_two_words_exist_and_validate():
    values = get_args(Intent)
    check('ASK is part of the vocabulary', 'ASK' in values)
    check('OUT_OF_SCOPE is part of the vocabulary', 'OUT_OF_SCOPE' in values)
    check('nothing was removed to make room',
          {'OPEN_APP', 'OPEN_URL', 'SEARCH_WEB', 'READ_EMAIL', 'SEND_EMAIL', 'CALENDAR_ACTION',
           'SYSTEM_ACTION', 'RESEARCH', 'CODING', 'CLASSIFY', 'EXTRACT', 'AUTOMATION',
           'FILE_ACTION', 'UNKNOWN'} <= set(values))
    d = Decision(intent='OUT_OF_SCOPE', tool='none', confidence=0.9,
                 reason='This machine has no telephony')
    check('an abstention validates and carries no tool', d.intent == 'OUT_OF_SCOPE' and d.tool == 'none')
    schema = Decision.model_json_schema()
    enum = schema['properties']['intent'].get('enum') or []
    check('grammar-constrained decoding can emit them',
          'ASK' in enum and 'OUT_OF_SCOPE' in enum)


async def test_the_prompt_demands_a_guess_only_when_abstention_is_switched_off():
    """Checked on the assembled instruction, not on the source text. The guess line
    still EXISTS in the module — it is the flag-off branch, which Part B needs in order
    to compare the two behaviours on one fixture rather than across a git checkout. What
    must hold is that the default does not contain it."""
    provider = router.LocalLLMDecisionProvider()
    previous = os.environ.get('ARIES_ROUTER_ABSTAIN')
    try:
        os.environ.pop('ARIES_ROUTER_ABSTAIN', None)
        default = provider.instruction()
        check('by default the model is not told to pick an intent regardless',
              'Select the most specific intent even when no executable tool is available' not in default)
        check('by default abstention is defined for it',
              'OUT_OF_SCOPE' in default and 'ASK the request names an action' in default)
        check('and tool=none is required with it', 'tool=none' in default)
        check('the default also states what this machine can and cannot do',
              'This machine can do the following' in default and 'measured limits of THIS machine' in default)
        os.environ['ARIES_ROUTER_ABSTAIN'] = '0'
        without = provider.instruction()
        check('switched off, it is the behaviour that shipped before 2026-10-03',
              'Select the most specific intent even when no executable tool is available' in without)
        check('switched off, abstention is not offered at all', 'OUT_OF_SCOPE' not in without)
        check('switching it off makes the prompt shorter, not merely different',
              len(without) < len(default))
    finally:
        if previous is None:
            os.environ.pop('ARIES_ROUTER_ABSTAIN', None)
        else:
            os.environ['ARIES_ROUTER_ABSTAIN'] = previous


async def test_an_abstention_routes_without_becoming_executable():
    await reset_db()

    class Abstains:
        def __init__(self, intent):
            self.intent = intent
        async def decide(self, db, text):
            return Decision(intent=self.intent, tool='none', confidence=0.95,
                            reason='Nothing here can carry this out')

    async with async_session() as db:
        for intent in ('ASK', 'OUT_OF_SCOPE'):
            r = await route(db, f'please do the {intent} thing', provider=Abstains(intent))
            check(f'{intent} survives routing intact', r.intent == intent)
            check(f'{intent} names no tool', r.tool == 'none')
            check(f'{intent} is not escalated for being unusual',
                  r.execution_level in ('local', 'cloud'))
            # learn_verified takes a mapping, and only caches CLASSIFY / EXTRACT /
            # SYSTEM_ACTION — so an abstention can never become a cached rule that
            # silences a later, better-specified request with the same wording.
            check(f'{intent} is never learned as a verified rule',
                  not await learn_verified(db, f'{intent} text',
                                           Decision(intent=intent, tool='none', confidence=1.0,
                                                    reason='x').model_dump(), verified=True))


async def test_deterministic_requests_are_untouched_by_the_change():
    """The rule layer runs first and must still answer without a model at all."""
    await reset_db()
    async with async_session() as db:
        with patch('aries.intelligence.router.LocalLLMDecisionProvider.decide',
                   AsyncMock(side_effect=AssertionError('LLM called'))) as model:
            for goal, intent in (('open YouTube', 'OPEN_URL'), ('show system status', 'SYSTEM_ACTION'),
                                 ('open Downloads', 'FILE_ACTION')):
                r = await route(db, goal)
                check(f'{goal} still decided by rule as {intent}',
                      r.execution_level == 'code' and r.intent == intent)
            check('and still without any model call', model.await_count == 0)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
