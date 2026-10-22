"""Run setup + mutation (never the verifier) for named items; report only whether it completed.

Used once, for the Amendment 1 pre-check (no verdict is computed). Committed after the H8 runs; the only
change from the copy that ran is the sys.path line, which was an absolute path to this folder.

    .venv/bin/python experiments/thesis-followup-20261012/h8/mutate_only.py <item id> ...
"""
import asyncio, json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_mutants as M
M.install_fakes()
from agentic_core.config.settings import settings as es
from aries.workspace.capabilities import TOOL_NAMES
es.dry_run = False; es.live_tools = ','.join(TOOL_NAMES)
cases = M.build_cases()
asyncio.run(M.prepare_db())
ids = set(sys.argv[1:])
man = json.loads((M.HERE / 'mutants.json').read_text())
items = [i for i in man['clean_replays'] + man['mutants'] if i['id'] in ids]
async def go():
    from agentic_core.database.base import async_session
    from aries.workspace.registry import registry
    for item in items:
        cap = registry._items[item['capability']]; case = cases[item['capability']]
        rng = random.Random(item.get('variant_seed', 0) if 'operator' in item else hash(item['id']) & 0xffffffff)
        world = M.World(); M.W['cur'] = world
        try:
            async with async_session() as db:
                ctx = await M.ctx_for(db)
                args = registry.validate(item['capability'], await M.special_setup(case, world, rng, db))
                if 'operator' in item:
                    await M.mutate(item['operator'], case, cap, world, args, ctx, rng)
                else:
                    await M.honest(cap, args, ctx)
            print('OK  ', item['id'])
        except Exception as e:
            print('FAIL', item['id'], type(e).__name__, str(e)[:120])
        finally:
            M.W['cur'] = None; world.discard()
asyncio.run(go())
