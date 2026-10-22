#!/usr/bin/env python3
"""Exploratory, DESIGNED AFTER H8: rerun the frozen H8 mutant harness with ARIES_VERIFY_SCOPE=1.

The harness itself is not copied and not edited. It is loaded from
experiments/thesis-followup-20261012/h8/run_mutants.py (its SHA-256 is recorded in run.json as before),
and only its output folder is redirected here, so nothing is written under the frozen tree.
Every other argument is passed through unchanged.

    cd <repo> && nice -n 19 .venv/bin/python experiments/exploratory/h8-verify-scope/run.py \
        --manifest experiments/thesis-followup-20261012/h8/mutants.json --label exploratory-verify-scope

Offline by construction (the harness's own tripwires): no service, no model, no GPU, no network.
"""
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HARNESS = ROOT / 'experiments/thesis-followup-20261012/h8/run_mutants.py'

if '--hardened' in sys.argv or '--sealed' in sys.argv:
    raise SystemExit('REFUSED: this exploratory rerun is the baseline registry plus ARIES_VERIFY_SCOPE only')
os.environ['ARIES_VERIFY_SCOPE'] = '1'

spec = importlib.util.spec_from_file_location('run_mutants', HARNESS)
harness = importlib.util.module_from_spec(spec)
sys.modules['run_mutants'] = harness
spec.loader.exec_module(harness)          # sets APP_ENV=test, a scratch DB and flag file, the tripwires
harness.HERE = HERE                        # output goes to HERE/runs/, never to the frozen h8/runs/

before = set((HERE / 'runs').glob('*')) if (HERE / 'runs').exists() else set()
harness.main()
after = sorted(set((HERE / 'runs').glob('*')) - before)
for run in after:
    from aries import flags
    (run / 'exploratory.json').write_text(json.dumps({
        'label': 'exploratory, designed after H8 (not part of the confirmatory H8 test)',
        'harness': str(HARNESS.relative_to(ROOT)),
        'harness_sha256': hashlib.sha256(HARNESS.read_bytes()).hexdigest(),
        'wrapper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'flags': flags.describe()}, indent=1) + '\n')
    print('exploratory metadata ->', (run / 'exploratory.json').relative_to(ROOT))
