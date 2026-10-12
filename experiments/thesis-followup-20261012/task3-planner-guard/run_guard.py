#!/usr/bin/env python3
"""Planner protocol (72 attempts) with the H4 treatment flags: "confirmation after the fix".

Runs the unchanged copy run_planner.py (byte copy of ../task3-planner/run_planner.py) with
the three H4 treatment flags pinned in the environment, which wins over every flags file
(aries/flags.py). Everything else (protocol, fixture, seeds, settings, scoring) is the copy.
Not independent evidence: ARIES_PLANNER_CLARIFY_GUARD was designed after the p20-p22
failure of the Task 3.2 run (preregistration H4, Amendment 2).

    run_guard.py --source-root var/followup-source/a2d1609 [--execute --window-id ID]
"""
import os, runpy, sys
from pathlib import Path

TREATMENT = {'ARIES_PLANNER_CLARIFY': '1', 'ARIES_PLANNER_CLARIFY_GUARD': '1',
             'ARIES_COMPLETION_READ_PARAPHRASE': '0'}
os.environ.update(TREATMENT)
sys.argv[0] = str(Path(__file__).resolve().parent / 'run_planner.py')
runpy.run_path(sys.argv[0], run_name='__main__')
