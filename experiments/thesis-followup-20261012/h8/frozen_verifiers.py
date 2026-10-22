#!/usr/bin/env python3
"""H8: fingerprint of every registered verifier, to prove ARIES_VERIFY_HARDENED=0 changes none of them.

A verifier's fingerprint is its module, qualified name, and a SHA-256 over its code object: bytecode,
constants (nested code objects recursively), names, and, for closures such as verify_probe(...), the
qualified names of the functions it closes over. `--write` records the fingerprints of the code as it
is now (run once, before any hardening, at the baseline-2 commit). Without `--write` it prints the
current fingerprints as JSON, which tests/test_verify_hardened.py compares with the recorded file.
Imports the registry only, against a scratch test database URL. Nothing is executed.

    .venv/bin/python experiments/thesis-followup-20261012/h8/frozen_verifiers.py --write
"""
import hashlib
import json
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'vendor/agentic-core'), str(ROOT / 'vendor'), str(ROOT)]
os.environ.setdefault('APP_ENV', 'test')
os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{tempfile.mkdtemp()}/h8-fp.db'
OUT = HERE / 'frozen_verifiers.json'


def code_digest(code, h):
    h.update(code.co_code)
    h.update(repr(code.co_names).encode())
    h.update(repr(code.co_varnames).encode())
    h.update(repr(code.co_freevars).encode())
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            code_digest(c, h)
        elif isinstance(c, frozenset):
            # A set constant's repr follows the process's hash seed; its sorted members do not.
            h.update(repr(sorted(map(repr, c))).encode())
        else:
            h.update(repr(c).encode())


def fingerprint(f):
    h = hashlib.sha256()
    code_digest(f.__code__, h)
    for name, cell in zip(f.__code__.co_freevars, f.__closure__ or ()):
        v = cell.cell_contents
        h.update(name.encode())
        h.update((f'{v.__module__}.{v.__qualname__}' if callable(v) else repr(v)).encode())
    return {'verifier': f'{f.__module__}.{f.__qualname__}', 'sha256': h.hexdigest()}


def current():
    from aries.workspace.registry import registry
    return {name: fingerprint(cap.verifier) for name, cap in sorted(registry._items.items())}


if __name__ == '__main__':
    fp = current()
    if '--write' in sys.argv[1:]:
        if OUT.exists():
            raise SystemExit('REFUSED: frozen_verifiers.json exists and is never rewritten')
        OUT.write_text(json.dumps({'what': 'H8 frozen verifier fingerprints, recorded before hardening',
                                   'python': sys.version.split()[0], 'verifiers': fp}, indent=1) + '\n')
        print(len(fp), 'verifiers recorded')
    else:
        print(json.dumps(fp))
