#!/usr/bin/env python3
"""R1 CLINC150 sample, drawn after the intent labels are frozen (Samples section): from `test`, 200 utterances
from SUPPORTED intents, 200 from in-scope intents labelled OUT_OF_SCOPE, 200 from `oos_test`, each spread evenly
over intents (seed 20261024). Texts go to ~/data-ext/r1 (local); the committed manifest has ids, intents and the
split index only."""
import json
import random
from collections import defaultdict
from common import DATA, HERE, LOCAL, OOS, canonical, check_data, sha, write_jsonl


def even(pool_by, total, rng):
    """Round-robin over intents (sorted), each intent's utterances in a seeded random order."""
    queues = {k: rng.sample(v, len(v)) for k, v in sorted(pool_by.items())}
    picked = []
    while len(picked) < total and any(queues.values()):
        for k in sorted(queues):
            if queues[k] and len(picked) < total:
                picked.append(queues[k].pop())
    return picked


def main():
    check_data()
    final = json.loads((HERE / 'labels' / 'clinc-final.json').read_text())
    labels = {k: canonical(v) for k, v in final['labels'].items()}
    data = json.loads((DATA / 'clinc150/data_full.json').read_text())
    sup, uns = defaultdict(list), defaultdict(list)
    for i, (text, intent) in enumerate(data['test']):
        (uns if labels[intent] == OOS else sup)[intent].append(i)
    rng = random.Random(20261024)
    s = even(sup, 200, rng)
    u = even(uns, 200, rng)
    o = rng.sample(range(len(data['oos_test'])), 200)
    rows = ([{'id': f'ct-{i:04d}', 'split': 'test', 'index': i, 'intent': data['test'][i][1], 'group': 'supported'}
             for i in s] + [{'id': f'ct-{i:04d}', 'split': 'test', 'index': i, 'intent': data['test'][i][1],
                             'group': 'unsupported-intent'} for i in u] +
            [{'id': f'co-{i:04d}', 'split': 'oos_test', 'index': i, 'intent': 'oos', 'group': 'oos'} for i in o])
    for r in rows:
        r['gold_label'] = OOS if r['group'] != 'supported' else labels[r['intent']]
    texts = LOCAL / 'clinc_sample.jsonl'
    write_jsonl(texts, [{**r, 'text': data[r['split']][r['index']][0]} for r in rows])
    manifest = {'seed': 20261024, 'pools': {'supported_intents': len(sup), 'supported_utterances': sum(map(len, sup.values())),
                'unsupported_intents': len(uns)}, 'n': {g: sum(r['group'] == g for r in rows) for g in
                ('supported', 'unsupported-intent', 'oos')}, 'labels_sha256': sha(HERE / 'labels' / 'clinc-final.json'),
                'local_texts_sha256': sha(texts), 'sample': rows}
    (HERE / 'clinc-sample-manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'sample'}))


if __name__ == '__main__':
    main()
