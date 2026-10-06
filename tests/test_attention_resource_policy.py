"""Registered local inference batch must pass the real automation resource gate."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-attention-resources')
from agentic_core.database.base import async_session
from aries.automations import runner
from aries.automations.genome import get
from aries.power import governor
from aries.settings import SettingsService

LIMITS={'temperature_celsius':85,'cpu_pct':90,'gpu_pct':90,'allow_heavy_cpu':False,
        'allow_gpu_jobs':False,'resume_margin_celsius':5,'clear_checks':2}

async def test_registered_attention_rejects_hot_and_blind_sensors_before_lifecycle():
    for measurement,expected in [(governor.Measurement(cpu_pct=5,temperature_c=95),'too_hot'),
            (governor.Measurement(cpu_pct=99,temperature_c=45),'cpu_busy'),
            (governor.Measurement(cpu_pct=5,temperature_unavailable='sensor absent'),'sensor_unavailable')]:
        await reset_db()
        with patch.object(governor,'limits',AsyncMock(return_value=LIMITS)), \
             patch.object(governor.state,'display_state',return_value=('on','fixture')), \
             patch.object(governor,'measure',AsyncMock(return_value=measurement)), \
             patch.object(runner,'_run_through_lifecycle',AsyncMock()) as execute:
            result=await runner.run_automation('aries.attention',force=True)
        check('actual batch admission refuses '+expected,result['reason']=='resource_policy:'+expected and not result['ran'])
        check('no lifecycle/model execution after refusal',not execute.called)

async def test_unattended_batch_requires_permission_but_explicit_cool_run_can_start():
    await reset_db()
    async with async_session() as db:await SettingsService(db).set('connect.attention_enabled',True)
    with patch.object(governor,'limits',AsyncMock(return_value=LIMITS)), \
         patch.object(governor.state,'display_state',return_value=('off','fixture')), \
         patch.object(governor,'measure',AsyncMock(return_value=governor.Measurement(cpu_pct=5,temperature_c=45))), \
         patch.object(runner,'_run_through_lifecycle',AsyncMock(return_value={'ran':True,'status':'ok'})) as execute:
        scheduled=await runner.run_automation('aries.attention',trigger='schedule')
        check('unattended inference batch cannot borrow permission from light work',scheduled.get('reason')=='resource_policy:not_enabled' and not execute.called)
        explicit=await runner.run_automation('aries.attention',force=True)
        check('explicit cool run reaches lifecycle once',explicit['ran'] and execute.call_count==1)
    check('completed lifecycle releases resource tracking',not governor.running())

async def test_health_measurement_stays_available_under_bad_sensors():
    await reset_db()
    with patch.object(governor,'measure',AsyncMock(side_effect=AssertionError('health must not depend on its own sensors'))):
        async with async_session() as db:verdict=await governor.may_run(db,get('aries.health'))
    check('diagnostic health pass remains available',verdict.allowed)

if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
