from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from agentic_core.database.base import Base

class IntelligenceEvent(Base):
    __tablename__='aries_intelligence_events'
    id: Mapped[str] = mapped_column(String(40),primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow,index=True)
    kind: Mapped[str] = mapped_column(String(30),index=True)
    data_json: Mapped[str] = mapped_column(Text)

class RoutingCache(Base):
    __tablename__='aries_routing_cache'
    id: Mapped[str] = mapped_column(String(64),primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow)
    data_json: Mapped[str] = mapped_column(Text)


class GoalBudget(Base):
    __tablename__='aries_goal_budgets'
    root_id: Mapped[str] = mapped_column(String(64),primary_key=True)
    max_calls: Mapped[int] = mapped_column(Integer)
    max_tokens: Mapped[int] = mapped_column(Integer)
    max_tools: Mapped[int] = mapped_column(Integer)
    max_cost_micros: Mapped[int] = mapped_column(Integer,default=0)
    deadline: Mapped[float] = mapped_column(Float)
    calls: Mapped[int] = mapped_column(Integer,default=0)
    tokens: Mapped[int] = mapped_column(Integer,default=0)
    tools: Mapped[int] = mapped_column(Integer,default=0)
    cost_micros: Mapped[int] = mapped_column(Integer,default=0)
    held: Mapped[bool] = mapped_column(Boolean,default=False)


class BudgetReservation(Base):
    __tablename__='aries_budget_reservations'
    id: Mapped[str] = mapped_column(String(40),primary_key=True)
    root_id: Mapped[str] = mapped_column(String(64),index=True)
    task_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20),default='reserved')
    tokens: Mapped[int] = mapped_column(Integer,default=0)
    cost_micros: Mapped[int] = mapped_column(Integer,default=0)
    measured_tokens: Mapped[int | None] = mapped_column(Integer,nullable=True)
    measured_cost_micros: Mapped[int | None] = mapped_column(Integer,nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow)
