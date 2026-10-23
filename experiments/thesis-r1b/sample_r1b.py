#!/usr/bin/env python3
"""R1b samples (docs/preregistration/R1b-improved-router-planner.md, Samples): new items, disjoint from R1.

NL2Bash: the unique NL lines of R1's pool minus R1's 600 (test and dev) and minus any line whose text equals
one of them; 500 drawn stratified by first utility with R1's allocation rule (seed 20261101).
CLINC150: from `test`, 200 utterances of supported intents and 200 of in-scope intents labelled OUT_OF_SCOPE
(R1's frozen intent labels), each spread evenly over intents, and 200 from `oos_test`, none of them in R1's
sample (seed 20261102). Texts go to ~/data-ext/r1b (local); the committed manifests hold ids, line numbers,
strata or intents and SHA-256s only."""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
HERE = Path(__file__).resolve().parent
R1 = HERE.parent / 'thesis-r1-real-data'
sys.path.insert(0, str(R1))
from common import DATA, OOS, canonical, check_data, jsonl, sha, write_jsonl  # noqa: E402
from sample import stratified, utility  # noqa: E402
from sample_clinc import even  # noqa: E402

LOCAL = DATA / 'r1b'


def nl2bash():
    nl = (DATA / 'nl2bash/all.nl').read_text().splitlines()
    cm = (DATA / 'nl2bash/all.cm').read_text().splitlines()
    old = json.loads((R1 / 'nl2bash-sample-manifest.json').read_text())['sample']
    old_lines = {s['line'] for s in old}
    old_texts = {nl[line - 1] for line in old_lines}
    seen, rows = set(), []
    for i, (n, c) in enumerate(zip(nl, cm), 1):
        if n.strip() and n not in seen:
            seen.add(n)
            if i not in old_lines and n not in old_texts:
                rows.append({'line': i, 'utility': utility(c)})
    by = defaultdict(list)
    for r in rows:
        by[r['utility']].append(r['line'])
    drawn = stratified(by, 500, random.Random(20261101))
    util = {r['line']: r['utility'] for r in rows}
    sample = [{'id': f'nb-{line:05d}', 'line': line, 'utility': util[line], 'split': 'r1b'} for line in sorted(drawn)]
    assert not {s['line'] for s in sample} & old_lines
    texts = LOCAL / 'nl2bash_sample.jsonl'
    write_jsonl(texts, [{**s, 'text': nl[s['line'] - 1]} for s in sample])
    manifest = {'pool_unique_lines_excluding_r1': len(rows), 'strata': len(by), 'drawn': len(sample),
                'excluded_r1_lines': len(old_lines), 'seed': 20261101,
                'data_sha256': {k: sha(DATA / k) for k in ('nl2bash/all.nl', 'nl2bash/all.cm')},
                'local_texts_sha256': sha(texts), 'sample': sample}
    (HERE / 'nl2bash-sample-manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'sample'}))


def clinc():
    final = json.loads((R1 / 'labels' / 'clinc-final.json').read_text())
    labels = {k: canonical(v) for k, v in final['labels'].items()}
    data = json.loads((DATA / 'clinc150/data_full.json').read_text())
    old = json.loads((R1 / 'clinc-sample-manifest.json').read_text())['sample']
    used = {(r['split'], r['index']) for r in old}
    sup, uns = defaultdict(list), defaultdict(list)
    for i, (text, intent) in enumerate(data['test']):
        if ('test', i) not in used:
            (uns if labels[intent] == OOS else sup)[intent].append(i)
    rng = random.Random(20261102)
    s = even(sup, 200, rng)
    u = even(uns, 200, rng)
    o = rng.sample([i for i in range(len(data['oos_test'])) if ('oos_test', i) not in used], 200)
    rows = ([{'id': f'ct-{i:04d}', 'split': 'test', 'index': i, 'intent': data['test'][i][1], 'group': 'supported'}
             for i in s] + [{'id': f'ct-{i:04d}', 'split': 'test', 'index': i, 'intent': data['test'][i][1],
                             'group': 'unsupported-intent'} for i in u] +
            [{'id': f'co-{i:04d}', 'split': 'oos_test', 'index': i, 'intent': 'oos', 'group': 'oos'} for i in o])
    for r in rows:
        r['gold_label'] = OOS if r['group'] != 'supported' else labels[r['intent']]
    assert not {(r['split'], r['index']) for r in rows} & used
    texts = LOCAL / 'clinc_sample.jsonl'
    write_jsonl(texts, [{**r, 'text': data[r['split']][r['index']][0]} for r in rows])
    manifest = {'seed': 20261102, 'excluded_r1_items': len(used),
                'n': {g: sum(r['group'] == g for r in rows) for g in ('supported', 'unsupported-intent', 'oos')},
                'labels_sha256': sha(R1 / 'labels' / 'clinc-final.json'), 'local_texts_sha256': sha(texts),
                'sample': rows}
    (HERE / 'clinc-sample-manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'sample'}))


if __name__ == '__main__':
    check_data()
    LOCAL.mkdir(parents=True, exist_ok=True)
    for f in ('nl2bash_sample.jsonl', 'clinc_sample.jsonl'):
        if (LOCAL / f).exists():
            raise SystemExit(f'REFUSED: {LOCAL / f} exists')
    nl2bash()
    clinc()
