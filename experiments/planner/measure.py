"""Does the LOCAL planner produce a usable plan? Measured, per goal, not asserted.

Why this exists. `aries/analytics/` measured `local/qwen2.5:7b/workspace.m14-planner`
at 0 successes in 18 calls while `cloud/cli-default` was 77 of 77. The cause of the
zero was the grammar (see tests/test_planner_grammar.py); after bounding the schema
the gateway answers 200. A 200 is not a plan, though — the first local answer to
"report how much disk space is free" carried `arguments.task_id`, `action: stop` and
never set `capability` at all. This harness is the number that tells us whether a
returned plan is worth executing.

It calls the REAL `agent_planner.plan()` against the REAL gateway, through the same
`structured()` path production uses, with `data` built exactly as `agent.run()`
builds it. Nothing is stubbed; the only difference from production is a throwaway
sqlite file, because a measurement must not write to the live database. The live
database was read first and carries no `ai.*` or `intelligence.local_*` override, so
a fresh test database reproduces the installed sampling configuration exactly
(temperature 0.1, top_p 0.9, num_ctx 8192, gateway 127.0.0.1:11435, qwen2.5:7b).

Five things are scored per attempt, cheapest gate first, because a failure at one
level says something different from a failure at the next:

    returned    the gateway answered at all (this is what the grammar fix bought)
    json        the answer is a JSON object
    capability  it names one of the registry's capabilities
    args        those arguments validate against THAT capability's own input model
    plausible   a person asking this goal would accept that capability as step one

`parses` is the production gate — `agent_planner.parse()`, which is what
`agent.run()` actually calls and which rejects everything the executor would refuse.
`usable` is `parses AND plausible`: a plan that both survives validation and is the
right thing to do. That is the only headline number worth quoting.

Plausibility is a judgement, so it is written down: PLAUSIBLE below lists, per goal,
every capability a reasonable person would accept. It is deliberately generous —
`system.status` counts for a disk question, `desktop.focus` counts for "open the
app" — because the point is to catch nonsense, not to insist on one right answer.

    .venv/bin/python experiments/planner/measure.py --label baseline --repeats 3
"""
import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Environment before any agentic_core import, for the reason tests/_bootstrap gives:
# a run that reads the live switches is a run against production state.
_TMP = tempfile.mkdtemp(prefix='aries-planner-quality-')
os.environ.update(APP_ENV='test', DATABASE_URL=f'sqlite+aiosqlite:///{_TMP}/planner.db',
                  DATA_DIR=_TMP, RUNTIME_STORE=f'{_TMP}/runtime.json',
                  CONTEXT_DIR=f'{_TMP}/context', AI_PROVIDER='template', DRY_RUN='true',
                  LIVE_TOOLS='', API_KEY='')
os.environ.pop('CREDENTIALS_KEY', None)
for _p in (ROOT / 'vendor' / 'agentic-core', ROOT / 'vendor', ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# Goals a person actually says to this machine, half Macedonian, half English,
# spanning the capability families the product advertises. The expected sets name
# every capability that would be a defensible first action.
GOALS = [
    ('disk.en',    'en', 'How much disk space is free?',
     {'system.disk', 'system.storage', 'system.status'}),
    ('disk.mk',    'mk', 'Колку слободен простор има на дискот?',
     {'system.disk', 'system.storage', 'system.status'}),
    ('windows.en', 'en', 'Which windows are open right now?',
     {'desktop.windows', 'desktop.observe'}),
    ('windows.mk', 'mk', 'Кои прозорци се отворени сега?',
     {'desktop.windows', 'desktop.observe'}),
    ('read.en',    'en', 'Read /home/stamenovmartin/aries-demo/notes.txt',
     {'file.read'}),
    ('read.mk',    'mk', 'Прочитај /home/stamenovmartin/aries-demo/notes.txt',
     {'file.read'}),
    ('app.en',     'en', 'Open the Calculator application',
     {'desktop.launch', 'desktop.focus'}),
    ('app.mk',     'mk', 'Отвори ја апликацијата Калкулатор',
     {'desktop.launch', 'desktop.focus'}),
    ('shot.en',    'en', 'Take a screenshot of the whole screen',
     {'screen.capture', 'screen.screenshot'}),
    ('shot.mk',    'mk', 'Сликај го екранот',
     {'screen.capture', 'screen.screenshot'}),
    ('net.en',     'en', 'Am I connected to the internet?',
     {'network.status'}),
    ('net.mk',     'mk', 'Дали сум поврзан на интернет?',
     {'network.status'}),
    ('music.en',   'en', 'Play the song Lozano on YouTube',
     {'browser.search', 'browser.open', 'desktop.launch'}),
    ('music.mk',   'mk', 'Пушти ја песната Лозано на YouTube',
     {'browser.search', 'browser.open', 'desktop.launch'}),
    ('list.en',    'en', 'List the files in my Downloads folder',
     {'file.list', 'file.search', 'file.semantic_search'}),
    ('list.mk',    'mk', 'Прикажи ги датотеките во папката Downloads',
     {'file.list', 'file.search', 'file.semantic_search'}),
    ('multi.en',   'en', 'Check disk usage and report which filesystem has the highest percentage used.',
     {'system.storage', 'system.disk', 'system.status'}),
    ('multi.mk',   'mk', 'Провери го статусот на системот и сликај го екранот.',
     {'system.status', 'system.storage', 'system.disk', 'screen.capture', 'screen.screenshot'}),
]


def blank_task(goal, directory, limit):
    """`data` as aries/workspace/agent.py builds it on the first planner call.

    Kept structurally identical on purpose: `context()` reads the contract, the
    steps, the environment and the bounded historical context, and a planner
    measured against a shape production never produces measures nothing.
    """
    from aries.workspace import agent_planner, contracts
    from aries.workspace.registry import now
    historical = {'reviews': [], 'preferences': [], 'working_context': {}}
    return {'steps': [], 'evidence': [], 'schema_version': 2,
            # Local only, and no cloud fallback: a cloud answer scored here would
            # be a lie about the local planner.
            'routing': {'execution_level': 'local', 'no_fallback': True,
                        'reason': 'local planner quality measurement'},
            'agent': {'engine': 'm14', 'request': goal, 'finished': False, 'max_steps': limit,
                      'contract': contracts.compile_goal(goal, directory), 'decisions': [],
                      'context': agent_planner.bounded(historical, max_chars=2500),
                      'environment': {'home': str(Path.home()), 'demo_directory': directory,
                                      'now': now()},
                      'metrics': {}}}


# A first step is not the whole job. The second planner call carries `history` back
# into the prompt — bounded(…, max_chars=12000) — which is exactly the budget that
# broke the first call, so continuation has to be measured, not assumed. Each case
# supplies the verified step it starts from.
DEMO = str(Path.home() / 'aries-demo' / 'notes.txt')
CONTINUATIONS = [
    ('cont.read.finish', 'en', 'Read ' + DEMO, 'finish', set(),
     'file.read', {'path': DEMO},
     {'met': True, 'type': 'file_state',
      'data': {'path': DEMO, 'size': 12, 'sha256': 'a' * 64, 'text': 'measurement'}}),
    ('cont.disk.finish', 'en', 'How much disk space is free?', 'finish', set(),
     'system.storage', {},
     {'met': True, 'type': 'storage_probe',
      'data': {'probe': 'statvfs', 'highest': {'subject': '/', 'metric': 'disk.used_pct',
               'value': 61.4, 'unit': '%', 'detail': {'free_gib': 128.5}}}}),
    ('cont.multi.next', 'mk', 'Провери го статусот на системот и сликај го екранот.', 'execute',
     {'screen.capture', 'screen.screenshot', 'screen.read'},
     'system.status', {},
     {'met': True, 'type': 'system_probe',
      'data': {'probes': [{'metric': 'cpu.used_pct', 'value': 7.1, 'ok': True}]}}),
    ('cont.music.next', 'en', 'Open https://www.python.org and report the page title.', 'execute',
     {'browser.read', 'browser.observe'},
     'browser.open', {'url': 'https://www.python.org'},
     {'met': True, 'type': 'browser_state',
      'data': {'session': 'sess-7f3a', 'url': 'https://www.python.org/', 'title': 'Welcome to Python.org'}}),
]
# The same goal after seven earlier steps, so `history` is at its 12,000-character
# bound. If the prompt only fits an empty task, the planner is good for one step.
LONG = ('cont.long.next', 'en', 'Open https://www.python.org and report the page title.', 'execute',
        {'browser.read', 'browser.observe'},
        'browser.open', {'url': 'https://www.python.org'},
        {'met': True, 'type': 'browser_state',
         'data': {'session': 'sess-7f3a', 'url': 'https://www.python.org/',
                  'title': 'Welcome to Python.org'}}, 7)


def with_verified_step(data, capability, args, verification, pad=0):
    """One verified step in history, shaped exactly as agent.run() leaves it.

    `pad` prepends that many failed filler steps. `context()` bounds history at 12,000
    characters, so a real multi-step task can put back most of what the compact
    catalogue saved — and overflowing the window is the whole bug. A padded case is the
    only way to find out whether it still fits when the task has actually been running.
    """
    from aries.workspace import agent_planner
    from aries.workspace.registry import now
    evidence_id = 'e' + '1' * 31

    def step(index, cap, arguments, status, refs, observation, verify=None):
        return {'step_id': f's{index}', 'task_id': 't1', 'step_index': index,
                'kind': 'capability', 'capability': cap, 'args': arguments,
                'execution_status': status,
                'verification_status': 'verified' if verify else 'verification_failed',
                'state': 'verified' if verify else 'failed',
                'execution_result': observation, 'verification': verify,
                'observation': agent_planner.bounded(observation), 'error': None if verify else
                {'error_type': 'VerificationFailed', 'message': 'not confirmed', 'retryable': False},
                'evidence_refs': refs}

    filler = []
    for i in range(pad):
        seen = {'path': str(Path.home() / f'dir-{i}'), 'count': 3, 'observed_at': now(), 'entries':
                [{'name': f'file-{i}-{j}.txt', 'directory': False,
                  'path': str(Path.home() / f'dir-{i}' / f'file-{i}-{j}.txt')} for j in range(3)]}
        filler.append(step(i, 'file.list', {'path': seen['path']}, 'observed', [f'e{i}'], seen,
                           {'met': True, 'type': 'directory_state', 'data': seen}))
    last = step(pad, capability, args, 'observed', [evidence_id], verification['data'], verification)
    # agent.py hands the planner the VERIFIED observation, not the executor's claim.
    last['observation'] = agent_planner.bounded(
        {'verification': verification['data'], 'evidence_id': evidence_id}, max_chars=8000)
    data['evidence'] = [{'evidence_id': evidence_id, 'type': verification['type'],
                         'source': capability, 'timestamp': now(), 'step_id': f's{pad}',
                         'verified': True, 'data': verification['data']}]
    data['steps'] = filler + [last]
    return data, evidence_id


def score_continuation(raw, want_action, expected, evidence_id):
    """A continuation is right when it takes the RIGHT NEXT action, not merely a legal one."""
    row = {'returned': bool(raw), 'json': False, 'capability': False, 'args': False,
           'plausible': False, 'parses': False, 'chose': None, 'action': None,
           'arg_keys': [], 'unknown_args': [], 'detail': ''}
    if not raw:
        return row
    from aries.workspace import agent_planner
    try:
        decision = json.loads(raw)
    except ValueError as exc:
        row['detail'] = 'json: ' + str(exc)[:120]
        return row
    row.update(json=True, action=decision.get('action'), chose=decision.get('capability'))
    row['arg_keys'] = sorted(decision.get('arguments') or {})
    try:
        parsed = agent_planner.parse(raw)
        row.update(parses=True, args=True, capability=True)
    except Exception as exc:
        row['detail'] = 'parse: ' + str(exc).splitlines()[0][:160]
        return row
    if want_action == 'finish':
        # Finishing means naming the evidence that already exists, and nothing else.
        row['plausible'] = (parsed.action == 'finish' and list(parsed.evidence_refs) == [evidence_id]
                            and not parsed.capability)
        if not row['plausible']:
            row['detail'] = f'wanted finish/[{evidence_id[:6]}…], got {parsed.action}/{parsed.evidence_refs}'
    else:
        row['plausible'] = parsed.action == 'execute' and parsed.capability in expected
        if not row['plausible']:
            row['detail'] = f'wanted execute/{sorted(expected)}, got {parsed.action}/{parsed.capability}'
    row['usable'] = row['parses'] and row['plausible']
    return row


def score(raw, expected):
    """One attempt, gate by gate. No repair, no substring extraction — production
    does not repair either, so a measurement that did would overstate the model."""
    from aries.workspace import agent_planner
    from aries.workspace.registry import registry
    names = {c['name'] for c in registry.describe_allowed()}
    row = {'returned': bool(raw), 'json': False, 'capability': False, 'args': False,
           'plausible': False, 'parses': False, 'chose': None, 'action': None,
           'arg_keys': [], 'unknown_args': [], 'detail': ''}
    if not raw:
        return row
    try:
        decision = json.loads(raw)
    except ValueError as exc:
        row['detail'] = 'json: ' + str(exc)[:120]
        return row
    if not isinstance(decision, dict):
        row['detail'] = 'json: not an object'
        return row
    row['json'] = True
    row['action'] = decision.get('action')
    row['chose'] = decision.get('capability')
    arguments = decision.get('arguments') or {}
    row['arg_keys'] = sorted(arguments) if isinstance(arguments, dict) else ['<not an object>']
    if row['chose'] in names:
        row['capability'] = True
        try:
            registry.validate(row['chose'], arguments)
            row['args'] = True
        except Exception as exc:
            row['detail'] = 'args: ' + str(exc).splitlines()[0][:160]
        allowed = set(registry.get(row['chose']).input_model.model_json_schema()
                      .get('properties', {}))
        row['unknown_args'] = sorted(set(row['arg_keys']) - allowed)
        row['plausible'] = row['chose'] in expected
    else:
        row['detail'] = 'capability: ' + repr(row['chose'])[:80]
    try:
        agent_planner.parse(raw)
        row['parses'] = True
    except Exception as exc:
        if not row['detail']:
            row['detail'] = 'parse: ' + str(exc).splitlines()[0][:160]
    row['usable'] = row['parses'] and row['plausible']
    return row


async def attempt(goal, expected, directory, limit, *, prior=None, want_action=None):
    from aries.workspace import agent_planner
    from agentic_core.database.base import async_session
    data = blank_task(goal, directory, limit)
    evidence_id = None
    if prior:
        data, evidence_id = with_verified_step(data, *prior)
    # What the model is actually shown. Recorded on every attempt because the whole
    # quality problem was a prompt that did not fit the context window.
    payload_chars = len(json.dumps(agent_planner.context(goal, data, limit), ensure_ascii=False))
    started = time.monotonic()
    raw, usage, failure = '', {}, None
    try:
        async with async_session() as db:
            raw, usage = await agent_planner.plan(db, goal, data, limit)
    except Exception as exc:
        failure = f'{type(exc).__name__}: {str(exc)[:200]}'
    row = (score_continuation(raw, want_action, expected, evidence_id) if prior
           else score(raw, expected))
    row.update(payload_chars=payload_chars, seconds=round(time.monotonic() - started, 3),
               supported=data['agent']['contract']['supported'],
               failure=failure, raw=raw[:1200],
               input_tokens=(usage.get('measured') or {}).get('input_tokens'),
               output_tokens=(usage.get('measured') or {}).get('output_tokens'))
    return row


GATES = ('returned', 'json', 'capability', 'args', 'plausible', 'parses', 'usable')


def table(rows, total_per_goal):
    order = list(dict.fromkeys(r['goal'] for r in rows))
    lines = [f"{'goal':17s} {'lang':4s} {'ret':>3s} {'json':>4s} {'cap':>3s} {'args':>4s} "
             f"{'plaus':>5s} {'parse':>5s} {'USABLE':>6s} {'chars':>6s} {'s':>5s}  chose"]
    for key in order:
        mine = [r for r in rows if r['goal'] == key]
        def n(gate):
            return sum(1 for r in mine if r.get(gate))
        chosen = sorted({str(r['chose'] if r['action'] != 'finish' else 'finish') for r in mine})
        lines.append(f"{key:17s} {mine[0]['lang']:4s} {n('returned'):3d} {n('json'):4d} "
                     f"{n('capability'):3d} {n('args'):4d} {n('plausible'):5d} {n('parses'):5d} "
                     f"{n('usable'):6d} {mine[0]['payload_chars']:6d} "
                     f"{statistics.median(r['seconds'] for r in mine):5.1f}  "
                     f"{', '.join(chosen)[:52]}")
    lines.append('-' * len(lines[0]))
    totals = {g: sum(1 for r in rows if r.get(g)) for g in GATES}
    lines.append(f"{'TOTAL':17s} {'':4s} " + ' '.join(
        f'{totals[g]:>{w}d}' for g, w in zip(GATES, (3, 4, 3, 4, 5, 5, 6))) +
        f"   of {len(rows)} attempts ({len(order)} cases x {total_per_goal})")
    return '\n'.join(lines)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', required=True, help='what code is being measured')
    ap.add_argument('--repeats', type=int, default=3)
    ap.add_argument('--only', default='', help='comma-separated goal keys')
    args = ap.parse_args()
    if not 1 <= args.repeats <= 10:
        ap.error('repeats must be 1..10')

    from tests._bootstrap import reset_db
    await reset_db()
    from aries.settings import SettingsService
    from agentic_core.database.base import async_session
    async with async_session() as db:
        settings = SettingsService(db)
        limit = await settings.get('workspace.agent_max_steps')
        directory = str(Path(await settings.get('workspace.agent_demo_directory')).expanduser())
        config = {k: await settings.get('intelligence.' + k) for k in
                  ('location', 'local_backend', 'local_model', 'gateway_enabled', 'gateway_url')}
        config.update(await settings.get_many(
            ['ai.temperature', 'ai.top_p', 'ai.context_tokens', 'ai.max_output_tokens']))

    wanted = {k.strip() for k in args.only.split(',') if k.strip()}
    plan_cases = [(k, l, t, e, None, None) for k, l, t, e in GOALS]
    cont_cases = [(k, l, t, e, (cap, cargs, ver, 0), want)
                  for k, l, t, want, e, cap, cargs, ver in CONTINUATIONS]
    k, l, t, want, e, cap, cargs, ver, pad = LONG
    cont_cases.append((k, l, t, e, (cap, cargs, ver, pad), want))
    cases = [c for c in plan_cases + cont_cases if not wanted or c[0] in wanted]
    print(json.dumps(config), flush=True)
    rows = []
    for repeat in range(args.repeats):
        for key, lang, text, expected, prior, want in cases:
            row = await attempt(text, expected, directory, limit,
                                prior=prior, want_action=want)
            row.update(goal=key, lang=lang, text=text, repeat=repeat,
                       expected=sorted(expected) or want)
            rows.append(row)
            verdict = 'USABLE ' if row.get('usable') else 'unusable'
            print(f"{verdict} {key:11s} r{repeat} {row['seconds']:6.1f}s "
                  f"act={str(row['action'])[:12]:12s} cap={str(row['chose'])[:24]:24s} "
                  f"args={','.join(row['arg_keys'])[:50]:50s} {row['failure'] or row['detail']}",
                  flush=True)

    out = ROOT / 'experiments' / 'planner' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + args.label)
    out.mkdir(parents=True, exist_ok=True)
    report = table(rows, args.repeats)
    (out / 'attempts.json').write_text(json.dumps(
        {'label': args.label, 'repeats': args.repeats, 'config': config,
         'rows': rows}, indent=2, ensure_ascii=False) + '\n')
    (out / 'table.txt').write_text(report + '\n')
    print('\n' + report)
    print('\n' + str(out))


if __name__ == '__main__':
    asyncio.run(main())
