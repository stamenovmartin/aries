#!/usr/bin/env python3
"""M2 analysis, as registered (docs/preregistration/M2-local-models.md). Written before any M2 run.

    analyze_m2.py   ->  summary.json (refuses to overwrite)

R1b's labels, manifests, prediction rules and metric functions (thesis-r1b/analyze_r1b.py, which uses R1's).
qwen2.5:7b rows are R1b's raw files, unchanged. HAL1's error kinds (hallucination_eval.kind_of) for M1."""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments/thesis-r1b'))
sys.path.insert(0, str(ROOT / 'experiments/thesis-improvements-20261022'))
import analyze_r1b as B  # noqa: E402
from analyze_r1b import A, OOS, router_acts  # noqa: E402
from hallucination_eval import kind_of  # noqa: E402

MODELS = ('qwen2.5:7b', 'llama3.1:8b', 'qwen2.5:1.5b', 'qwen2.5:14b')
TESTS = {'M2-a': ('llama3.1:8b', 'nl2bash'), 'M2-b': ('llama3.1:8b', 'clinc150'),
         'M2-c': ('qwen2.5:1.5b', 'nl2bash'), 'M2-d': ('qwen2.5:1.5b', 'clinc150'),
         'M2-e': ('qwen2.5:14b', 'nl2bash'), 'M2-f': ('qwen2.5:14b', 'clinc150')}


def tag(model):
    return model.replace(':', '_').replace('.', '_')


def zeroshot_file(model, s):
    return f'zeroshot-{s}' if model == 'qwen2.5:7b' else f'zeroshot-{tag(model)}-{s}'


def m1(rows, key):
    calls = [r for r in rows.values() if key in r or 'decision' in r or 'raw_output' in r]
    bad = [r for r in calls if r.get(key)]
    return {'invalid': A.rate(len(bad), len(calls)), 'by_kind': dict(Counter(kind_of(r[key]) for r in bad))}


def m5(rows, gold_oos, acts):
    ids = [i for i in rows if gold_oos.get(i)]
    conf = sum(acts(rows[i]) and ((rows[i].get('route') or rows[i]).get('confidence') or 0) >= 0.9 for i in ids)
    return A.rate(conf, len(ids))


def main():
    dest = HERE / 'summary.json'
    if dest.exists():
        raise SystemExit('REFUSED: summary.json exists')
    T = B.TREATMENT
    out = {'label': 'M2 family (Holm over the four registered tests); other rows descriptive',
           'treatment_config': T, 'models': {}, 'tests': {}}
    gold = json.loads((B.HERE / 'labels/nl2bash-final.json').read_text())['labels']
    ids = [s['id'] for s in json.loads((B.HERE / 'nl2bash-sample-manifest.json').read_text())['sample']]
    in_scope = [i for i in ids if gold[i] != OOS]
    cm = json.loads((B.HERE / 'clinc-sample-manifest.json').read_text())
    cids = [r['id'] for r in cm['sample']]
    uns = {r['id']: r['gold_label'] == OOS for r in cm['sample']}
    oks = {}
    for model in MODELS:
        t = tag(model)
        res = {'nl2bash': {}, 'clinc150': {}, 'hallucination': {}}
        h, treat, _ = A.raw(f'aries-{T}-{t}-nl2bash-r1b')
        _, fr, _ = A.raw(f'router-{t}-A1-nl2bash-r1b')
        _, fp, _ = A.raw(f'planner-{t}-nl2bash-r1b')
        _, zq, _ = A.raw(zeroshot_file(model, 'nl2bash-r1b'))
        preds = {'aries_treatment': B.current_predictions(treat), 'aries_frozen': A.aries_predictions(fr, fp),
                 'zeroshot': A.zeroshot_predictions(zq)}
        for name, p in preds.items():
            res['nl2bash'][name], oks[(model, 'nl2bash', name)] = A.label_metrics(ids, gold, p)
        res['nl2bash']['in_scope_top1'] = {name: A.rate(sum(p[i] == gold[i] for i in in_scope), len(in_scope))
                                           for name, p in preds.items()}
        res['nl2bash']['stages_treatment'] = B.stage_counts(treat, gold)
        _, ct, _ = A.raw(f'aries-{T}-{t}-clinc-r1b')
        _, cf, _ = A.raw(f'router-{t}-A1-clinc-r1b')
        _, zc, _ = A.raw(zeroshot_file(model, 'clinc-r1b'))
        acts = {'aries_treatment': {i: bool(ct[i].get('acts')) for i in cids},
                'aries_frozen': {i: router_acts(cf[i]) for i in cids},
                'zeroshot': {i: bool(zc[i].get('label')) and B.canonical(zc[i]['label']) != OOS for i in cids}}
        for name, a in acts.items():
            res['clinc150'][name], oks[(model, 'clinc150', name)] = A.binary_metrics(cids, uns, a)
        res['clinc150']['stages_treatment'] = B.stage_counts(ct, None)
        for d in ('nl2bash', 'clinc150'):
            res[d]['treatment_vs_zeroshot'] = A.paired(oks[(model, d, 'aries_treatment')], oks[(model, d, 'zeroshot')])
            res[d]['treatment_vs_frozen'] = A.paired(oks[(model, d, 'aries_treatment')], oks[(model, d, 'aries_frozen')])
        nb_oos = {i: gold[i] == OOS for i in ids}
        res['hallucination'] = {
            'M1_planner_invalid_treatment': m1(treat, 'planner_error'),
            'M1_planner_invalid_frozen': m1(fp, 'error'),
            'M5_confident_action_on_oos_nl2bash_treatment': m5(treat, nb_oos, lambda r: bool(r.get('acts'))),
            'M5_confident_action_on_oos_nl2bash_frozen': m5(fr, nb_oos, router_acts),
            'M5_confident_action_on_oos_clinc_treatment': m5(ct, uns, lambda r: bool(r.get('acts'))),
            'M5_confident_action_on_oos_clinc_frozen': m5(cf, uns, router_acts)}
        res['model_digest'] = (h.get('model_before') or {}).get('digest')
        out['models'][model] = res
    for test, (model, d) in TESTS.items():
        out['tests'][test] = {'model': model, 'dataset': d, 'first': 'aries_treatment', 'second': 'aries_frozen',
                              **A.paired(oks[(model, d, 'aries_treatment')], oks[(model, d, 'aries_frozen')])}
    adj = A.holm({k: v['p_two_sided_exact'] for k, v in out['tests'].items()})
    for k in out['tests']:
        out['tests'][k]['p_holm'] = adj[k]
        out['tests'][k]['significant_holm_0_05'] = adj[k] < 0.05
    dest.write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps(out['tests'], indent=1))


if __name__ == '__main__':
    main()
