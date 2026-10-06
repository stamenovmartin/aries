"""Concurrent admission, uncertain consumption and restart-safe accounting."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-goal-budgets')
from agentic_core.database.base import async_session
from aries.intelligence import budgets
from aries.intelligence.context import task_context
from aries.intelligence.generation import generate
from aries.intelligence.providers import Generation


async def test_parallel_children_share_atomic_limits():
    await reset_db()
    await budgets.create('root',max_calls=3,max_tokens=90)
    async def child(n):
        try:return await budgets.reserve('root','child-'+str(n),'model',tokens=30,cost_micros=0)
        except budgets.BudgetExceeded:return None
    keys=await asyncio.gather(*(child(n) for n in range(12)))
    check('exactly three of twelve racing children admitted',sum(k is not None for k in keys)==3)
    state=await budgets.snapshot('root')
    check('reservations never overspend shared call/token cap',state['calls']==3 and state['tokens']==90)
    key=next(k for k in keys if k)
    await budgets.settle(key,tokens=10,cost_micros=0)
    await budgets.settle(key,tokens=0,cost_micros=0)
    check('duplicate settlement cannot refund twice',(await budgets.snapshot('root'))['tokens']==70)
    await budgets.create('root',max_calls=100,max_tokens=90000)
    check('resume cannot reset or widen original budget',(await budgets.snapshot('root'))['max_calls']==3)


async def test_unknown_usage_and_unpriced_calls_fail_closed():
    await reset_db()
    await budgets.create('uncertain')
    key=await budgets.reserve('uncertain','child','model',tokens=500)
    await budgets.settle(key,tokens=None,known=False)
    state=await budgets.snapshot('uncertain')
    check('unknown consumption retained and root held',state['tokens']==500 and state['unknown']==1 and state['held'])
    try:await budgets.reserve('uncertain','other','model',tokens=1);blocked=False
    except budgets.BudgetExceeded:blocked=True
    check('uncertain call cannot fund a fresh sibling retry',blocked)
    await budgets.create('priced',max_cost_micros=100)
    try:await budgets.reserve('priced','child','model',tokens=1);blocked=False
    except budgets.BudgetExceeded:blocked=True
    check('positive cost cap refuses unknown CLI price',blocked)
    key=await budgets.reserve('priced','child','model',tokens=1,cost_micros=90)
    await budgets.settle(key,tokens=1,cost_micros=120)
    check('reported cost overrun is debt and holds root',(await budgets.snapshot('priced'))['held'])


async def test_tool_deadlines_and_provider_boundary():
    await reset_db()
    await budgets.create('tools',max_tools=1)
    key=await budgets.reserve('tools','child','verification',cost_micros=0)
    await budgets.settle(key,tokens=0,cost_micros=0)
    try:await budgets.reserve('tools','child','tool',cost_micros=0);blocked=False
    except budgets.BudgetExceeded:blocked=True
    check('verification consumes shared tool budget',blocked)
    await budgets.create('expired',seconds=1)
    with patch('aries.intelligence.budgets.time.time',return_value=10**12):
        try:await budgets.reserve('expired','child','model',tokens=1);blocked=False
        except budgets.BudgetExceeded:blocked=True
    check('expired root refuses dispatch',blocked)
    await budgets.create('provider',max_calls=1)
    model=AsyncMock(return_value=Generation('{}',15,2,'local','test'))
    with patch('aries.intelligence.generation.local_generate',model):
        with task_context('child',root_id='provider',budgeted=True):
            async with async_session() as db:
                await generate(db,[],None,purpose='budget-test',max_tokens=20)
                try:await generate(db,[],None,purpose='budget-test',max_tokens=20);blocked=False
                except budgets.BudgetExceeded:blocked=True
        check('budget refusal occurs before second provider invocation',blocked and model.await_count==1)
        state=await budgets.snapshot('provider')
        check('measured tokens settle conservative reservation',state['tokens']==17 and state['pending']==0)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
