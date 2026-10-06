"""Read-only forensics on step verification, straight against the live database.

WHY a script and not `aries.analytics`: analytics answers "how many steps were
verified". This has to answer "which code path wrote the step, and did that path
have a verifier to invoke at all" — which means looking at the step's SHAPE
(which keys exist), not just its bucket. Same rows, different question.

Read-only, one snapshot per query, rolled back immediately: `aries-core.service`
is writing to this file and a held WAL read stops it checkpointing.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

DB = "file:/home/stamenovmartin/aries/var/aries.db?mode=ro"
# Same window as aries.analytics.core.Window() defaults, so the numbers are
# comparable to what `verification_honesty` printed.
DAYS, CAP = 7, 500


def cutoff(days=DAYS):
    return (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)).isoformat(sep=" ")


def connect():
    return sqlite3.connect(DB, uri=True, isolation_level=None, timeout=10)


def goals(days=DAYS, cap=CAP):
    c = connect()
    try:
        ids = [r[0] for r in c.execute(
            "SELECT id FROM aries_workspace_goals WHERE created_at >= ?"
            " ORDER BY created_at DESC LIMIT ?", (cutoff(days), cap))]
        rows = []
        for gid in ids:
            r = c.execute("SELECT id, state, created_at, result_json"
                          " FROM aries_workspace_goals WHERE id = ?", (gid,)).fetchone()
            if r:
                rows.append(r)
        return rows
    finally:
        c.close()


def bucket(step):
    """aries.analytics.core.STEP_BUCKET, in Python, same order."""
    vs, es, st = (step.get("verification_status"), step.get("execution_status"),
                  step.get("state"))
    if vs == "verified":
        return "verified"
    if vs == "verification_failed" or es == "failed":
        return "failed"
    if es == "planned":
        return "pending"
    if st == "unconfirmed":
        return "unconfirmed"
    if st in ("held", "proposed"):
        return "withheld"
    if st == "failed":
        return "failed"
    if st in ("done", "verified"):
        return "accepted"
    if st is None and es is None and vs is None:
        return "no_outcome_recorded"
    return "unclassified"


def engine(step):
    """Which of the three writers produced this step.

    The discriminator is the KEY SET, not the capability name: only the M14
    engines (orchestration.py / agent.py / recovery.py) ever write
    `execution_status`/`verification_status`; `capabilities.execute()` writes
    `state` + a nested `result`; legacy operator steps write `state` alone.
    """
    if "verification_status" in step or "execution_status" in step:
        return "m14_registry"
    k = step.get("kind")
    if k == "research":
        return "service_research"
    if k == "capability":
        return "catalogue_execute"
    if k == "desktop":
        return "legacy_operator"
    return "other:" + str(k)


def steps(rows):
    for gid, gstate, created, raw in rows:
        try:
            data = json.loads(raw or "{}")
        except (ValueError, TypeError):
            continue
        for s in data.get("steps") or []:
            if isinstance(s, dict):
                yield gid, created, s


def recoverable(step):
    """Is an independent verdict ALREADY in this step's record, unread?

    Three places a verdict is written today, none of them the top-level
    `verification_status` that `aries.analytics.core.STEP_BUCKET` reads:
      operator   `result.operator.verified_success` — the legacy operator engine
                 reserves outcome `done` for all-steps-verified and records the
                 per-step verdict, grade and what it checked
      catalogue  `result.verification.met` — the branches of
                 `capabilities.execute()` that do attach one
    Returns the name of the place, or "" when the record really holds no verdict.
    """
    r = step.get("result") if isinstance(step.get("result"), dict) else {}
    v = r.get("verification")
    if isinstance(v, dict) and v.get("met") is True:
        return "result.verification"
    op = r.get("operator") if isinstance(r.get("operator"), dict) else {}
    if op.get("verified_success") is True:
        return "result.operator.verified_success"
    return ""


def main():
    rows = goals()
    overall, per_cap, per_engine = Counter(), defaultdict(Counter), Counter()
    shape = defaultdict(Counter)          # capability -> which keys exist
    contradictions, verif_present = [], defaultdict(Counter)
    recover = defaultdict(Counter)
    n = 0
    for gid, created, s in steps(rows):
        n += 1
        cap = s.get("capability") or "(none)"
        b, e = bucket(s), engine(s)
        overall[b] += 1
        per_cap[cap][b] += 1
        per_engine[e] += 1
        shape[cap]["_n"] += 1
        shape[cap]["engine:" + e] += 1
        for key in ("verification_status", "execution_status", "state"):
            if key in s:
                shape[cap]["key:" + key] += 1
        if b in ("accepted", "unconfirmed"):
            recover[cap][recoverable(s) or "NO_VERDICT_RECORDED"] += 1
        res = s.get("result") if isinstance(s.get("result"), dict) else {}
        if "verification" in res:
            shape[cap]["result.verification"] += 1
            met = (res["verification"] or {}).get("met")
            verif_present[cap][f"met={met}"] += 1
        if s.get("verification_status") == "verification_failed":
            contradictions.append({
                "goal": gid, "created": created, "capability": cap,
                "step_id": s.get("step_id"), "args": s.get("args"),
                "execution_status": s.get("execution_status"),
                "error": s.get("error"), "observation": s.get("observation"),
                "execution_result": s.get("execution_result"),
                "evidence_refs": s.get("evidence_refs"),
            })
    out = {
        "database": DB, "snapshot_at": datetime.now().isoformat(timespec="seconds"),
        "window_days": DAYS, "goal_scan_cap": CAP,
        "goals_scanned": len(rows), "steps": n,
        "buckets": dict(overall), "by_engine": dict(per_engine),
        "looks_successful": sum(overall[k] for k in ("verified", "accepted", "unconfirmed")),
        "per_capability": {c: dict(b) for c, b in sorted(
            per_cap.items(), key=lambda kv: -sum(kv[1].values()))},
        "shape": {c: dict(v) for c, v in sorted(shape.items(), key=lambda kv: -kv[1]["_n"])},
        "result_verification_met": {c: dict(v) for c, v in verif_present.items()},
        "recoverable_on_unverified": {c: dict(v) for c, v in recover.items()},
        "contradictions": contradictions,
    }
    json.dump(out, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()
