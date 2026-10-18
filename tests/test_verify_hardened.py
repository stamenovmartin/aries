"""ARIES_VERIFY_HARDENED (H8): off, every verifier is the frozen one; on, exactly the 23 are replaced.

The frozen fingerprints were recorded by experiments/thesis-followup-20261012/h8/frozen_verifiers.py
before aries/workspace/hardened_verifiers.py existed. Each flag setting is checked in its own process,
because the flag is read when the registry is imported.
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import check, run_module

ROOT = Path(__file__).resolve().parents[1]
H8 = ROOT / 'experiments/thesis-followup-20261012/h8'
FROZEN = json.loads((H8 / 'frozen_verifiers.json').read_text())['verifiers']
HARDENED = json.loads((H8 / 'mutants.json').read_text())['hardened_capabilities']
EXTRA = ['notification.send', 'system.disk']


def fingerprints(hardened, extra):
    env = {**os.environ, 'ARIES_VERIFY_HARDENED': hardened, 'ARIES_VERIFY_HARDENED_EXTRA': extra,
           'ARIES_FLAG_FILE': '/nonexistent/aries-flags.env'}
    code = ('import runpy,sys,json; sys.argv=["x"]; '
            'm=runpy.run_path(%r); print(json.dumps({"fp": m["current"](), '
            '"loaded": "aries.workspace.hardened_verifiers" in sys.modules}))' % str(H8 / 'frozen_verifiers.py'))
    out = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def changed(fp):
    return sorted(n for n in FROZEN if fp[n] != FROZEN[n])


def test_flag_off_is_byte_identical():
    got = fingerprints('0', '0')
    check('58 verifiers registered', len(got['fp']) == len(FROZEN) == 58)
    check('flag off: every verifier fingerprint equals the frozen one', changed(got['fp']) == [])
    check('flag off: the hardened module is never imported', got['loaded'] is False)


def test_flag_on_replaces_exactly_the_23():
    got = fingerprints('1', '0')
    check('the manifest names 23 hardened capabilities', len(HARDENED) == 23)
    check('flag on: exactly those 23 verifiers change', changed(got['fp']) == sorted(HARDENED))
    check('flag on: each is a hardened verifier',
          all(got['fp'][n]['verifier'].startswith('aries.workspace.hardened_verifiers.hardened_') for n in HARDENED))


def test_extra_is_separate():
    check('extra alone: only notification.send and system.disk change', changed(fingerprints('0', '1')['fp']) == EXTRA)
    check('both: 25 change', changed(fingerprints('1', '1')['fp']) == sorted(HARDENED + EXTRA))


def test_verdict_logic():
    from aries.workspace import hardened_verifiers as H
    check('a value within measured drift plus resolution agrees', H._within(10.4, 10.0, 10.2, 0.5))
    check('a value outside it does not', not H._within(12.0, 10.0, 10.2, 0.5))
    check('a missing value never agrees', not H._within(None, 10.0, 10.2, 0.5))
    v = H.verdict('k', {'a': True, 'b': False}, {})
    check('one failed check fails the verdict', v['met'] is False and v['checks'] == {'a': True, 'b': False})
    v = H.verdict('k', {'a': True}, {}, frozen={'met': False, 'data': {}})
    check('a failed frozen verdict fails the hardened one', v['met'] is False)

    async def boom(args, result, ctx):
        raise OSError('collaborator unavailable')
    out = asyncio.run(H.guarded('x.y', boom)({}, {}, {}))
    check('an exception in the independent read is UNVERIFIED, not met',
          out['met'] is False and out['status'] == 'UNVERIFIED')


def test_reading_identity():
    from aries.workspace import hardened_verifiers as H
    probe = lambda unit: {'probes': [{'probe': 'cpu', 'readings': [
        {'metric': 'cpu.used_pct', 'subject': None, 'value': 5.0, 'unit': unit}]}]}
    checks, range_only = H._reading_checks(probe('%'), probe('%'), probe('%'))
    check('identical identity agrees; a CPU sample is range-checked only',
          all(checks.values()) and range_only == ['cpu.used_pct@-'])
    checks, _ = H._reading_checks(probe('% changed'), probe('%'), probe('%'))
    check('a changed unit breaks identity', checks['identity_agrees'] is False)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
