#!/usr/bin/env python3
"""Изврши ги фикстурите врз живиот ARIES и оцени ги со нивните сопствени оракули.

Трите контроли долу постојат затоа што без нив веќе паднаа две серии мерења:

  * знаменцата се ЗАПИШУВААТ со разрешена вредност И извор. B1/B2 ги поставија како
    променливи на околината што никогаш не стигнаа до долгоживиот сервис, па 75 од 90
    цели се извршија во погрешен услов.
  * состојбата на сесијата се проверува пред старт и мерењето ОДБИВА ако е изгасната.
    B1b/B2b беа расипани од гаснење по мирување, кое помести 11 цели.
  * hash на фикстурата и commit одат во секој артефакт, за да може резултат да се
    припише на точна состојба на дрвото.

Ништо не се пушта без `--go`. Случаите со `requires` се прескокнуваат освен ако не се
побара изречно со `--allow-requires`, бидејќи тие бараат рестарт на сервис.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
API = 'http://127.0.0.1:8000'

PREAMBLE = r'''
set -u
export ROOT="__ROOT__"; export ID="__ID__"; export C="$ROOT/$ID"
export M="__M__"; export TASK="__TASK__"; export T0="__T0__"
MANIFEST() { find "$1" -printf '%y %p %s\n' 2>/dev/null | LC_ALL=C sort; }
REC() { cat "__REC__"; }
WINDOWS() { gdbus call --session --dest org.aries.Shell --object-path /org/aries/Shell \
  --method org.aries.Shell.Windows 2>/dev/null | python3 -c \
  "import sys,ast,json;print(json.dumps(json.loads(ast.literal_eval(sys.stdin.read().strip())[0])))" \
  2>/dev/null || echo '{\"windows\":[]}'; }
SCHEDCOUNT() { python3 -c "
import sqlite3
c=sqlite3.connect('file:__DB__?mode=ro',uri=True)
print(*[c.execute('select count(*) from '+t).fetchone()[0] for t in
        ('scheduled_tasks','aries_automation_runs','automation_logs')])"; }
export -f MANIFEST REC WINDOWS SCHEDCOUNT 2>/dev/null || true
'''


def sh(script, cwd, timeout=40):
    try:
        p = subprocess.run(['bash', '-c', script], cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or '')[:600], (p.stderr or '')[:400]
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'


def preflight() -> dict:
    """Одбиј да мериш ако условите не се познати. Враќа состојба или кренува."""
    state = {}
    code, out, _ = sh("gdbus call --session --dest org.gnome.ScreenSaver "
                      "--object-path /org/gnome/ScreenSaver "
                      "--method org.gnome.ScreenSaver.GetActive", str(ROOT), 15)
    state['screensaver_active'] = out.strip()
    if 'true' in out.lower():
        raise SystemExit('ОДБИЕНО: сесијата е заклучена или изгасната. '
                         'Тоа е конфундот што ги поништи B1b/B2b.')
    code, out, _ = sh('gsettings get org.gnome.desktop.session idle-delay', str(ROOT), 10)
    state['idle_delay'] = out.strip()
    code, out, _ = sh('systemctl --user is-active aries-core.service', str(ROOT), 10)
    state['aries_core'] = out.strip()
    if state['aries_core'] != 'active':
        raise SystemExit(f'ОДБИЕНО: aries-core е {state["aries_core"]}')
    try:
        with urllib.request.urlopen(f'{API}/api/aries/analytics?days=1', timeout=20) as r:
            state['api'] = r.status
    except Exception as exc:
        raise SystemExit(f'ОДБИЕНО: API не одговара: {exc}')
    code, out, _ = sh('git rev-parse --short HEAD', str(ROOT), 10)
    state['commit'] = out.strip()
    code, out, _ = sh('git status --porcelain | wc -l', str(ROOT), 15)
    state['dirty_paths'] = int(out.strip() or 0)
    sys.path[:0] = [str(ROOT / p) for p in ('vendor/agentic-core', 'vendor', '.')]
    from aries import flags
    state['flags'] = flags.describe()
    return state


def submit(goal: str) -> str:
    """Поднеси цел преку вистинската рута.

    Првата верзија погодуваше `/workspace/goals` и добиваше 405. Патеката е прочитана
    од `aries/api/routes.py:1619`, не претпоставена — истата грешка во мерна скрипта
    порано поминуваше како „нула резултати“ наместо како погрешна рута.
    """
    body = json.dumps({'request': goal}).encode()
    req = urllib.request.Request(f'{API}/api/aries/workspace', data=body,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    for key in ('id', 'task_id', 'goal_id'):
        if isinstance(payload, dict) and payload.get(key):
            return payload[key]
    raise RuntimeError(f'нема идентификатор во одговорот: {str(payload)[:200]}')


def record(task_id: str) -> dict:
    import sqlite3
    c = sqlite3.connect(f'file:{ROOT}/var/aries.db?mode=ro', uri=True)
    row = c.execute('select state, result_json from aries_workspace_goals where id=?',
                    (task_id,)).fetchone()
    if row is None:
        return {'state': 'missing'}
    return {'state': row[0], **json.loads(row[1] or '{}')}


TERMINAL = {'done', 'answered', 'failed', 'partial', 'refused', 'proposed', 'cancelled',
            'interrupted', 'error'}


def wait(task_id: str, budget: int) -> dict:
    deadline = time.monotonic() + budget
    last = {}
    while time.monotonic() < deadline:
        last = record(task_id)
        if last.get('state') in TERMINAL:
            return last
        time.sleep(2)
    last['_timed_out'] = True
    return last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--go', action='store_true', help='навистина поднесувај цели')
    ap.add_argument('--only', help='запирка-одделени идентификатори')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--allow-requires', action='store_true')
    cli = ap.parse_args()

    fixtures = HERE / 'fixtures.jsonl'
    digest = hashlib.sha256(fixtures.read_bytes()).hexdigest()
    cases = [json.loads(l) for l in fixtures.read_text().splitlines() if l.strip()]

    validation = HERE / 'raw/oracle_validation.json'
    discriminating = set()
    if validation.exists():
        v = json.loads(validation.read_text())
        discriminating = {c['id'] for c in v['cases'] if c.get('verdict') == 'DISCRIMINATING'}

    if cli.only:
        wanted = set(cli.only.split(','))
        cases = [c for c in cases if c['id'] in wanted]
    else:
        cases = [c for c in cases if c['id'] in discriminating]
        if not cli.allow_requires:
            cases = [c for c in cases if not c.get('requires')]
    if cli.limit:
        cases = cases[:cli.limit]

    if not cli.go:
        print(f'СУВО ТРЧАЊЕ. Ништо не е поднесено.')
        print(f'фикстура sha256 : {digest[:16]}…')
        print(f'случаи кои би се извршиле: {len(cases)}')
        print('   ' + ', '.join(c["id"] for c in cases))
        print('\nдодај --go за да се поднесат навистина.')
        return 0

    state = preflight()
    print(f'предуслови во ред: commit={state["commit"]} idle_delay={state["idle_delay"]} '
          f'валкани патеки={state["dirty_paths"]}')

    sandbox = pathlib.Path(tempfile.mkdtemp(prefix='aries-fixture-run-'))
    results = []
    for case in cases:
        cid = case['id']
        croot = pathlib.Path.home() / 'Documents/ARIES-CIA-01'
        m = pathlib.Path.home() / '.local/state/aries-cia'
        recfile = sandbox / f'{cid}.record.json'
        pre = (PREAMBLE.replace('__ROOT__', str(croot)).replace('__ID__', cid)
               .replace('__M__', str(m)).replace('__REC__', str(recfile))
               .replace('__DB__', f'{ROOT}/var/aries.db'))
        t0 = str(int(time.time()))
        code, _, err = sh(pre.replace('__TASK__', 'pending').replace('__T0__', t0)
                          + '\n' + '\n'.join(case.get('setup') or []), str(sandbox))
        if code != 0:
            results.append({'id': cid, 'verdict': 'SETUP_FAILED', 'detail': err[:200]})
            continue
        try:
            task = submit(case['goal'])
        except Exception as exc:
            results.append({'id': cid, 'verdict': 'SUBMIT_FAILED', 'detail': str(exc)[:200]})
            sh(pre.replace('__TASK__', '-').replace('__T0__', t0)
               + '\n' + '\n'.join(case.get('teardown') or []), str(sandbox))
            continue
        rec = wait(task, case.get('budget_seconds', 180))
        recfile.write_text(json.dumps(rec, ensure_ascii=False))
        pre2 = pre.replace('__TASK__', task).replace('__T0__', t0)
        checks = []
        for chk in (case['independent_oracle'].get('checks') or []):
            c, out, e = sh(pre2 + '\n' + chk['command'], str(sandbox))
            checks.append({'id': chk.get('id'), 'kind': 'check', 'passed': c == 0, 'exit': c})
        forbidden = []
        for chk in (case['independent_oracle'].get('forbidden_state') or []):
            c, out, e = sh(pre2 + '\n' + chk['command'], str(sandbox))
            forbidden.append({'id': chk.get('id'), 'kind': 'forbidden_state',
                              'passed': c == 0, 'exit': c})
        sh(pre2 + '\n' + '\n'.join(case.get('teardown') or []), str(sandbox))
        # ПРОВЕРКА ШТО НЕ МОЖЕЛА ДА ОДГОВОРИ НЕ Е ПРОВЕРКА ШТО РЕКЛА „НЕ“.
        # `jq -e` враќа 1 кога изразот е false или null — тоа е вистински негативен
        # одговор. Излез 5 е грешка во самиот jq, 124 е истечено време, 127 е
        # непостоечка команда. Првата верзија ги броеше сите како паднати, па едно
        # скршено читање на фајл изгледаше како прекршена забранета состојба. Истата
        # мана што овој преглед ја најде кај verify_probe, сега во мојот инструмент.
        every = checks + forbidden
        broken = [c for c in every if not c['passed'] and c['exit'] not in (0, 1)]
        genuine = [c for c in every if not c['passed'] and c['exit'] == 1]
        ok = not broken and not genuine
        results.append({'id': cid, 'class': case['class'], 'held_out': case.get('held_out', False),
                        'expected_outcome': case['expected_outcome'], 'task_id': task,
                        'terminal_state': rec.get('state'), 'timed_out': rec.get('_timed_out', False),
                        'verdict': ('PASS' if ok else
                                    'FAIL' if genuine else 'INCONCLUSIVE'),
                        'inconclusive_checks': [{'id': c['id'], 'exit': c['exit']} for c in broken],
                        'checks': checks, 'forbidden_state': forbidden})
        print(f"{results[-1]['verdict']:4s} {cid:8s} {case['class']:24s} "
              f"state={rec.get('state')}")

    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    out = HERE / f'raw/fixture_run_{stamp}.json'
    out.write_text(json.dumps({'fixture_sha256': digest, 'conditions': state,
                               'cases_run': len(results), 'results': results},
                              ensure_ascii=False, indent=2))
    shutil.rmtree(sandbox, ignore_errors=True)
    tally: dict[str, int] = {}
    for r in results:
        tally[r['verdict']] = tally.get(r['verdict'], 0) + 1
    print(f'\n{tally}\nзапишано {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
