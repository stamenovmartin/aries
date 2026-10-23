#!/usr/bin/env python3
"""R1b analysis, as registered (docs/preregistration/R1b-improved-router-planner.md). Written before any R1b run.

    analyze_r1b.py   ->  summary.json (refuses to overwrite)

Reads labels/nl2bash-final.json (R1b NL2Bash labels), R1's frozen CLINC intent labels, the R1b sample manifests
and raw/*.jsonl; a raw file without its footer is refused. The metrics, the prediction rules, the McNemar test,
Holm's correction and the intervals are R1's own functions (thesis-r1-real-data/analyze_r1.py). The embedding
and BM25 thresholds are R1's, read from R1's summary.json (set on R1's dev and val; nothing is set on R1b data).
Errors and fallbacks count as wrong in every fixed denominator."""
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
R1 = HERE.parent / 'thesis-r1-real-data'
sys.path.insert(0, str(R1))
import analyze_r1 as A  # noqa: E402
from common import CAPABILITIES, OOS, canonical  # noqa: E402
from run_r1 import router_acts  # noqa: E402

A.RAW = HERE / 'raw'
CONFIGS = json.loads((HERE / 'configs.json').read_text())
TREATMENT = CONFIGS['treatment']
EXPLORATORY = [c for c in CONFIGS['exploratory_on_r1b'] if c != TREATMENT]


def current_predictions(rows):
    """ARIES with the current source: OUT_OF_SCOPE unless the router acts and the planner executes a capability."""
    out = {}
    for i, r in rows.items():
        d = r.get('decision') or {}
        cap = d.get('capability')
        out[i] = canonical(cap) if r.get('acts') and d.get('action') == 'execute' and cap in CAPABILITIES else OOS
    return out


def stage_counts(rows, gold):
    c = Counter()
    for i, r in rows.items():
        route = r.get('route') or {}
        c['router_error'] += 'error' in route
        c['router_acts'] += bool(r.get('acts'))
        c['gate_out_of_scope'] += route.get('gate_capability') == OOS
        c['planner_called'] += 'planner_seconds' in r
        c['planner_invalid'] += bool(r.get('planner_error'))
        c['planner_fail'] += (r.get('decision') or {}).get('action') == 'fail'
        if gold is not None and gold[i] != OOS:
            c['in_scope_router_abstained'] += not r.get('acts')
    seconds = [r.get('router_seconds', 0) + r.get('planner_seconds', 0) for r in rows.values()]
    return {**dict(c), 'n': len(rows), 'seconds_per_request_mean': round(statistics.mean(seconds), 3),
            'seconds_per_request_median': round(statistics.median(seconds), 3)}


def main():
    dest = HERE / 'summary.json'
    if dest.exists():
        raise SystemExit('REFUSED: summary.json exists')
    r1 = json.loads((R1 / 'summary.json').read_text())
    taus = {'embedding': r1['nl2bash']['thresholds_from_dev']['embedding']['tau'],
            'bm25': r1['nl2bash']['thresholds_from_dev']['bm25']['tau'],
            'clinc_embedding': r1['clinc150']['embedding_threshold_from_val']['tau']}
    out = {'label': 'R1b family (Holm over the four registered tests); rows marked exploratory are outside Holm',
           'treatment_config': {TREATMENT: CONFIGS['configs'][TREATMENT]}, 'thresholds_from_r1': taus,
           'nl2bash': {}, 'clinc150': {}, 'tests': {}, 'exploratory': {'nl2bash': {}, 'clinc150': {}}}

    # NL2Bash (R1b sample, 500)
    gold = json.loads((HERE / 'labels' / 'nl2bash-final.json').read_text())['labels']
    ids = [s['id'] for s in json.loads((HERE / 'nl2bash-sample-manifest.json').read_text())['sample']]
    _, treat, _ = A.raw(f'aries-{TREATMENT}-qwen2_5_7b-nl2bash-r1b')
    _, fr, _ = A.raw('router-qwen2_5_7b-A1-nl2bash-r1b')
    _, fp, _ = A.raw('planner-qwen2_5_7b-nl2bash-r1b')
    _, zq, _ = A.raw('zeroshot-nl2bash-r1b')
    _, emb, _ = A.raw('embedding-nl2bash-r1b')
    _, bm, _ = A.raw('bm25-nl2bash-r1b')
    preds = {'aries_treatment': current_predictions(treat), 'aries_frozen': A.aries_predictions(fr, fp),
             'zeroshot_qwen': A.zeroshot_predictions(zq),
             'embedding': A.threshold_predict(emb, taus['embedding']), 'bm25': A.threshold_predict(bm, taus['bm25']),
             'always_out_of_scope': {i: OOS for i in ids}}
    oks = {}
    for name, p in preds.items():
        out['nl2bash'][name], oks[name] = A.label_metrics(ids, gold, p)
    in_scope = [i for i in ids if gold[i] != OOS]
    out['nl2bash']['in_scope_top1'] = {name: A.rate(sum(p[i] == gold[i] for i in in_scope), len(in_scope))
                                       for name, p in preds.items()}
    out['nl2bash']['stages_treatment'] = stage_counts(treat, gold)
    out['nl2bash']['gold_label_counts'] = dict(Counter(gold[i] for i in ids).most_common())
    for t, other in (('H-R1b-a', 'aries_frozen'), ('H-R1b-b', 'zeroshot_qwen')):
        out['tests'][t] = {'dataset': 'nl2bash-r1b', 'first': 'aries_treatment', 'second': other,
                           **A.paired(oks['aries_treatment'], oks[other])}
    for c in EXPLORATORY:
        try:
            _, rows, _ = A.raw(f'aries-{c}-qwen2_5_7b-nl2bash-r1b')
        except (FileNotFoundError, SystemExit) as exc:
            out['exploratory']['nl2bash'][c] = {'missing': str(exc)}
            continue
        m, ok = A.label_metrics(ids, gold, current_predictions(rows))
        out['exploratory']['nl2bash'][c] = {**m, 'stages': stage_counts(rows, gold),
                                            'paired_vs_treatment': A.paired(ok, oks['aries_treatment'])}

    # CLINC150 (R1b sample, 600): act or abstain
    cm = json.loads((HERE / 'clinc-sample-manifest.json').read_text())
    cids = [r['id'] for r in cm['sample']]
    uns = {r['id']: r['gold_label'] == OOS for r in cm['sample']}
    _, ct, _ = A.raw(f'aries-{TREATMENT}-qwen2_5_7b-clinc-r1b')
    _, cf, _ = A.raw('router-qwen2_5_7b-A1-clinc-r1b')
    _, zc, _ = A.raw('zeroshot-clinc-r1b')
    _, ec, _ = A.raw('embedding-clinc-r1b')
    acts = {'aries_treatment': {i: bool(ct[i].get('acts')) for i in cids},
            'router_A1_frozen': {i: router_acts(cf[i]) for i in cids},
            'zeroshot_qwen': {i: bool(zc[i].get('label')) and canonical(zc[i]['label']) != OOS for i in cids},
            'embedding': {i: p != OOS for i, p in A.threshold_predict(ec, taus['clinc_embedding']).items()},
            'always_abstain': {i: False for i in cids}}
    oks_c = {}
    for name, a in acts.items():
        out['clinc150'][name], oks_c[name] = A.binary_metrics(cids, uns, a)
    out['clinc150']['stages_treatment'] = stage_counts(ct, None)
    out['clinc150']['groups'] = cm['n']
    for t, other in (('H-R1b-c', 'router_A1_frozen'), ('H-R1b-d', 'zeroshot_qwen')):
        out['tests'][t] = {'dataset': 'clinc-r1b', 'first': 'aries_treatment', 'second': other,
                           **A.paired(oks_c['aries_treatment'], oks_c[other])}
    for c in EXPLORATORY:
        try:
            _, rows, _ = A.raw(f'aries-{c}-qwen2_5_7b-clinc-r1b')
        except (FileNotFoundError, SystemExit) as exc:
            out['exploratory']['clinc150'][c] = {'missing': str(exc)}
            continue
        m, ok = A.binary_metrics(cids, uns, {i: bool(rows[i].get('acts')) for i in cids})
        out['exploratory']['clinc150'][c] = {**m, 'stages': stage_counts(rows, None),
                                             'paired_vs_treatment': A.paired(ok, oks_c['aries_treatment'])}

    adj = A.holm({t: v['p_two_sided_exact'] for t, v in out['tests'].items()})
    for t in out['tests']:
        out['tests'][t]['p_holm'] = adj[t]
        out['tests'][t]['significant_holm_0_05'] = adj[t] < 0.05
    dest.write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps(out['tests'], indent=1))


if __name__ == '__main__':
    main()
