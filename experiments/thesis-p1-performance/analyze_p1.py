#!/usr/bin/env python3
"""P1 analysis, as registered (docs/preregistration/P1-performance.md). Written before any P1 run.

    analyze_p1.py   ->  summary.json (refuses to overwrite)

Descriptive: no hypothesis test. Rates carry Clopper-Pearson 95% intervals (R1's helper); latencies are
reported as quantiles over all requests; resources as means and maxima over the samples inside each phase."""
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = HERE / 'raw'
sys.path.insert(0, str(ROOT / 'experiments/thesis-r1-real-data'))
import analyze_r1 as A  # noqa: E402

MODELS = ('qwen2.5:1.5b', 'qwen2.5:7b', 'llama3.1:8b', 'qwen2.5:14b')
SETS = ('nl2bash-r1b', 'clinc-r1b')
B8 = ROOT / 'eval/agent_suite/20261004T095522Z-B8-final-full/results.json'


def tag(model):
    return model.replace(':', '_').replace('.', '_')


def quant(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {'n': 0}
    q = statistics.quantiles(xs, n=100, method='inclusive') if len(xs) > 1 else [xs[0]] * 99
    return {'n': len(xs), 'mean': round(statistics.fmean(xs), 3), 'median': round(q[49], 3),
            'p90': round(q[89], 3), 'p95': round(q[94], 3), 'max': round(xs[-1], 3)}


def rows(path):
    out = []
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if 'id' in r:
            out.append(r)
    return out


def decision_latency(rs):
    router = [r.get('router_seconds') for r in rs]
    planner = [r['planner_seconds'] for r in rs if 'planner_seconds' in r]
    total = [r.get('router_seconds', 0) + r.get('planner_seconds', 0) for r in rs]
    errors = sum(1 for r in rs if (r.get('route') or {}).get('error') or r.get('planner_error'))
    return {'router_and_gate_s': quant(router), 'planner_s': quant(planner), 'decision_total_s': quant(total),
            'requests': len(rs), 'errors_or_invalid': A.rate(errors, len(rs))}


def phases():
    open_, out = {}, {}
    for line in (RAW / 'phases.jsonl').read_text().splitlines():
        p = json.loads(line)
        if p['edge'] == 'start':
            open_[p['phase']] = p['t']
        else:
            out[p['phase']] = {'start': open_.pop(p['phase']), 'end': p['t'],
                               **{k: v for k, v in p.items() if k not in ('phase', 'edge', 't')}}
    return out


def samples():
    out = []
    for f in sorted(RAW.glob('resources-*.jsonl')):
        out += [json.loads(l) for l in f.read_text().splitlines() if '"header"' not in l]
    return out


def resources(ss, start, end, requests=None):
    s = [x for x in ss if start <= x['t'] <= end and 'gpu_mem_mb' in x]
    if not s:
        return {'samples': 0}

    def stat(key, sub=None):
        v = [(x[sub][key] if sub else x[key]) for x in s]
        return {'mean': round(statistics.fmean(v), 1), 'max': round(max(v), 1)}
    energy = sum(0.5 * (a['gpu_power_w'] + b['gpu_power_w']) * (b['t'] - a['t']) for a, b in zip(s, s[1:]))
    out = {'samples': len(s), 'seconds': round(end - start, 1), 'gpu_mem_mb': stat('gpu_mem_mb'),
           'gpu_util_pct': stat('gpu_util_pct'), 'gpu_power_w': stat('gpu_power_w'), 'gpu_temp_c': stat('gpu_temp_c'),
           'system_cpu_pct': stat('cpu_pct'), 'system_mem_used_mb': stat('mem_used_mb'),
           'ollama_rss_mb': stat('rss_mb', 'ollama'), 'ollama_cpu_pct_of_one_core': stat('cpu_pct', 'ollama'),
           'aries_rss_mb': stat('rss_mb', 'aries'), 'aries_cpu_pct_of_one_core': stat('cpu_pct', 'aries'),
           'gpu_energy_j': round(energy, 1)}
    if requests:
        out['gpu_energy_j_per_request'] = round(energy / requests, 2)
    return out


def suite(run):
    d = json.loads((HERE / 'suite' / run / 'results.json').read_text())
    goals = d['goals']
    by_cat = defaultdict(list)
    for g in goals:
        by_cat[g['category']].append(g)
    c = d['counts']
    return d, {'counts': c, 'pass': A.rate(c['pass'], c['scored']),
               'false_success': A.rate(c['false_success'], c['scored']),
               'latency_s': quant([g.get('latency_s') for g in goals]),
               'by_category': {k: {'pass': A.rate(sum(g['outcome'] == 'pass' for g in v),
                                                  sum(g['outcome'] != 'skip' for g in v)),
                                   'latency_s': quant([g.get('latency_s') for g in v])} for k, v in by_cat.items()},
               'service_flags': d.get('flags', {}).get('aries_core_environment'),
               'models': d.get('models'), 'runtime_changed': d.get('runtime_changed')}


def main():
    dest = HERE / 'summary.json'
    if dest.exists():
        raise SystemExit('REFUSED: summary.json exists')
    ph, ss = phases(), samples()
    out = {'label': 'P1, descriptive (no hypothesis test)', 'decision': {}, 'decision_full_samples': {},
           'installed_system': {}}
    # P1-A: decision latency on the full R1b/M2 samples (1,100 requests per model, already measured)
    for m in MODELS:
        rs = sum((rows(ROOT / f'experiments/thesis-r1b/raw/aries-C1-{tag(m)}-{s}.jsonl') for s in SETS), [])
        out['decision_full_samples'][m] = decision_latency(rs)
    # P1-B: cold load, idle and workload resources, and latency on the 200-request workload, per model
    for m in MODELS:
        rs = sum((rows(RAW / f'aries-C1-{tag(m)}-{s}.jsonl') for s in SETS), [])
        load = ph[f'load:{m}']
        w0, w1 = ph[f'workload:{m}:{SETS[0]}']['start'], ph[f'workload:{m}:{SETS[1]}']['end']
        out['decision'][m] = {
            'cold_load_s': load['load_seconds'], 'ollama_size_vram': load.get('size_vram'),
            'latency': decision_latency(rs),
            'idle_unloaded': resources(ss, ph[f'idle-unloaded:{m}']['start'], ph[f'idle-unloaded:{m}']['end']),
            'idle_loaded': resources(ss, ph[f'idle-loaded:{m}']['start'], ph[f'idle-loaded:{m}']['end']),
            'workload': resources(ss, w0, w1, requests=len(rs))}
    # P1-C: the installed system: idle, and the agent suite three times
    out['installed_system']['idle'] = resources(ss, ph['live-idle']['start'], ph['live-idle']['end'])
    runs, outcome = {}, {}
    for r in (1, 2, 3):
        d, s = suite(f'p1-run{r}')
        s['resources'] = resources(ss, ph[f'suite-run-{r}']['start'], ph[f'suite-run-{r}']['end'],
                                   requests=s['counts']['attempted'])
        runs[f'run{r}'] = s
        outcome[r] = {g['id']: g['outcome'] for g in d['goals']}
    ids = sorted(set.intersection(*(set(o) for o in outcome.values())))
    same = [i for i in ids if len({outcome[r][i] for r in outcome}) == 1]
    out['installed_system']['agent_suite'] = runs
    out['installed_system']['reliability'] = {
        'goals_same_outcome_all_runs': A.rate(len(same), len(ids)),
        'goals_pass_all_runs': A.rate(sum(all(outcome[r][i] == 'pass' for r in outcome) for i in ids), len(ids)),
        'goals_pass_in_some_but_not_all': sorted(i for i in ids if i not in same and
                                                 any(outcome[r][i] == 'pass' for r in outcome)),
        'outcome_patterns': dict(Counter('/'.join(outcome[r][i] for r in sorted(outcome)) for i in ids))}
    b8 = json.loads(B8.read_text())['counts']
    out['installed_system']['reference_B8_20261004'] = {'pass': A.rate(b8['pass'], b8['scored']),
                                                        'false_success': A.rate(b8['false_success'], b8['scored'])}
    dest.write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps({m: {'load': v['cold_load_s'], 'median': v['latency']['decision_total_s'].get('median'),
                          'vram': v['workload'].get('gpu_mem_mb')} for m, v in out['decision'].items()}, indent=1))


if __name__ == '__main__':
    main()
