#!/usr/bin/env python3
"""H8: for each capability, does the frozen verifier read through a different path than the executor?

Static, from source only: the executor and verifier of every registered capability are resolved with
inspect. The source of every function the verifier calls is followed one level into the same module,
looking for a call to the executor function, which would mean it reads by re-running the executor.
Writes read_paths.json next to this file. No capability is executed, and no service, model or database
is used (the registry is imported against a scratch test database URL).

    .venv/bin/python experiments/thesis-followup-20261012/h8/read_paths.py
"""
import inspect
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'vendor/agentic-core'), str(ROOT / 'vendor'), str(ROOT)]
os.environ['APP_ENV'] = 'test'
os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{tempfile.mkdtemp()}/h8-paths.db'


def unwrap(f):
    """verify_probe(...) returns a closure over the executor: report the closure's free variables too."""
    free = {}
    if getattr(f, '__closure__', None):
        for name, cell in zip(f.__code__.co_freevars, f.__closure__):
            try:
                free[name] = cell.cell_contents
            except ValueError:
                pass
    return free


def main():
    from aries.workspace.registry import registry
    review = {r['name']: r for r in json.loads(
        (ROOT / 'experiments/product/independent-acceptance/raw/review_verifier_integrity.json').read_text())['capabilities']}
    rows = []
    for name, cap in sorted(registry._items.items()):
        ex, ve = cap.executor, cap.verifier
        ex_name = ex.__name__
        free = unwrap(ve)
        reruns = any(v is ex for v in free.values())
        src = inspect.getsource(ve)
        calls_ex_directly = bool(re.search(rf'\b{re.escape(ex_name)}\s*\(', src)) and ve.__name__ != ex_name
        # one level: helper functions of the verifier's module that it calls
        module = sys.modules[ve.__module__]
        helpers = [n for n in re.findall(r'\b([a-z_][a-z0-9_]*)\s*\(', src)
                   if inspect.isfunction(getattr(module, n, None)) and getattr(module, n) is not ve]
        via_helper = [h for h in helpers if re.search(rf'\b{re.escape(ex_name)}\s*\(', inspect.getsource(getattr(module, h)))
                      and h != ex_name]
        same = reruns or calls_ex_directly or bool(via_helper)
        rows.append({'capability': name, 'effect': cap.effect, 'verifier_class': review[name]['verifier_class'],
                     'executor': f'{ex.__module__}.{ex.__qualname__}', 'verifier': f'{ve.__module__}.{ve.__qualname__}',
                     'verifier_reruns_executor': same,
                     'how': ('closure over the executor (verify_probe)' if reruns else
                             'calls the executor function' if calls_ex_directly else
                             f'calls the executor via {via_helper}' if via_helper else
                             'separate read path'),
                     'collaborators_called': sorted(set(helpers))[:12]})
    out = {'what': 'H8 static read-path analysis of the frozen verifiers', 'rows': rows,
           'counts': {'capabilities': len(rows), 'verifier_reruns_executor': sum(r['verifier_reruns_executor'] for r in rows)}}
    (HERE / 'read_paths.json').write_text(json.dumps(out, indent=1) + '\n')
    for r in rows:
        if r['verifier_reruns_executor']:
            print(f"SAME  {r['capability']:24} {r['verifier_class']:16} {r['how']}")
    print(out['counts'])


if __name__ == '__main__':
    main()
