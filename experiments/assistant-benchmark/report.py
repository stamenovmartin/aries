"""Summarize frozen live runs without hiding incomplete runs or failed cases."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def summarize(path):
    data = json.loads(path.read_text())
    groups = defaultdict(lambda: {'passed': 0, 'n': 0})
    for case in data['cases']:
        for key in ('all', 'category:' + case['category'], 'language:' + case['language']):
            groups[key]['n'] += 1
            groups[key]['passed'] += case['passed'] is True
    return {
        'artifact': str(path),
        'artifact_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'started_at': data['started_at'],
        'finished_at': data.get('finished_at'),
        'fixture_sha256': data['fixture_sha256'],
        'complete': bool(data.get('finished_at') and len(data['cases']) == 60),
        'runtime_changed': data.get('runtime_changed'),
        'paused_for_approval': data.get('paused_for_approval'),
        'groups': dict(groups),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--monograph', type=Path)
    parser.add_argument('--environment-changed', action='store_true')
    parser.add_argument('--limitation', action='append', default=[])
    args = parser.parse_args()
    before, after = summarize(args.before), summarize(args.after)
    comparable = (before['complete'] and after['complete']
                  and before['runtime_changed'] is False
                  and after['runtime_changed'] is False
                  and before['fixture_sha256'] == after['fixture_sha256']
                  and before['started_at'][:10] == after['started_at'][:10])
    result = {'before': before, 'after': after, 'paired_fixture_complete': comparable,
              'comparable': comparable and not args.environment_changed,
              'environment_changed': args.environment_changed,
              'limitations': ['60 scoped trials, not overall assistant maturity.',
                              'Generic HTTP refusal and unstructured clarification are not credited.',
                              'File and package cases do not test adaptive planning or ASR.',
                              'Runtime stability covers the recorded core invocation and source hashes only; other clients are not isolated. No causal latency claim.',
                              'No 48-hour stability or acoustic playback acceptance claim.', *args.limitation]}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    rows = ['# Frozen live goal benchmark', '',
            f"Before: {before['started_at']}; after: {after['started_at']}.",
            f'Complete, stable, same-day pair: {comparable}.', '',
            f"Comparable environment: {not args.environment_changed}.", '',
            '| Group | Before (n) | After (n) |', '|---|---:|---:|']
    for key in sorted(before['groups'].keys() | after['groups'].keys()):
        b = before['groups'].get(key, {'passed': 0, 'n': 0})
        a = after['groups'].get(key, {'passed': 0, 'n': 0})
        rows.append(f"| {key} | {b['passed']}/{b['n']} | {a['passed']}/{a['n']} |")
    rows += ['', *result['limitations'], '']
    rendered = '\n'.join(rows)
    (args.output / 'REPORT.md').write_text(rendered)
    if args.monograph:
        start = '<!-- ASSISTANT-BENCHMARK:START -->'
        end = '<!-- ASSISTANT-BENCHMARK:END -->'
        block = start + '\n' + rendered + '\n' + end
        previous = args.monograph.read_text()
        if start in previous:
            previous = previous[:previous.index(start)] + block + previous[previous.index(end) + len(end):]
        else:
            previous += '\n\n' + block + '\n'
        args.monograph.write_text(previous)
    print(json.dumps(result, ensure_ascii=False))
