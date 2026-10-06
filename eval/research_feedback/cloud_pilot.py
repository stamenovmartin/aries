"""Excluded cloud development pilot. Never starts the confirmatory 600 study."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    directory = HERE / 'cloud_pilots' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory.mkdir(parents=True)
    assignments = [dict(condition=arm, case=case, fault=fault)
                   for case, fault in ((None, 'none'), (None, 'stale_read'), ('vf-09', 'none'))
                   for arm in ('tool_only', 'structured')]
    report = {'purpose': 'excluded cloud development pilot', 'confirmatory': False,
              'provider': 'codex-cli', 'model': 'gpt-6-astra', 'model_seed': None,
              'terminal_examples': True, 'completion_progress_guard': True,
              'assigned_n': len(assignments), 'assignments': assignments, 'episodes': [],
              'reroute_verified': None, 'reroute_verified_status': 'unmeasurable',
              'started_at': datetime.now(timezone.utc).isoformat()}
    path = directory / 'results.json'

    def save():
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2) + '\n')
        temp.replace(path)

    save()
    print(path, flush=True)
    for index, assignment in enumerate(assignments, 1):
        command = [sys.executable, str(HERE / 'run_loop.py'), '--provider', report['provider'],
                   '--model', report['model'], '--condition', assignment['condition'],
                   '--fault', assignment['fault'], '--terminal-examples', '--timeout', '180']
        if assignment['case']:
            command += ['--case', assignment['case'], '--controlled-screen']
        episode = {'index': index, **assignment}
        try:
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=210,
                                 env={**os.environ, 'ARIES_COMPLETION_PROGRESS_GUARD': '1',
                                      'PYTHONDONTWRITEBYTECODE': '1'})
            artifact = Path(json.loads(run.stdout.strip().splitlines()[-1])['artifact'])
            raw = json.loads(artifact.read_text())
            episode.update(artifact=str(artifact.relative_to(ROOT)),
                           sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(), exit_code=run.returncode)
            for key in ('outcome', 'error', 'oracle_met', 'unsupported_model_claims', 'model_chose_stop',
                        'fault_reached', 'planner_exposed_to_fault', 'source_stable', 'valid_for_comparison',
                        'runtime_stop_reason', 'latency_s', 'user_visible_false_success'):
                episode[key] = raw.get(key)
            episode['calls'] = len(raw.get('prompts', []))
            episode['provider_identities'] = sorted({(p.get('usage', {}).get('provider', ''),
                                                       p.get('usage', {}).get('model', ''))
                                                      for p in raw.get('prompts', []) if 'usage' in p})
        except (subprocess.TimeoutExpired, ValueError, KeyError, IndexError, OSError) as exc:
            episode['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        report['episodes'].append(episode)
        save()
        print(json.dumps(episode), flush=True)
        if episode.get('error') or episode.get('source_stable') is not True:
            report['paused_reason'] = 'Provider/infrastructure failure or source change; unrun assignments preserved'
            save()
            return 2
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    save()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
