"""Evidence selection must preserve labels, expiry and honest missing coverage."""
import json
import sys
import time
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,run_module
bootstrap('aries-context-engine')
from aries.workspace.context_engine import Item,select,required_sources,planner_context


async def test_prompt_rechecks_expiry_and_retains_user_preferences():
    packet=select([Item('a','tasks','comet task',expires_at=time.time()+20,relevance=1)],'project comet')
    with patch('aries.workspace.context_engine.time.time',return_value=time.time()+30):
        prompt=planner_context({'preferences':['Use concise replies']},packet)
    check('expired task text cannot survive into a later prompt',prompt['memories']==[])
    check('expired domain becomes missing again','tasks' in prompt['context_coverage']['missing_sources'])
    check('user preferences survive context selection',prompt['preferences']==['Use concise replies'])


async def test_planner_does_not_flatten_source_metadata():
    packet=select([Item('a','memory','project comet deadline',relevance=1)],'project comet',max_chars=2000)
    context=planner_context({'reviews':['large '*2000],'preferences':[]},packet)
    check('planner preserves structured source identity',context['memories'][0]['id']=='a' and 'preview' not in context)
    check('planner envelope fits actual bound',len(json.dumps(context,ensure_ascii=False))<=2500)
    check('oversize historical sections are disclosed','reviews' in context['omitted_sections'])


async def test_prompt_omissions_distinguish_budget_from_absence_and_expiry():
    packet=select([Item('trimmed','memory','comet '*300,relevance=1)],'project comet')
    original=json.dumps(packet,sort_keys=True)
    context=planner_context({},packet,max_chars=700)
    check('oversize record is removed',context['memories']==[])
    check('dropped source and cause are named',context['context_coverage']['omitted_items']==[
        {'id':'trimmed','source':'memory','reason':'budget'}])
    check('coverage reflects actual delivered evidence','memory' in context['context_coverage']['missing_sources'])
    check('audit metadata fits the prompt budget',len(json.dumps(context,ensure_ascii=False))<=700)
    check('saved evidence packet is immutable',json.dumps(packet,sort_keys=True)==original)
    packet['items'][0]['expires_at']=1
    context=planner_context({},packet,max_chars=700)
    check('expired evidence is distinguished from budget removal',
          context['context_coverage']['omitted_items'][0]['reason']=='expired')


async def test_budget_retains_provenance_and_privacy():
    rows=[Item('wanted','memory','Project comet build fails on import',relevance=1.0),
          Item('old','memory','Project comet obsolete decision',expires_at=1.0),
          Item('noise','memory','Recipes for lentil soup'),
          Item('large','files','comet '*5000,relevance=0.8,data_class='file_content')]
    result=select(rows,'Continue project comet',max_chars=600,now=100.0)
    check('relevant source survives within packet budget',[i['id'] for i in result['items']]==['wanted'])
    check('serialized evidence including metadata fits bound',result['context_chars']<=600)
    check('personal class and origin survive selection',result['data_classes']==['personal'] and result['items'][0]['source']=='memory')
    check('expiry irrelevant and oversize exclusions explained',{i['reason'] for i in result['omitted']}=={'expired','irrelevant','budget'})
    check('missing project evidence stays explicit','projects' in result['missing_sources'])
    check('estimated tokens are labelled','estimate' in result['token_method'])


async def test_no_context_is_not_a_claim_about_tomorrow():
    packet=select([],'Prepare me for tomorrow')
    check('calendar tasks messages and projects are required',{'calendar','tasks','messages','projects'}<=set(packet['missing_sources']))
    check('empty set never invents user facts',packet['items']==[])
    check('simple system probe does not require memory',required_sources('show system status')==[])
    rows=[Item('a','memory','comet deadline'),Item('a','memory','comet changed deadline'),
          Item('b','memory','comet deadline')]
    packet=select(rows,'comet')
    check('duplicate source IDs and duplicate content not repeated',len(packet['items'])==1)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
