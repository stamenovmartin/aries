"""Exercise actual executor retry decisions with synthetic timeout-after-effect."""
import sys
import tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import AsyncMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.test_agent_execution import setup,run_goal,execute,finish
from tests._bootstrap import check,run_module
from aries.workspace.registry import registry


async def test_timeout_after_mutation_is_not_replayed():
    await setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'replay-fixture.txt'
        calls=[]
        async def uncertain(args,ctx):
            calls.append(dict(args))
            path.write_text('effect occurred '+str(len(calls)))
            raise TimeoutError('Acknowledgement lost after synthetic write')
        verifier=AsyncMock()
        cap=replace(registry.get('file.write'),executor=uncertain,verifier=verifier)
        action=execute('file.write',path=str(path),content='fixture')
        with patch.dict(registry._items,{'file.write':cap}):
            result=await run_goal(f'Create a file called replay-fixture.txt in {directory} containing:\nfixture\nThen read it back.',
                                  [action,action,{'action':'fail','reason':'Uncertain outcome'}])
        check('mutation executes exactly once despite identical retry proposal',len(calls)==1)
        check('first real side effect remains without a second write',path.read_text()=='effect occurred 1')
        check('timeout is retained as original observation',result['steps'][0]['error']['error_type']=='TimeoutError')
        check('duplicate mutation is explicitly rejected',len(result['steps'])==2 and
              'Duplicate' in result['steps'][1]['error']['message'])
        check('uncertain mutation is not reported successful',result['state']=='failed' and not result.get('final_evidence_refs'))
        check('executor timeout cannot fabricate verification',not verifier.called and not any(e['verified'] for e in result['evidence']))


async def test_transient_read_can_retry_and_verify():
    await setup()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        path=Path(directory)/'read-fixture.txt';path.write_text('known bytes')
        original=registry.get('file.read');calls=[]
        async def flaky(args,ctx):
            calls.append(dict(args))
            if len(calls)==1:raise TimeoutError('Synthetic read interruption')
            return await original.executor(args,ctx)
        with patch.dict(registry._items,{'file.read':replace(original,executor=flaky)}):
            action=execute('file.read',path=str(path))
            result=await run_goal('Read '+str(path),[action,action,finish])
        check('transient read retains one permitted retry',len(calls)==2)
        check('retry succeeds with independent final proof',result['state']=='done' and bool(result.get('final_evidence_refs')))
        check('read retry is counted',result['agent']['metrics']['retries']==1)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
