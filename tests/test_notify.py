"""The notification policy: three gates between a finding and the user (§26)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-notify")

from datetime import datetime, timedelta  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.health.findings import Severity  # noqa: E402
from aries.notify import Level, decide, emit, in_quiet_hours, pending_for_briefing  # noqa: E402
from aries.notify.policy import AriesNotification  # noqa: E402

CFG = {"notifications.minimum_level": "important",
       "notifications.quiet_hours_start": "22:00", "notifications.quiet_hours_end": "07:00"}
NOON = datetime(2026, 9, 12, 12, 0)
NIGHT = datetime(2026, 9, 12, 23, 30)


async def test_level_gate():
    await reset_db()
    async with async_session() as db:
        d = await decide(db, key="a", level=Level.BRIEFING, severity=Severity.NOTICE,
                         config=CFG, now=NOON)
        check("a briefing item does not interrupt when the minimum is 'important'",
              d.disposition == "held_below_threshold")
        d = await decide(db, key="b", level=Level.IMPORTANT, severity=Severity.WARNING,
                         config=CFG, now=NOON)
        check("an important one does", d.delivered)
        d = await decide(db, key="c", level=Level.BACKGROUND, severity=Severity.OK,
                         config=CFG, now=NOON)
        check("background is only ever logged", d.disposition == "logged")


async def test_quiet_hours():
    check("23:30 is inside 22:00–07:00", in_quiet_hours(NIGHT, "22:00", "07:00"))
    check("03:00 is inside a window that wraps midnight",
          in_quiet_hours(datetime(2026, 9, 12, 3, 0), "22:00", "07:00"))
    check("12:00 is not", not in_quiet_hours(NOON, "22:00", "07:00"))
    check("a non-wrapping window works too",
          in_quiet_hours(datetime(2026, 9, 12, 10, 0), "09:00", "17:00"))
    check("start == end disables quiet hours entirely",
          not in_quiet_hours(NIGHT, "00:00", "00:00"))
    check("an unparsable time falls back rather than crashing",
          in_quiet_hours(NIGHT, "not a time", "07:00"))

    await reset_db()
    async with async_session() as db:
        d = await decide(db, key="q1", level=Level.IMPORTANT, severity=Severity.WARNING,
                         config=CFG, now=NIGHT)
        check("an important notification waits until morning",
              d.disposition == "held_quiet_hours")
        d = await decide(db, key="q2", level=Level.CRITICAL, severity=Severity.CRITICAL,
                         config=CFG, now=NIGHT)
        check("a critical one wakes the user anyway", d.delivered)


async def test_repeat_gate():
    """The gate that stops a monitor from becoming background noise."""
    await reset_db()
    async with async_session() as db:
        d1, _ = await emit(db, key="disk.full:/", title="/ is 94% full",
                           severity=Severity.WARNING, config=CFG, now=NOON)
        check("the first report is delivered", d1.delivered)
        await db.commit()

        d2, _ = await emit(db, key="disk.full:/", title="/ is 94% full",
                           severity=Severity.WARNING, config=CFG, now=NOON)
        check("the same finding minutes later is suppressed",
              d2.disposition == "suppressed_repeat")
        check("and the reason says how long ago", "ago" in d2.reason)
        await db.commit()

        d3, _ = await emit(db, key="disk.full:/", title="/ is 97% full",
                           severity=Severity.CRITICAL, config=CFG, now=NOON)
        check("but getting worse always breaks through", d3.delivered)
        await db.commit()

        d4, _ = await emit(db, key="other:/", title="something else",
                           severity=Severity.WARNING, config=CFG, now=NOON)
        check("a different finding is unaffected by another's cooldown", d4.delivered)


async def test_repeat_gate_uses_utc_not_local():
    """Regression: the age of a notification is arithmetic against created_at,
    which the database writes in UTC. Judging it in local time made a
    seconds-old notification look hours old, and would make it look NEGATIVE
    west of UTC — which fails open and re-notifies every single pass.

    `now=NOON` is not decoration. Without it this test used the real wall clock,
    so after 22:00 the first notification was held by quiet hours instead of
    delivered, the repeat gate had no delivered notification to find, and the
    test failed — every evening, and only in the evening. A test that depends on
    the time of day passes until it does not.
    """
    await reset_db()
    async with async_session() as db:
        await emit(db, key="k", title="t", severity=Severity.WARNING, config=CFG, now=NOON)
        await db.commit()
        d, _ = await emit(db, key="k", title="t", severity=Severity.WARNING, config=CFG,
                          now=NOON)
        check("a just-delivered notification is suppressed whatever the local offset",
              d.disposition == "suppressed_repeat")
        check("and its reported age is minutes, not hours",
              "min ago" in d.reason)


async def test_cooldown_expires():
    await reset_db()
    async with async_session() as db:
        old = AriesNotification(key="k", source="t", level=int(Level.IMPORTANT),
                                severity=int(Severity.WARNING), title="t", disposition="delivered",
                                reason="", created_at=datetime.utcnow() - timedelta(hours=9))
        db.add(old)
        await db.commit()
        d = await decide(db, key="k", level=Level.IMPORTANT, severity=Severity.WARNING,
                         config=CFG, now=NOON, repeat_cooldown_hours=6)
        check("past the cooldown, the same finding is reported again", d.delivered)


async def test_everything_is_recorded():
    """§29: nothing ARIES does may be invisible — including a decision to stay quiet."""
    await reset_db()
    async with async_session() as db:
        await emit(db, key="a", title="held", severity=Severity.NOTICE, config=CFG, now=NOON)
        await emit(db, key="b", title="night", severity=Severity.WARNING, config=CFG, now=NIGHT)
        await db.commit()
        held = await pending_for_briefing(db)
        check("suppressed notifications are still recorded", len(held) == 2)
        check("and are what the next briefing collects",
              {h.disposition for h in held} == {"held_below_threshold", "held_quiet_hours"})
        check("each records why it was held", all(h.reason for h in held))


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
