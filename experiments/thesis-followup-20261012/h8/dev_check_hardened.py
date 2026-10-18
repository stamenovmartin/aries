#!/usr/bin/env python3
"""H8 development check of the hardened verifiers on HONEST executions only (no mutant is run).

For each hardened capability: a fresh fake world from run_mutants.py's own case setup, with seed 7
(the manifest's clean replays use other seeds), the honest executor, then the hardened verifier.
It finds bugs in the hardened code (exceptions, checks that fail on correct work) before the
measured run. It never applies a mutation operator. Output: dev_check_hardened.json.

    ARIES_VERIFY_HARDENED=1 ARIES_VERIFY_HARDENED_EXTRA=1 .venv/bin/python experiments/thesis-followup-20261012/h8/dev_check_hardened.py
"""
import asyncio
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_mutants as M                                            # noqa: E402

SEED = 7


async def go(cases):
    from agentic_core.database.base import async_session
    from aries.workspace.registry import registry
    from aries.workspace.hardened_verifiers import HARDENED, EXTRA
    out = {}
    for name in HARDENED + EXTRA:
        cap, case = registry._items[name], cases[name]
        world = M.World()
        M.W['cur'] = world
        try:
            async with async_session() as db:
                ctx = await M.ctx_for(db)
                args = await M.special_setup(case, world, random.Random(SEED), db)
                if name == 'browser.forward':
                    world.state['sessions']['s1'].update(history=['https://site2.example/', 'https://site3.example/'],
                                                         index=0, url='https://site2.example/')
                    args = {'session': 's1'}
                args = registry.validate(name, args)
                result = await cap.executor(args, ctx)
                v = await cap.verifier(args, result, ctx)
            out[name] = {'met': v.get('met') is True and v.get('status') != 'UNVERIFIED', 'status': v.get('status'),
                         'hardened': v.get('hardened'), 'failed_checks': sorted(k for k, ok in (v.get('checks') or {}).items() if not ok),
                         'error': (v.get('data') or {}).get('error') if v.get('status') == 'UNVERIFIED' else None}
        except Exception as exc:                                    # noqa: BLE001
            out[name] = {'met': False, 'harness_error': f'{type(exc).__name__}: {str(exc)[:200]}'}
        finally:
            M.W['cur'] = None
            world.discard()
    return out


def main():
    import os
    if os.environ.get('ARIES_VERIFY_HARDENED') != '1':
        raise SystemExit('set ARIES_VERIFY_HARDENED=1 (and ARIES_VERIFY_HARDENED_EXTRA=1)')
    M.install_fakes()
    from agentic_core.config.settings import settings as es
    from aries.workspace.capabilities import TOOL_NAMES
    es.dry_run = False
    es.live_tools = ','.join(TOOL_NAMES)
    cases = M.build_cases()
    asyncio.run(M.prepare_db())
    res = asyncio.run(go(cases))
    target = HERE / sys.argv[1] if len(sys.argv) > 1 else HERE / 'dev_check_hardened.json'
    target.write_text(json.dumps({'when': M.now(), 'seed': SEED, 'results': res}, indent=1) + '\n')
    bad = {k: v for k, v in res.items() if not v['met']}
    print(f'{len(res) - len(bad)}/{len(res)} honest executions verified by the hardened verifier')
    for k, v in bad.items():
        print('  NOT MET', k, v)


if __name__ == '__main__':
    main()
