"""Reversal detection: when a learned preference may be taken back.

The seven cases the requirement names, plus fatigue and provenance. Evidence is
constructed with real timestamps and real source attribution, because the whole
point of the classifier is telling apart situations that share an overall rate.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-reversal")

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.interests import service as interests  # noqa: E402
from aries.learning import evidence, history, reversal  # noqa: E402
from aries.learning.loop import apply, propose, run_pass, verdicts_for  # noqa: E402
from aries.learning.reversal import AriesReversal  # noqa: E402
from aries.news.models import AriesNewsItem, fingerprint  # noqa: E402
from aries.settings import SettingsService  # noqa: E402

WINDOW = 30


async def _seed(topic: str, plan: list[tuple[int, int, int, str]], *, tag: str = "") -> None:
    """plan: (days_ago, shown, engaged, source_id) — real timestamps, real sources."""
    now = datetime.utcnow()
    async with async_session() as db:
        for days_ago, shown, engaged, source in plan:
            when = now - timedelta(days=days_ago)
            for i in range(shown):
                db.add(AriesNewsItem(
                    item_id=fingerprint(topic, tag, source, str(days_ago), str(i)),
                    source_id=source, title=f"{topic} {days_ago}-{i}",
                    disposition="delivered", relevance=0.8,
                    matched_json=json.dumps([{"topic": topic, "weight": 0.8}]),
                    engaged=i < engaged, first_seen_at=when))
        await db.commit()


async def _setup(*, learned: float | None = 0.9, user: float | None = None, **settings):
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("learning.enabled", True, set_by="user")
        await s.set("learning.window_days", WINDOW, set_by="user")
        for k, v in settings.items():
            await s.set(k.replace("__", "."), v, set_by="user")
        await interests.add(db, topic="ai", weight=user)
        if learned is not None:
            await interests.learn(db, "ai", learned, confidence=0.9,
                                  rationale="established earlier")


async def _verdict_for(topic: str = "ai") -> dict:
    async with async_session() as db:
        props = await propose(db)
    return next((v for v in verdicts_for(props) if v["target"] == topic), {})


# ── 1. weak contradiction ───────────────────────────────────────────────────

async def test_weak_contradiction_changes_nothing():
    await _setup(learned=0.9)
    await _seed("ai", [(20, 8, 1, "s1"), (5, 4, 0, "s1")])     # 1/12 — few observations
    v = await _verdict_for()
    check("a thin contradiction is not a reversal",
          v["classification"] in (reversal.TEMPORARY, reversal.NOISE))
    check("and it says how much evidence reversing would need",
          "enough" in v["reason"] or "not contradict" in v["reason"])
    async with async_session() as db:
        row = await interests.get(db, "ai")
        pend = await reversal.pending(db, status=reversal.PENDING)
    check("the learned value is untouched", row.learned_weight == 0.9)
    check("and nothing is pending", pend == [])


# ── 2 & 3. strong, sustained contradiction ──────────────────────────────────

async def test_strong_sustained_contradiction_reverses_after_confirmation():
    await _setup(learned=0.9, learning__reversal_confirmations=2)
    # 2 of 60, spread across the window and recent in both halves.
    await _seed("ai", [(25, 15, 0, "s1"), (18, 15, 0, "s1"),
                       (8, 15, 0, "s1"), (2, 15, 0, "s1")])

    v = await _verdict_for()
    check("a strong, sustained contradiction is classified as such",
          v["classification"] == reversal.SUSTAINED)

    async with async_session() as db:
        props = await apply(db, await propose(db))
        pend = await reversal.pending(db, status=reversal.PENDING)
        row = await interests.get(db, "ai")
    check("the first pass does not reverse — it opens a pending reversal",
          len(pend) == 1 and pend[0].confirmations == 1)
    check("and changes nothing yet", row.learned_weight == 0.9)
    check("no proposal was made on the first pass",
          not [p for p in props if p.classification == reversal.SUSTAINED])

    async with async_session() as db:
        props = await apply(db, await propose(db))
        applied = await reversal.pending(db, status=reversal.APPLIED)
        row = await interests.get(db, "ai")
    check("the second confirming pass applies it", len(applied) == 1)
    check("the learned value moves down", row.learned_weight < 0.9)
    check("the proposal is marked as a reversal",
          any(p.classification == reversal.SUSTAINED for p in props))
    check("and says so in words",
          any("REVERSAL" in p.rationale for p in props))


# ── 4. alternating evidence ─────────────────────────────────────────────────

async def test_alternating_evidence_never_reverses():
    """The pending reversal is opened and withdrawn, repeatedly, and nothing moves."""
    await _setup(learned=0.9, learning__reversal_confirmations=2)
    await _seed("ai", [(25, 15, 0, "s1"), (18, 15, 0, "s1"),
                       (8, 15, 0, "s1"), (2, 15, 0, "s1")])
    async with async_session() as db:
        await apply(db, await propose(db))
        opened = await reversal.pending(db, status=reversal.PENDING)
    check("a contradiction opens a pending reversal", len(opened) == 1)

    # The user starts reading them again: the contradiction stops holding.
    async with async_session() as db:
        rows = (await db.execute(select(AriesNewsItem).where(
            AriesNewsItem.first_seen_at >= datetime.utcnow() - timedelta(days=12)))).scalars().all()
        for r in rows:
            r.engaged = True
        await db.commit()

    async with async_session() as db:
        await apply(db, await propose(db))
        still_pending = await reversal.pending(db, status=reversal.PENDING)
        abandoned = await reversal.pending(db, status=reversal.ABANDONED)
        row = await interests.get(db, "ai")
    check("the pending reversal is withdrawn when the contradiction stops",
          still_pending == [] and len(abandoned) == 1)
    check("the withdrawal records why", "withdrawn" in abandoned[0].reason)
    check("and the learned value never moved", row.learned_weight == 0.9)


# ── 5. context-specific reversal ────────────────────────────────────────────

async def test_contextual_collapse_blames_the_source_not_the_topic():
    await _setup(learned=0.9)
    # One source went bad; another is as good as ever.
    await _seed("ai", [(20, 20, 0, "bad-feed"), (6, 20, 0, "bad-feed"),
                       (20, 12, 12, "good-feed"), (6, 12, 12, "good-feed")])
    v = await _verdict_for()
    check("a one-sided collapse is classified as contextual",
          v["classification"] == reversal.CONTEXTUAL)
    check("and the reason names both sources",
          "bad-feed" in v["reason"] and "good-feed" in v["reason"])
    async with async_session() as db:
        row = await interests.get(db, "ai")
        pend = await reversal.pending(db, status=reversal.PENDING)
    check("the topic's weight is left alone", row.learned_weight == 0.9)
    check("and no reversal is opened", pend == [])


# ── 6. explicit override ────────────────────────────────────────────────────

async def test_an_explicit_user_weight_is_immutable():
    await _setup(learned=0.9, user=0.95, learning__reversal_confirmations=1)
    await _seed("ai", [(25, 20, 0, "s1"), (18, 20, 0, "s1"),
                       (8, 20, 0, "s1"), (2, 20, 0, "s1")])
    async with async_session() as db:
        await apply(db, await propose(db))
        await apply(db, await propose(db))
        row = await interests.get(db, "ai")
        effective = (await interests.score_text(db, "ai news")).score
    check("the user's weight is untouched by a reversal", row.weight == 0.95)
    check("and it is still what applies", effective == 0.95)
    check("while ARIES records its own, reversed, opinion", row.learned_weight < 0.9)

    async with async_session() as db:
        await interests.update(db, "ai", weight=None)
        after = (await interests.score_text(db, "ai news")).score
    check("clearing the override reveals the reversed learned value", after < 0.9)


# ── 7. recovery after a reversal ────────────────────────────────────────────

async def test_recovery_after_a_reversal():
    """Having been reversed down, a topic can rise again — with hysteresis
    applying in the other direction now."""
    await _setup(learned=0.9, learning__reversal_confirmations=1)
    await _seed("ai", [(25, 20, 0, "s1"), (18, 20, 0, "s1"),
                       (8, 20, 0, "s1"), (2, 20, 0, "s1")], tag="down")
    async with async_session() as db:
        await apply(db, await propose(db))
        low = (await interests.get(db, "ai")).learned_weight
    check("the topic is reversed downward", low < 0.9)

    # The user starts reading them again, decisively and across the window.
    async with async_session() as db:
        for r in (await db.execute(select(AriesNewsItem))).scalars().all():
            r.engaged = True
        await db.commit()
    async with async_session() as db:
        await apply(db, await propose(db))
        await apply(db, await propose(db))
        row = await interests.get(db, "ai")
        changes = await history.history(db, "ai")
    check("it recovers when the evidence turns back", row.learned_weight > low)
    check("and the turn is recorded as a reversal of the previous change",
          any(c.reversal for c in changes))


# ── fatigue ─────────────────────────────────────────────────────────────────

async def test_fading_interest_decays_rather_than_inverting():
    await _setup(learned=0.9)
    # Declining across every bucket, but still well above the ignored line.
    await _seed("ai", [(26, 12, 11, "s1"), (19, 12, 7, "s1"),
                       (12, 12, 3, "s1"), (3, 12, 1, "s1")])
    v = await _verdict_for()
    check("a steady decline is fatigue, not a reversal",
          v["classification"] == reversal.FATIGUE)
    check("and the reason says it is fading rather than gone", "fading" in v["reason"])
    async with async_session() as db:
        props = await apply(db, await propose(db))
        row = await interests.get(db, "ai")
    check("the weight decays by a small step", 0.8 <= row.learned_weight < 0.9)
    check("rather than jumping toward zero", row.learned_weight > 0.5)
    check("and the change is labelled fatigue",
          any(p.classification == reversal.FATIGUE for p in props))


# ── hysteresis is asymmetric ────────────────────────────────────────────────

async def test_reversing_needs_stricter_evidence_than_continuing():
    """The same evidence that would ESTABLISH a low weight is not enough to
    REVERSE a high one."""
    strict_cfg = {"learning.engaged_threshold": 0.4, "learning.ignored_threshold": 0.1,
                  "learning.reversal_hysteresis": 0.4, "learning.min_observations": 10,
                  "learning.reversal_min_observations_factor": 2.0,
                  "learning.established_margin": 0.1, "learning.fatigue_step": 0.05}

    # Fresh topic, no established position: the ordinary path applies.
    await _setup(learned=None)
    await _seed("ai", [(20, 20, 0, "s1"), (5, 20, 0, "s1")])    # 0/40
    async with async_session() as db:
        props = await apply(db, await propose(db))
        fresh = (await interests.get(db, "ai")).learned_weight
    check("with no established position, that evidence moves the weight down",
          fresh is not None and fresh < 0.6)

    # Exactly the same evidence, against an established high preference.
    await _setup(learned=0.9)
    await _seed("ai", [(20, 20, 0, "s1"), (5, 20, 0, "s1")])
    v = await _verdict_for()
    check("against an established preference the same evidence is not enough",
          v["classification"] != reversal.SUSTAINED)


# ── provenance ──────────────────────────────────────────────────────────────

async def test_every_change_carries_its_provenance():
    await _setup(learned=0.9, learning__reversal_confirmations=1)
    await _seed("ai", [(25, 20, 0, "s1"), (18, 20, 0, "s1"),
                       (8, 20, 0, "s1"), (2, 20, 0, "s1")])
    async with async_session() as db:
        await apply(db, await propose(db))
        change = (await history.history(db, "ai"))[0].as_dict()
        rev = (await reversal.pending(db, status=reversal.APPLIED))[0].as_dict()

    for field in ("from", "to", "direction", "confidence", "rationale", "scope",
                  "policy_version", "window_days", "interval", "at", "classification"):
        check(f"the change records '{field}'", field in change and change[field] is not None
              or field == "scope")
    check("the policy version is stamped", change["policy_version"] == reversal.POLICY_VERSION)
    check("the interval it decided from is kept", "lower" in change["interval"])

    for field in ("established", "proposed", "classification", "confidence", "window_days",
                  "observations", "interval", "evidence", "reason", "status",
                  "confirmations", "policy_version", "first_seen"):
        check(f"the reversal records '{field}'", field in rev)
    check("and it is marked applied", rev["status"] == reversal.APPLIED)


async def test_reversal_rate_is_honest_before_any_data():
    await reset_db()
    async with async_session() as db:
        r = await reversal.rate(db)
    check("with nothing recorded the rate is null", r["applied_rate"] is None)
    check("and it says why", r["reason"] == "no reversals suspected yet")


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
