"""The working set: what ARIES pulled in to do one piece of work.

This is the browser-tab half of the analogy. When ARIES answers "what do I have
tomorrow?" it may read a calendar, three emails and a project folder. Those
bodies are needed for as long as the task runs and are nobody's business
afterwards — least of all a SQLite file's.

WHY IT IS A TABLE AND NOT JUST VARIABLES
----------------------------------------
Because work is resumable. The engine's plans survive a restart (at-most-once
side effects, `uncertain` as a first-class outcome), so a task interrupted
halfway has to be able to pick up its context. Holding that only in memory would
mean either losing it or quietly re-fetching — and re-fetching is how a system
that promised at-most-once sends an email twice.

So it is stored, and **its lifetime is the task's, not a timer's**. A task that
finishes deletes its working set. A task that dies leaves one behind, which the
sweep collects — the only reason there is an age at all.

WHAT MAY NOT GO IN HERE
-----------------------
Anything ARIES concluded. A conclusion belongs in memory with its provenance; if
it is only in the working set it disappears when the task ends, and the user is
told something ARIES can no longer explain.
"""
from __future__ import annotations


from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

# Far longer than any task ARIES runs. Anything older belongs to a task that is
# not coming back, which is the only reason a working set has an age at all.
SWEEP_HOURS = 6


class AriesWorkingSet(Base):
    """One piece of context, held for one task.

    `content` is deliberately opaque text: this table is a scratchpad, and giving
    it a schema would invite it to become a second memory.
    """

    __tablename__ = "aries_working_set"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(200), default="")   # where it came from
    sensitive: Mapped[bool] = mapped_column(default=False)         # never leaves the machine
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    def as_dict(self, *, include_content: bool = False) -> dict:
        out = {"id": self.id, "task_id": self.task_id, "label": self.label,
               "source": self.source, "sensitive": self.sensitive,
               "bytes": len(self.content or ""),
               "created_at": self.created_at.isoformat() if self.created_at else None}
        if include_content:
            out["content"] = self.content
        return out


async def put(db: AsyncSession, task_id: str, *, label: str, source: str,
              content: str, sensitive: bool = False) -> AriesWorkingSet:
    """Hold something for the duration of a task."""
    row = AriesWorkingSet(task_id=str(task_id), label=label, source=source,
                          content=content, sensitive=sensitive)
    db.add(row)
    return row


async def get(db: AsyncSession, task_id: str) -> list[AriesWorkingSet]:
    return list((await db.execute(
        select(AriesWorkingSet).where(AriesWorkingSet.task_id == str(task_id))
        .order_by(AriesWorkingSet.id))).scalars().all())


async def release(db: AsyncSession, task_id: str) -> int:
    """The task is done. Close the tab.

    Called on every terminal outcome — success, failure, escalation — because
    the context is worthless in all three, and only success would be remembered.
    """
    result = await db.execute(
        delete(AriesWorkingSet).where(AriesWorkingSet.task_id == str(task_id)))
    return result.rowcount or 0


async def sweep(db: AsyncSession, *, older_than_hours: int = SWEEP_HOURS) -> dict:
    """Collect what dead tasks left behind.

    The only reason a working set has an age: a task that crashed cannot release
    its own context. `SWEEP_HOURS` is far longer than any task ARIES runs, so
    anything older belongs to something that is not coming back.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    orphans = list((await db.execute(
        select(AriesWorkingSet).where(
            AriesWorkingSet.created_at < cutoff.replace(tzinfo=None)))).scalars().all())
    if not orphans:
        return {"swept": 0, "tasks": []}
    tasks = sorted({row.task_id for row in orphans})
    await db.execute(delete(AriesWorkingSet).where(
        AriesWorkingSet.created_at < cutoff.replace(tzinfo=None)))
    return {"swept": len(orphans), "tasks": tasks}


async def summary(db: AsyncSession) -> dict:
    """What is being held right now — for the Control Centre and `aries data`."""
    rows = list((await db.execute(select(AriesWorkingSet))).scalars().all())
    return {
        "held": len(rows),
        "bytes": sum(len(r.content or "") for r in rows),
        "tasks": sorted({r.task_id for r in rows}),
        "sensitive": sum(1 for r in rows if r.sensitive),
    }


