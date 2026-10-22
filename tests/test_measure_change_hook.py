"""ARIES_MEASURE_CHANGE_HOOK (H5 changed_after_read controls), tested on the H5 example items.

The goal loop runs in-process with a scripted planner (no model): read the file, then finish. The runner
side is experiments/thesis-followup-20261012/h5-runs/change_hook.py, serving from a thread exactly as the
H5 runner will, and the item's own setup, change command and oracle run through run_fixtures.sh with its
PREAMBLE. The case folder is a temporary folder under $HOME instead of ~/Documents/ARIES-CIA-01, and the goal
text is rewritten to name it.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-measure-change-hook')
from aries.workspace import agent, agent_planner
from aries.workspace.models import WorkspaceGoal
from agentic_core.database.base import async_session

ROOT = Path(__file__).resolve().parents[1]
FU = ROOT / 'experiments/thesis-followup-20261012'
GOAL_ROOT = '/home/stamenovmartin/Documents/ARIES-CIA-01'
ITEMS = {json.loads(l)['id']: json.loads(l) for l in (FU / 'h5-items/example_items.jsonl').read_text().splitlines()}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RF = load('run_fixtures', ROOT / 'experiments/product/independent-acceptance/run_fixtures.py')
CH = load('change_hook', FU / 'h5-runs/change_hook.py')


def hook_folder():
    """<DATA_DIR>/measure-hook, without importing the hook module."""
    from agentic_core.config.settings import settings
    return Path(settings.data_dir) / 'measure-hook'


class Case:
    """One example item in a temporary root: setup on enter, teardown on exit."""

    def __init__(self, item_id, anchored=False):
        self.item = ITEMS[item_id]
        self.anchored = anchored

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home())
        base = Path(self.temp.name)
        self.root, self.m, self.sandbox = base / 'cases', base / 'state', base / 'sandbox'
        self.root.mkdir(); self.sandbox.mkdir()
        self.c = self.root / self.item['id']
        self.recfile = self.sandbox / 'record.json'
        self.goal = (f'Read {self.c}/{self.item["change_after_read"]["file"] if "change_after_read" in self.item else "packing-list.txt"}'
                     if self.anchored else self.item['goal'].replace(GOAL_ROOT, str(self.root)))
        code, _, err = RF.sh(self.pre('pending') + '\n' + '\n'.join(self.item['setup']), str(self.sandbox))
        assert code == 0, err
        return self

    def pre(self, task):
        return (RF.PREAMBLE.replace('__ROOT__', str(self.root)).replace('__ID__', self.item['id'])
                .replace('__M__', str(self.m)).replace('__REC__', str(self.recfile)).replace('__DB__', '/nonexistent')
                .replace('__TASK__', task).replace('__T0__', '0'))

    def oracle(self, record):
        self.recfile.write_text(json.dumps(record))
        return {c['id']: RF.sh(self.pre('root') + '\n' + c['command'], str(self.sandbox))[0]
                for c in self.item['independent_oracle']['checks']}

    def __exit__(self, *exc):
        RF.sh(self.pre('root') + '\n' + '\n'.join(self.item['teardown']), str(self.sandbox))
        self.temp.cleanup()


async def run_goal(case, *, flag, arm, serve=True, timeout=30):
    """The goal loop with a scripted planner; returns (record, hook record or None, planner calls)."""
    await reset_db()
    target = str(case.c / 'packing-list.txt')
    async with async_session() as db:
        db.add(WorkspaceGoal(id='root', request=case.goal, state='running', result_json='{}'))
        await db.commit()
    calls = 0

    async def planner(db, goal, data, budget):
        nonlocal calls
        calls += 1
        verified = [e['evidence_id'] for e in data['evidence'] if e['verified']]
        if not data['steps']:
            decision = {'action': 'execute', 'capability': 'file.read', 'arguments': {'path': target}}
        elif not data['agent'].get('completion_checks'):
            decision = {'action': 'finish', 'evidence_refs': verified, 'summary': 'read it'}
        else:
            decision = {'action': 'fail', 'reason': 'finish rejected; stop'}
        return json.dumps(decision), {'measured': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}

    hook = CH.ChangeHook(hook_folder(), timeout_seconds=timeout)
    thread = None
    if arm:
        hook.arm(case.goal)
        if serve:
            apply = CH.shell_apply(RF.sh, case.pre('root'), case.item, case.c, case.sandbox)
            thread = hook.start(case.goal, apply, wait_seconds=timeout)
    env = {'ARIES_MEASURE_CHANGE_HOOK': '1' if flag else '0', 'ARIES_GOAL_TEAMS': '0', 'ARIES_CONTRACT_FINISH': '0'}
    with patch.dict('os.environ', env), patch.object(agent_planner, 'plan', side_effect=planner):
        await agent.run('root', case.goal, {})
    hook_record = hook.finish(case.goal, thread) if arm else None
    async with async_session() as db:
        row = await db.get(WorkspaceGoal, 'root')
        record = {'state': row.state, **json.loads(row.result_json or '{}')}
    return record, hook_record, calls


async def test_example_control_as_written():
    """ex-n-01 exactly as written (its own goal text): the change lands between the read and the finish."""
    with Case('ex-n-01') as case:
        record, hook, _ = await run_goal(case, flag=True, arm=True)
        check('the hook fired once, after a verified file.read', hook['fired'] and
              [s['capability'] for s in hook['paused']['verified_steps']] == ['file.read'])
        check('the change command ran and changed the file',
              hook['change']['exit'] == 0 and hook['change']['sha256_before'] != hook['change']['sha256_after'])
        check('the instance resumed after the release, and recorded it',
              record['agent']['measurement_hook']['released'] is True)
        check('manifest.after was written by the runner', (case.m / 'ex-n-01.manifest.after').exists())
        verdict = case.oracle(record)
        check('the example oracle runs on the record: both checks exit 0 or 1', set(verdict.values()) <= {0, 1})
        print('    ex-n-01 as written: state', record['state'], 'oracle exits', verdict)


async def test_recheck_sees_the_change():
    """The anchored variant has a contract, so the finish is re-checked: the re-check reads the changed file."""
    with Case('ex-n-01', anchored=True) as case:
        record, hook, _ = await run_goal(case, flag=True, arm=True)
        checks = record['agent'].get('completion_checks', [])
        check('the hook fired before the first completion check', hook['fired'] and len(checks) >= 1)
        check('the first finish is rejected after the change', checks[0]['met'] is False)
        check('the goal does not end in done', record['state'] != 'done')
        check('example oracle: PASS (terminal_not_done and sandbox_as_changed)',
              case.oracle(record) == {'terminal_not_done': 0, 'sandbox_as_changed': 0})


async def test_unarmed_goal_is_not_paused():
    with Case('ex-g-01', anchored=True) as case:
        record, _, _ = await run_goal(case, flag=True, arm=False)
        check('an unarmed goal never pauses', 'measurement_hook' not in record['agent']
              and not list(hook_folder().glob('*.paused')))
        check('an unarmed read goal reaches done', record['state'] == 'done')
        check('example goal oracle: PASS', set(case.oracle(record).values()) == {0})


async def test_flag_off_ignores_an_armed_goal():
    sys.modules.pop('aries.workspace.measurement_hook', None)
    with Case('ex-n-01', anchored=True) as case:
        before = (case.c / 'packing-list.txt').read_bytes()
        hook = CH.ChangeHook(hook_folder(), timeout_seconds=2)
        hook.arm(case.goal)
        thread = hook.start(case.goal, lambda: {'unexpected': True}, wait_seconds=2)
        record, _, calls = await run_goal(case, flag=False, arm=False)
        rec = hook.finish(case.goal, thread)
        check('flag off: the hook module is never imported', 'aries.workspace.measurement_hook' not in sys.modules)
        check('flag off: nothing paused, nothing changed',
              not rec['fired'] and (case.c / 'packing-list.txt').read_bytes() == before)
        check('flag off: the goal runs as without the hook (read, finish, done)',
              record['state'] == 'done' and calls == 2 and 'measurement_hook' not in record['agent'])


async def test_no_release_times_out():
    with Case('ex-n-01', anchored=True) as case:
        record, hook, _ = await run_goal(case, flag=True, arm=True, serve=False, timeout=0.5)
        check('without a release the check proceeds after the timeout, and says so',
              record['agent']['measurement_hook']['released'] is False and not hook['fired'])


async def test_pause_needs_a_verified_step():
    from aries.workspace import measurement_hook as MH
    folder = MH.hook_dir()
    check('the runner and the instance use the same folder', folder == hook_folder())
    folder.mkdir(parents=True, exist_ok=True)
    goal = 'Read /tmp/nothing-verified-yet'
    (folder / f'{MH.key(goal)}.watch').write_text('{"timeout_seconds": 0.2}')
    try:
        out = await MH.pause('t', goal, {'steps': [{'verification_status': 'failed'}]})
        check('no verified step: no pause, no paused file', out is None and not (folder / f'{MH.key(goal)}.paused').exists())
    finally:
        for p in folder.glob(f'{MH.key(goal)}.*'):
            p.unlink()


def test_unfired_writes_the_setup_manifest():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'x.manifest').write_text('f a 1\n')
        CH.apply_unfired(d, 'x')
        check('unfired: manifest.after equals the setup manifest',
              (Path(d) / 'x.manifest.after').read_text() == 'f a 1\n')


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
