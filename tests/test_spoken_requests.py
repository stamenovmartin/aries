"""Natural read-only questions and verified Macedonian conversational references."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-spoken-requests')
from agentic_core.database.base import async_session
from aries.workspace.measurement_requests import questions
from aries.workspace.contracts import compile_goal
from aries.workspace import working_context
from aries.workspace.models import WorkspaceGoal


def test_natural_measurements():
    cases = [
        ('провери ги дискот и меморијата', ['disk.used_pct', 'memory.used_pct']),
        ('прикажи процесор, меморија и диск', ['cpu.used_pct', 'memory.used_pct', 'disk.used_pct']),
        ('proveri gi diskot i memorijata', ['disk.used_pct', 'memory.used_pct']),
        ('check CPU and memory', ['cpu.used_pct', 'memory.used_pct']),
        ('show disk space', ['disk.used_pct']),
        ('колку место има на дискот и колку меморија се користи?', ['disk.used_pct', 'memory.used_pct']),
        ('How much disk space do I have?', ['disk.used_pct']),
        ('Show CPU usage and memory', ['cpu.used_pct', 'memory.used_pct']),
        ('колку место има на дискот?; колку меморија се користи?', ['disk.used_pct', 'memory.used_pct']),
        ('а меморијата?', ['memory.used_pct']),
        ('a RAM?', ['memory.used_pct']),
        ('what about CPU?', ['cpu.used_pct']),
    ]
    for text, expected in cases:
        result = questions(text)
        metrics = [compile_goal(q, '')['requirements'][0]['metric'] for q in result or []]
        check('whole request understood: ' + text, metrics == expected)
    check('Macedonian follow-up retains Macedonian answer language',
          compile_goal(questions('a RAM?')[0], '')['language'] == 'mk')
    for text in ['check CPU and delete all files', 'провери диск и избриши документи',
                 'show CPU usage and reboot', 'колку место има на дискот; испрати е-пошта',
                 'check CPU,', 'check CPU and', 'show disk space on the USB drive']:
        check('unknown requirement is never silently dropped: ' + text, questions(text) is None)


async def test_verified_context_in_macedonian():
    await reset_db()
    def goal(key, payload, *, age=0, verified=True, state='answered'):
        return WorkspaceGoal(id=key, request='read', state=state,
            updated_at=datetime.utcnow()-timedelta(minutes=age),
            result_json=json.dumps({'evidence': [{'evidence_id': key, 'verified': verified, 'data': payload}]}))
    async with async_session() as db:
        db.add_all([goal('file', {'path': '/recent.txt', 'title': None}),
                    goal('old', {'path': '/expired.txt'}, age=31),
                    goal('unverified', {'path': '/unverified.txt'}, verified=False),
                    goal('badflag', {'path': '/unverified-string.txt'}, verified='false'),
                    goal('readings', [{'metric': 'cpu.used_pct', 'value': 10}]),
                    goal('mixed', {'matches': [None, 'invalid', {'value': 5}]})])
        await db.commit()
        for text in ['прочитај ја', 'Прочитај го!', 'prochitaj ja', 'отвори ја', 'otvori go']:
            resolved, reference = await working_context.resolve(db, text)
            check('verified Macedonian follow-up: ' + text,
                  resolved.endswith('/recent.txt') and reference['original'] == text
                  and reference['resolved']['evidence_id'] == 'file')
        check('stale, malformed and unverified evidence never becomes a reference',
              len((await working_context.current(db))['entities']) == 1)
        unchanged = 'прочитај ја и избриши ја'
        check('additional actions are not consumed by reference shorthand',
              await working_context.resolve(db, unchanged) == (unchanged, None))
        db.add(goal('second', {'path': '/second.txt'})); await db.commit()
        try:
            await working_context.resolve(db, 'отвори ја')
            refused = False
        except ValueError as exc:
            refused = 'AMBIGUOUS' in str(exc) and 'наведи' in str(exc)
        check('multiple eligible files require a named choice in Macedonian', refused)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
