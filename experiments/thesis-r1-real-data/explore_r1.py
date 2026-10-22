#!/usr/bin/env python3
"""R1 exploratory diagnostics, written AFTER summary.json was seen. Outside the R1 Holm family; no test here.

Writes exploratory.json:
- the majority-class reference (always OUT_OF_SCOPE / always abstain), which the preregistration did not list;
- NL2Bash label accuracy on the in-scope gold items only;
- planner calls whose output failed Decision validation (counted OUT_OF_SCOPE by the preregistered rule; the
  harness did not keep their raw output, so no capability can be recovered from them);
- CLINC150 act/abstain correctness per sample group (supported, unsupported intent, oos).
"""
import json
from collections import Counter

from analyze_r1 import (HERE, OOS, aries_predictions, best_tau, canonical, rate, raw, router_acts,
                        threshold_predict, zeroshot_predictions)


def main():
    dest = HERE / 'exploratory.json'
    if dest.exists():
        raise SystemExit('REFUSED: exploratory.json exists')
    out = {'label': 'exploratory, written after the confirmatory summary was seen; outside Holm', 'nl2bash': {},
           'clinc150': {}}
    gold = json.loads((HERE / 'labels' / 'nl2bash-final.json').read_text())['labels']
    man = json.loads((HERE / 'nl2bash-sample-manifest.json').read_text())
    test = [s['id'] for s in man['sample'] if s['split'] == 'test']
    dev = [s['id'] for s in man['sample'] if s['split'] == 'dev']
    _, rq, _ = raw('router-qwen2_5_7b-A1-nl2bash-test')
    _, pq, _ = raw('planner-qwen2_5_7b-nl2bash-test')
    _, zq, _ = raw('zeroshot-nl2bash-test')
    preds = {'aries': aries_predictions(rq, pq), 'zeroshot_qwen': zeroshot_predictions(zq),
             'always_oos': {i: OOS for i in test}}
    for name in ('embedding', 'bm25'):
        _, rows, _ = raw(f'{name}-nl2bash')
        tau, _ = best_tau({i: rows[i] for i in dev}, lambda p: sum(p[i] == gold[i] for i in dev))
        preds[name] = threshold_predict({i: rows[i] for i in test}, tau)
    inscope = [i for i in test if gold[i] != OOS]
    out['nl2bash']['in_scope_gold_n'] = len(inscope)
    for name, p in preds.items():
        out['nl2bash'][name] = {'top1_all': rate(sum(p[i] == gold[i] for i in test), len(test)),
                                'top1_in_scope_gold': rate(sum(p[i] == gold[i] for i in inscope), len(inscope))}
    errs = [i for i, r in pq.items() if r.get('error')]
    out['nl2bash']['planner_validation_errors'] = {
        'n': len(errs), 'of_planner_calls': len(pq),
        'gold_of_those': dict(Counter(gold[i] for i in errs).most_common()),
        'error_field': dict(Counter(r['error'].split('\n')[1].strip() for i, r in pq.items()
                                    if r.get('error') and '\n' in r['error']).most_common(8))}
    router_hold = [i for i in test if not router_acts(rq[i])]
    out['nl2bash']['router_abstained'] = {'n': len(router_hold),
                                          'gold_oos': sum(gold[i] == OOS for i in router_hold)}

    cm = json.loads((HERE / 'clinc-sample-manifest.json').read_text())
    cids = [r['id'] for r in cm['sample']]
    uns = {r['id']: r['gold_label'] == OOS for r in cm['sample']}
    group = {r['id']: r['group'] for r in cm['sample']}
    acts = {'always_abstain': {i: False for i in cids}}
    for arm in ('A1', 'A0'):
        _, r, _ = raw(f'router-qwen2_5_7b-{arm}-clinc')
        acts[f'router_{arm}'] = {i: router_acts(r[i]) for i in cids}
    _, zc, _ = raw('zeroshot-clinc')
    acts['zeroshot_qwen'] = {i: bool(zc[i].get('label')) and canonical(zc[i]['label']) != OOS for i in cids}
    for name, a in acts.items():
        ok = {i: a[i] != uns[i] for i in cids}
        out['clinc150'][name] = {'correct_all': rate(sum(ok.values()), len(cids)),
                                 **{g: rate(sum(ok[i] for i in cids if group[i] == g),
                                            sum(group[i] == g for i in cids)) for g in sorted(set(group.values()))}}
    dest.write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
