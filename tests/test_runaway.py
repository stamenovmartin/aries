import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-runaway')
from httpx import ASGITransport, AsyncClient
from aries.workspace import runaway as r


async def test_the_2026_09_29_loop_is_stopped():
    # What the microphone produced from a song ARIES itself had started.
    r.resume()
    heard = [(0, 'play some music.'), (20, 'open settings.'), (40, 'play some music.'), (60, 'Play some music')]
    verdicts = [r.check(text, 'voice', now=t) for t, text in heard]
    check('first two identical requests run', verdicts[0].allowed and verdicts[2].allowed)
    check('the third identical request trips the guard', not verdicts[3].allowed and verdicts[3].tripped)
    later = r.check('open youtube', 'voice', now=100)
    check('a tripped source stays paused for a different request', not later.allowed and not later.tripped)
    check('typing is not paused by the microphone', r.check('play some music', 'default', now=100).allowed)
    check('the pause expires by itself', r.check('open youtube', 'voice', now=60 + r.PAUSE_S + 1).allowed)


async def test_rate_and_resume():
    r.resume()
    out = [r.check(f'command {i}', 'voice', now=i * 5) for i in range(8)]
    check('six distinct voice commands a minute are allowed', all(v.allowed for v in out[:6]))
    check('the seventh inside a minute trips', not out[6].allowed and out[6].tripped)
    check('status explains the pause', 'voice' in r.status(now=40) and 'minute' in r.status(now=40)['voice']['reason'])
    r.resume('voice')
    check('resume lifts it', r.check('command 9', 'voice', now=41).allowed and not r.status(now=41))


async def test_route_refuses_and_notifies():
    from aries.api.app import app
    from tests._bootstrap import reset_db
    await reset_db()
    r.resume()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://t') as c:
        body = {'kind': 'workspace', 'text': 'play some music.', 'source': 'voice'}
        codes = [(await c.post('/api/aries/shell/act', json=body)).status_code for _ in range(3)]
        import json
        from agentic_core.database.base import async_session
        from sqlalchemy import select
        from aries.workspace.models import WorkspaceGoal
        async with async_session() as db:
            data = [json.loads(g.result_json) for g in (await db.execute(select(WorkspaceGoal))).scalars()]
        check('a spoken command opens no window', data and all(d.get('present_dashboard') is False for d in data))
        check('and is marked as spoken, so its outcome is notified', all(d.get('origin') == 'voice' for d in data))
        check('the looping voice request is refused with 429', codes == [200, 200, 429])
        guard = (await c.get('/api/aries/shell/guard')).json()
        check('the guard reports the paused source', 'voice' in guard['paused'])
        notes = (await c.get('/api/aries/notifications?limit=12')).text
        check('the person is told a loop was stopped', 'command loop' in notes)
        await c.post('/api/aries/shell/guard/resume')
        check('resume through the API', not (await c.get('/api/aries/shell/guard')).json()['paused'])


async def test_voice_outcome_reaches_the_person_without_a_window():
    import json
    from tests._bootstrap import reset_db
    from agentic_core.database.base import async_session
    from sqlalchemy import select
    from aries.notify.policy import AriesNotification
    from aries.workspace import service
    from aries.workspace.models import WorkspaceGoal
    await reset_db()
    async with async_session() as db:
        for gid, state, card in [('a', 'answered', 'Macedonia'), ('f', 'failed', 'no player'), ('d', 'done', 'Playing')]:
            row = WorkspaceGoal(id=gid, request='q ' + gid, state=state,
                                result_json=json.dumps({'origin': 'voice', 'cards': [{'text': card}]}))
            db.add(row); await db.flush()
            await service._tell_voice_outcome(db, row, json.loads(row.result_json))
        notes = (await db.execute(select(AriesNotification))).scalars().all()
    bodies = {n.key: n.body for n in notes}
    check('an answer is delivered', bodies.get('voice.a') == 'Macedonia')
    check('a failure is explained', bodies.get('voice.f') == 'no player')
    check('a success stays silent', 'voice.d' not in bodies)


if __name__ == '__main__':
    run_module(sys.modules[__name__])
