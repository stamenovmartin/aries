"""Deciding what actually reaches the user — specification §26.

"Do not notify the user about everything agents discover." The hard part of a
system that watches a machine continuously is not noticing things; it is
noticing things and then mostly keeping quiet. Every unnecessary interruption
spends the user's attention, and attention spent on a notification that did not
matter is attention unavailable for one that does.

Four levels, exactly as §26 specifies:

    CRITICAL     interrupt now, even during quiet hours
    IMPORTANT    normal notification, held during quiet hours
    BRIEFING     hold for the next briefing
    BACKGROUND   log only; never shown

Three independent gates stand between a finding and the user:

  1. LEVEL      — is this at or above `notifications.minimum_level`?
  2. QUIET HOURS— is it late, and is this less than critical?
  3. REPEAT     — has the user already been told this, recently?

The third gate is the one monitoring systems usually forget, and it is why they
become background noise. A disk that is 94% full is 94% full on the next pass
fifteen minutes later, and the one after that. Told each time, the user stops
reading. So a notification's identity is the finding's key, and re-notifying
about the same thing is refused until either the cooldown expires or the
situation gets materially worse — escalation always gets through.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum

from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from agentic_core.database.base import Base

from aries.health.findings import Severity


class Level(IntEnum):
    """How loudly something is delivered. Higher interrupts more."""

    BACKGROUND = 0
    BRIEFING = 1
    IMPORTANT = 2
    CRITICAL = 3

    @property
    def label(self) -> str:
        return self.name.lower()


LEVEL_BY_NAME = {l.label: l for l in Level}

# Severity and Level are separate vocabularies on purpose: severity is about the
# machine, level is about the user's attention. They map one-to-one today, but a
# future rule ("failed units are only a briefing item on a laptop") changes the
# mapping without touching what the health judge decided.
SEVERITY_TO_LEVEL: dict[Severity, Level] = {
    Severity.CRITICAL: Level.CRITICAL,
    Severity.WARNING: Level.IMPORTANT,
    Severity.NOTICE: Level.BRIEFING,
    Severity.OK: Level.BACKGROUND,
}


class AriesNotification(Base):
    """A delivery decision, recorded whether or not it was delivered.

    Recording the suppressed ones is the point: "ARIES noticed this at 02:14 and
    held it because of quiet hours" is answerable, and §29 requires that nothing
    ARIES does be invisible.
    """

    __tablename__ = "aries_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(200), index=True)     # the finding's identity
    source: Mapped[str] = mapped_column(String(120), default="")  # which automation raised it
    level: Mapped[int] = mapped_column(Integer, index=True)
    severity: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # delivered | held_quiet_hours | held_below_threshold | suppressed_repeat | logged
    disposition: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    def as_dict(self) -> dict:
        return {"id": self.id, "key": self.key, "source": self.source,
                "level": Level(self.level).label, "severity": Severity(self.severity).label,
                "title": self.title, "body": self.body, "disposition": self.disposition,
                "reason": self.reason,
                "created_at": self.created_at.isoformat() if self.created_at else None}


@dataclass
class Decision:
    level: Level
    disposition: str
    reason: str

    @property
    def delivered(self) -> bool:
        return self.disposition == "delivered"

    def as_dict(self) -> dict:
        return {"level": self.level.label, "disposition": self.disposition,
                "reason": self.reason, "delivered": self.delivered}


def _parse_hhmm(text: str, fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        h, m = str(text).strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError):
        pass
    return fallback


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    """Whether `now` falls in the quiet window.

    The window normally wraps midnight (22:00 → 07:00), so it cannot be a simple
    `start <= t < end` comparison — that would be false for every hour of a
    wrapping window. Both orientations are handled explicitly.
    """
    sh, sm = _parse_hhmm(start, (22, 0))
    eh, em = _parse_hhmm(end, (7, 0))
    s, e, t = sh * 60 + sm, eh * 60 + em, now.hour * 60 + now.minute
    if s == e:
        return False                      # start == end disables quiet hours
    return t >= s or t < e if s > e else s <= t < e


async def _last_delivered(db: AsyncSession, key: str) -> AriesNotification | None:
    return (await db.execute(
        select(AriesNotification)
        .where(AriesNotification.key == key, AriesNotification.disposition == "delivered")
        .order_by(AriesNotification.id.desc()).limit(1)
    )).scalar_one_or_none()


async def decide(db: AsyncSession, *, key: str, level: Level, severity: Severity, config: dict,
                 now: datetime | None = None, repeat_cooldown_hours: int = 6) -> Decision:
    """Apply the three gates. Reads only; `emit` is what records.

    TWO CLOCKS, deliberately. Quiet hours are a statement about the user's day,
    so they are judged in LOCAL time. The repeat cooldown is arithmetic against
    `created_at`, which the database writes in UTC, so it is judged in UTC.

    Using one clock for both is a real bug and not a cosmetic one: with local
    time on a UTC+2 machine an age of seconds reads as two hours, and west of
    UTC it reads as negative — which makes the repeat gate fail OPEN and
    re-notify every pass, exactly the noise the gate exists to prevent.
    """
    now = now or datetime.now()          # local — for quiet hours
    now_utc = datetime.utcnow()          # UTC — for age against created_at
    minimum = LEVEL_BY_NAME.get(str(config.get("notifications.minimum_level", "important")),
                                Level.IMPORTANT)

    if level <= Level.BACKGROUND:
        return Decision(level, "logged", "background — recorded, never shown")

    if level < minimum:
        return Decision(level, "held_below_threshold",
                        f"{level.label} is below the configured minimum ({minimum.label})")

    # Repeat gate before quiet hours: a repeat is a repeat at any hour, and
    # checking it first keeps the recorded reason the honest one.
    previous = await _last_delivered(db, key)
    if previous is not None:
        age = now_utc - (previous.created_at or now_utc)
        worsened = severity > Severity(previous.severity)
        if timedelta(0) <= age < timedelta(hours=repeat_cooldown_hours) and not worsened:
            mins = age.total_seconds() / 60
            ago = f"{mins:.0f} min" if mins < 90 else f"{mins / 60:.1f}h"
            return Decision(level, "suppressed_repeat",
                            f"already delivered {ago} ago and no worse since")

    if level < Level.CRITICAL and in_quiet_hours(
            now, config.get("notifications.quiet_hours_start", "22:00"),
            config.get("notifications.quiet_hours_end", "07:00")):
        return Decision(level, "held_quiet_hours",
                        "quiet hours — held for the next briefing; only critical interrupts")

    return Decision(level, "delivered", "above threshold, outside quiet hours, not a repeat")


async def emit(db: AsyncSession, *, key: str, title: str, severity: Severity, source: str = "",
               body: str | None = None, config: dict | None = None, level: Level | None = None,
               now: datetime | None = None) -> tuple[Decision, AriesNotification]:
    """Decide and record in one step. Caller commits."""
    config = config or {}
    level = level if level is not None else SEVERITY_TO_LEVEL.get(severity, Level.BRIEFING)
    decision = await decide(db, key=key, level=level, severity=severity, config=config, now=now)
    row = AriesNotification(key=key, source=source, level=int(decision.level), severity=int(severity),
                            title=title[:300], body=body, disposition=decision.disposition,
                            reason=decision.reason[:300])
    db.add(row)
    await db.flush()
    return decision, row


async def pending_for_briefing(db: AsyncSession, *, since_hours: int = 24) -> list[AriesNotification]:
    """Everything held back for the next briefing — what automation 01 collects."""
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    rows = (await db.execute(
        select(AriesNotification)
        .where(AriesNotification.created_at >= cutoff,
               AriesNotification.disposition.in_(("held_quiet_hours", "held_below_threshold")))
        .order_by(AriesNotification.level.desc(), AriesNotification.id.desc())
    )).scalars().all()
    return list(rows)
