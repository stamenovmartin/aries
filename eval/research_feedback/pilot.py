"""Run one paired exploratory pass; preserve every assignment and raw artifact.

Not a confirmatory 600-run launcher. Native and synthetic surfaces stay separate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

from case_tools import cases

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-file-controls', action='store_true')
    parser.add_argument('--resume', type=Path, help='Resume an interrupted pilot results.json, preserving assignments')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = HERE / 'pilots' / stamp
    rng = random.Random(20261004)
    assignments = []
    for case, row in cases().items():
        arms = ['tool_only', 'structured']
        rng.shuffle(arms)
        for condition in arms:
            assignments.append({'case': case, 'condition': condition, 'fault': row['fault'],
                                'surface': 'controlled_screen_fixture' if row['reaches'].startswith('screen.') else 'native_read_only'})
    if args.include_file_controls:
        for fault in ('none', 'stale_read'):
            for arm in ('tool_only', 'structured'):
                assignments.append({'case': 'owned_files', 'condition': arm, 'fault': fault, 'surface': 'owned_files'})
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'purpose': 'exploratory feasibility pilot',
              'schedule_seed': 20261004, 'model_seed': None, 'confirmatory': False,
              'assigned_n': len(assignments), 'assignments': assignments, 'episodes': [],
              'launch_ready': False, 'pilot_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if args.resume:
        path = args.resume.resolve()
        if not path.is_relative_to(HERE / 'pilots'):
            parser.error('--resume must reference a saved research pilot')
        report = json.loads(path.read_text())
        assignments = report['assignments']
        report.pop('paused_reason', None)
        report['resumed_at'] = datetime.now(timezone.utc).isoformat()
    else:
        directory.mkdir(parents=True)
        path = directory / 'results.json'

    def save():
        path.write_text(json.dumps(report, indent=2) + '\n')

    save()
    for index in range(len(report['episodes']), len(assignments)):
        assignment = assignments[index]
        # Protect the other owner's measurement rather than compete for inference.
        processes = subprocess.run(['ps', '-eo', 'comm=,args='], capture_output=True, text=True, check=True).stdout
        if any(line.split()[0].startswith('python') and 'eval/agent_suite/run.py' in line
               for line in processes.splitlines() if line.split()):
            report['paused_reason'] = 'Another agent_suite measurement is active; unrun assignments retained'
            save()
            print(report['paused_reason'], flush=True)
            return 2
        command = [sys.executable, str(HERE / 'run_loop.py'), '--condition', assignment['condition'], '--timeout', '90']
        if assignment['case'] == 'owned_files':
            command += ['--fault', assignment['fault']]
        else:
            command += ['--case', assignment['case']]
            if assignment['surface'] == 'controlled_screen_fixture':
                command += ['--controlled-screen']
        episode = {**assignment, 'index': index + 1}
        try:
            run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120,
                                 env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            envelope = json.loads(run.stdout.strip().splitlines()[-1])
            artifact = Path(envelope['artifact'])
            raw = json.loads(artifact.read_text())
            episode.update(artifact=str(artifact), artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                           exit_code=run.returncode, settings=raw.get('settings'),
                           source_before=raw.get('source_before'), source_after=raw.get('source_after'))
            for key in ('outcome', 'error', 'skip_reason', 'final_state', 'oracle_met', 'unsupported_model_claims',
                        'user_visible_false_success', 'fault_reached', 'planner_exposed_to_fault',
                        'affected_verification_available_to_planner', 'post_action_feedback_exposed',
                        'contradiction_detected', 'completed_recovery', 'model_chose_stop', 'runtime_stop_reason',
                        'source_stable', 'valid_for_comparison', 'latency_s', 'final_answer_adjudication'):
                episode[key] = raw.get(key)
            episode['first_post_fault_decision'] = raw.get('first_post_fault_decision')
            episode['metrics'] = raw.get('trace', {}).get('agent', {}).get('metrics', {})
            episode['llm_calls'] = len(raw.get('prompts', []))
        except (subprocess.TimeoutExpired, ValueError, KeyError, IndexError, OSError) as exc:
            episode.update(outcome='pilot_infrastructure_error', error=f'{type(exc).__name__}: {exc}')
        report['episodes'].append(episode)
        save()
        print(f"{index + 1}/{len(assignments)} {assignment['case']} {assignment['condition']}: "
              f"{episode.get('outcome')} claims={episode.get('unsupported_model_claims')}", flush=True)
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    groups = []
    for surface in sorted({x['surface'] for x in assignments}):
        for arm in ('tool_only', 'structured'):
            rows = [r for r in report['episodes'] if r['surface'] == surface and r['condition'] == arm]
            scored = [r for r in rows if r.get('oracle_met') is not None and not r.get('error')]
            groups.append({'surface': surface, 'condition': arm, 'assigned_n': len(rows), 'scored_n': len(scored),
                           'skipped_n': sum(r.get('outcome') == 'skipped' for r in rows),
                           'error_n': sum(bool(r.get('error')) for r in rows),
                           'episodes_with_unsupported_claim': sum((r.get('unsupported_model_claims') or 0) > 0 for r in scored),
                           'user_visible_false_success': sum(r.get('user_visible_false_success') is True for r in scored),
                           'goal_completed': sum(r.get('oracle_met') is True for r in scored),
                           'verified_recovery': sum(r.get('completed_recovery') is True for r in scored),
                           'model_chose_stop': sum(r.get('model_chose_stop') is True for r in scored),
                           'verification_opportunity_n': sum(r.get('affected_verification_available_to_planner') is True for r in rows)})
    report['groups'] = groups
    report['source_stable_across_episodes'] = (all(r.get('source_stable') is True for r in report['episodes'])
        and len({json.dumps(r.get('source_before'), sort_keys=True) for r in report['episodes']}) == 1)
    report['settings_stable_across_episodes'] = len({json.dumps(r.get('settings'), sort_keys=True) for r in report['episodes']}) == 1
    report['launch_blockers'] = ['Mixed native and returned-artifact interventions; do not pool',
        'Free-form final screen descriptions require human adjudication',
        'Native fault cases may refuse before independent verification; inspect opportunity counts',
        'A pilot is development data, not a confirmatory result; freeze revised protocol before launch']
    save()
    print(path, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
