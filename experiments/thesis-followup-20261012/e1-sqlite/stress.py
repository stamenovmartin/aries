#!/usr/bin/env python3
"""E1 stress test: many agent goals in several processes against ONE scratch SQLite file.

Never the live database: the file lives in a fresh temporary folder, and APP_ENV=test.

Why processes, not 20 goals in one process: an agent goal reserves the files, desktop,
local-model and browser lanes (service.resources_for), so one process never runs two agent
goals at once. Contention in ARIES comes from other processes writing the same file
(aries-core, aries-voice, aries-local-model, CLI calls). So WORKERS processes each run GOALS
goals of STEPS verified file.read steps with a scripted planner (no model), while one more
process writes small audit-like rows as fast as it can through a plain session.

Counted per worker: goals by terminal state, every exception or log line that mentions a
lock (database is locked, SQLITE_BUSY, WriterBusy, "lost the lock", "waited"), writer.stats(),
and wall time. Output: <out>/stress-<label>.json.

    .venv/bin/python experiments/thesis-followup-20261012/e1-sqlite/stress.py --label before --out <dir>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOCK_WORDS = ('database is locked', 'sqlite_busy', 'writerbusy', 'lost the lock', 'waited', 'table is locked')


def env_for(db_dir):
    env = dict(os.environ, APP_ENV='test', DATABASE_URL=f'sqlite+aiosqlite:///{db_dir}/stress.db', DATA_DIR=db_dir,
               RUNTIME_STORE=f'{db_dir}/runtime.json', CONTEXT_DIR=f'{db_dir}/context', AI_PROVIDER='template',
               DRY_RUN='true', LIVE_TOOLS='', API_KEY='', ARIES_FLAG_FILE=f'{db_dir}/flags.env')
    env.pop('CREDENTIALS_KEY', None)
    return env


def imports():
    for p in (ROOT / 'vendor/agentic-core', ROOT / 'vendor', ROOT):
        sys.path.insert(0, str(p))


class LockLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        msg = record.getMessage()
        if any(w in msg.lower() for w in LOCK_WORDS):
            self.lines.append(msg[:300])


async def worker(index, goals, steps, files_dir, out):
    imports()
    handler = LockLog()
    logging.getLogger().addHandler(handler)
    from unittest.mock import patch
    from agentic_core.config.settings import settings as engine_settings
    from agentic_core.database import writer
    from agentic_core.database.base import async_session
    from aries.workspace import agent_planner, service
    from aries.workspace.models import WorkspaceGoal
    from aries.workspace.capabilities import TOOL_NAMES
    files = sorted(str(p) for p in Path(files_dir).iterdir())

    def plan_for():
        i = 0
        async def plan(db, goal, data, budget):
            nonlocal i
            choice = ({'action': 'execute', 'capability': 'file.read', 'arguments': {'path': files[i % len(files)]},
                       'reason': 'stress'} if i < steps else {'action': 'fail', 'summary': 'stress done'})
            i += 1
            return json.dumps(choice), {'measured': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
        return plan

    states, errors, t0 = [], [], time.monotonic()
    for g in range(goals):
        try:
            with patch.object(agent_planner, 'plan', side_effect=plan_for()), \
                    patch.object(engine_settings, 'dry_run', False), \
                    patch.object(engine_settings, 'live_tools', ','.join(TOOL_NAMES)):
                async with async_session() as db:
                    row = await service.submit(db, '', capability='agent_task',
                                               args={'task': f'Stress goal {index}-{g}: read the files in {files_dir}'},
                                               origin='user')
                await service.dispatch()
                async with async_session() as db:
                    done = (await db.get(WorkspaceGoal, row['id'])).as_dict()
            states.append(done['state'])
            text = json.dumps(done).lower()
            if any(w in text for w in ('database is locked', 'sqlite_busy', 'writerbusy')):
                errors.append(f'goal {g}: lock text inside the goal record')
            steps_done = len(done.get('steps', []))
            if steps_done != steps:
                errors.append(f'goal {g}: {steps_done} steps, expected {steps}')
        except Exception as exc:                                   # noqa: BLE001
            states.append('exception')
            errors.append(f'goal {g}: {type(exc).__name__}: {str(exc)[:300]}')
    Path(out).write_text(json.dumps({'worker': index, 'states': states, 'errors': errors,
                                     'lock_log_lines': handler.lines, 'writer_stats': writer.stats(),
                                     'seconds': round(time.monotonic() - t0, 2)}, indent=1))


async def background(seconds, out):
    """Small independent writes through a plain session, like another ARIES process would make."""
    imports()
    handler = LockLog()
    logging.getLogger().addHandler(handler)
    from sqlalchemy import text
    from agentic_core.database.base import async_session
    async with async_session() as db:
        await db.execute(text('CREATE TABLE IF NOT EXISTS stress_bg (id INTEGER PRIMARY KEY, at REAL)'))
        await db.commit()
    n, errors, t_end = 0, [], time.monotonic() + seconds
    stop = Path(out).with_name('stop')
    while time.monotonic() < t_end and not stop.exists():
        try:
            async with async_session() as db:
                await db.execute(text('INSERT INTO stress_bg (at) VALUES (:t)'), {'t': time.time()})
                await db.commit()
            n += 1
        except Exception as exc:                                   # noqa: BLE001
            errors.append(f'{type(exc).__name__}: {str(exc)[:200]}')
        await asyncio.sleep(0.01)
    Path(out).write_text(json.dumps({'writes': n, 'errors': errors, 'lock_log_lines': handler.lines}, indent=1))


async def setup_db(steps):
    imports()
    sys.path.insert(0, str(ROOT))
    from tests._bootstrap import reset_db
    from agentic_core.database.base import async_session
    from aries.settings import SettingsService
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set('operator.enabled', True, set_by='user')
        await s.set('operator.confirm_model_plans', False, set_by='user')
        await s.set('workspace.agent_max_steps', steps, set_by='user')
        await db.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--goals', type=int, default=5)
    ap.add_argument('--steps', type=int, default=50)
    ap.add_argument('--role', default='coordinator')
    ap.add_argument('--index', type=int, default=0)
    ap.add_argument('--files', default='')
    ap.add_argument('--seconds', type=float, default=0)
    ap.add_argument('--part', default='')
    cli = ap.parse_args()
    if cli.role == 'worker':
        asyncio.run(worker(cli.index, cli.goals, cli.steps, cli.files, cli.part))
        return
    if cli.role == 'background':
        asyncio.run(background(cli.seconds, cli.part))
        return
    if cli.role == 'setup':
        asyncio.run(setup_db(cli.steps))
        return
    out = Path(cli.out)
    out.mkdir(parents=True, exist_ok=True)
    db_dir = tempfile.mkdtemp(prefix='aries-e1-stress-')
    env = env_for(db_dir)
    files_dir = tempfile.mkdtemp(prefix='aries-e1-files-', dir=Path.home())
    for i in range(cli.steps):
        Path(files_dir, f'f{i:03d}.txt').write_text(f'stress file {i}\n')
    me = [sys.executable, '-I', str(Path(__file__).resolve())]
    subprocess.run(me + ['--label', cli.label, '--out', str(out), '--role', 'setup', '--steps', str(cli.steps)],
                   env=env, check=True)
    parts = Path(db_dir) / 'parts'
    parts.mkdir()
    t0 = time.monotonic()
    procs = [subprocess.Popen(me + ['--label', cli.label, '--out', str(out), '--role', 'worker', '--index', str(i),
                                    '--goals', str(cli.goals), '--steps', str(cli.steps), '--files', files_dir,
                                    '--part', str(parts / f'w{i}.json')], env=env,
                              stdout=subprocess.DEVNULL, stderr=open(parts / f'w{i}.err', 'w'))
             for i in range(cli.workers)]
    bg = subprocess.Popen(me + ['--label', cli.label, '--out', str(out), '--role', 'background', '--seconds', '1e9',
                                '--part', str(parts / 'bg.json')], env=env, stdout=subprocess.DEVNULL,
                          stderr=open(parts / 'bg.err', 'w'))
    codes = [p.wait() for p in procs]
    wall = round(time.monotonic() - t0, 2)
    (parts / 'stop').write_text('')
    bg.wait(timeout=30)
    background_result = json.loads((parts / 'bg.json').read_text()) if (parts / 'bg.json').exists() else {'missing': True}
    workers = [json.loads((parts / f'w{i}.json').read_text()) if (parts / f'w{i}.json').exists()
               else {'worker': i, 'missing': True, 'stderr_tail': (parts / f'w{i}.err').read_text()[-1500:]}
               for i in range(cli.workers)]
    stderr_locks = sum(sum(w in line.lower() for w in LOCK_WORDS[:3]) for i in range(cli.workers)
                       for line in (parts / f'w{i}.err').read_text().splitlines())
    states = [s for w in workers for s in w.get('states', [])]
    report = {'label': cli.label, 'workers': cli.workers, 'goals_per_worker': cli.goals, 'steps_per_goal': cli.steps,
              'exit_codes': codes, 'wall_seconds': wall,
              'goal_states': {s: states.count(s) for s in sorted(set(states))},
              'goal_errors': sum(len(w.get('errors', [])) for w in workers),
              'lock_log_lines': sum(len(w.get('lock_log_lines', [])) for w in workers),
              'lock_mentions_in_stderr': stderr_locks,
              'background': {'writes': background_result.get('writes'), 'errors': len(background_result.get('errors', [])),
                             'lock_log_lines': len(background_result.get('lock_log_lines', []))},
              'workers_detail': workers}
    (out / f'stress-{cli.label}.json').write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != 'workers_detail'}, indent=1))
    import shutil
    shutil.rmtree(files_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
