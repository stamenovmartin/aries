#!/usr/bin/env python3
"""Exploratory re-runs of H5 and H4b with the remedies designed after their results
(docs/preregistration/X1-remedy-reruns.md). The registered runners are used unchanged; this wrapper only
changes where they look and write, and adds the conditions below.

    run_followup_rerun.py h5  --condition remedies|consolidated --label r1 [--go]
    run_followup_rerun.py h4b --condition code-select           --label r1 [--go]

- The item files are the frozen H5 and H4b items in the thesis-followup checkout (~/aries/...). They are
  validated by the runners' own validators and never opened here.
- The ARIES instance runs this checkout's code: the captured service environment points PYTHONPATH at the
  live service's checkout, so it is replaced with this checkout's paths (recorded in run.json).
- Settings are copied from the live database read-only, as in the registered runs.
- Run folders are written next to this file and stay local (they contain item texts).
"""
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FU = ROOT / 'experiments/thesis-followup-20261012'
LIVE = pathlib.Path.home() / 'aries'

H5_REMEDIES = {'ARIES_COMPLETION_READ_PARAPHRASE': '1', 'ARIES_COMPLETION_TYPED_CONTRACT': '1',
               'ARIES_CONTRACT_FILENAME_JOIN': '1', 'ARIES_TYPED_CONTRACT_CODE_PATH': '1'}
CONSOLIDATED = {**H5_REMEDIES, 'ARIES_READ_PATH_STRICT': '1', 'ARIES_LOOP_GUARD': '1', 'ARIES_PLAN_DISPATCH_FIX': '1'}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def this_checkout(original):
    def instance_env(run):
        env, note = original(run)
        env['PYTHONPATH'] = ':'.join(str(p) for p in (ROOT / 'vendor/agentic-core', ROOT / 'vendor', ROOT))
        note['pythonpath'] = 'replaced with this checkout (' + str(ROOT) + ')'
        return env, note
    return instance_env


def main():
    which, args = sys.argv[1], sys.argv[2:]
    if which == 'h5':
        m = load(FU / 'h5-runs/run_h5.py', 'run_h5')
        m.ITEMS = LIVE / 'experiments/thesis-followup-20261012/h5-items'
        m.CONDITIONS = {'remedies': {**H5_REMEDIES, **m.PINNED}, 'consolidated': {**CONSOLIDATED, **m.PINNED}}
        m.HERE = HERE / 'h5-reruns'
        m.HERE.mkdir(exist_ok=True)
        hook = m.HERE / 'change_hook.py'           # run.json records the hook's SHA-256 from HERE
        if not hook.exists():
            hook.symlink_to(FU / 'h5-runs/change_hook.py')
    elif which == 'h4b':
        m = load(FU / 'h4b-runs/run_h4b.py', 'run_h4b')
        m.ITEMS = LIVE / 'experiments/thesis-followup-20261012/h4b-items'
        m.CONDITIONS = {'code-select': {**m.H4_TREATMENT, 'ARIES_CLARIFY_RESOLVER': '1',
                                        'ARIES_RESOLVER_CODE_SELECT': '1', **m.PINNED}}
        m.HERE = HERE / 'h4b-reruns'
    else:
        raise SystemExit(__doc__)
    m.HERE.mkdir(exist_ok=True)
    m.LIVE_DB = LIVE / 'var/aries.db'
    m.instance_env = this_checkout(m.instance_env)
    sys.argv = [f'run_{which}.py', *args]
    return m.main()


if __name__ == '__main__':
    sys.exit(main())
