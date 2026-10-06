"""Противнички тест на `aries.intelligence.budgets` под истовремено влегување.

Изолирана база во привремен директориум преку DATABASE_URL. Не ја допира
var/aries.db, не стартува сервис, не повикува модел.
"""
import asyncio, json, os, pathlib, sys, tempfile, time

TMP = pathlib.Path(tempfile.mkdtemp(prefix='aries-budget-'))
os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{TMP}/probe.db'
sys.path[:0] = [os.path.abspath(p) for p in ('vendor/agentic-core', 'vendor', '.')]

from agentic_core.database.base import Base, engine, async_session   # noqa: E402
from aries.intelligence import budgets                              # noqa: E402
from aries.intelligence.models import GoalBudget                    # noqa: E402

R = []


def note(case, expected, observed, detail=''):
    R.append({'case': case, 'expected': expected, 'observed': observed,
              'verdict': 'PASS' if expected == observed else 'FAIL', 'detail': str(detail)[:120]})


async def main():
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    # 1 — дваесет истовремени барања наспроти таван од пет повици
    await budgets.create('r-calls', max_calls=5, max_tokens=10**6, max_tools=999, seconds=600)
    async def one(i):
        try:
            await budgets.reserve('r-calls', f't{i}', 'model', tokens=0)
            return True
        except budgets.BudgetExceeded:
            return False
    got = sum(await asyncio.gather(*[one(i) for i in range(20)]))
    note('20 истовремени повици, таван 5', 5, got)

    # 2 — истовремени токени наспроти таван
    await budgets.create('r-tok', max_calls=999, max_tokens=1000, max_tools=999, seconds=600)
    async def tok(i):
        try:
            await budgets.reserve('r-tok', f't{i}', 'model', tokens=300)
            return True
        except budgets.BudgetExceeded:
            return False
    got = sum(await asyncio.gather(*[tok(i) for i in range(10)]))
    note('10 истовремени по 300 токени, таван 1000', 3, got)

    # 3 — дупло подмирување не враќа двапати
    await budgets.create('r-settle', max_calls=99, max_tokens=10000, max_tools=99, seconds=600)
    k = await budgets.reserve('r-settle', 't1', 'model', tokens=500)
    first = await budgets.settle(k, tokens=100)
    second = await budgets.settle(k, tokens=100)
    note('подмирување двапати', [True, False], [first, second])
    snap = await budgets.snapshot('r-settle')
    note('наплатено токени по подмирување', 100, snap['tokens'])

    # 4 — непозната потрошувачка го задржува коренот
    await budgets.create('r-unknown', max_calls=99, max_tokens=10000, max_tools=99, seconds=600)
    k = await budgets.reserve('r-unknown', 't1', 'model', tokens=500)
    await budgets.settle(k, tokens=None, known=False)
    snap = await budgets.snapshot('r-unknown')
    note('непозната потрошувачка задржува', True, bool(snap['held']))
    try:
        await budgets.reserve('r-unknown', 't2', 'model', tokens=1)
        note('задржан корен прима ново барање', 'refuse', 'allow')
    except budgets.BudgetExceeded:
        note('задржан корен прима ново барање', 'refuse', 'refuse')

    # 5 — измерено пречекорување го задржува коренот
    await budgets.create('r-over', max_calls=99, max_tokens=1000, max_tools=99, seconds=600)
    k = await budgets.reserve('r-over', 't1', 'model', tokens=100)
    await budgets.settle(k, tokens=5000)
    snap = await budgets.snapshot('r-over')
    note('измерено пречекорување задржува', True, bool(snap['held']))

    # 6 — истечен рок одбива
    await budgets.create('r-exp', max_calls=99, max_tokens=10000, max_tools=99, seconds=1)
    async with async_session() as db:
        row = await db.get(GoalBudget, 'r-exp')
        row.deadline = time.time() - 1
        await db.commit()
    try:
        await budgets.reserve('r-exp', 't1', 'model', tokens=1)
        note('истечен рок', 'refuse', 'allow')
    except budgets.BudgetExceeded:
        note('истечен рок', 'refuse', 'refuse')

    # 7 — повик без цена под таван за цена
    await budgets.create('r-cost', max_calls=99, max_tokens=10000, max_tools=99,
                         max_cost_micros=1000, seconds=600)
    try:
        await budgets.reserve('r-cost', 't1', 'model', tokens=1, cost_micros=None)
        note('повик без цена под таван за цена', 'refuse', 'allow')
    except budgets.BudgetExceeded:
        note('повик без цена под таван за цена', 'refuse', 'refuse')

    # 8 — повторен create со построги лимити
    await budgets.create('r-idem', max_calls=10, max_tokens=100, max_tools=10, seconds=600)
    await budgets.create('r-idem', max_calls=1, max_tokens=1, max_tools=1, seconds=600)
    snap = await budgets.snapshot('r-idem')
    note('повторен create ги менува лимитите', 10, snap['max_calls'],
         'on_conflict_do_nothing: вториот повик нема ефект')

    out = pathlib.Path('experiments/product/independent-acceptance/raw/budgets_concurrent.json')
    fails = [r for r in R if r['verdict'] == 'FAIL']
    out.write_text(json.dumps({'n': len(R), 'passed': len(R) - len(fails),
                               'failed': len(fails), 'results': R},
                              ensure_ascii=False, indent=2))
    for r in R:
        print(f"{r['verdict']:4s} {r['case']:44s} очекувано={r['expected']} добиено={r['observed']}")
    print(f"\n{len(R) - len(fails)}/{len(R)} поминаа")


asyncio.run(main())
