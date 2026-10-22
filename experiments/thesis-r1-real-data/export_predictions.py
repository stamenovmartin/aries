#!/usr/bin/env python3
"""Write predictions.json: every system's per-item prediction for R1, with no request text and no model output.

raw/*.jsonl stay local (model reasons and planner arguments echo the dataset requests). predictions.json carries
item ids, the frozen gold labels, each system's predicted label (NL2Bash) or act/abstain (CLINC150), and the
SHA-256 of every raw file it was derived from, so thesis-tables/check.py can recompute summary.json without them.
The prediction rules are imported from analyze_r1.py unchanged.
"""
import hashlib
import json

from analyze_r1 import (HERE, OOS, RAW, aries_predictions, best_tau, canonical, raw, router_acts,
                        threshold_predict, zeroshot_predictions)


def main():
    dest = HERE / 'predictions.json'
    if dest.exists():
        raise SystemExit('REFUSED: predictions.json exists')
    gold = json.loads((HERE / 'labels' / 'nl2bash-final.json').read_text())['labels']
    man = json.loads((HERE / 'nl2bash-sample-manifest.json').read_text())
    test = [s['id'] for s in man['sample'] if s['split'] == 'test']
    dev = [s['id'] for s in man['sample'] if s['split'] == 'dev']
    nb = {}
    for model, tag in (('qwen2.5:7b', 'qwen2_5_7b'), ('llama3.1:8b', 'llama3_1_8b')):
        _, r, _ = raw(f'router-{tag}-A1-nl2bash-test')
        _, p, _ = raw(f'planner-{tag}-nl2bash-test')
        name = 'aries' if model == 'qwen2.5:7b' else 'aries_llama_secondary'
        nb[name] = aries_predictions(r, p)
        if name == 'aries':
            router_q, planner_q = r, p
    _, zq, _ = raw('zeroshot-nl2bash-test')
    nb['zeroshot_qwen'] = zeroshot_predictions(zq)
    for name in ('embedding', 'bm25'):
        _, rows, _ = raw(f'{name}-nl2bash')
        tau, _ = best_tau({i: rows[i] for i in dev}, lambda p: sum(p[i] == gold[i] for i in dev))
        nb[name] = threshold_predict({i: rows[i] for i in test}, tau)
    items = [{'id': i, 'gold': gold[i], 'router_acts': router_acts(router_q[i]),
              'planner_valid': None if i not in planner_q else not planner_q[i].get('error'),
              **{k: v[i] for k, v in nb.items()}} for i in test]

    cm = json.loads((HERE / 'clinc-sample-manifest.json').read_text())
    cids = [r['id'] for r in cm['sample']]
    acts = {}
    for name, f in (('router_A1', 'router-qwen2_5_7b-A1-clinc'), ('router_A0', 'router-qwen2_5_7b-A0-clinc'),
                    ('router_A1_llama_secondary', 'router-llama3_1_8b-A1-clinc')):
        _, r, _ = raw(f)
        acts[name] = {i: router_acts(r[i]) for i in cids}
    _, zc, _ = raw('zeroshot-clinc')
    acts['zeroshot_qwen'] = {i: bool(zc[i].get('label')) and canonical(zc[i]['label']) != OOS for i in cids}
    summary = json.loads((HERE / 'summary.json').read_text())
    tau = summary['clinc150']['embedding_threshold_from_val']['tau']
    _, ec, _ = raw('embedding-clinc')
    acts['embedding'] = {i: p != OOS for i, p in threshold_predict(ec, tau).items()}
    citems = [{'id': r['id'], 'group': r['group'], 'unsupported': r['gold_label'] == OOS,
               **{k: v[r['id']] for k, v in acts.items()}} for r in cm['sample']]
    out = {'note': 'per-item predictions derived from raw/*.jsonl by the analyze_r1.py rules; no request text',
           'raw_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(RAW.glob('*.jsonl'))},
           'nl2bash_test': items, 'clinc150': citems}
    dest.write_text(json.dumps(out, indent=0) + '\n')
    print(len(items), len(citems))


if __name__ == '__main__':
    main()
