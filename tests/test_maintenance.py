import sys,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,run_module
bootstrap('aries-maintenance')
from aries.runtime import maintenance as m
from aries.workspace import service

async def test_drain_and_lease():
    token=m.acquire()
    try:
        check('new queue launches paused',(await service.dispatch(wait=False)).get('maintenance') is True)
        with patch.dict(service._supervisors,{'active-task':object()}):
            check('active workspace task prevents restart',not m.status()['ready_to_restart'])
        try:m.acquire();rejected=False
        except ValueError:rejected=True
        check('second updater rejected',rejected)
        try:m.release('wrong');rejected=False
        except ValueError:rejected=True
        check('wrong lease cannot resume queues',rejected and m.active())
        with patch.object(m.time,'monotonic',return_value=time.monotonic()+241):
            check('abandoned update lease expires',not m.active())
    finally:m.release(token)
    check('release resumes normal dispatch',not m.active())

if __name__=='__main__':run_module(sys.modules[__name__])
