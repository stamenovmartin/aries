#!/usr/bin/env python3
"""Score the llama3.1:8b router run with the frozen ARIES-FINAL-20261006 analysis.

Imports experiments/thesis-final-20261006/analyze_router.py and uses its score() and
correct() unchanged, and reproduces its main(): the same per-arm metrics, the same
case-cluster bootstrap (seed 61006, 2000 samples) for A3 - A1, and the same
predeclared criterion, evaluated descriptively (it was declared for qwen2.5:7b).
Writes summary.json here. qwen2.5:7b stays the primary result.
"""
import hashlib, importlib.util, json, random, statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parents[1] / 'thesis-final-20261006'


def load():
    spec = importlib.util.spec_from_file_location('analyze_router', ORIGINAL / 'analyze_router.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    A = load()
    protocol = A.read(HERE / 'protocol.json')
    status = A.read(HERE / 'run-status.json')
    assert status['status'] == 'complete' and status['model_stable'] and status['frozen_source_stable']
    labels = {r['id']: r for r in A.read(HERE / 'semantic_labels.json')['rows']}
    arms, by_arm, raw_sha = {}, {}, {}
    for arm in ('A0', 'A1', 'A2', 'A3'):
        pooled, reps = [], []
        for rep in range(1, 4):
            p = HERE / 'raw' / f'r{rep}-{arm}.jsonl'
            raw_sha[p.name] = A.sha(p)
            rows = [json.loads(l) for l in p.read_text().splitlines()]
            assert len(rows) == 225 and {r['id'] for r in rows} == set(labels)
            assert all(r['rep'] == rep and r['arm'] == arm and r['utterance'] == labels[r['id']]['utterance'] for r in rows)
            reps.append({'rep': rep, **A.score(rows, labels)})
            pooled += rows
        by_arm[arm] = pooled
        summary = A.score(pooled, labels)
        summary.update(repetitions=reps, binary_mean_pct=statistics.mean(r['binary']['pct'] for r in reps),
                       binary_min_pct=min(r['binary']['pct'] for r in reps),
                       binary_max_pct=max(r['binary']['pct'] for r in reps),
                       by_class={c: A.score([r for r in pooled if r['klass'] == c], labels)
                                 for c in ('actionable', 'ambiguous', 'out_of_scope', 'unsafe')},
                       by_language={l: A.score([r for r in pooled if r['lang'] == l], labels)
                                    for l in sorted({r['lang'] for r in pooled})},
                       model_path=A.score([r for r in pooled if r.get('source') != 'rule'], labels),
                       rule_only=A.score([r for r in pooled if r.get('source') == 'rule'], labels))
        arms[arm] = summary
    models = {r.get('provider_usage', {}).get('model') for rows in by_arm.values() for r in rows
              if r.get('source') == 'local' and r.get('provider_usage')}
    rates = {a: {i: statistics.mean(A.correct(r) for r in rows if r['id'] == i) for i in labels}
             for a, rows in by_arm.items()}
    differences = [rates['A3'][i] - rates['A1'][i] for i in labels]
    rng = random.Random(61006)
    samples = sorted(100 * statistics.mean(rng.choices(differences, k=225)) for _ in range(2000))
    paired = {'comparison': 'A3-A1', 'mean_difference_pp': 100 * statistics.mean(differences),
              'case_bootstrap_95_interval_pp': [samples[49], samples[1949]], 'bootstrap_samples': 2000,
              'independent_units': 225, 'case_mean_improved': sum(d > 0 for d in differences),
              'case_mean_worse': sum(d < 0 for d in differences), 'case_mean_equal': sum(d == 0 for d in differences)}
    criterion = {
        'binary_improves': arms['A3']['binary']['pct'] > arms['A1']['binary']['pct'],
        'native_semantic_noninferiority_2pp': arms['A3']['semantic_native']['pct'] >= arms['A1']['semantic_native']['pct'] - 2,
        'ood_false_action_decreases': arms['A3']['ood_false_action']['pct'] < arms['A1']['ood_false_action']['pct'],
        'note': 'Declared for qwen2.5:7b in ARIES-FINAL-20261006; evaluated here descriptively, not as a new hypothesis.'}
    criterion['all_met'] = all(v for k, v in criterion.items() if k != 'note')
    qwen = A.read(HERE.parent / 'inputs/final-evaluation.json')['router']
    comparison = {a: {'qwen2.5:7b': qwen['arms'][a]['binary'], protocol['model']['name']: arms[a]['binary']}
                  for a in arms}
    out = {'experiment': 'ARIES-FINAL-20261006 router protocol, second local model', 'model': protocol['model'],
           'primary_result': 'qwen2.5:7b (ARIES-FINAL-20261006)', 'models_seen_in_rows': sorted(m for m in models if m),
           'protocol_sha256': A.sha(HERE / 'protocol.json'), 'run_status': status, 'raw_sha256': raw_sha,
           'observations': sum(len(v) for v in by_arm.values()), 'unique_cases': 225, 'repetitions': 3,
           'arms': arms, 'paired': paired, 'predeclared_criterion_descriptive': criterion,
           'binary_comparison_with_primary': comparison,
           'scorer_sha256': A.sha(ORIGINAL / 'analyze_router.py'), 'analysis_sha256': A.sha(__file__)}
    (HERE / 'summary.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'arms': {a: {k: v[k] for k in ('binary', 'semantic_native', 'ood_out_of_scope', 'ood_false_action',
                                                     'abstention_precision', 'false_holds', 'errors')} for a, v in arms.items()},
                      'paired': paired, 'criterion': criterion, 'models_seen': out['models_seen_in_rows']}, indent=1))


if __name__ == '__main__':
    main()
