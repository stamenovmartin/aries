"""Goal planning never turns repeated or premature model claims into actions."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-goal-planner')
from aries.workspace.planner import next_step, allowed, verified_navigation


async def test_repeat_gets_one_correction_without_reexecution():
    args={'session':'observed-id','label':'Documentation'}
    completed=[{'capability':'browser_follow','args':args,'state':'done',
                'result':{'browser':{'url':'https://www.python.org/doc/','title':'Our Documentation | Python.org'},'summary':'Observed destination'}}]
    repeat=json.dumps({'capability':'browser_follow','arguments':args,'reason':'Follow documentation'})
    finish=json.dumps({'capability':'finish','arguments':{},'reason':'The final page is Our Documentation | Python.org.'})
    with patch('aries.workspace.reviews.relevant', AsyncMock(return_value=[])), patch('aries.learning.feedback.implementation_notes', AsyncMock(return_value=[])), patch('aries.learning.feedback.standing_rules', AsyncMock(return_value=[])), patch('aries.intelligence.local_structured',AsyncMock(side_effect=[(repeat,{'eval_count':4}),(finish,{'eval_count':6})])) as generate:
        step,summary,usage=await next_step(None,'Open Python documentation and report its title',completed)
    check('repeat is corrected without emitting another executable step',step is None and generate.call_count==2)
    check('both model calls contribute measured usage',usage['eval_count']==10 and usage['planning_attempts']==2)
    check('final summary uses the observed title','Our Documentation' in summary)


async def test_premature_finish_is_refused():
    reply=json.dumps({'capability':'finish','arguments':{},'reason':'Done'})
    with patch('aries.workspace.reviews.relevant', AsyncMock(return_value=[])), patch('aries.learning.feedback.implementation_notes', AsyncMock(return_value=[])), patch('aries.learning.feedback.standing_rules', AsyncMock(return_value=[])), patch('aries.intelligence.local_structured',AsyncMock(return_value=(reply,{}))):
        try:
            await next_step(None,'Open Python documentation',[])
        except ValueError:
            check('a model cannot complete a goal without tool evidence',True)
        else:
            check('a model cannot complete a goal without tool evidence',False)


def test_installed_is_not_an_install_request():
    check('intent matching uses complete words','install_app' not in allowed('Show installed applications'))
    check('explicit installation still uses its guarded capability','install_app' in allowed('Install VLC'))


async def test_navigation_contract_finishes_from_evidence_without_more_actions():
    request='Open https://www.python.org, follow the Documentation link, and report the final page title.'
    steps=[{'capability':'browser_open','args':{'url':'https://www.python.org'},'state':'done','result':{'browser':{'session':'s','url':'https://www.python.org/','title':'Python'}}},
           {'capability':'browser_follow','args':{'session':'s','label':'Documentation'},'state':'done','result':{'browser':{'session':'s','url':'https://www.python.org/doc/','title':'Our Documentation'}}}]
    with patch('aries.workspace.reviews.relevant', AsyncMock(return_value=[])), patch('aries.learning.feedback.implementation_notes', AsyncMock(return_value=[])), patch('aries.learning.feedback.standing_rules', AsyncMock(return_value=[])), patch('aries.intelligence.local_structured',AsyncMock()) as model:
        step,summary,usage=await next_step(None,request,steps)
    check('verified navigation goal stops without speculative extra browsing',step is None and 'Our Documentation' in summary and not model.called)
    steps[1]['args']['session']='different-session'
    check('completion is bound to the requested browser session',verified_navigation(request,steps) is None)
    check('unrelated additional requirements cannot use the title-only contract',verified_navigation(request+' Then download and install Python.',steps) is None)


if __name__=='__main__':
    sys.exit(run_module(sys.modules[__name__]))
