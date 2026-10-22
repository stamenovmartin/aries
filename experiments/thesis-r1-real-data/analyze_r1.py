#!/usr/bin/env python3
"""R1 analysis, as registered (docs/preregistration/R1-real-data-benchmarks.md). Written before any run.

    analyze_r1.py   ->  summary.json (refuses to overwrite)

Reads the frozen labels (labels/*-final.json), the sample manifests and raw/*.jsonl. A raw file without its
footer (an incomplete run) is refused. Errors and fallbacks count as wrong in every fixed denominator."""
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import CAPABILITIES, OOS, canonical  # noqa: E402
from run_r1 import router_acts  # noqa: E402

RAW = HERE / 'raw'
CAPS = list(CAPABILITIES)


def raw(name):
    lines = [json.loads(l) for l in (RAW / f'{name}.jsonl').read_text().splitlines() if l.strip()]
    if not lines or not lines[0].get('header') or not lines[-1].get('footer'):
        raise SystemExit(f'REFUSED: {name} is incomplete')
    return lines[0], {r['id']: r for r in lines[1:-1]}, lines[-1]


def binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))


def clopper_pearson(k, n):
    """Exact 95% interval by bisection on the binomial tails."""
    if not n:
        return None

    def bisect(f, target, increasing):
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if (f(mid) < target) == increasing:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    lower = 0.0 if k == 0 else bisect(lambda p: 1 - binom_cdf(k - 1, n, p), 0.025, True)
    upper = 1.0 if k == n else bisect(lambda p: binom_cdf(k, n, p), 0.025, False)
    return [round(lower, 4), round(upper, 4)]


def rate(k, n):
    return {'k': k, 'n': n, 'rate': round(k / n, 4) if n else None, 'cp95': clopper_pearson(k, n)}


def mcnemar(b, c):
    m = b + c
    return 1.0 if not m else min(1.0, 2 * sum(math.comb(m, i) for i in range(0, min(b, c) + 1)) / 2 ** m)


def holm(ps):
    order = sorted(ps, key=lambda k: ps[k])
    out, running = {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, (len(ps) - i) * ps[k]))
        out[k] = running
    return out


def f1(gold, pred, label):
    tp = sum(g == label and p == label for g, p in zip(gold, pred))
    fp = sum(g != label and p == label for g, p in zip(gold, pred))
    fn = sum(g == label and p != label for g, p in zip(gold, pred))
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def macro_f1(gold, pred):
    labels = sorted(set(gold))
    return sum(f1(gold, pred, l) for l in labels) / len(labels)


def boot(fn, n, reps=2000, seed=61022):
    rng = random.Random(seed)
    vals = sorted(fn([rng.randrange(n) for _ in range(n)]) for _ in range(reps))
    return [round(vals[int(0.025 * reps)], 4), round(vals[int(0.975 * reps) - 1], 4)]


def threshold_predict(rows, tau):
    out = {}
    for i, r in rows.items():
        s = r['scores']
        j = max(range(len(s)), key=lambda x: s[x])
        out[i] = canonical(CAPS[j]) if s[j] >= tau else OOS
    return out


def grid(rows):
    top = max(max(r['scores']) for r in rows.values())
    lo = min(max(r['scores']) for r in rows.values())
    return [round(lo + i * 0.001, 3) for i in range(int((top - lo) / 0.001) + 2)]


def best_tau(rows, objective):
    best, best_v = None, -1
    for tau in grid(rows):
        v = objective(threshold_predict(rows, tau))
        if v > best_v:      # strict: ties go to the lowest tau
            best, best_v = tau, v
    return best, best_v


def label_metrics(ids, gold, pred):
    g = [gold[i] for i in ids]
    p = [pred.get(i) for i in ids]
    ok = [x == y for x, y in zip(g, p)]
    oos_pred = sum(x == OOS for x in p)
    oos_tp = sum(x == OOS and y == OOS for x, y in zip(g, p))
    return {'top1': rate(sum(ok), len(ids)),
            'macro_f1': round(macro_f1(g, p), 4),
            'macro_f1_boot95': boot(lambda idx: macro_f1([g[k] for k in idx], [p[k] for k in idx]), len(ids)),
            'oos_precision': rate(oos_tp, oos_pred), 'oos_recall': rate(oos_tp, sum(x == OOS for x in g)),
            'predicted': dict(Counter(x if x is not None else 'none' for x in p).most_common())}, ok


def binary_metrics(ids, unsupported, acts):
    g = [unsupported[i] for i in ids]
    a = [bool(acts.get(i)) for i in ids]
    ok = [(not x) == y for x, y in zip(g, a)]
    tp = sum(x and not y for x, y in zip(g, a))
    pred_oos = sum(not y for y in a)
    pos = sum(g)
    f1v = lambda idx: (lambda t, pp, gg: 2 * t / (pp + gg) if t else 0.0)(  # noqa: E731
        sum(g[k] and not a[k] for k in idx), sum(not a[k] for k in idx), sum(g[k] for k in idx))
    return {'correct': rate(sum(ok), len(ids)), 'oos_precision': rate(tp, pred_oos), 'oos_recall': rate(tp, pos),
            'oos_f1': round(2 * tp / (pred_oos + pos), 4) if tp else 0.0,
            'oos_f1_boot95': boot(f1v, len(ids)),
            'in_scope_accuracy': rate(sum(not x and y for x, y in zip(g, a)), len(ids) - pos)}, ok


def paired(ok1, ok2):
    b = sum(x and not y for x, y in zip(ok1, ok2))
    c = sum(y and not x for x, y in zip(ok1, ok2))
    return {'b_first_only': b, 'c_second_only': c, 'p_two_sided_exact': mcnemar(b, c)}


def aries_predictions(router, planner):
    out = {}
    for i, r in router.items():
        if not router_acts(r):
            out[i] = OOS
            continue
        d = (planner.get(i) or {}).get('decision') or {}
        cap = d.get('capability')
        out[i] = canonical(cap) if d.get('action') == 'execute' and cap in CAPABILITIES else OOS
    return out


def zeroshot_predictions(rows):
    return {i: canonical(r['label']) if r.get('label') else None for i, r in rows.items()}


def main():
    dest = HERE / 'summary.json'
    if dest.exists():
        raise SystemExit('REFUSED: summary.json exists')
    nb_gold = json.loads((HERE / 'labels' / 'nl2bash-final.json').read_text())['labels']
    nb_manifest = json.loads((HERE / 'nl2bash-sample-manifest.json').read_text())
    test = [s['id'] for s in nb_manifest['sample'] if s['split'] == 'test']
    dev = [s['id'] for s in nb_manifest['sample'] if s['split'] == 'dev']
    out = {'label': 'R1 family (Holm inside R1); secondary llama rows exploratory, outside Holm', 'nl2bash': {},
           'clinc150': {}, 'tests': {}}
    # NL2Bash
    _, rq, _ = raw('router-qwen2_5_7b-A1-nl2bash-test')
    _, pq, _ = raw('planner-qwen2_5_7b-nl2bash-test')
    _, zq, _ = raw('zeroshot-nl2bash-test')
    _, emb, _ = raw('embedding-nl2bash')
    _, bm, _ = raw('bm25-nl2bash')
    preds = {'aries': aries_predictions(rq, pq), 'zeroshot_qwen': zeroshot_predictions(zq)}
    taus = {}
    for name, rows in (('embedding', emb), ('bm25', bm)):
        dev_rows = {i: rows[i] for i in dev}
        tau, v = best_tau(dev_rows, lambda p: sum(p[i] == nb_gold[i] for i in dev))
        taus[name] = {'tau': tau, 'dev_top1': v, 'dev_n': len(dev)}
        preds[name] = threshold_predict({i: rows[i] for i in test}, tau)
    oks = {}
    for name, p in preds.items():
        out['nl2bash'][name], oks[name] = label_metrics(test, nb_gold, p)
    out['nl2bash']['thresholds_from_dev'] = taus
    nb_unsupported = {i: nb_gold[i] == OOS for i in test}
    out['nl2bash']['router_only_in_vs_out'], _ = binary_metrics(test, nb_unsupported, {i: router_acts(rq[i]) for i in test})
    try:
        _, rl, _ = raw('router-llama3_1_8b-A1-nl2bash-test')
        _, pl, _ = raw('planner-llama3_1_8b-nl2bash-test')
        out['nl2bash']['aries_llama_secondary'], ok_l = label_metrics(test, nb_gold, aries_predictions(rl, pl))
        out['nl2bash']['aries_llama_secondary']['paired_vs_aries_qwen'] = paired(ok_l, oks['aries'])
    except (FileNotFoundError, SystemExit) as exc:
        out['nl2bash']['aries_llama_secondary'] = {'missing': str(exc)}
    out['nl2bash']['gold_label_counts_test'] = dict(Counter(nb_gold[i] for i in test).most_common())
    for t, other in (('H-R1a', 'embedding'), ('H-R1b', 'bm25'), ('H-R1c', 'zeroshot_qwen')):
        out['tests'][t] = {'dataset': 'nl2bash-test', 'first': 'aries', 'second': other, **paired(oks['aries'], oks[other])}
    # CLINC150
    cm = json.loads((HERE / 'clinc-sample-manifest.json').read_text())
    cids = [r['id'] for r in cm['sample']]
    uns = {r['id']: r['gold_label'] == OOS for r in cm['sample']}
    acts = {}
    for arm in ('A1', 'A0'):
        _, r, _ = raw(f'router-qwen2_5_7b-{arm}-clinc')
        acts[f'router_{arm}'] = {i: router_acts(r[i]) for i in cids}
    _, zc, _ = raw('zeroshot-clinc')
    acts['zeroshot_qwen'] = {i: bool(zc[i].get('label')) and canonical(zc[i]['label']) != OOS for i in cids}
    _, ev, _ = raw('embedding-clinc-val')
    clinc_gold = json.loads((HERE / 'labels' / 'clinc-final.json').read_text())['labels']
    data = json.loads((Path.home() / 'data-ext/clinc150/data_full.json').read_text())
    val = data['val'] + data['oos_val']
    val_uns = {f'cv-{k:05d}': (intent == 'oos' or canonical(clinc_gold[intent]) == OOS) for k, (_, intent) in enumerate(val)}

    def val_f1(pred):
        tp = sum(val_uns[i] and pred[i] == OOS for i in pred)
        pp = sum(pred[i] == OOS for i in pred)
        return 2 * tp / (pp + sum(val_uns.values())) if tp else 0.0
    tau, v = best_tau(ev, val_f1)
    _, ec, _ = raw('embedding-clinc')
    acts['embedding'] = {i: p != OOS for i, p in threshold_predict(ec, tau).items()}
    out['clinc150']['embedding_threshold_from_val'] = {'tau': tau, 'val_oos_f1': round(v, 4), 'val_n': len(val)}
    oks_c = {}
    for name, a in acts.items():
        out['clinc150'][name], oks_c[name] = binary_metrics(cids, uns, a)
    try:
        _, rl, _ = raw('router-llama3_1_8b-A1-clinc')
        out['clinc150']['router_A1_llama_secondary'], _ = binary_metrics(cids, uns, {i: router_acts(rl[i]) for i in cids})
    except (FileNotFoundError, SystemExit) as exc:
        out['clinc150']['router_A1_llama_secondary'] = {'missing': str(exc)}
    out['clinc150']['groups'] = cm['n']
    for t, other in (('H-R1d', 'router_A0'), ('H-R1e', 'embedding'), ('H-R1f', 'zeroshot_qwen')):
        out['tests'][t] = {'dataset': 'clinc150', 'first': 'router_A1', 'second': other,
                           **paired(oks_c['router_A1'], oks_c[other])}
    adj = holm({t: v['p_two_sided_exact'] for t, v in out['tests'].items()})
    for t in out['tests']:
        out['tests'][t]['p_holm'] = adj[t]
        out['tests'][t]['significant_holm_0_05'] = adj[t] < 0.05
    dest.write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps(out['tests'], indent=1))


if __name__ == '__main__':
    main()
