#!/usr/bin/env python3
"""H4b runner: one condition, one run, on a fresh isolated ARIES instance.

docs/preregistration/H4b-clarify-resolver.md (Procedure, Outcome definitions, Amendments 1 and 2). Adapted from
experiments/thesis-followup-20261012/h5-runs/run_h5.py (itself adapted from h4-runs/run_h4.py); the differences:

- **Conditions.** baseline: the registered H4 treatment (ARIES_PLANNER_CLARIFY=1, ARIES_PLANNER_CLARIFY_GUARD=1,
  ARIES_COMPLETION_READ_PARAPHRASE=0, ARIES_CLARIFY_RESOLVER=0); treatment: the same with
  ARIES_CLARIFY_RESOLVER=1. Flags added after the registration are pinned at their defaults (off) in both:
  ARIES_COMPLETION_TYPED_CONTRACT=0, ARIES_MEASURE_CHANGE_HOOK=0. The resolver is the only difference. Effective
  values are resolved in the instance's exact environment and the run refuses to start if any differs.
- **Live ARIES stopped.** As for H5: `--capture-env` copies the running service's environment once to
  ~/.local/state/aries-h4b/service-env (mode 600, outside the repository, never committed); a run refuses to
  start while aries-core is active or the screen can blank.
- **Items.** The 40 ambiguous items, then the 40 twins, in file order; the same order in every run. Before
  anything is submitted, the unchanged validator is re-run into the run folder and must print PASS for the
  frozen SHA-256s of Amendment 1.
- **Outcomes** (Outcome definitions; operational details in Amendment 2):
  - ambiguous correct = state needs_clarification, clarification.source "planner" or "resolver", the choices are
    exactly the fitting files by full path, no fitting file was read (no executed file.read step on it, and the
    oracle's forbidden state no_candidate_read holds), sandbox_unchanged passes, no forbidden state is violated,
    and the oracle verdict is PASS;
  - twin correct = the oracle verdict is PASS;
  - over-ask = a twin that ends in needs_clarification.
  INCONCLUSIVE counts as not correct. Scoring of the checks is run_fixtures.py's (same PREAMBLE, same check
  execution, exit 1 = genuine no, other non-zero = INCONCLUSIVE).
- **Recorded per item** for the secondary outcomes: the resolver's stage, candidate count, the raw model
  decision, whether code accepted it and why, latency, and model calls (planner + resolver).

Nothing is submitted without --go. Every invocation writes a new folder; nothing is overwritten.

    run_h4b.py --capture-env                                   # once, while aries-core runs
    run_h4b.py --condition treatment --label r1 [--go]
    run_h4b.py --condition baseline  --label r2 [--go]
    run_h4b.py --condition treatment --label smoke --sets example --go   # the example pair only
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
ITEMS = FU / 'h4b-items'
LIVE_DB = ROOT / 'var/aries.db'
SERVICE_ENV = pathlib.Path.home() / '.local/state/aries-h4b/service-env'
CASE_ROOT = pathlib.Path.home() / 'Documents/ARIES-CIA-01'
FROZEN_ITEMS = {'pairs_ambiguous.jsonl': 'ff2826c52268d01fda0ebf35dafcf61134fcc6d9896593e0f9ef787961a47352',
                'pairs_twin.jsonl': '91a7e99a2dda52cfff20207a865dbe7c1d16f02e543b808655d795e5c269d142'}
H4_TREATMENT = {'ARIES_PLANNER_CLARIFY': '1', 'ARIES_PLANNER_CLARIFY_GUARD': '1', 'ARIES_COMPLETION_READ_PARAPHRASE': '0'}
PINNED = {'ARIES_COMPLETION_TYPED_CONTRACT': '0', 'ARIES_MEASURE_CHANGE_HOOK': '0'}
CONDITIONS = {
    'baseline': {**H4_TREATMENT, 'ARIES_CLARIFY_RESOLVER': '0', **PINNED},
    'treatment': {**H4_TREATMENT, 'ARIES_CLARIFY_RESOLVER': '1', **PINNED},
}
TERMINAL = {'done', 'answered', 'failed', 'partial', 'refused', 'proposed', 'cancelled',
            'interrupted', 'error', 'needs_clarification'}
NOT_EXECUTED = ('planned', 'not_run')
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


def ollama(path):
    with urllib.request.urlopen('http://127.0.0.1:11434' + path, timeout=20) as r:
        return json.load(r)


def model_digest(name='qwen2.5:7b'):
    return next(m['digest'] for m in ollama('/api/tags')['models'] if m['name'] == name)


def rows(path):
    return [json.loads(l) for l in pathlib.Path(path).read_text().splitlines() if l.strip()]


def cases_for(selection):
    """(set label, case) in a fixed order: the ambiguous items, then the twins, each in file order."""
    if selection == 'example':
        return [('example', r) for r in rows(ITEMS / 'example_pair.jsonl')]
    return ([('ambiguous', r) for r in rows(ITEMS / 'pairs_ambiguous.jsonl')]
            + [('twin', r) for r in rows(ITEMS / 'pairs_twin.jsonl')])


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
            rec['set_by'] = 'h4b-runner:isolation'
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


def fitting_paths(case, case_dir):
    return sorted(str(pathlib.Path(case_dir) / f) for f in case['fitting_files'])


def read_paths(rec):
    """Paths of file.read steps that were executed (any status other than planned or not run)."""
    return sorted({str(pathlib.Path((s.get('args') or {}).get('path', '')).expanduser())
                   for s in rec.get('steps') or []
                   if s.get('capability') == 'file.read' and s.get('execution_status') not in NOT_EXECUTED})


def h4b_outcome(case, rec, checks, forbidden, verdict, case_dir):
    """The registered item outcomes (Outcome definitions; Amendment 2)."""
    clar = rec.get('clarification') or {}
    asked = rec.get('state') == 'needs_clarification'
    fitting = fitting_paths(case, case_dir)
    if case['kind'] == 'ambiguous':
        parts = {'asked': asked,
                 'source_planner_or_resolver': clar.get('source') in ('planner', 'resolver'),
                 'choices_exactly_fitting': sorted(clar.get('choices') or []) == fitting,
                 'no_fitting_file_read': not set(read_paths(rec)) & set(fitting),
                 'sandbox_unchanged': any(c['id'] == 'sandbox_unchanged' for c in checks)
                 and all(c['passed'] for c in checks if c['id'] == 'sandbox_unchanged'),
                 'no_forbidden_violated': all(f['passed'] for f in forbidden),
                 'oracle_pass': verdict == 'PASS'}
        return {'correct': all(parts.values()), 'parts': parts, 'over_ask': None,
                'question_source': clar.get('source') if asked else None}
    return {'correct': verdict == 'PASS', 'parts': {'oracle_pass': verdict == 'PASS'}, 'over_ask': asked,
            'question_source': clar.get('source') if asked else None}


def resolver_summary(rec):
    """What the resolver did on this item (secondary outcomes 3 and 4); None if it never ran."""
    state = (rec.get('agent') or {}).get('resolver')
    if state is None:
        return None
    n = state.get('n')
    bucket = None if n is None else '0' if n == 0 else '1' if n == 1 else '2-5' if n <= 5 else '>5'
    decision = state.get('decision') or {}
    return {'applies': state.get('applies'), 'outcome': state.get('outcome'), 'n_candidates': n,
            'candidate_bucket': bucket, 'model_decision': decision.get('decision'),
            'selected_index': decision.get('selected_index'), 'evidence_span': decision.get('evidence_span'),
            'accepted': state.get('accepted'), 'why': state.get('why'), 'selected': state.get('selected'),
            'model_error': (state.get('decision_call') or {}).get('error'),
            'model_seconds': (state.get('decision_call') or {}).get('seconds')}


def model_calls(rec):
    m = (rec.get('agent') or {}).get('metrics') or {}
    return {'planner_calls': m.get('planner_calls', 0), 'resolver_model_calls': m.get('resolver_model_calls', 0)}


def preflight(sets):
    state = {}
    active = subprocess.run(['systemctl', '--user', 'is-active', 'aries-core.service'],
                            capture_output=True, text=True).stdout.strip()
    state['aries_core'] = active
    if sets != 'example' and active == 'active':
        raise SystemExit('REFUSED: the live ARIES is running; the H4b procedure stops it (run-h4b.sh does this)')
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
            raise SystemExit(f'REFUSED: {name} is not the frozen file of Amendment 1')
    out = subprocess.run([sys.executable, '-I', str(ITEMS / 'validate_items.py'), *FROZEN_ITEMS,
                          '--out', str(run / 'validation')], cwd=ITEMS, capture_output=True, text=True)
    line = (out.stdout.strip().splitlines() or [''])[0]
    report = json.loads((run / 'validation/validation.json').read_text())
    if out.returncode != 0 or not line.startswith('PASS') or report.get('files') != FROZEN_ITEMS:
        raise SystemExit('REFUSED: the H4b items do not validate: ' + line)
    return line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture-env', action='store_true')
    ap.add_argument('--condition', choices=sorted(CONDITIONS))
    ap.add_argument('--label')
    ap.add_argument('--sets', choices=['h4b', 'example'], default='h4b')
    ap.add_argument('--port', type=int, default=8102)
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
    if cli.sets == 'h4b' and counts != {'ambiguous': 40, 'twin': 40}:
        raise SystemExit(f'REFUSED: H4b needs 40 + 40 items; found {counts}')
    if cli.sets == 'h4b' and any(c.get('example') or c['id'].startswith('ex-') for _, c in cases):
        raise SystemExit('REFUSED: an example row appears in an H4b set')

    state = preflight(cli.sets)
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    run = HERE / f'{stamp}-{cli.label}-{cli.condition}'
    run.mkdir(parents=False, exist_ok=False)
    (run / 'var').mkdir()
    validation = validate_items(run) if cli.sets == 'h4b' else 'example pair: not validated here'
    flags_text = ''.join(f'{k}={v}\n' for k, v in CONDITIONS[cli.condition].items())
    (run / 'flags.env').write_text('# H4b condition ' + cli.condition + '\n' + flags_text)
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
            'scorer': {'run_fixtures.py': sha(IA / 'run_fixtures.py'), 'run_h4b.py': sha(__file__)},
            'inputs': {name: sha(ITEMS / name) for name in (FROZEN_ITEMS if cli.sets == 'h4b' else ['example_pair.jsonl'])},
            'started_at': stamp, 'case_counts': counts}
    (run / 'run.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    results = []
    sandbox = pathlib.Path(tempfile.mkdtemp(prefix='aries-h4b-'))
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
            m = pathlib.Path.home() / '.local/state/aries-cia'
            recfile = sandbox / f'{cid}.record.json'
            pre = (RF.PREAMBLE.replace('__ROOT__', str(CASE_ROOT)).replace('__ID__', cid)
                   .replace('__M__', str(m)).replace('__REC__', str(recfile))
                   .replace('__DB__', str(run / 'aries.sqlite3')))
            t0 = str(int(time.time()))
            code, _, err = RF.sh(pre.replace('__TASK__', 'pending').replace('__T0__', t0)
                                 + '\n' + '\n'.join(case.get('setup') or []), str(sandbox))
            if code != 0:
                results.append({'set': label, 'id': cid, 'pair_id': case['pair_id'], 'kind': case['kind'],
                                'verdict': 'SETUP_FAILED', 'detail': err[:200],
                                'h4b': {'correct': False, 'over_ask': None, 'parts': {}}})
                continue
            started = time.monotonic()
            try:
                task = submit(api, case['goal'])
            except Exception as exc:
                results.append({'set': label, 'id': cid, 'pair_id': case['pair_id'], 'kind': case['kind'],
                                'verdict': 'SUBMIT_FAILED', 'detail': str(exc)[:200],
                                'h4b': {'correct': False, 'over_ask': None, 'parts': {}}})
                RF.sh(pre.replace('__TASK__', '-').replace('__T0__', t0) + '\n'
                      + '\n'.join(case.get('teardown') or []), str(sandbox))
                continue
            rec = wait(run, task, case.get('budget_seconds', 180))
            seconds = round(time.monotonic() - started, 1)
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
            results.append({'set': label, 'id': cid, 'pair_id': case['pair_id'], 'kind': case['kind'],
                            'twin_type': case.get('twin_type'), 'intended_file': case.get('intended_file'),
                            'n_fitting': len(case['fitting_files']), 'expected_outcome': case['expected_outcome'],
                            'task_id': task, 'terminal_state': rec.get('state'), 'timed_out': rec.get('_timed_out', False),
                            'seconds': seconds, 'verdict': verdict,
                            'inconclusive_checks': [{'id': c['id'], 'exit': c['exit']} for c in broken],
                            'h4b': h4b_outcome(case, rec, checks, forbidden, verdict, CASE_ROOT / cid),
                            'resolver': resolver_summary(rec), 'model_calls': model_calls(rec),
                            'checks': checks, 'forbidden_state': forbidden})
            print(f"{verdict:12s} {label:9s} {cid:9s} state={rec.get('state')} correct={results[-1]['h4b']['correct']}",
                  flush=True)
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
