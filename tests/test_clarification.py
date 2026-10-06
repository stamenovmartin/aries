"""Missing-target goals ask before any executor or planner is called."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests import test_workspace as harness
from tests._bootstrap import check,run_module
from aries.workspace import capabilities, service
from aries.workspace.clarification import question
from aries.speech.replies import sentence

async def test_missing_target_queue_and_speech():
    await harness.setup()
    requests=['пушти нешто','play something','премести го таму','move it there','отвори го','open it','среди го','fix it']
    for request in requests:
        executor=AsyncMock(side_effect=AssertionError('No execution authorized by missing target'))
        with patch.object(capabilities,'execute',executor),patch.object(service,'plan',side_effect=AssertionError('No guessed plan')):
            goal=await harness.run(request)
        check('durable question: '+request,goal['state']=='needs_clarification' and len(goal['clarification']['choices'])>=2)
        check('no action: '+request,goal['steps']==[] and executor.await_count==0)
        check('spoken question: '+request,sentence(goal)==goal['clarification']['question'])


def test_named_requests_are_not_captured():
    for request in ['play music Bohemian Rhapsody','пушти музика Лозано','open Firefox',
                    'read file ~/Documents/a.txt','play something by Mozart',
                    'move file /tmp/a to /tmp/b','fix it and delete everything',
                    'say play something','remember I enjoy something']:
        check('not consumed: '+request,question(request) is None)


async def test_unique_verified_reference_still_resolves():
    await harness.setup()
    reference={'original':'open it','resolved':{'value':'/owned/example.txt'}}
    with patch('aries.workspace.working_context.resolve',AsyncMock(return_value=('Read file /owned/example.txt',reference))):
        goal=await harness.submit('open it')
    check('verified reference not replaced by generic question',goal['state']=='queued' and goal['working_reference']==reference)


async def test_shell_envelope_does_not_claim_a_question_is_queued():
    import httpx
    await harness.setup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=harness.app),base_url='http://test') as client:
        response=await client.post('/api/aries/shell/act',json={'kind':'workspace','text':'play something','source':'voice'})
        data=response.json()
        check('voice API returns actual question',response.status_code==200 and data['message']==data['result']['clarification']['question'])
        check('voice API dispatches no action',data['result']['steps']==[])

async def test_declined_pronouns_do_not_reach_a_guessing_planner():
    await harness.setup()
    requests=['read file it','read file that one','read file this file','read file both',
              'прочитај ми го','прочитај ги','прочитај таа датотека','прочитај тоа',
              'инсталирај го','install it','избриши го','open both','пушти ја другата']
    for request in requests:
        with patch.object(service,'plan',side_effect=AssertionError('Missing reference reached planner')):
            goal=await harness.submit(request)
        check('clarification before planning: '+request,goal['state']=='needs_clarification' and goal['steps']==[])
        check('question has choices: '+request,len(goal['clarification']['choices'])>=2)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
