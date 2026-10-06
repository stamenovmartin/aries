#!/usr/bin/env python3
"""Дали оракулите на фикстурите МОЖАТ да паднат?

Истата лекција како F-06 и F-11, свртена кон нашиот сопствен инструмент. Проверка
што не може да врати неуспех не е проверка. Затоа секој оракул се извршува против
запис во кој ARIES **не направил ништо**:

    {"state": "queued", "steps": [], "evidence": [], "cards": [], "gaps": []}

За случај што очекува дејство, барем една проверка мора да ПАДНЕ врз таков запис.
Ако сите поминат, тој случај не разликува успех од ништо и е безвреден.

Ништо не се поднесува до ARIES. Базата не се отвора. Сервиси не се допираат.
Песочникот е во привремен директориум, не во домот на корисникот.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE / 'fixtures.jsonl'
NULL_RECORD = {'state': 'queued', 'steps': [], 'evidence': [], 'cards': [], 'gaps': []}

PREAMBLE = r'''
set -u
export ROOT="__ROOT__"; export ID="__ID__"; export C="$ROOT/$ID"
export M="__M__"; export TASK="synthetic-null"; export T0=0
MANIFEST() { find "$1" -printf '%y %p %s\n' 2>/dev/null | LC_ALL=C sort; }
REC() { cat "__REC__"; }
WINDOWS() { echo '{"windows":[]}'; }
SCHEDCOUNT() { echo '0 0 0'; }
export -f MANIFEST REC WINDOWS SCHEDCOUNT 2>/dev/null || true
'''


def run(script: str, cwd: str, timeout: int = 25):
    try:
        p = subprocess.run(['bash', '-c', script], cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or '')[:400], (p.stderr or '')[:400]
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'


def main() -> int:
    cases = [json.loads(line) for line in FIXTURES.read_text().splitlines() if line.strip()]
    sandbox = pathlib.Path(tempfile.mkdtemp(prefix='aries-oracle-validate-'))
    root = sandbox / 'ARIES-CIA-01'
    state = sandbox / 'aries-cia'
    rec = sandbox / 'null_record.json'
    rec.write_text(json.dumps(NULL_RECORD))
    results = []

    for case in cases:
        cid = case['id']
        if case.get('requires'):
            results.append({'id': cid, 'class': case['class'],
                            'expected_outcome': case['expected_outcome'],
                            'verdict': 'SKIPPED_NEEDS_CONSENT',
                            'requires': case['requires']})
            continue
        pre = (PREAMBLE.replace('__ROOT__', str(root)).replace('__ID__', cid)
               .replace('__M__', str(state)).replace('__REC__', str(rec)))
        code, _, err = run(pre + '\n' + '\n'.join(case.get('setup') or []), str(sandbox))
        if code != 0:
            results.append({'id': cid, 'class': case['class'],
                            'expected_outcome': case['expected_outcome'],
                            'verdict': 'SETUP_FAILED', 'detail': err[:200]})
            run(pre + '\n' + '\n'.join(case.get('teardown') or []), str(sandbox))
            continue

        oracle = case['independent_oracle']
        checks = []
        for chk in oracle.get('checks') or []:
            c, out, e = run(pre + '\n' + chk['command'], str(sandbox))
            checks.append({'id': chk.get('id'), 'kind': 'check',
                           'passes_on_null_record': c == 0,
                           'exit': c, 'stderr': e[:120]})
        forbidden = []
        for chk in oracle.get('forbidden_state') or []:
            c, out, e = run(pre + '\n' + chk['command'], str(sandbox))
            forbidden.append({'id': chk.get('id'), 'kind': 'forbidden_state',
                              'passes_on_null_record': c == 0,
                              'exit': c, 'stderr': e[:120]})
        run(pre + '\n' + '\n'.join(case.get('teardown') or []), str(sandbox))

        blind = checks and all(c['passes_on_null_record'] for c in checks)
        broken_forbidden = [f for f in forbidden if not f['passes_on_null_record']]
        verdict = ('NO_CHECKS' if not checks else
                   'BLIND_TO_INACTION' if blind else 'DISCRIMINATING')
        results.append({'id': cid, 'class': case['class'],
                        'expected_outcome': case['expected_outcome'],
                        'held_out': case.get('held_out', False),
                        'verdict': verdict,
                        'checks_failing_on_null': sum(1 for c in checks if not c['passes_on_null_record']),
                        'checks_total': len(checks),
                        'forbidden_violated_by_setup': [f['id'] for f in broken_forbidden],
                        'detail': checks + forbidden})

    shutil.rmtree(sandbox, ignore_errors=True)
    tally: dict[str, int] = {}
    for r in results:
        tally[r['verdict']] = tally.get(r['verdict'], 0) + 1
    out = HERE / 'raw/oracle_validation.json'
    out.write_text(json.dumps({
        'question': 'Can each fixture oracle fail? A check that passes when ARIES did nothing '
                    'cannot distinguish success from inaction.',
        'method': 'Every oracle executed against a record in which ARIES did nothing. Isolated '
                  'temp sandbox; no goal submitted, no database opened, no service touched.',
        'null_record': NULL_RECORD,
        'summary': tally, 'cases': results}, ensure_ascii=False, indent=2))

    print(f'случаи: {len(results)}')
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f'   {k:24s} {v}')
    blind_cases = [r for r in results if r['verdict'] == 'BLIND_TO_INACTION']
    if blind_cases:
        print('\nСЛЕПИ НА НЕРАБОТЕЊЕ (секоја проверка поминува кога ништо не се случило):')
        for r in blind_cases:
            print(f"   {r['id']:8s} {r['class']:24s} очекувано={r['expected_outcome']}")
    bad_setup = [r for r in results if r['verdict'] in ('SETUP_FAILED', 'NO_CHECKS')]
    if bad_setup:
        print('\nпроблем со поставување:')
        for r in bad_setup:
            print(f"   {r['id']:8s} {r['verdict']}  {str(r.get('detail'))[:100]}")
    print(f'\nзапишано {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
