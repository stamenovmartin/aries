import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-news-summaries')
from aries.news.summaries import summarize

async def test_cache_and_failure():
    await reset_db()
    with TemporaryDirectory() as directory:
        fake=AsyncMock(return_value=('{"summary_mk":"Објавен е нов модел за машинско учење."}',{'execution_level':'local'}))
        with patch('aries.news.summaries.local_structured',fake):
            a=await summarize('New model','A new model',directory=directory)
            b=await summarize('New model','A new model',directory=directory)
            check('local summary cached without repeated inference',a['status']=='generated' and b['cached'] and fake.await_count==1)
            await summarize('New model','Changed article',directory=directory)
            check('changed source content invalidates cache',fake.await_count==2)
        with patch('aries.news.summaries.local_structured',AsyncMock(side_effect=RuntimeError('offline'))) as failure:
            a=await summarize('Offline','Text',directory=directory)
            b=await summarize('Offline','Text',directory=directory)
            check('model outage preserves explicit fallback',a['status']=='fallback' and a['summary_mk'] is None)
            check('outage cooldown prevents retry storm',b['cached'] and failure.await_count==1)
        for i,text in enumerate(['not json','{"summary_mk":"English only summary here."}','{"summary_mk":"Ова е македонско резиме.","tool":"shell"}']):
            with patch('aries.news.summaries.local_structured',AsyncMock(return_value=(text,{}))):
                result=await summarize(str(i),'test',directory=directory)
                check('invalid/language/action output rejected '+str(i),result['status']=='fallback')

if __name__=='__main__':run_module(sys.modules[__name__])
