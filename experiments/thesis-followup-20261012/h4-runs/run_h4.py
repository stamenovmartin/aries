#!/usr/bin/env python3
"""H4 runner: one condition, one run, on a fresh isolated ARIES instance.

What it does (docs/preregistration/H4-planner-clarification.md and Amendment 1):

- **Fresh isolated database per run.** A new SQLite file, data dir, runtime store and
  context dir under this run's folder. The live var/aries.db is opened only read-only,
  once, to copy the owner's settings (not memories, history or goals).
- **Same server as the service.** The same command as aries-core.service
  (`uvicorn aries.api.app:app`) in a subprocess on its own port. Its environment is the
  running aries-core's own environment with only the isolation keys replaced.
- **Explicit flags.** A per-run flags file sets ARIES_PLANNER_CLARIFY and
  ARIES_COMPLETION_READ_PARAPHRASE. The effective values are resolved with
  aries.flags.describe() in the instance's exact environment, and the run refuses to
  start if they differ from the declared condition.
- **needs_clarification is terminal.** It is the agent's end state for a question.
  Without it every question would wait for the whole budget.
- **Scoring is run_fixtures.py's.** The same PREAMBLE helpers, the same check
  execution and the same verdict rule (exit 1 = genuine no, other non-zero =
  INCONCLUSIVE), imported from experiments/product/independent-acceptance/run_fixtures.py.

Isolation measures that are identical in every condition: no Telegram token or
polling, connect/news/briefing switched off, shell.* and power.* settings not copied.

Nothing is submitted without --go. Every invocation writes a new folder; nothing is
overwritten.

H4 treatment is `on-guard` and control is `off` (preregistration, Amendment 2); `on`
(clarify without the guard) is refused for --sets h4 and kept only for dev/example runs.

    run_h4.py --condition on-guard --label r1 [--go]
    run_h4.py --condition off      --label r2 [--go]
    run_h4.py --condition completion-fix --label x1 [--go]     # separate, NOT H4
    run_h4.py --condition on --label smoke --sets example --go  # example pair only
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
ROOT = HERE.parents[2]
IA = ROOT / 'experiments/product/independent-acceptance'
SCEN = HERE.parent / 'h4-scenarios'
DEV = HERE.parent / 'h4-dev'
LIVE_DB = ROOT / 'var/aries.db'
CONDITIONS = {
    'on': {'ARIES_PLANNER_CLARIFY': '1', 'ARIES_PLANNER_CLARIFY_GUARD': '0', 'ARIES_COMPLETION_READ_PARAPHRASE': '0'},
    'off': {'ARIES_PLANNER_CLARIFY': '0', 'ARIES_PLANNER_CLARIFY_GUARD': '0', 'ARIES_COMPLETION_READ_PARAPHRASE': '0'},
    'on-guard': {'ARIES_PLANNER_CLARIFY': '1', 'ARIES_PLANNER_CLARIFY_GUARD': '1', 'ARIES_COMPLETION_READ_PARAPHRASE': '0'},
    'completion-fix': {'ARIES_PLANNER_CLARIFY': '1', 'ARIES_PLANNER_CLARIFY_GUARD': '1', 'ARIES_COMPLETION_READ_PARAPHRASE': '1'},
}
TERMINAL = {'done', 'answered', 'failed', 'partial', 'refused', 'proposed', 'cancelled',
            'interrupted', 'error', 'needs_clarification'}
NOT_COPIED_PREFIXES = ('shell.', 'power.')
FORCED_OFF = ('connect.enabled', 'connect.attention_enabled', 'news.enabled', 'news.local_summaries',
              'briefing.morning_enabled', 'workspace.ai_briefings')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RF = load(IA / 'run_fixtures.py', 'ia_run_fixtures')   # scoring helpers, unchanged


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def model_digest(name='qwen2.5:7b'):
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=20) as r:
        models = json.load(r)['models']
    return next(m['digest'] for m in models if m['name'] == name)


def cases_for(selection):
    """(set label, case) in a fixed order: A, C, held-out."""
    out = []
    if selection == 'example':
        rows = [json.loads(l) for l in (SCEN / 'example_pair.jsonl').read_text().splitlines() if l.strip()]
        return [('example', r) for r in rows]
    if selection == 'dev':
        # Development set: never mixed with A/C or the held-out fixture, never scored for H4.
        rows = [json.loads(l) for l in (DEV / 'dev.jsonl').read_text().splitlines() if l.strip()]
        assert all(r.get('dev') and r['id'].startswith('dev-') for r in rows)
        return [('dev', r) for r in rows]
    for label, name in (('A', 'set_a.jsonl'), ('C', 'set_c.jsonl')):
        rows = [json.loads(l) for l in (SCEN / name).read_text().splitlines() if l.strip()]
        out += [(label, r) for r in rows]
    validation = json.loads((IA / 'raw/oracle_validation.json').read_text())
    discriminating = {c['id'] for c in validation['cases'] if c.get('verdict') == 'DISCRIMINATING'}
    held = [json.loads(l) for l in (IA / 'fixtures.jsonl').read_text().splitlines() if l.strip()]
    out += [('heldout', c) for c in held if c['id'] in discriminating and not c.get('requires')]
    return out


def instance_env(run, port):
    pid = subprocess.run(['systemctl', '--user', 'show', '-p', 'MainPID', '--value', 'aries-core.service'],
                         capture_output=True, text=True).stdout.strip()
    raw = pathlib.Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
    env = dict(x.decode().split('=', 1) for x in raw if b'=' in x)
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
    return env, {'service_pid': pid, 'removed_inherited_aries_vars': leaked}


INIT = r'''
import asyncio, json, sqlite3, sys
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
    rows = live.execute(f'select {",".join(cols)} from aries_settings').fetchall()
    fresh = sqlite3.connect(run / 'aries.sqlite3')
    copied, skipped = [], []
    for row in rows:
        rec = dict(zip(cols, row))
        if rec['key'].startswith(NOT_COPIED_PREFIXES):
            skipped.append(rec['key'])
            continue
        if rec['key'] in FORCED_OFF:
            rec['value_json'] = 'false'
            rec['set_by'] = 'h4-runner:isolation'
        fresh.execute(f'insert into aries_settings ({",".join(cols)}) values ({",".join("?" * len(cols))})',
                      [rec[c] for c in cols])
        copied.append({'key': rec['key'], 'value': json.loads(rec['value_json']), 'set_by': rec['set_by']})
    fresh.commit()
    fresh.close()
    return {'copied': copied, 'not_copied': skipped, 'forced_off': list(FORCED_OFF)}


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


def h4_outcome(rec, sandbox_ok, forbidden_ok):
    clar = rec.get('clarification') or {}
    asked = rec.get('state') == 'needs_clarification'
    return {'asked': asked, 'asked_by_planner': asked and clar.get('source') == 'planner',
            'grounded_question': bool(asked and clar.get('source') == 'planner'
                                      and len(clar.get('choices') or []) >= 2 and sandbox_ok and forbidden_ok)}


def preflight():
    state = {}
    out = subprocess.run(['gdbus', 'call', '--session', '--dest', 'org.gnome.ScreenSaver', '--object-path',
                          '/org/gnome/ScreenSaver', '--method', 'org.gnome.ScreenSaver.GetActive'],
                         capture_output=True, text=True).stdout
    state['screensaver_active'] = out.strip()
    if 'true' in out.lower():
        raise SystemExit('REFUSED: the session is locked or blanked (the B1b/B2b confound)')
    state['idle_delay'] = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.session', 'idle-delay'],
                                         capture_output=True, text=True).stdout.strip()
    state['commit'] = git('rev-parse', 'HEAD')
    state['code_dirty'] = git('status', '--porcelain', '--untracked-files=no', '--', 'aries', 'aries_ui', 'vendor', 'tests',
                              'requirements.txt').splitlines()
    if state['code_dirty']:
        raise SystemExit(f'REFUSED: code differs from the commit: {state["code_dirty"][:5]}')
    state['model'] = 'qwen2.5:7b'
    state['model_digest_before'] = model_digest()
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--condition', choices=sorted(CONDITIONS), required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--sets', choices=['h4', 'example', 'dev'], default='h4')
    ap.add_argument('--port', type=int, default=8100)
    ap.add_argument('--go', action='store_true')
    cli = ap.parse_args()
    cases = cases_for(cli.sets)
    counts = {}
    for label, _ in cases:
        counts[label] = counts.get(label, 0) + 1
    if not cli.go:
        print(f'DRY RUN. Nothing submitted. condition={cli.condition} flags={CONDITIONS[cli.condition]} cases={counts}')
        return 0
    if cli.sets == 'h4' and cli.condition == 'on':
        raise SystemExit('REFUSED: the H4 treatment is on-guard (Amendment 2); on is for dev/example runs only')
    if cli.sets == 'h4' and (counts.get('A', 0) != 10 or counts.get('C', 0) != 10):
        raise SystemExit(f'REFUSED: H4 needs 10 + 10 scenarios; found {counts}')
    if cli.sets == 'dev':
        v = DEV / 'validation/validation.json'
        if not v.exists() or json.loads(v.read_text()).get('result') != 'PASS' or \
                json.loads(v.read_text()).get('sha256') != sha(DEV / 'dev.jsonl'):
            raise SystemExit('REFUSED: dev.jsonl has no PASS validation for its current content')
    if cli.sets == 'h4':
        if any(c['id'].startswith(('dev-', 'ex-')) for _, c in cases):
            raise SystemExit('REFUSED: a development or example row appears in an H4 set')
        for name in ('set_a', 'set_c'):
            v = SCEN / f'validation/{name}/validation.json'
            if not v.exists() or json.loads(v.read_text()).get('result') != 'PASS' or \
                    json.loads(v.read_text()).get('sha256') != sha(SCEN / f'{name}.jsonl'):
                raise SystemExit(f'REFUSED: {name}.jsonl has no PASS validation for its current content')

    state = preflight()
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    run = HERE / f'{stamp}-{cli.label}-{cli.condition}'
    run.mkdir(parents=False, exist_ok=False)
    (run / 'var').mkdir()
    flags_text = ''.join(f'{k}={v}\n' for k, v in CONDITIONS[cli.condition].items())
    (run / 'flags.env').write_text('# H4 condition ' + cli.condition + '\n' + flags_text)
    env, env_note = instance_env(run, cli.port)
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
            'effective_flags': described, 'preflight': state, 'environment_note': env_note,
            'isolated': {k: env[k] for k in ('DATABASE_URL', 'DATA_DIR', 'RUNTIME_STORE', 'CONTEXT_DIR', 'ARIES_FLAG_FILE')},
            'settings': settings, 'api': api, 'terminal_states': sorted(TERMINAL),
            'scorer': {'run_fixtures.py': sha(IA / 'run_fixtures.py'), 'run_h4.py': sha(__file__)},
            'inputs': {'set_a.jsonl': sha(SCEN / 'set_a.jsonl'), 'set_c.jsonl': sha(SCEN / 'set_c.jsonl'),
                       'fixtures.jsonl': sha(IA / 'fixtures.jsonl'),
                       'oracle_validation.json': sha(IA / 'raw/oracle_validation.json')},
            'started_at': stamp, 'case_counts': counts}
    (run / 'run.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    results = []
    sandbox = pathlib.Path(tempfile.mkdtemp(prefix='aries-h4-'))
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
            started = time.monotonic()
            try:
                task = submit(api, case['goal'])
            except Exception as exc:
                results.append({'set': label, 'id': cid, 'verdict': 'SUBMIT_FAILED', 'detail': str(exc)[:200]})
                RF.sh(pre.replace('__TASK__', '-').replace('__T0__', t0) + '\n'
                      + '\n'.join(case.get('teardown') or []), str(sandbox))
                continue
            rec = wait(run, task, case.get('budget_seconds', 180))
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
            sandbox_ok = all(c['passed'] for c in checks if c['id'] == 'sandbox_unchanged')
            forbidden_ok = all(f['passed'] for f in forbidden)
            results.append({'set': label, 'id': cid, 'class': case['class'], 'expected_outcome': case['expected_outcome'],
                            'task_id': task, 'terminal_state': rec.get('state'), 'timed_out': rec.get('_timed_out', False),
                            'seconds': round(time.monotonic() - started, 1),
                            'verdict': 'PASS' if not broken and not genuine else 'FAIL' if genuine else 'INCONCLUSIVE',
                            'inconclusive_checks': [{'id': c['id'], 'exit': c['exit']} for c in broken],
                            'h4': h4_outcome(rec, sandbox_ok, forbidden_ok), 'checks': checks, 'forbidden_state': forbidden})
            print(f"{results[-1]['verdict']:12s} {label:8s} {cid:8s} state={rec.get('state')} "
                  f"asked_by_planner={results[-1]['h4']['asked_by_planner']}", flush=True)
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
    meta['model_stable'] = meta['model_digest_after'] == state['model_digest_before']
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
