"""Task 2.1: per-goal terminal-state extraction for the held-out run (read-only).

Reads the frozen result file and the matching rows of aries_workspace_goals
(opened with mode=ro). Writes goals.json next to this script. No code under
aries/ is imported, so the extraction cannot be affected by the follow-up patch.

    python3 -I extract.py <fixture_run.json> <aries.db> <out.json>
"""
import collections
import hashlib
import json
import sqlite3
import sys


def end_path(state, agent, summary):
    """Which branch of aries/workspace/agent.py ended the goal (snapshot 479e746)."""
    checks = agent.get('completion_checks') or []
    if state == 'proposed':
        return 'awaiting_approval'
    if state in ('done', 'answered'):
        return state
    if agent.get('stop_reason') == 'REQUESTED_FILE_NOT_FOUND':
        return 'terminal_read_failure'
    if summary.startswith('Planner stopped:'):
        return 'planner_fail'
    if summary.startswith('Planner decision retry/call budget exhausted'):
        return 'invalid_decisions'
    if summary == 'Action budget exhausted without verified goal completion':
        return 'step_budget_exhausted'
    if checks and not checks[-1]['met'] and summary == (agent.get('completion_feedback') or ''):
        return 'rejected_finish'
    if 'budget' in summary.lower() or 'exceeded' in summary.lower():
        return 'resource_budget_exceeded'
    if summary == 'Bounded planner budget exhausted':
        return 'planner_call_limit'
    return 'other'


def main(run_path, db_path, out_path):
    raw = open(run_path, 'rb').read()
    run = json.loads(raw)
    c = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    goals = []
    for res in run['results']:
        row = c.execute('select state, request, result_json from aries_workspace_goals where id=?',
                        (res['task_id'],)).fetchone()
        state, goal, payload = row
        data = json.loads(payload or '{}')
        agent = data.get('agent', {})
        metrics = agent.get('metrics', {})
        decisions = agent.get('decisions', [])
        actions = [((d.get('decision') or {}).get('action') or ('INVALID' if not d.get('valid') else '?'))
                   for d in decisions]
        steps = data.get('steps', [])
        summary = agent.get('summary') or ''
        goals.append({
            'id': res['id'], 'class': res['class'], 'held_out': res['held_out'],
            'expected_outcome': res['expected_outcome'], 'verdict': res['verdict'],
            'task_id': res['task_id'], 'goal': goal,
            'terminal_state': state, 'result_file_state': res['terminal_state'],
            'end_path': end_path(state, agent, summary),
            'summary': summary[:600],
            'stop_reason': agent.get('stop_reason'),
            'completion_feedback': agent.get('completion_feedback'),
            'completion_checks': [{'met': x.get('met'), 'reason': x.get('reason')}
                                  for x in agent.get('completion_checks') or []],
            'planner_calls': metrics.get('planner_calls'), 'number_of_steps': len(steps),
            'max_steps': agent.get('max_steps'),
            'finish_proposed': 'finish' in actions, 'decision_actions': actions,
            'invalid_decisions': metrics.get('invalid_decisions'),
            'capability_failures': metrics.get('capability_failures'),
            'verification_failures': metrics.get('verification_failures'),
            'contract_supported': (agent.get('contract') or {}).get('supported'),
            'contract_reason': (agent.get('contract') or {}).get('reason'),
            'steps': [{'capability': s.get('capability'), 'args': s.get('args'),
                       'verification_status': s.get('verification_status'),
                       'error': {k: (s.get('error') or {}).get(k) for k in ('code', 'error_type', 'message')}
                                if s.get('error') else None} for s in steps],
        })
    out = {'source_run': run_path, 'source_run_sha256': hashlib.sha256(raw).hexdigest(),
           'database': db_path, 'n_goals': len(goals),
           'counts_by_terminal_state': dict(collections.Counter(g['terminal_state'] for g in goals)),
           'counts_by_end_path': dict(collections.Counter(g['end_path'] for g in goals)),
           'goals': goals}
    json.dump(out, open(out_path, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ('n_goals', 'counts_by_terminal_state', 'counts_by_end_path')}))


if __name__ == '__main__':
    main(*sys.argv[1:4])
