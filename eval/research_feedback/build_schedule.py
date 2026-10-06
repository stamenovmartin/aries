"""Generate a proposed balanced 600-episode schedule; never execute a model/tool."""
from pathlib import Path
import hashlib
import json
import random

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE = ROOT / "experiments/verification-feedback/fixture.jsonl"
SEED = 20261003


def main():
    cases = [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]
    if len(cases) != 15 or len({x['id'] for x in cases}) != 15:
        raise ValueError('The proposed design requires exactly 15 distinct case IDs; review amendments first')
    rng = random.Random(SEED)
    blocks = []
    for case in cases:
        orders = [('tool_only', 'structured')] * 10 + [('structured', 'tool_only')] * 10
        rng.shuffle(orders)
        for repetition, order in enumerate(orders, 1):
            blocks.append([{'goal_id': case['id'], 'fault_type': case['fault'],
                            'repetition': repetition, 'condition': condition,
                            'paired_block': f"{case['id']}-r{repetition:02d}",
                            'model_seed': None, 'status': 'planned'} for condition in order])
    rng.shuffle(blocks)
    episodes = [dict(episode, schedule_index=i + 1)
                for i, episode in enumerate(row for pair in blocks for row in pair)]
    assert len(episodes) == 600
    assert all(sum(x['condition'] == arm for x in episodes) == 300
               for arm in ('tool_only', 'structured'))
    result = {'status': 'DRAFT_NOT_EXECUTED', 'launch_ready': False,
              'blocking_requirements': 'STUDY_600.md admission checks; broader hooks/oracles not wired yet',
              'schedule_seed': SEED, 'schedule_seed_is_model_seed': False,
              'fixture': str(FIXTURE.relative_to(ROOT)),
              'fixture_sha256': hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
              'study_sha256': hashlib.sha256((HERE / 'STUDY_600.md').read_bytes()).hexdigest(),
              'cases': len(cases), 'fault_families': len({x['fault'] for x in cases}),
              'episodes': episodes}
    path = HERE / 'proposed_schedule.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(f'{path}: 600 planned, 0 executed; launch_ready=false')


if __name__ == '__main__':
    main()
