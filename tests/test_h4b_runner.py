"""The H4b runner's conditions, outcome rules and analysis (experiments/thesis-followup-20261012/h4b-runs/).

No instance, model or item is used: the runner and analysis modules are loaded and their pure functions are
checked on synthetic records and on the example pair only.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import check, run_module

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'experiments/thesis-followup-20261012/h4b-runs'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = load('run_h4b', RUNS / 'run_h4b.py')
A = load('analyze_h4b', RUNS / 'analyze_h4b.py')
H4 = load('run_h4', ROOT / 'experiments/thesis-followup-20261012/h4-runs/run_h4.py')
C = '/h/c/x-01'


def test_conditions_are_the_registered_ones():
    from aries import flags
    t, b = H.CONDITIONS['treatment'], H.CONDITIONS['baseline']
    check('every named flag exists', all(k in flags.FLAGS for cond in H.CONDITIONS.values() for k in cond))
    check('baseline is the registered H4 treatment (run_h4 on-guard) plus the resolver off',
          {k: b[k] for k in H4.CONDITIONS['on-guard']} == H4.CONDITIONS['on-guard'] and b['ARIES_CLARIFY_RESOLVER'] == '0')
    check('the conditions differ only in ARIES_CLARIFY_RESOLVER', {k for k in t if t[k] != b[k]} == {'ARIES_CLARIFY_RESOLVER'}
          and t['ARIES_CLARIFY_RESOLVER'] == '1')
    check('flags added after the registration are pinned at their off defaults',
          all(cond[k] == '0' and not flags.FLAGS[k][0] for cond in (t, b)
              for k in ('ARIES_COMPLETION_TYPED_CONTRACT', 'ARIES_MEASURE_CHANGE_HOOK')))
    check('the frozen item SHA-256s are those of H4b Amendment 1', all(
        sha in (ROOT / 'docs/preregistration/H4b-clarify-resolver.md').read_text() for sha in H.FROZEN_ITEMS.values()))


def amb_case():
    return {'kind': 'ambiguous', 'fitting_files': ['a.txt', 'b.txt']}


def checks(sandbox=True):
    return [{'id': 'question_asked', 'passed': True}, {'id': 'sandbox_unchanged', 'passed': sandbox}]


def asked(source='resolver', choices=(C + '/a.txt', C + '/b.txt'), steps=()):
    return {'state': 'needs_clarification', 'clarification': {'source': source, 'choices': list(choices)},
            'steps': list(steps)}


def test_ambiguous_outcome():
    ok = H.h4b_outcome(amb_case(), asked(), checks(), [{'id': 'no_candidate_read', 'passed': True}], 'PASS', C)
    check('a resolver question with exactly the fitting choices is correct', ok['correct'] and ok['over_ask'] is None)
    check('a planner question counts too',
          H.h4b_outcome(amb_case(), asked('planner'), checks(), [], 'PASS', C)['correct'])
    bad = {
        'another source': (asked('pre-planning'), checks(), [], 'PASS'),
        'a missing choice': (asked(choices=[C + '/a.txt']), checks(), [], 'PASS'),
        'an extra choice': (asked(choices=[C + '/a.txt', C + '/b.txt', C + '/c.txt']), checks(), [], 'PASS'),
        'a candidate read before asking': (asked(steps=[{'capability': 'file.read', 'args': {'path': C + '/b.txt'},
                                                         'execution_status': 'observed'}]), checks(), [], 'PASS'),
        'sandbox changed': (asked(), checks(False), [], 'PASS'),
        'a forbidden state violated': (asked(), checks(), [{'id': 'x', 'passed': False}], 'PASS'),
        'oracle INCONCLUSIVE': (asked(), checks(), [], 'INCONCLUSIVE'),
        'not asked': ({'state': 'done', 'steps': []}, checks(), [], 'FAIL'),
    }
    for label, (rec, ch, forb, verdict) in bad.items():
        check('not correct: ' + label, H.h4b_outcome(amb_case(), rec, ch, forb, verdict, C)['correct'] is False)
    planned = asked(steps=[{'capability': 'file.read', 'args': {'path': C + '/b.txt'}, 'execution_status': 'planned'}])
    check('a planned but never executed read is not a read',
          H.h4b_outcome(amb_case(), planned, checks(), [], 'PASS', C)['correct'])
    check('a listing is not a read', H.read_paths(asked(steps=[{'capability': 'file.list', 'args': {'path': C},
                                                                'execution_status': 'observed'}])) == [])


def test_twin_outcome():
    twin = {'kind': 'twin', 'fitting_files': ['a.txt', 'b.txt'], 'intended_file': 'b.txt'}
    done = {'state': 'done', 'steps': []}
    check('twin correct = oracle PASS', H.h4b_outcome(twin, done, [], [], 'PASS', C)['correct'])
    check('twin FAIL and INCONCLUSIVE are not correct', not H.h4b_outcome(twin, done, [], [], 'FAIL', C)['correct']
          and not H.h4b_outcome(twin, done, [], [], 'INCONCLUSIVE', C)['correct'])
    o = H.h4b_outcome(twin, asked(), [], [], 'FAIL', C)
    check('a twin that asks is an over-ask, with its question source', o['over_ask'] is True and o['question_source'] == 'resolver')
    check('a twin that does not ask is not an over-ask', H.h4b_outcome(twin, done, [], [], 'PASS', C)['over_ask'] is False)


def test_resolver_summary():
    check('no resolver state: None', H.resolver_summary({'agent': {}}) is None)
    rec = {'agent': {'resolver': {'applies': True, 'n': 3, 'outcome': 'asked', 'accepted': False, 'why': 'span',
                                  'decision': {'decision': 'select', 'selected_index': 1, 'evidence_span': 'x'},
                                  'decision_call': {'seconds': 0.4}},
                     'metrics': {'planner_calls': 2, 'resolver_model_calls': 1}}}
    s = H.resolver_summary(rec)
    check('the raw decision, the code check and the bucket are recorded', s['model_decision'] == 'select'
          and s['accepted'] is False and s['why'] == 'span' and s['candidate_bucket'] == '2-5')
    check('buckets 0, 1, >5', [H.resolver_summary({'agent': {'resolver': {'n': n}}})['candidate_bucket']
                                for n in (0, 1, 6)] == ['0', '1', '>5'])
    check('model calls per item', H.model_calls(rec) == {'planner_calls': 2, 'resolver_model_calls': 1})


def test_statistics():
    up0 = A.newcombe_paired(0, 0, 0, 30)[2]
    up1 = A.newcombe_paired(0, 1, 0, 29)[2]
    check('Newcombe method 10 reproduces the registered 8.3 and 13.6 points (30 pairs)',
          round(100 * up0, 1) == 8.3 and round(100 * up1, 1) == 13.6)
    check('40 pairs: two extra over-asks always fail the margin',
          all(A.newcombe_paired(a, 2, 0, 38 - a)[2] >= A.MARGIN for a in range(0, 20)))
    check('exact two-sided McNemar', A.mcnemar_two_sided(5, 0) == 0.0625 and A.mcnemar_two_sided(3, 3) == 1.0
          and A.mcnemar_two_sided(0, 0) == 1.0)
    w = A.wilson(0, 40)
    check('Wilson interval for 0/40', w[0] == 0.0 and abs(w[1] - 0.0876) < 1e-3)


def synthetic_run(folder, condition, correct_pairs, over_asks):
    res = []
    for i in range(1, 41):
        p = f'p{i:02d}'
        good = i <= correct_pairs
        res.append({'id': f'h4b-a-{i:02d}', 'pair_id': p, 'kind': 'ambiguous', 'terminal_state': 'needs_clarification',
                    'verdict': 'PASS', 'seconds': 10, 'h4b': {'correct': True, 'over_ask': None}, 'resolver': None})
        oa = i > 40 - over_asks
        res.append({'id': f'h4b-t-{i:02d}', 'pair_id': p, 'kind': 'twin', 'twin_type': 't2' if i <= 15 else 't1',
                    'terminal_state': 'needs_clarification' if oa else 'done', 'verdict': 'PASS' if good else 'FAIL',
                    'seconds': 10, 'h4b': {'correct': good, 'over_ask': oa}, 'resolver': None})
    meta = {'condition': condition, 'sets': 'h4b', 'finished_at': 'x', 'model_stable': True, 'code_stable': True,
            'preflight': {'commit': 'abc'}}
    folder.mkdir()
    (folder / 'results.json').write_text(json.dumps({'run': meta, 'results': res}))


def test_analysis_on_synthetic_runs():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        A.HERE = d
        folders = []
        for i, cond in enumerate(['treatment', 'baseline'] * 3):
            f = d / f'2026101{i}T000000Z-r{i}-{cond}'
            synthetic_run(f, cond, 30 if cond == 'treatment' else 20, 0)
            folders.append(f)
        check('six complete runs are analysed', A.main([str(f) for f in folders]) == 0)
        out = json.loads(next(d.glob('summary-*.json')).read_text())
        check('paired accuracy and McNemar counts', out['primary']['paired_accuracy'] == {'treatment': 30, 'baseline': 20}
              and out['primary']['b_treatment_only'] == 10 and out['primary']['c_baseline_only'] == 0)
        check('no over-asks: non-inferior', out['secondary']['over_ask_non_inferiority']['all']['non_inferior'])
        check('a second analysis of the same runs refuses to overwrite', _raises(lambda: A.main([str(f) for f in folders])))
        check('five runs are refused', A.main([str(f) for f in folders[:5]]) == 1)


def _raises(fn):
    try:
        fn()
    except SystemExit:
        return True
    return False


def test_example_pair_only():
    cases = H.cases_for('example')
    check('the example set is the example pair', [c['id'] for _, c in cases] == ['ex-a-01', 'ex-t-01']
          and all(c.get('example') for _, c in cases))


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
