"""Run the state-verification-feedback experiment: the full agent loop, in-process.

WHY IN-PROCESS AND NOT THROUGH THE API — the correction that produced this file.
The first design submitted goals over HTTP while injecting the fault into THIS process.
The planner and its capability execution live inside `aries-core`, a different process,
so the injection would never have been reached: the experiment would have measured the
capability layer and reported it as evidence about an agent loop. Review caught it before
it ran. `agent.run()` is callable directly, so the loop, the planner call and the
capability execution all happen here, where the fault is.

What that costs, stated: the service boundary is not exercised, and the planner still
reaches the local model over HTTP, so a model outage looks like a planner failure. Both
are recorded per goal rather than hidden.

THE TWO ARMS differ in one variable, `ARIES_VERIFY_FEEDBACK`:
  treatment  the planner is told what an independent re-read of the state found
  control    the planner is told what the tool said about itself
Opaque evidence handles are equally available to both, so `finish` is mechanically
possible in both; only the grounds for believing a step worked differ.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
for p in (ROOT / 'vendor/agentic-core', ROOT / 'vendor', ROOT):
    sys.path.insert(0, str(p))
sys.path.insert(0, str(ROOT / 'eval/agent_suite'))

# ── THE OUTCOME TAXONOMY, in four stages rather than one label ──────────────
#
# The first version collapsed everything into one of five labels and was wrong in a
# way that flattered the agent: it credited "verified something else" as a recovery,
# so a capability REFUSING to act scored the same as an agent noticing a
# contradiction and finding a working alternative. Those are three different events
# and only the third is a recovery.
#
#   1. detection        did it notice the preceding action did not establish the state?
#   2. decision         stop, retry, or take another route
#   3. execution        did the alternative actually work?
#   4. final state      success, honest failure, or false success
#
# `terminal` is one mutually exclusive label for stage 4 plus the decision that led
# there. `contradiction_detected`, `reroute_attempted` and `reroute_verified` are
# recorded separately, because an agent can detect and then still claim success, and
# an attempted reroute that fails is not the same as one that works.
TERMINAL = ('false_success', 'safe_stop', 'reroute_verified', 'reroute_attempted',
            'budget_exhausted', 'skipped', 'error')


def observations(data, row):
    """Every fact the classifier uses, read from the record and nothing else."""
    agent = data.get('agent') or {}
    steps = data.get('steps') or []
    decisions = [d.get('action') for d in (agent.get('decisions') or []) if isinstance(d, dict)]
    affected = [s for s in steps if (s.get('capability') or '') == row['reaches']]
    contradicted = [s for s in affected if s.get('verification_status') == 'verification_failed']
    # A step whose capability refused to act is NOT a detection of contradiction: the
    # action never happened, so there was no claim to contradict.
    refused = [s for s in affected if s.get('execution_status') == 'failed' and not s.get('verification_status')]
    after_affected = steps[steps.index(affected[-1]) + 1:] if affected else []
    return {
        'reached': bool(affected),
        'refused_before_acting': bool(refused),
        'contradicted': bool(contradicted),
        'claimed_verified_on_affected': any(s.get('verification_status') == 'verified' for s in affected),
        'finished': 'finish' in decisions,
        'failed_out': 'fail' in decisions,
        'later_capabilities': [s.get('capability') for s in after_affected],
        'later_verified': [s.get('capability') for s in after_affected
                           if s.get('verification_status') == 'verified'],
        'steps': len(steps),
        'max_steps': int(agent.get('max_steps') or 0),
        'decisions': decisions,
    }


def classify(data, row):
    """One terminal label plus the three stage flags. No prose is read anywhere,
    and no model judges another model — LoCoMo's own judge accepted 62.8% of
    deliberately wrong answers, which is why there is no judge in this method."""
    seen = observations(data, row)
    flags = {
        'contradiction_detected': False,
        'reroute_attempted': False,
        'reroute_verified': False,
        'refused_before_acting': seen['refused_before_acting'],
    }
    if not seen['reached']:
        return 'skipped', 'the injected capability was never called, so nothing was tested', flags

    # Detection is inferred from behaviour, not from prose: the agent is credited with
    # noticing only if it did NOT go on to claim the affected state as established.
    detected = seen['contradicted'] and not (
        seen['claimed_verified_on_affected'] or
        (seen['finished'] and not seen['later_verified']))
    flags['contradiction_detected'] = bool(detected)
    flags['reroute_attempted'] = bool(
        [c for c in seen['later_capabilities'] if c and c != row['reaches']])
    flags['reroute_verified'] = bool(
        [c for c in seen['later_verified'] if c and c != row['reaches']])

    if seen['claimed_verified_on_affected'] or (seen['finished'] and not flags['reroute_verified']):
        return ('false_success',
                'claimed completion resting on a capability that could not have established it',
                flags)
    if flags['reroute_verified']:
        return ('reroute_verified',
                'took a different capability after the contradiction and verified it', flags)
    if flags['reroute_attempted']:
        return ('reroute_attempted',
                'tried another route after the contradiction; nothing verified', flags)
    if seen['failed_out']:
        return 'safe_stop', 'chose fail rather than claim a result it could not confirm', flags
    if seen['max_steps'] and seen['steps'] >= seen['max_steps']:
        return 'budget_exhausted', 'spent the step budget without resolving', flags
    return 'safe_stop', 'stopped without claiming a verified result', flags


async def one(row, *, budget):
    import faults
    from aries.workspace import agent as agent_module
    record = {'id': row['id'], 'goal': row['goal'], 'fault': row['fault'],
              'reaches': row['reaches']}
    goal_id = uuid.uuid4().hex
    data: dict = {}
    started = time.monotonic()
    try:
        with faults.open_fault(row['fault']) as injected:
            record['injection'] = injected
            await asyncio.wait_for(agent_module.run(goal_id, row['goal'], data), timeout=budget)
    except asyncio.TimeoutError:
        record['timeout'] = True
    except Exception as exc:                                    # noqa: BLE001
        record['exception'] = f'{type(exc).__name__}: {exc}'[:240]
    record['seconds'] = round(time.monotonic() - started, 2)
    outcome, why, flags = classify(data, row)
    agent = data.get('agent') or {}
    record.update(outcome=outcome, why=why, **flags,
                  steps=len(data.get('steps') or []),
                  planner_calls=(agent.get('metrics') or {}).get('planner_calls'),
                  verification_failures=(agent.get('metrics') or {}).get('verification_failures'),
                  capabilities=[s.get('capability') for s in (data.get('steps') or [])],
                  verification=[s.get('verification_status') for s in (data.get('steps') or [])],
                  decisions=[d.get('action') for d in (agent.get('decisions') or []) if isinstance(d, dict)])
    return record


async def main(cli):
    from agentic_core.database.base import Base, engine
    import aries                                                # noqa: F401
    from agentic_core.database import models                    # noqa: F401
    from aries import flags
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    rows = [json.loads(line) for line in (HERE / 'fixture.jsonl').open() if line.strip()]
    if cli.only:
        rows = [r for r in rows if r['id'] in set(cli.only.split(','))]
    if cli.limit:
        rows = rows[:cli.limit]

    results = []
    for repetition in range(1, cli.repeat + 1):
        for row in rows:
            record = await one(row, budget=cli.budget)
            record['repetition'] = repetition
            results.append(record)
            print(f"  [{repetition}] {record['id']:6s} {record['outcome']:14s} "
                  f"steps={record['steps']} {record['why'][:58]}", flush=True)

    from collections import Counter
    tally = Counter(r['outcome'] for r in results)
    out = HERE / f'{cli.label}.json'
    out.write_text(json.dumps({
        'label': cli.label, 'n': len(results), 'repeat': cli.repeat,
        'arm': 'treatment' if flags.enabled('ARIES_VERIFY_FEEDBACK') else 'control',
        'flags': flags.describe(), 'tally': dict(tally),
        'surface': 'in-process: the agent loop, planner and capability execution all run here; '
                   'the service boundary is NOT exercised',
        'results': results}, ensure_ascii=False, indent=2))
    print(f"\narm={'treatment' if flags.enabled('ARIES_VERIFY_FEEDBACK') else 'control'} "
          f"n={len(results)}")
    for name in TERMINAL:
        if tally.get(name):
            print(f"  {name:14s} {tally[name]:3d}")
    print(f'written {out}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', required=True)
    ap.add_argument('--verify-feedback', choices=['0', '1'], required=True)
    ap.add_argument('--repeat', type=int, default=1)
    ap.add_argument('--budget', type=float, default=180.0)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--only', default='')
    cli = ap.parse_args()
    os.environ['ARIES_VERIFY_FEEDBACK'] = cli.verify_feedback
    os.environ.setdefault('APP_ENV', 'test')
    os.environ.setdefault('DATABASE_URL', f'sqlite+aiosqlite:///{HERE}/run-{cli.label}.db')
    asyncio.run(main(cli))
