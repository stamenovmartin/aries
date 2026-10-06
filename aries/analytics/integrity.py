"""Recorded verification coverage and contradictions within an explicit goal sample.

The stored status is an outcome label, not proof that its verifier was independent
or falsifiable. Metrics expose actual scanned and eligible goal counts. Coverage
uses verified / (verified + accepted + unconfirmed); contradictions use
verification_failed / (verified + verification_failed), with separate denominators.
Neither a zero contradiction rate nor full recorded coverage proves correctness.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aries.analytics.core import GOAL_STEPS, STEP_BUCKET, Window, absent, metric, rate

LOOKS_SUCCESSFUL = ("verified", "accepted", "unconfirmed")


async def _scan_coverage(db, window, cutoff):
    total=int((await db.execute(text(
        'SELECT COUNT(*) FROM aries_workspace_goals WHERE created_at >= :cutoff'),
        {'cutoff':cutoff})).scalar() or 0)
    return {'goals_in_window':total, 'goals_scanned':min(total,window.goal_scan),
            'goal_scan_cap':window.goal_scan, 'cutoff_utc':cutoff,
            'truncated':total>window.goal_scan,
            'note':f'Only the {window.goal_scan} most recent of {total} goals were parsed; this is a sample, not a total'
                   if total>window.goal_scan else None,
            'verification_independence':'Recorded verification status alone does not establish verifier independence or falsifiability'}


@metric("verification_honesty", source="aries_workspace_goals.result_json (steps)",
        cost="one capped result_json parse, shared shape with outcomes_by_capability; "
             "~27 ms / 600 goals measured")
async def verification_honesty(db: AsyncSession, window: Window, *, top: int = 20) -> dict:
    """Accepted-but-not-verified, overall and per capability."""
    cutoff=window.cutoff
    scan=await _scan_coverage(db,window,cutoff)
    rows = (await db.execute(text(f"""
        WITH steps AS ({GOAL_STEPS})
        SELECT COALESCE(json_extract(step, '$.capability'), '(none)') AS cap,
               {STEP_BUCKET} AS bucket, COUNT(*) AS n
          FROM steps GROUP BY cap, bucket
    """), {"cutoff": cutoff, "cap": window.goal_scan})).all()
    if not rows:
        return {**absent("no steps were recorded in the scanned goals, so there is nothing to verify"), **scan}

    overall: dict[str, int] = {}
    per: dict[str, dict] = {}
    for cap, bucket, n in rows:
        overall[bucket] = overall.get(bucket, 0) + int(n)
        per.setdefault(cap, {})[bucket] = int(n)

    def coverage(b: dict) -> dict:
        looks = sum(b.get(k, 0) for k in LOOKS_SUCCESSFUL)
        return rate(b.get("verified", 0), looks,
                    of="steps that look successful (verified + accepted + unconfirmed)")

    caps = [{"capability": c, "buckets": b,
             "unverified": sum(b.get(k, 0) for k in ("accepted", "unconfirmed")),
             "coverage": coverage(b)}
            for c, b in per.items()]
    # Worst coverage first, biggest unverified count breaking ties: the reader
    # wants the capability doing the most unchecked work.
    caps.sort(key=lambda r: (r["coverage"].get("rate") if r["coverage"].get("rate") is not None
                             else 1.0, -r["unverified"]))
    looks = sum(overall.get(k, 0) for k in LOOKS_SUCCESSFUL)
    return {
        **scan,
        "n": sum(overall.values()), "buckets": overall,
        "looks_successful": looks,
        "unverified": looks - overall.get("verified", 0),
        "coverage": coverage(overall),
        # `failed` is every failure, not only the ones a verifier caught — the
        # verifier's own catches are counted by `verification_contradictions`,
        # and naming this field anything narrower would overstate the mechanism.
        "failed": overall.get("failed", 0),
        "no_outcome_recorded": overall.get("no_outcome_recorded", 0),
        "by_capability": caps[:top],
        "capability_count": len(caps),
        "means": "coverage is the share of apparently-successful sampled steps carrying a verified "
                 "status. This does not measure whether the verifier was independent or falsifiable",
    }


@metric("verification_contradictions", source="aries_workspace_goals.result_json (steps)",
        cost="one capped result_json parse, numerator and denominator in the same pass; "
             "~18 ms / 500 goals measured")
async def verification_contradictions(db: AsyncSession, window: Window) -> dict:
    """Steps where the verifier contradicted the executor.

    The value of independent verification, measured rather than asserted: each of
    these is a step that reported success to itself and would have been shown to
    the user as success by any engine without a verifier.
    """
    cutoff=window.cutoff
    scan=await _scan_coverage(db,window,cutoff)
    # Numerator and denominator in ONE pass: the CTE parses result_json, and
    # running it twice for two counts doubled this metric's cost (36 ms to 18 ms
    # measured on the live database).
    rows = (await db.execute(text(f"""
        WITH steps AS ({GOAL_STEPS})
        SELECT COALESCE(json_extract(step, '$.capability'), '(none)') AS cap,
               json_extract(step, '$.verification_status') AS vs, COUNT(*) AS n
          FROM steps
         WHERE json_extract(step, '$.verification_status') IN ('verified', 'verification_failed')
         GROUP BY cap, vs
    """), {"cutoff": cutoff, "cap": window.goal_scan})).all()
    verified = sum(int(n) for _, _, n in rows)
    caught = {cap: int(n) for cap, vs, n in rows if vs == 'verification_failed'}
    n = sum(caught.values())
    if verified == 0:
        return {**absent("no scanned step has a verified or verification_failed status; "
                         "this says nothing about unscanned goals or verifier independence"), **scan}
    return {**scan, "n": n, "by_capability": dict(sorted(caught.items(), key=lambda kv: -kv[1])) or None,
            "verified_or_contradicted": int(verified),
            "contradiction": rate(n, int(verified),
                                  of="steps that actually reached a verifier"),
            "means": "sampled steps with verification_failed among steps marked verified or "
                     "verification_failed. A zero rate does not establish executor correctness; "
                     "some verifiers may not be independent or falsifiable"}


@metric("approval_discipline", source="action_proposals + approval_requests + audit_events",
        cost="four queries over tables of 18, 16 and 17k rows. The audit LIKE has a leading "
             "wildcard and cannot use an index, but `at >= :cutoff` narrows first (EXPLAIN "
             "confirms SEARCH ... USING INDEX ix_audit_events_at), so it only ever scans the "
             "window. ~7 ms / 30-day window measured, and flat to 365 days")
async def approval_discipline(db: AsyncSession, window: Window) -> dict:
    """Did anything act without the approval it was supposed to wait for.

    A second integrity question, from a different table: proposals are frozen
    until a person decides, and `approval_requests` records the decision. A
    proposal in state `executed` with no approved request against it would be a
    gate that leaked. Reported as a count, and the count should be zero.
    """
    props = (await db.execute(text(
        "SELECT status, risk, COUNT(*) FROM action_proposals"
        " WHERE created_at >= :cutoff GROUP BY 1, 2"), {"cutoff": window.cutoff})).all()
    if not props:
        return absent("no action was proposed for approval in this window")
    decisions = (await db.execute(text(
        "SELECT decision, COUNT(*) FROM approval_requests"
        " WHERE requested_at >= :cutoff GROUP BY 1"), {"cutoff": window.cutoff})).all()
    leaked = (await db.execute(text(
        "SELECT COUNT(*) FROM action_proposals p"
        " WHERE p.created_at >= :cutoff AND p.status = 'executed'"
        "   AND NOT EXISTS (SELECT 1 FROM approval_requests a"
        "                    WHERE a.proposal_id = p.id AND a.decision = 'approved')"),
        {"cutoff": window.cutoff})).scalar() or 0
    withheld = (await db.execute(text(
        "SELECT COUNT(*) FROM audit_events WHERE at >= :cutoff AND action LIKE '%approve%'"),
        {"cutoff": window.cutoff})).scalar() or 0
    total = sum(int(n) for _, _, n in props)
    return {"n": total,
            "proposals": [{"status": s, "risk": r, "n": int(n)} for s, r, n in props],
            "decisions": {d: int(n) for d, n in decisions} or None,
            "executed_without_recorded_approval": int(leaked),
            "approval_audit_events": int(withheld),
            "means": "executed_without_recorded_approval should be 0. Anything else is a policy "
                     "gate that did not hold, which is more serious than any failure count "
                     "on this dashboard"}
