"""Production queue wiring: real submission, probes, evidence and shared slots."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-orchestration-integration')
from agentic_core.database.base import async_session
from agentic_core.security import principal
from agentic_core.security.permissions import Role
from aries.workspace import service, orchestration as orc, runaway
from aries.workspace.models import WorkspaceGoal
import httpx
from aries.api.app import app


async def row(goal_id):
    async with async_session() as db:
        value = await db.get(WorkspaceGoal, goal_id)
        return value.state, json.loads(value.result_json)


async def test_measurement_questions_use_the_production_tick():
    await reset_db()
    runaway.resume()
    async with async_session() as db:
        parent = await service.submit(db, 'провери ги дискот и меморијата', origin='voice')
        parent_id = parent['id']
        children = parent['orchestration']['children']
    check('one explicit compound request creates durable child goals', len(children) == 2)
    await service.dispatch()
    check('legacy dispatcher never claims empty orchestration plans',
          [(await row(i))[0] for i in children] == ['queued', 'queued'])
    with patch.object(orc, 'capacity', new=AsyncMock(return_value=orc.Capacity(1, 'test budget'))):
        first = await service.tick()
        check('production tick uses the shared one-slot budget', first['launched'] == 1 and len(service._supervisors) <= 1)
        for _ in range(6):
            tasks = list(service._supervisors.values())
            if tasks:
                await asyncio.gather(*tasks)
            await service.tick()
            if (await row(parent_id))[0] != 'running':
                break
    state, data = await row(parent_id)
    check('both real independently verified probes roll up to the parent',
          state == 'done' and all(o['state'] == 'done' for o in data['orchestration']['outcomes']))
    answer = next(c['text'] for c in data['cards'] if c['title'] == 'Answer')
    check('parent answers both questions with measurements', 'гигабајти' in answer and 'Меморијата' in answer)
    check('every child retains independent verification evidence',
          all([any(e.get('verified') is True for e in (await row(i))[1]['evidence']) for i in children]))
    async with async_session() as db:
        await orc.roll_up(db, parent_id)
    check('completed parent reports are not appended again on later ticks',
          (await row(parent_id))[1]['cards'] == data['cards'])


async def test_parallel_submission_cannot_bypass_authority():
    await reset_db()
    runaway.resume()
    token = principal.set_current(principal.build(99, Role.READONLY))
    try:
        async with async_session() as db:
            try:
                await orc.fan_out(db, 'read status', [{'capability': 'system.status'}])
                denied = False
            except ValueError:
                denied = True
        check('fan-out requires the same permission as ordinary submission', denied)
    finally:
        principal.reset(token)
    for item in [{'capability': 'notification.send', 'args': {'title': 'test', 'body': 'test'}},
                 {'capability': 'system.status', 'approved': True}]:
        async with async_session() as db:
            try:
                await orc.fan_out(db, 'do this', [item])
                denied = False
            except ValueError:
                denied = True
        check('parallel input cannot authorise mutations or self-approve', denied)


async def test_voice_receipt_counts_each_utterance_once():
    await reset_db()
    runaway.resume()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        receipts = []
        statuses = []
        for _ in range(3):
            response = await client.post('/api/aries/shell/act', json={
                'kind': 'workspace', 'text': 'колку место има на дискот?', 'source': 'voice'})
            receipts.append(response.json())
            statuses.append(response.status_code)
    check('single measurements return the normal serializable voice receipt',
          receipts[0].get('ok') is True and receipts[0]['result']['id']
          and receipts[0]['result']['orchestration']['width'] == 1)
    check('fan-out never double-charges the shell loop guard',
          receipts[1].get('ok') is True and statuses == [200, 200, 429])
    runaway.resume()


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
