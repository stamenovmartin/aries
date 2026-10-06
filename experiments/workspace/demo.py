"""Demonstrate the real API; preserve failures and independently check file effects."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error
import uuid

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', action='store_true', help='Skip desktop/network/model cases')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    out = ROOT / 'experiments' / 'demo' / stamp
    out.mkdir(parents=True)
    files = Path.home() / 'Documents' / ('ARIES-Demo-' + stamp)
    report = {'run': stamp, 'mode': 'core' if args.core else 'full', 'cases': [],
              'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
              'scope': 'Installed-system acceptance, not a controlled agent benchmark.'}
    digest = hashlib.sha256()
    for directory in ('aries', 'aries_ui', 'shell'):
        for path in sorted((ROOT / directory).rglob('*')):
            if path.is_file() and path.suffix in {'.py', '.js', '.css'}:
                digest.update(str(path.relative_to(ROOT)).encode() + b'\0' + path.read_bytes())
    report['source_sha256'] = digest.hexdigest()

    def api(method, path, body=None):
        headers = {'Content-Type': 'application/json'}
        request = urllib.request.Request(os.environ.get('ARIES_API', 'http://127.0.0.1:8000') + '/api/aries' + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'HTTP {exc.code}: {exc.read(2000).decode()}') from exc

    def save():
        report['passed'] = sum(c['passed'] for c in report['cases'])
        report['total'] = len(report['cases'])
        (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        lines = ['# ARIES demo evidence', '', f"Run: {stamp}", '',
                 '| Case | Passed | Seconds |', '|---|---|---:|']
        lines += [f"| {c['name']} | {c['passed']} | {c['seconds']} |" for c in report['cases']]
        lines += ['', f"{report['passed']}/{report['total']} acceptance checks passed.", '', report['scope'],
                  'See results.json for goal IDs, observed outcomes and failures. Demo files are retained in ' + str(files)]
        (out / 'README.md').write_text('\n'.join(lines) + '\n')

    def check(name, action, verify):
        start = time.monotonic()
        item = {'name': name}
        try:
            result = action()
            item.update(result=result, passed=bool(verify(result)))
        except Exception as exc:
            item.update(passed=False, error=f'{type(exc).__name__}: {exc}')
        item['seconds'] = round(time.monotonic() - start, 3)
        report['cases'].append(item)
        save()
        print(f"{name}: {'PASS' if item['passed'] else 'FAIL'} ({item['seconds']}s)", flush=True)

    def goal(capability=None, values=None, request=None):
        body = {'request': request} if request else {'capability': capability, 'args': values or {}}
        queued = api('POST', '/workspace', body)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            snapshot = api('GET', '/workspace?goal_id=' + queued['id'])
            row = next(g for g in snapshot['goals'] if g['id'] == queued['id'])
            if row['state'] == 'proposed' and capability == 'agent_task':
                pending = next((s for s in row.get('steps',[]) if s.get('state')=='proposed'),{})
                if pending.get('capability') == 'browser.open' and pending.get('args') == {'url':'https://www.python.org'}:
                    # This demo explicitly requests this public page. Keep the
                    # user confirmation setting; approve only this frozen action.
                    api('POST','/workspace/'+queued['id']+'/approve',{})
                    continue
            if row['state'] not in {'queued', 'running'}:
                return row
            time.sleep(0.5)
        # Cancel only this runner's goal; never leave a timed-out demo working invisibly.
        api('POST', '/workspace/' + queued['id'] + '/cancel', {})
        raise TimeoutError('Demo deadline exceeded; cancellation requested for ' + queued['id'])

    done = lambda r: r.get('state') == 'done'
    check('create folder', lambda: goal('create_folder', {'path': str(files)}), lambda r: done(r) and files.is_dir())
    note = files / 'demo.txt'
    content = 'ARIES demo: independently verified file content.\n'
    check('create file', lambda: goal('create_file', {'path': str(note), 'content': content}),
          lambda r: done(r) and note.read_text() == content)
    check('three-step workflow', lambda: goal(request=f'read file {note}; list folder {files}; system status'),
          lambda r: done(r) and len(r['steps']) == 3 and all(s['state'] == 'done' for s in r['steps']))
    check('negative control: missing file', lambda: goal('read_file', {'path': str(files / 'missing.txt')}),
          lambda r: r['state'] == 'failed' and not (files / 'missing.txt').exists())
    check('health automation', lambda: api('POST', '/automations/aries.health/run', {'force': True}),
          lambda r: r.get('ran') is True and r.get('status') == 'ok')
    versions = api('GET', '/settings/workspace.review_retrieval')['definition']['choices']
    check('learning comparison', lambda: goal('learning_eval'),
          lambda r: done(r) and set(r['steps'][0]['result']['comparison']['versions']) == set(versions))
    check('operational evaluation', lambda: goal('evaluation'), done)
    if not args.core:
        check('open application', lambda: goal('open_app', {'app': 'Firefox'}), done)
        check('news workflow', lambda: goal('refresh_news'), done)
        check('morning brief', lambda: goal('brief'), done)
        check('agent observes page title', lambda: goal('agent_task',
              {'task': 'Open https://www.python.org and report the page title'}), done)
    print('Evidence: ' + str(out / 'README.md'), flush=True)
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
