#!/usr/bin/env python3
"""H8 diagnostic (descriptive, not a measurement): HOW each mutant newly killed by the hardening was killed.

The run records store the verdict only. This re-runs the given mutants exactly as run_mutants.py does
(same case setup, same variant seed, same mutation), calls the hardened verifier, and stores which
checks failed or whether the verdict was UNVERIFIED (an exception in the verifier's own reads, which
could hide a bug in the hardened code). It also checks that each re-run verdict equals the recorded
one. The recorded runs are not changed.

    .venv/bin/python experiments/thesis-followup-20261012/h8/diagnose_kills.py <hardened-run> <baseline-run> <out.json>
"""
import asyncio
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ['ARIES_VERIFY_HARDENED'] = '1'
import run_mutants as M                                            # noqa: E402


async def one(item, cases):
    from agentic_core.database.base import async_session
    from aries.workspace.registry import registry
    cap, case = registry._items[item['capability']], cases[item['capability']]
    rng = random.Random(item['variant_seed'])
    world = M.World()
    M.W['cur'] = world
    try:
        async with async_session() as db:
            ctx = await M.ctx_for(db)
            args = await M.special_setup(case, world, rng, db)
            if item['capability'] == 'browser.forward':
                world.state['sessions']['s1'].update(history=['https://site2.example/', 'https://site3.example/'], index=0,
                                                     url='https://site2.example/')
                args = {'session': 's1'}
            args = registry.validate(item['capability'], args)
            result, _, _ = await M.mutate(item['operator'], case, cap, world, args, ctx, rng)
            v = await cap.verifier(args, result, ctx)
        met = v.get('met') is True and v.get('status') != 'UNVERIFIED'
        return {'killed': not met, 'status': v.get('status'), 'hardened': v.get('hardened'),
                'failed_checks': sorted(k for k, ok in (v.get('checks') or {}).items() if not ok),
                'unverified_error': (v.get('data') or {}).get('error') if v.get('status') == 'UNVERIFIED' else None}
    finally:
        M.W['cur'] = None
        world.discard()


def main(hard, base, out):
    L = lambda p: {json.loads(l)['id']: json.loads(l) for l in (Path(p) / 'records.jsonl').read_text().splitlines()}
    h, b = L(hard), L(base)
    ids = sorted(i for i in h if h[i]['operator'] != 'clean' and h[i]['killed'] and not b[i]['killed'])
    man = {m['id']: m for m in json.loads((HERE / 'mutants.json').read_text())['mutants']}
    M.install_fakes()
    from agentic_core.config.settings import settings as es
    from aries.workspace.capabilities import TOOL_NAMES
    es.dry_run = False
    es.live_tools = ','.join(TOOL_NAMES)
    cases = M.build_cases()
    asyncio.run(M.prepare_db())

    async def go():
        return {i: await one(man[i], cases) for i in ids}
    res = asyncio.run(go())
    summary = {'newly_killed': len(ids), 'reproduced': sum(r['killed'] for r in res.values()),
               'by_failed_check': sum(1 for r in res.values() if r['killed'] and r['failed_checks']),
               'by_unverified': sorted(i for i, r in res.items() if r['status'] == 'UNVERIFIED')}
    Path(out).write_text(json.dumps({'hardened_run': hard, 'baseline_run': base, 'summary': summary,
                                     'mutants': res}, indent=1) + '\n')
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:4])
