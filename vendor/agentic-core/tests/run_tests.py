#!/usr/bin/env python3
"""Run every test file in its own process (own sqlite, APP_ENV=test).
Usage: python tests/run_tests.py [filter...]"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main() -> int:
    filters = [a for a in sys.argv[1:] if not a.startswith("--")]
    tests = sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "test_*.py")))
    if filters:
        tests = [t for t in tests if any(f in t for f in filters)]
    passed, failed = [], []
    t_all = time.time()
    for i, t in enumerate(tests, 1):
        t0 = time.time()
        env = dict(os.environ, APP_ENV="test", PYTHONPATH=ROOT + os.pathsep + HERE)
        r = subprocess.run([sys.executable, os.path.join(HERE, t)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
        ok = r.returncode == 0
        print(f"[{i:>2}/{len(tests)}] {t:<30} {'passed' if ok else 'FAILED'} {time.time() - t0:5.1f}s")
        (passed if ok else failed).append((t, (r.stdout + r.stderr)))
    print(f"\npassed {len(passed)} · failed {len(failed)} · {time.time() - t_all:.0f}s")
    for name, out in failed:
        print(f"\n─── {name}\n" + "\n".join(out.strip().splitlines()[-25:]))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
