"""Durable atomic admission shared by every child of a goal.

Token reservations use an explicitly conservative estimate. Actual usage can
exceed a provider estimate; that puts the root on hold instead of hiding debt.
Unknown/interrupted consumption is never refunded. No transaction spans I/O.
"""
import time
import uuid
from sqlalchemy import update, select
from agentic_core.database.base import async_session
from .models import GoalBudget, BudgetReservation


class BudgetExceeded(ValueError):
    code = 'BUDGET_EXCEEDED'


async def create(root_id, *, max_calls=32, max_tokens=250000, max_tools=64,
                 max_cost_micros=0, seconds=1800):
    limits = (max_calls,max_tokens,max_tools,max_cost_micros,seconds)
    if any(type(v) is not int or v<0 for v in limits) or not seconds:
        raise ValueError('Nonnegative integer limits and positive seconds required')
    async with async_session() as db:
        dialect = db.bind.dialect.name
        if dialect == 'sqlite':
            from sqlalchemy.dialects.sqlite import insert
        elif dialect == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError('Budget admission requires an atomic insert dialect')
        await db.execute(insert(GoalBudget).values(root_id=root_id,max_calls=max_calls,
            max_tokens=max_tokens,max_tools=max_tools,max_cost_micros=max_cost_micros,
            deadline=time.time()+seconds,calls=0,tokens=0,tools=0,cost_micros=0,held=False)
            .on_conflict_do_nothing(index_elements=['root_id']))
        await db.commit()


async def reserve(root_id, task_id, kind, *, tokens=0, cost_micros=None):
    if kind not in {'model','tool','verification'} or type(tokens) is not int or tokens<0:
        raise ValueError('Invalid budget reservation')
    if cost_micros is not None and (type(cost_micros) is not int or cost_micros<0):
        raise ValueError('Invalid cost reservation')
    call, tool = int(kind=='model'), int(kind!='model')
    cost = cost_micros or 0
    key=uuid.uuid4().hex
    async with async_session() as db:
        conditions=[GoalBudget.root_id==root_id,GoalBudget.held.is_(False),
                    GoalBudget.deadline>time.time(),GoalBudget.calls+call<=GoalBudget.max_calls,
                    GoalBudget.tokens+tokens<=GoalBudget.max_tokens,
                    GoalBudget.tools+tool<=GoalBudget.max_tools]
        if cost_micros is None:
            conditions.append(GoalBudget.max_cost_micros==0)
        else:
            conditions.append((GoalBudget.max_cost_micros==0) |
                              (GoalBudget.cost_micros+cost<=GoalBudget.max_cost_micros))
        changed=await db.execute(update(GoalBudget).where(*conditions).values(
            calls=GoalBudget.calls+call,tokens=GoalBudget.tokens+tokens,
            tools=GoalBudget.tools+tool,cost_micros=GoalBudget.cost_micros+cost))
        if changed.rowcount!=1:
            raise BudgetExceeded('Root budget unavailable, held, expired or exhausted; unpriced calls require an uncapped cost policy')
        db.add(BudgetReservation(id=key,root_id=root_id,task_id=task_id,kind=kind,
                                tokens=tokens,cost_micros=cost))
        await db.commit()
    return key


async def settle(key, *, tokens=None, cost_micros=None, known=True):
    for value in (tokens,cost_micros):
        if value is not None and (type(value) is not int or value<0):
            raise ValueError('Measured consumption must be a nonnegative integer or unknown')
    async with async_session() as db:
        row=await db.get(BudgetReservation,key)
        if row is None:
            raise ValueError('Unknown budget reservation')
        # CAS ensures duplicate callbacks never refund twice.
        complete=known and (row.kind!='model' or tokens is not None)
        state='settled' if complete else 'unknown'
        changed=await db.execute(update(BudgetReservation).where(
            BudgetReservation.id==key,BudgetReservation.state=='reserved').values(
                state=state,measured_tokens=tokens,measured_cost_micros=cost_micros))
        if changed.rowcount!=1:
            return False
        charged_tokens=tokens if complete and tokens is not None else row.tokens
        charged_cost=cost_micros if complete and cost_micros is not None else row.cost_micros
        await db.execute(update(GoalBudget).where(GoalBudget.root_id==row.root_id).values(
            tokens=GoalBudget.tokens-row.tokens+charged_tokens,
            cost_micros=GoalBudget.cost_micros-row.cost_micros+charged_cost))
        # Missing usage cannot be used to fund another retry after an uncertain call.
        await db.execute(update(GoalBudget).where(GoalBudget.root_id==row.root_id,
            (GoalBudget.tokens>GoalBudget.max_tokens) |
            ((GoalBudget.max_cost_micros>0)&(GoalBudget.cost_micros>GoalBudget.max_cost_micros)) |
            (True if not complete else False)).values(held=True))
        await db.commit()
    return True


async def snapshot(root_id):
    async with async_session() as db:
        row=await db.get(GoalBudget,root_id)
        if row is None:return None
        reservations=(await db.execute(select(BudgetReservation).where(
            BudgetReservation.root_id==root_id))).scalars().all()
        return {key:getattr(row,key) for key in ('root_id','max_calls','max_tokens','max_tools',
            'max_cost_micros','deadline','calls','tokens','tools','cost_micros','held')} | {
                'pending':sum(r.state=='reserved' for r in reservations),
                'unknown':sum(r.state=='unknown' for r in reservations),
                'token_policy':'conservative admission estimate; measured overrun holds root',
                'unpriced_cost_is_unknown':True}
