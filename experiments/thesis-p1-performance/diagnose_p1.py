#!/usr/bin/env python3
"""P1 exploratory diagnosis (designed after the P1 result; not registered): why each agent-suite goal that did
not pass did not pass.

    diagnose_p1.py   ->  diagnosis.json (refuses to overwrite)

Reads the three suite results and, read-only, the goal records of the installed system's database
(~/aries/var/aries.db) by the goal ids the suite recorded. Writes only goal ids, categories, outcomes and the
cause class with the error code or gap text that decided it; no memory, context or user text."""
import json
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = Path.home() / 'aries/var/aries.db'


def cause(goal, record):
    detail = goal.get('detail') or ''
    if 'blanked or locked' in detail or 'session is locked' in detail or 'Shell.Windows did not answer' in detail:
        return 'desktop session locked during the run', detail[:120]
    if record is None:
        return 'no goal record', ''
    r = json.loads(record or '{}')
    gaps = r.get('gaps') or []
    if any('exceeds planner budget' in g for g in gaps):
        return 'planner context over budget before the first decision', gaps[0]
    errors = [d.get('error') for d in (r.get('agent') or {}).get('decisions', []) if d.get('error')]
    if errors:
        e = errors[-1]
        kind = 'planner output failed validation' if e.get('error_type') == 'ValidationError' else 'planner error'
        return kind, f"{e.get('code')}: {(e.get('message') or '').splitlines()[0][:100]}"
    steps = r.get('steps') or []
    if any(isinstance(s.get('verification'), dict) and s['verification'].get('unverifiable') for s in steps):
        return 'action not independently verifiable', ''
    if 'systemd evidence' in detail:
        return 'step verified but its evidence did not reach the goal record', detail[:120]
    return 'other', detail[:120]


def main():
    dest = HERE / 'diagnosis.json'
    if dest.exists():
        raise SystemExit('REFUSED: diagnosis.json exists')
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    out = {'label': 'exploratory diagnosis, designed after the P1 result', 'runs': {}}
    for run in ('p1-run1', 'p1-run2', 'p1-run3'):
        d = json.loads((HERE / 'suite' / run / 'results.json').read_text())
        rows = []
        for g in d['goals']:
            if g['outcome'] == 'pass':
                continue
            rec = con.execute('select result_json from aries_workspace_goals where id=?',
                              (g.get('goal_id'),)).fetchone() if g.get('goal_id') else None
            c, why = cause(g, rec[0] if rec else None)
            rows.append({'id': g['id'], 'category': g['category'], 'outcome': g['outcome'], 'cause': c, 'evidence': why})
        out['runs'][run] = {'not_passed': len(rows), 'by_cause': dict(Counter(r['cause'] for r in rows)), 'goals': rows}
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + '\n')
    for run, v in out['runs'].items():
        print(run, v['not_passed'], v['by_cause'])


if __name__ == '__main__':
    main()
