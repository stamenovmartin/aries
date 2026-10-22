#!/usr/bin/env python3
"""R1 NL2Bash sample (Samples section): dedupe NL lines, stratify by first utility, 600 drawn (seed 20261022),
split test 500 / dev 100 (seed 20261023). Texts go to ~/data-ext/r1 (local); the committed manifest holds line
numbers, strata and SHA-256s only."""
import json
import random
from collections import defaultdict
from common import DATA, HERE, LOCAL, check_data, sha, write_jsonl


def utility(cm):
    toks = cm.strip().split()
    while toks and toks[0] == 'sudo':
        toks = toks[1:]
    return toks[0] if toks else '<empty>'


def allocate(sizes, total):
    n = sum(sizes.values())
    quota = {k: total * v / n for k, v in sizes.items()}
    out = {k: int(q) for k, q in quota.items()}
    rest = total - sum(out.values())
    for k in sorted(quota, key=lambda k: (-(quota[k] - out[k]), k))[:rest]:
        out[k] += 1
    return out


def stratified(pool_by, total, rng):
    alloc = allocate({k: len(v) for k, v in pool_by.items()}, total)
    picked = []
    for k in sorted(pool_by):
        picked += rng.sample(pool_by[k], alloc[k])
    return picked


def main():
    check_data()
    nl = (DATA / 'nl2bash/all.nl').read_text().splitlines()
    cm = (DATA / 'nl2bash/all.cm').read_text().splitlines()
    assert len(nl) == len(cm)
    seen, rows = set(), []
    for i, (n, c) in enumerate(zip(nl, cm), 1):
        if n.strip() and n not in seen:
            seen.add(n)
            rows.append({'line': i, 'utility': utility(c)})
    by = defaultdict(list)
    for r in rows:
        by[r['utility']].append(r['line'])
    drawn = stratified(by, 600, random.Random(20261022))
    util = {r['line']: r['utility'] for r in rows}
    by2 = defaultdict(list)
    for line in drawn:
        by2[util[line]].append(line)
    dev = set(stratified(by2, 100, random.Random(20261023)))
    sample = [{'id': f'nb-{line:05d}', 'line': line, 'utility': util[line], 'split': 'dev' if line in dev else 'test'}
              for line in sorted(drawn)]
    LOCAL.mkdir(parents=True, exist_ok=True)
    texts = LOCAL / 'nl2bash_sample.jsonl'
    write_jsonl(texts, [{**s, 'text': nl[s['line'] - 1]} for s in sample])
    manifest = {'unique_nl_lines': len(rows), 'strata': len(by), 'drawn': len(sample),
                'test': sum(s['split'] == 'test' for s in sample), 'dev': len(dev),
                'seeds': {'draw': 20261022, 'split': 20261023}, 'data_sha256': {k: sha(DATA / k) for k in
                ('nl2bash/all.nl', 'nl2bash/all.cm')}, 'local_texts_sha256': sha(texts), 'sample': sample}
    (HERE / 'nl2bash-sample-manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'sample'}))


if __name__ == '__main__':
    main()
