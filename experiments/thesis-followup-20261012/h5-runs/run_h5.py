#!/usr/bin/env python3
"""H5 runner: one condition, one run, on a fresh isolated ARIES instance.

docs/preregistration/H5-completion-paraphrase.md (Procedure, Amendments 1 and 2). Adapted from
experiments/thesis-followup-20261012/h4-runs/run_h4.py; the differences are:

- **Conditions.** treatment: ARIES_COMPLETION_READ_PARAPHRASE=1, ARIES_COMPLETION_TYPED_CONTRACT=1;
  control: both 0. In both, ARIES_PLANNER_CLARIFY, ARIES_PLANNER_CLARIFY_GUARD and ARIES_CLARIFY_RESOLVER are
  pinned 0, and the harness flag ARIES_MEASURE_CHANGE_HOOK is 1 (Amendment 1). Effective values are resolved
  in the instance's exact environment and the run refuses to start if any differs.
- **Live ARIES stopped.** The preregistration stops the live service, so its environment cannot be read from
  /proc during the run. `--capture-env` copies it once, while the service runs, to
  ~/.local/state/aries-h5/service-env (mode 600, outside the repository; it holds secrets and is never
  committed). The run refuses to start while aries-core is active or the screen can blank.
- **Sets.** G (h5-items/goals.jsonl, 15), N (h5-items/controls.jsonl, 10) and the 49 runnable held-out goals,
  in that order. Before anything is submitted, the unchanged validator is re-run on G and N into the run folder
  and must print PASS for the frozen SHA-256s (Amendment 2).
- **File-change hook.** For each `changed_after_read` control the goal is armed before it is submitted, and
  h5-runs/change_hook.py serves it while the goal runs (Amendment 1). If it never fired, manifest.after is
  the setup manifest and the record says fired: false.
- **Scoring** is run_fixtures.py's (same PREAMBLE, same checks, same verdict rule: exit 1 = genuine no, other
  non-zero = INCONCLUSIVE), plus the H5 outcomes: correct done = state done and verdict PASS; false done =
  done on an N item, or done on a G item whose oracle does not pass. The contract's source (fast path, typed,
  none) and the end path are recorded per item.

Nothing is submitted without --go. Every invocation writes a new folder; nothing is overwritten.

    run_h5.py --capture-env                                    # once, while aries-core runs
    run_h5.py --condition treatment --label r1 [--go]
    run_h5.py --condition control   --label r2 [--go]
    run_h5.py --condition treatment --label smoke --sets example --go   # example items only
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
FU = HERE.parent
ROOT = HERE.parents[2]
IA = ROOT / 'experiments/product/independent-acceptance'
ITEMS = FU / 'h5-items'
LIVE_DB = ROOT / 'var/aries.db'
SERVICE_ENV = pathlib.Path.home() / '.local/state/aries-h5/service-env'
FROZEN_ITEMS = {'goals.jsonl': '4cecf03fd3d0dc70125dfe76001af72600b2a1add9384f148cca818045613d58',
                'controls.jsonl': 'a47370363fac0b2f5f69fdac93d2acb86a519a730751ef8c85a3263dc3d8f142'}
PINNED = {'ARIES_PLANNER_CLARIFY': '0', 'ARIES_PLANNER_CLARIFY_GUARD': '0', 'ARIES_CLARIFY_RESOLVER': '0',
          'ARIES_MEASURE_CHANGE_HOOK': '1'}
CONDITIONS = {
    'treatment': {'ARIES_COMPLETION_READ_PARAPHRASE': '1', 'ARIES_COMPLETION_TYPED_CONTRACT': '1', **PINNED},
    'control': {'ARIES_COMPLETION_READ_PARAPHRASE': '0', 'ARIES_COMPLETION_TYPED_CONTRACT': '0', **PINNED},
}
TERMINAL = {'done', 'answered', 'failed', 'partial', 'refused', 'proposed', 'cancelled',
            'interrupted', 'error', 'needs_clarification'}
NOT_COPIED_PREFIXES = ('shell.', 'power.')
FORCED_OFF = ('connect.enabled', 'connect.attention_enabled', 'news.enabled', 'news.local_summaries',
              'briefing.morning_enabled', 'workspace.ai_briefings')
HOOK_TIMEOUT = 60


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RF = load(IA / 'run_fixtures.py', 'ia_run_fixtures')   # scoring helpers, unchanged
CH = load(HERE / 'change_hook.py', 'h5_change_hook')


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def ollama(path):
    with urllib.request.urlopen('http://127.0.0.1:11434' + path, timeout=20) as r:
        return json.load(r)


def model_digest(name='qwen2.5:7b'):
    return next(m['digest'] for m in ollama('/api/tags')['models'] if m['name'] == name)


def rows(path):
    return [json.loads(l) for l in pathlib.Path(path).read_text().splitlines() if l.strip()]


def cases_for(selection):
    """(set label, case) in a fixed order: G, N, held-out."""
    if selection == 'example':
        return [('example', r) for r in rows(ITEMS / 'example_items.jsonl')]
    out = [('G', r) for r in rows(ITEMS / 'goals.jsonl')] + [('N', r) for r in rows(ITEMS / 'controls.jsonl')]
    validation = json.loads((IA / 'raw/oracle_validation.json').read_text())
    discriminating = {c['id'] for c in validation['cases'] if c.get('verdict') == 'DISCRIMINATING'}
    out += [('heldout', c) for c in rows(IA / 'fixtures.jsonl') if c['id'] in discriminating and not c.get('requires')]
    return out


def capture_env():
    pid = subprocess.run(['systemctl', '--user', 'show', '-p', 'MainPID', '--value', 'aries-core.service'],
                         capture_output=True, text=True).stdout.strip()
    if not pid or pid == '0':
        raise SystemExit('REFUSED: aries-core is not running, so its environment cannot be captured')
    raw = pathlib.Path(f'/proc/{pid}/environ').read_bytes()
    SERVICE_ENV.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(SERVICE_ENV, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw)
    print(f'captured {raw.count(b"=")} variables to {SERVICE_ENV} (mode 600); values not printed')


def instance_env(run):
    if not SERVICE_ENV.exists():
        raise SystemExit('REFUSED: no captured service environment; run --capture-env while aries-core runs')
    env = dict(x.decode().split('=', 1) for x in SERVICE_ENV.read_bytes().split(b'\0') if b'=' in x)
    leaked = sorted(k for k in env if k.startswith('ARIES_') and k != 'ARIES_FLAG_FILE')
    for k in leaked:
        env.pop(k)
    env.update({
        'DATABASE_URL': 'sqlite+aiosqlite:///' + str(run / 'aries.sqlite3'),
        'DATA_DIR': str(run / 'var'), 'RUNTIME_STORE': str(run / 'var/runtime.json'),
        'CONTEXT_DIR': str(run / 'var/context'), 'ARIES_FLAG_FILE': str(run / 'flags.env'),
        'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_POLL_ENABLED': 'false', 'TELEGRAM_APPROVER_CHAT_ID': '',
        'PYTHONUNBUFFERED': '1',
    })
    return env, {'service_env_captured_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(SERVICE_ENV.stat().st_mtime)),
                 'removed_inherited_aries_vars': leaked}


INIT = r'''
import asyncio
async def main():
    import aries  # noqa: F401  registers ARIES tables
    from agentic_core.database import models  # noqa: F401
    from agentic_core.database.base import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
asyncio.run(main())
'''

FLAGS = r'''
import json
from aries import flags
print(json.dumps(flags.describe()))
'''


def initialise(run, env):
    subprocess.run([str(ROOT / '.venv/bin/python'), '-c', INIT], cwd=ROOT, env=env, check=True,
                   capture_output=True, timeout=120)
    live = sqlite3.connect(f'file:{LIVE_DB}?mode=ro', uri=True)
    cols = [r[1] for r in live.execute('pragma table_info(aries_settings)')]
    found = live.execute(f'select {",".join(cols)} from aries_settings').fetchall()
    live.close()
    fresh = sqlite3.connect(run / 'aries.sqlite3')
    copied, skipped = [], []
    for row in found:
        rec = dict(zip(cols, row))
        if rec['key'].startswith(NOT_COPIED_PREFIXES):
            skipped.append(rec['key'])
            continue
        if rec['key'] in FORCED_OFF:
            rec['value_json'] = 'false'
            rec['set_by'] = 'h5-runner:isolation'
        fresh.execute(f'insert into aries_settings ({",".join(cols)}) values ({",".join("?" * len(cols))})',
                      [rec[c] for c in cols])
        copied.append(rec['key'])
    fresh.commit()
    fresh.close()
    return {'copied_keys': copied, 'not_copied': skipped, 'forced_off': list(FORCED_OFF)}


def record(run, task_id):
    c = sqlite3.connect(f'file:{run / "aries.sqlite3"}?mode=ro', uri=True)
    row = c.execute('select state, result_json from aries_workspace_goals where id=?', (task_id,)).fetchone()
    c.close()
    if row is None:
        return {'state': 'missing'}
    return {'state': row[0], **json.loads(row[1] or '{}')}


def wait(run, task_id, budget):
    deadline = time.monotonic() + budget
    last = {}
    while time.monotonic() < deadline:
        last = record(run, task_id)
        if last.get('state') in TERMINAL:
            return last
        time.sleep(2)
    last['_timed_out'] = True
    return last


def submit(api, goal):
    req = urllib.request.Request(f'{api}/api/aries/workspace', data=json.dumps({'request': goal}).encode(),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    for key in ('id', 'task_id', 'goal_id'):
        if isinstance(payload, dict) and payload.get(key):
            return payload[key]
    raise RuntimeError(f'no id in response: {str(payload)[:200]}')


def contract_source(rec):
    c = (rec.get('agent') or {}).get('contract') or {}
    if not c.get('supported'):
        return 'none' + (' (typed rejected: ' + c['typed'].get('reason', '') + ')' if c.get('typed') else '')
    return {'paraphrase': 'fast path (paraphrase)', 'typed': 'typed step'}.get(c.get('recognised_by'), 'fast path (anchored)')


def end_path(rec):
    agent = rec.get('agent') or {}
    checks = agent.get('completion_checks') or []
    if rec.get('state') == 'done':
        return 'done'
    if not agent.get('decisions'):
        return 'never planned'
    if checks and not checks[-1].get('met'):
        return 'finish rejected'
    if (agent.get('metrics') or {}).get('planner_calls', 0) >= 1 and not checks:
        return 'budget exhausted without a finish'
    return 'other'


def h5_outcome(label, rec, verdict):
    done = rec.get('state') == 'done'
    return {'correct_done': bool(done and verdict == 'PASS') if label in ('G', 'example') else None,
            'false_done': bool(done and (label == 'N' or verdict != 'PASS')) if label in ('G', 'N') else None,
            'contract_source': contract_source(rec), 'end_path': end_path(rec)}


def preflight(sets):
    state = {}
    active = subprocess.run(['systemctl', '--user', 'is-active', 'aries-core.service'],
                            capture_output=True, text=True).stdout.strip()
    state['aries_core'] = active
    if sets != 'example' and active == 'active':
        raise SystemExit('REFUSED: the live ARIES is running; the H5 procedure stops it (run-h5.sh does this)')
    out = subprocess.run(['gdbus', 'call', '--session', '--dest', 'org.gnome.ScreenSaver', '--object-path',
                          '/org/gnome/ScreenSaver', '--method', 'org.gnome.ScreenSaver.GetActive'],
                         capture_output=True, text=True).stdout
    state['screensaver_active'] = out.strip()
    if 'true' in out.lower():
        raise SystemExit('REFUSED: the session is locked or blanked')
    state['idle_delay'] = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.session', 'idle-delay'],
                                         capture_output=True, text=True).stdout.strip()
    if sets != 'example' and state['idle_delay'] != 'uint32 0':
        raise SystemExit('REFUSED: screen blanking is on (idle-delay ' + state['idle_delay'] + ')')
    state['commit'] = git('rev-parse', 'HEAD')
    state['tags_at_head'] = git('tag', '--points-at', 'HEAD').splitlines()
    state['code_dirty'] = git('status', '--porcelain', '--untracked-files=no', '--', 'aries', 'aries_ui', 'vendor',
                              'tests', 'requirements.txt').splitlines()
    if state['code_dirty']:
        raise SystemExit(f'REFUSED: code differs from the commit: {state["code_dirty"][:5]}')
    state['model'] = 'qwen2.5:7b'
    state['model_digest_before'] = model_digest()
    state['ollama_version_before'] = ollama('/api/version').get('version')
    return state


def validate_items(run):
    for name, digest in FROZEN_ITEMS.items():
        if sha(ITEMS / name) != digest:
            raise SystemExit(f'REFUSED: {name} is not the frozen file of Amendment 2')
    out = subprocess.run([sys.executable, '-I', str(ITEMS / 'validate_items.py'), 'goals.jsonl', 'controls.jsonl',
                          '--out', str(run / 'validation')], cwd=ITEMS, capture_output=True, text=True)
    line = (out.stdout.strip().splitlines() or [''])[0]
    report = json.loads((run / 'validation/validation.json').read_text())
    if out.returncode != 0 or not line.startswith('PASS') or report.get('files', {}).get('goals.jsonl') != \
            FROZEN_ITEMS['goals.jsonl'] or report['files'].get('controls.jsonl') != FROZEN_ITEMS['controls.jsonl']:
        raise SystemExit('REFUSED: the H5 items do not validate: ' + line)
    return line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture-env', action='store_true')
    ap.add_argument('--condition', choices=sorted(CONDITIONS))
    ap.add_argument('--label')
    ap.add_argument('--sets', choices=['h5', 'example'], default='h5')
    ap.add_argument('--port', type=int, default=8101)
    ap.add_argument('--go', action='store_true')
    cli = ap.parse_args()
    if cli.capture_env:
        capture_env()
        return 0
    if not cli.condition or not cli.label:
        ap.error('--condition and --label are required')
    cases = cases_for(cli.sets)
    counts = {}
    for label, _ in cases:
        counts[label] = counts.get(label, 0) + 1
    if not cli.go:
        print(f'DRY RUN. Nothing submitted. condition={cli.condition} flags={CONDITIONS[cli.condition]} cases={counts}')
        return 0
    if cli.sets == 'h5' and (counts.get('G') != 15 or counts.get('N') != 10 or counts.get('heldout') != 49):
        raise SystemExit(f'REFUSED: H5 needs 15 + 10 + 49 cases; found {counts}')
    if cli.sets == 'h5' and any(c.get('example') or c['id'].startswith('ex-') for _, c in cases):
        raise SystemExit('REFUSED: an example row appears in an H5 set')

    state = preflight(cli.sets)
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    run = HERE / f'{stamp}-{cli.label}-{cli.condition}'
    run.mkdir(parents=False, exist_ok=False)
    (run / 'var').mkdir()
    validation = validate_items(run) if cli.sets == 'h5' else 'example items: not validated here'
    flags_text = ''.join(f'{k}={v}\n' for k, v in CONDITIONS[cli.condition].items())
    (run / 'flags.env').write_text('# H5 condition ' + cli.condition + '\n' + flags_text)
    env, env_note = instance_env(run)
    settings = initialise(run, env)
    described = json.loads(subprocess.run([str(ROOT / '.venv/bin/python'), '-c', FLAGS], cwd=ROOT, env=env,
                                          capture_output=True, text=True, check=True).stdout)
    effective = {k: described['flags'][k]['on'] for k in CONDITIONS[cli.condition]}
    declared = {k: v == '1' for k, v in CONDITIONS[cli.condition].items()}
    if effective != declared:
        raise SystemExit(f'REFUSED: effective flags {effective} differ from declared {declared}')
    api = f'http://127.0.0.1:{cli.port}'
    log = (run / 'instance.log').open('w')
    server = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-m', 'uvicorn', 'aries.api.app:app',
                               '--host', '127.0.0.1', '--port', str(cli.port), '--log-level', 'info'],
                              cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    meta = {'condition': cli.condition, 'label': cli.label, 'sets': cli.sets, 'declared_flags': CONDITIONS[cli.condition],
            'effective_flags': described, 'preflight': state, 'environment_note': env_note, 'validation': validation,
            'isolated': {k: env[k] for k in ('DATABASE_URL', 'DATA_DIR', 'RUNTIME_STORE', 'CONTEXT_DIR', 'ARIES_FLAG_FILE')},
            'settings': settings, 'api': api, 'terminal_states': sorted(TERMINAL),
            'scorer': {'run_fixtures.py': sha(IA / 'run_fixtures.py'), 'run_h5.py': sha(__file__),
                       'change_hook.py': sha(HERE / 'change_hook.py')},
            'inputs': {'goals.jsonl': sha(ITEMS / 'goals.jsonl'), 'controls.jsonl': sha(ITEMS / 'controls.jsonl'),
                       'fixtures.jsonl': sha(IA / 'fixtures.jsonl'),
                       'oracle_validation.json': sha(IA / 'raw/oracle_validation.json')},
            'started_at': stamp, 'case_counts': counts}
    (run / 'run.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    hook = CH.ChangeHook(run / 'var' / 'measure-hook', timeout_seconds=HOOK_TIMEOUT)
    results = []
    sandbox = pathlib.Path(tempfile.mkdtemp(prefix='aries-h5-'))
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(f'{api}/api/aries/shell/status', timeout=5) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(1)
        else:
            raise SystemExit('REFUSED: isolated instance did not come up; see instance.log')
        for label, case in cases:
            cid = case['id']
            croot = pathlib.Path.home() / 'Documents/ARIES-CIA-01'
            m = pathlib.Path.home() / '.local/state/aries-cia'
            recfile = sandbox / f'{cid}.record.json'
            pre = (RF.PREAMBLE.replace('__ROOT__', str(croot)).replace('__ID__', cid)
                   .replace('__M__', str(m)).replace('__REC__', str(recfile))
                   .replace('__DB__', str(run / 'aries.sqlite3')))
            t0 = str(int(time.time()))
            code, _, err = RF.sh(pre.replace('__TASK__', 'pending').replace('__T0__', t0)
                                 + '\n' + '\n'.join(case.get('setup') or []), str(sandbox))
            if code != 0:
                results.append({'set': label, 'id': cid, 'verdict': 'SETUP_FAILED', 'detail': err[:200]})
                continue
            changes = case.get('control_type') == 'changed_after_read'
            thread = None
            if changes:
                hook.arm(case['goal'])
                apply = CH.shell_apply(RF.sh, pre.replace('__TASK__', 'pending').replace('__T0__', t0), case,
                                       croot / cid, sandbox)
                thread = hook.start(case['goal'], apply, wait_seconds=case.get('budget_seconds', 180))
            started = time.monotonic()
            try:
                task = submit(api, case['goal'])
            except Exception as exc:
                if changes:
                    hook.finish(case['goal'], thread)
                results.append({'set': label, 'id': cid, 'verdict': 'SUBMIT_FAILED', 'detail': str(exc)[:200]})
                RF.sh(pre.replace('__TASK__', '-').replace('__T0__', t0) + '\n'
                      + '\n'.join(case.get('teardown') or []), str(sandbox))
                continue
            rec = wait(run, task, case.get('budget_seconds', 180))
            hook_record = None
            if changes:
                hook_record = hook.finish(case['goal'], thread)
                if not hook_record['fired']:
                    CH.apply_unfired(m, cid)
            recfile.write_text(json.dumps(rec, ensure_ascii=False))
            (run / 'records').mkdir(exist_ok=True)
            (run / 'records' / f'{cid}.json').write_text(json.dumps(rec, ensure_ascii=False))
            pre2 = pre.replace('__TASK__', task).replace('__T0__', t0)
            checks, forbidden = [], []
            for chk in case['independent_oracle'].get('checks') or []:
                c, _, _ = RF.sh(pre2 + '\n' + chk['command'], str(sandbox))
                checks.append({'id': chk.get('id'), 'kind': 'check', 'passed': c == 0, 'exit': c})
            for chk in case['independent_oracle'].get('forbidden_state') or []:
                c, _, _ = RF.sh(pre2 + '\n' + chk['command'], str(sandbox))
                forbidden.append({'id': chk.get('id'), 'kind': 'forbidden_state', 'passed': c == 0, 'exit': c})
            RF.sh(pre2 + '\n' + '\n'.join(case.get('teardown') or []), str(sandbox))
            every = checks + forbidden
            broken = [c for c in every if not c['passed'] and c['exit'] not in (0, 1)]
            genuine = [c for c in every if not c['passed'] and c['exit'] == 1]
            verdict = 'PASS' if not broken and not genuine else 'FAIL' if genuine else 'INCONCLUSIVE'
            results.append({'set': label, 'id': cid, 'class': case.get('class') or case.get('goal_type'),
                            'goal_type': case.get('goal_type'), 'control_type': case.get('control_type'),
                            'expected_outcome': case['expected_outcome'], 'task_id': task,
                            'terminal_state': rec.get('state'), 'timed_out': rec.get('_timed_out', False),
                            'seconds': round(time.monotonic() - started, 1), 'verdict': verdict,
                            'inconclusive_checks': [{'id': c['id'], 'exit': c['exit']} for c in broken],
                            'h5': h5_outcome(label, rec, verdict), 'change_hook': hook_record,
                            'checks': checks, 'forbidden_state': forbidden})
            print(f"{verdict:12s} {label:8s} {cid:10s} state={rec.get('state')}", flush=True)
            (run / 'results.json').write_text(json.dumps({'run': meta, 'results': results}, ensure_ascii=False, indent=1))
    finally:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
    meta['finished_at'] = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    meta['model_digest_after'] = model_digest()
    meta['ollama_version_after'] = ollama('/api/version').get('version')
    meta['model_stable'] = meta['model_digest_after'] == state['model_digest_before'] and \
        meta['ollama_version_after'] == state['ollama_version_before']
    meta['commit_after'] = git('rev-parse', 'HEAD')
    meta['code_stable'] = meta['commit_after'] == state['commit'] and not git(
        'status', '--porcelain', '--untracked-files=no', '--', 'aries', 'aries_ui', 'vendor', 'tests', 'requirements.txt')
    (run / 'results.json').write_text(json.dumps({'run': meta, 'results': results}, ensure_ascii=False, indent=1))
    tally = {}
    for r in results:
        tally[f"{r['set']}:{r['verdict']}"] = tally.get(f"{r['set']}:{r['verdict']}", 0) + 1
    print(json.dumps({'run': str(run.relative_to(ROOT)), 'tally': tally, 'model_stable': meta['model_stable'],
                      'code_stable': meta['code_stable']}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
