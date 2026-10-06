"""No guessed success from executor state; file changes invalidate evidence."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-verification-recording')
from aries.workspace.verification import record
from aries.workspace import capabilities
from agentic_core.database.base import async_session
from unittest.mock import patch

async def test_recording():
    for value in (None,1,'true',{},[]):
        s={'state':'done','result':{'verification':{'met':value}}}
        record(s)
        check('non-literal verdict never verified '+repr(value),s['verification_status']=='unverifiable')
    s={'state':'done','result':{'verification':{'met':True,'evidence':'fresh read'}}}
    record(s);check('actual positive verifier exposed',s['verification_status']=='verified')
    s={'state':'done','result':{'verification':{'met':False}}}
    record(s);check('contradictory done downgraded',s['state']=='unconfirmed' and s['verification_status']=='verification_failed')
    s={'state':'proposed','result':{}}
    record(s);check('approval never becomes completed',s['state']=='proposed' and s['verification_status']=='pending')
    s={'state':'done','verification':{'met':None,'unverifiable':True,'evidence':'research'}}
    record(s);check('research marker preserved',s['verification']['evidence']=='research' and s['verification_status']=='unverifiable')

async def test_real_file_and_mutation():
    await reset_db()
    import tempfile
    with tempfile.TemporaryDirectory(dir=Path.home()) as temp:
        p=Path(temp)/'x.txt';p.write_text('first')
        step={'capability':'read_file','args':{'path':str(p)},'request':'read owned fixture'}
        async with async_session() as db:
            result=await capabilities.execute(db,step)
            check('real independent file read',result['verification']['met'] is True)
            original=Path.read_bytes
            calls=0
            def changing(self):
                nonlocal calls
                if self==p:
                    calls+=1
                    if calls==2:self.write_text('changed')
                return original(self)
            with patch.object(Path,'read_bytes',changing):
                result=await capabilities.execute(db,step)
            check('change between execution and verification rejected',result['state']=='unconfirmed' and result['verification']['met'] is False)
            step={'capability':'list_folder','args':{'path':temp},'request':'list fixture'}
            result=await capabilities.execute(db,step)
            check('directory independently re-read',result['verification']['met'] is True)

async def test_spoken_uncertainty_in_mixed_and_summary_results():
    from aries.speech.replies import sentence
    mixed={'state':'done','steps':[{'verification_status':'verified'},
           {'verification':{'met':None,'unverifiable':True}}],
           'cards':[{'title':'Finding','text':'Example'}]}
    check('mixed evidence says uncertainty in English', 'cannot confirm' in sentence(mixed,language='en'))
    check('mixed evidence says uncertainty in Macedonian', 'не можам да потврдам' in sentence(mixed,language='mk'))
    mixed.pop('cards');mixed['summary']='Collected several findings'
    check('summary cannot suppress uncertainty', 'cannot confirm' in sentence(mixed,language='en'))

if __name__=='__main__':run_module(sys.modules[__name__])
