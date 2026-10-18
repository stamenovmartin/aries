#!/usr/bin/env python3
"""Thesis data tables: build every CSV in this folder from its sources, or check them.

    .venv/bin/python experiments/thesis-followup-20261012/thesis-tables/check.py           # check (default)
    .venv/bin/python experiments/thesis-followup-20261012/thesis-tables/check.py --write   # (re)write the CSVs

Check mode rebuilds each table in memory and fails (exit 1) if any CSV on disk differs by one byte,
including its first line, which names the source files with their sha256 and last commit.

Every table is also recomputed a second way wherever the raw data allows it, and the build fails if the
two disagree:
- router tables: the raw decisions are re-scored with the frozen analyze_router.score() and must
  equal the published summaries (final-evaluation.json for qwen2.5:7b, summary.json for llama3.1:8b);
- McNemar and Cochran's Q: recomputed from the raw decisions with the functions of
  scripts/thesis_stats.py and must equal stats.json (GEE and the variational GLMM are taken from
  stats.json; the GLMM varies by ~1e-6 between fits, so it is not refitted here);
- verifier classes: counted from the raw review file and must equal the ledger;
- held-out results: counted per case from the run file and must equal the per-goal diagnosis;
- end paths: counted from goals.json and must equal its own counts_by_end_path;
- contract coverage: recomputed with aries.workspace.contracts.compile_goal on the 57 fixture
  goals and must equal contract-coverage-static.txt;
- planner runs: counted from attempts.jsonl and must equal each run's summary.json;
- H4 development rounds: counted per case from results.redacted.json (the committed copy, with the copied
  owner settings values removed); where the local results.json exists, its redaction must equal that copy;
- H8 fault injection: every rate, criterion and McNemar count is recounted from records.jsonl and must equal
  summary.json; each Clopper-Pearson end is checked against the binomial tails; each run's manifest must match
  its recorded SHA-256, and every run after run 1 must have run the committed run_mutants.py.
- H6: majority-of-3 correctness, McNemar b, c and p, and every secondary rate are recounted from the raw
  decisions with the frozen analyze_router.correct() and must equal summary.json; the paired difference interval
  is recomputed from Clopper-Pearson ends found by bisection on the binomial tails.
Nothing is written to any source; no model, service or database is used.
"""
from __future__ import annotations

import csv
import collections
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FU = HERE.parent                                        # experiments/thesis-followup-20261012
FROZEN = ROOT / 'experiments/thesis-final-20261006'
IA = ROOT / 'experiments/product/independent-acceptance'
ARMS = ('A0', 'A1', 'A2', 'A3')
ROUTER_METRICS = ('binary', 'semantic_coarse', 'semantic_native', 'abstention_precision', 'abstention_recall',
                  'ood_false_action', 'ood_out_of_scope', 'false_holds')
MODELS = {'qwen2.5:7b': {'raw': FROZEN / 'raw', 'stats': FU / 'stats.json'},
          'llama3.1:8b': {'raw': FU / 'task6-model/raw', 'stats': FU / 'task6-model/stats/stats.json'}}
PLANNER_RUNS = (('frozen ARIES-FINAL-20261006', FROZEN / 'planner/runs/20261006T173518.677345Z', '4b3fd50 (frozen)',
                 'protocol flags; ARIES_PLANNER_CLARIFY did not exist'),
                ('clarify alone (Task 3.2)', FU / 'task3-planner/runs/20261012T171631.114537Z', '79d1f23',
                 'ARIES_PLANNER_CLARIFY=1 (default), GUARD not present'),
                ('clarify + guard (confirmation after the fix)', FU / 'task3-planner-guard/runs/20261012T193022.180980Z',
                 'a2d1609', 'CLARIFY=1 GUARD=1 PARAPHRASE=0'))
DEV_RUNS = (('baseline', '20261012T172818Z-dev-baseline-on'),
            ('round 1', '20261012T173115Z-dev-round1-on-guard'),
            ('round 2', '20261012T173411Z-dev-round2-on-guard'),
            ('round 3', '20261012T173631Z-dev-round3-on-guard'))


class Mismatch(Exception):
    pass


def must_equal(what, a, b):
    if a != b:
        raise Mismatch(f'{what}: {a!r} != {b!r}')


def read(p):
    return json.loads(Path(p).read_text())


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rel(p):
    return str(Path(p).resolve().relative_to(ROOT))


def published(files):
    """Files a public clone has: git-ignored files (databases, flag files, runtime state) are left out."""
    ignored = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], cwd=ROOT, capture_output=True,
                             text=True, input='\n'.join(rel(f) for f in files)).stdout.splitlines()
    return [f for f in files if rel(f) not in set(ignored) and '__pycache__' not in f.parts]


def provenance(paths, label):
    """First line of every CSV: source paths, sha256 of files (or of the sorted file list of a folder), commit."""
    parts = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files = published(sorted(f for f in p.rglob('*') if f.is_file()))
            digest = hashlib.sha256(b''.join(f.name.encode() + f.read_bytes() for f in files)).hexdigest()
        else:
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
        commit = subprocess.run(['git', 'log', '-1', '--format=%h', '--', rel(p)], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip() or 'not tracked by git'
        parts.append(f'{rel(p)} (sha256 {digest[:12]}, commit {commit})')
    return f'# source: {"; ".join(parts)} | label: {label}'


def render(header, columns, rows, note=None):
    out = io.StringIO()
    out.write(header + '\n')
    if note:
        out.write('# note: ' + note + '\n')
    w = csv.writer(out, lineterminator='\n')
    w.writerow(columns)
    for r in rows:
        w.writerow(['' if v is None else (f'{v:.6g}' if isinstance(v, float) else v) for v in r])
    return out.getvalue()


def pct(k, n):
    return None if not n else round(100 * k / n, 2)


# ---------------------------------------------------------------- router
def router_rows(model):
    A = load_module('analyze_router', FROZEN / 'analyze_router.py')
    labels = {r['id']: r for r in read(FROZEN / 'semantic_labels.json')['rows']}
    raw = {arm: {rep: [json.loads(l) for l in (MODELS[model]['raw'] / f'r{rep}-{arm}.jsonl').read_text().splitlines()]
                 for rep in (1, 2, 3)} for arm in ARMS}
    return A, labels, raw


def published_router(model):
    if model == 'qwen2.5:7b':
        return read(FU / 'inputs/final-evaluation.json')['router']['arms']
    return read(FU / 'task6-model/summary.json')['arms']


def table_router_arms():
    rows = []
    for model in MODELS:
        A, labels, raw = router_rows(model)
        pub = published_router(model)
        for arm in ARMS:
            pooled = [r for rep in (1, 2, 3) for r in raw[arm][rep]]
            mine = {'pooled': A.score(pooled, labels), **{f'rep{rep}': A.score(raw[arm][rep], labels) for rep in (1, 2, 3)}}
            theirs = {'pooled': pub[arm], **{f'rep{x["rep"]}': x for x in pub[arm]['repetitions']}}
            for scope in ('pooled', 'rep1', 'rep2', 'rep3'):
                for m in ROUTER_METRICS:
                    must_equal(f'{model} {arm} {scope} {m} (raw vs published)',
                               (mine[scope][m]['k'], mine[scope][m]['n']), (theirs[scope][m]['k'], theirs[scope][m]['n']))
                    k, n = theirs[scope][m]['k'], theirs[scope][m]['n']
                    rows.append((model, arm, scope, m, k, n, pct(k, n)))
    head = provenance([FU / 'inputs/final-evaluation.json', FROZEN / 'raw', FU / 'task6-model/summary.json',
                       FU / 'task6-model/raw', FROZEN / 'analyze_router.py', FROZEN / 'semantic_labels.json'],
                      'qwen2.5:7b confirmatory (ARIES-FINAL-20261006); llama3.1:8b exploratory')
    note = ('pct = 100k/n rounded to 2 decimals; ood_out_of_scope = out-of-scope requests declined, '
            'ood_false_action = out-of-scope requests acted on; qwen2.5:7b is copied from dokazi/final-evaluation.json')
    return render(head, ('model', 'arm', 'scope', 'metric', 'k', 'n', 'pct'), rows, note)


def table_router_by_class():
    rows = []
    for model in MODELS:
        A, labels, raw = router_rows(model)
        pub = published_router(model)
        for arm in ARMS:
            pooled = [r for rep in (1, 2, 3) for r in raw[arm][rep]]
            for klass in ('actionable', 'ambiguous', 'out_of_scope', 'unsafe'):
                mine = A.score([r for r in pooled if r['klass'] == klass], labels)['binary']
                theirs = pub[arm]['by_class'][klass]['binary']
                must_equal(f'{model} {arm} {klass} binary', (mine['k'], mine['n']), (theirs['k'], theirs['n']))
                rows.append((model, arm, klass, theirs['k'], theirs['n'], pct(theirs['k'], theirs['n'])))
    head = provenance([FU / 'inputs/final-evaluation.json', FROZEN / 'raw', FU / 'task6-model/summary.json',
                       FU / 'task6-model/raw'], 'qwen2.5:7b confirmatory data; llama3.1:8b exploratory')
    return render(head, ('model', 'arm', 'true_class', 'binary_k', 'n', 'pct'), rows,
                  'binary correctness per true class, 3 repetitions pooled')


def table_router_tests():
    S = load_module('thesis_stats', ROOT / 'scripts/thesis_stats.py')
    rows = []
    for model in MODELS:
        A, labels, raw = router_rows(model)
        st = read(MODELS[model]['stats'])
        ids = sorted(labels)
        score = {(arm, rep, r['id']): bool(A.correct(r)) for arm in ARMS for rep in (1, 2, 3) for r in raw[arm][rep]}
        maj = {a: {i: int(sum(score[(a, rep, i)] for rep in (1, 2, 3)) >= 2) for i in ids} for a in ARMS}
        gee, glmm = st['mixed_effects']['gee']['terms'], st['mixed_effects']['glmm']['fixed_effects']
        for x, y in (('A3', 'A1'), ('A2', 'A1'), ('A1', 'A0')):
            b = sum(maj[x][i] and not maj[y][i] for i in ids)
            c = sum(maj[y][i] and not maj[x][i] for i in ids)
            both = sum(maj[x][i] and maj[y][i] for i in ids)
            neither = sum(not maj[x][i] and not maj[y][i] for i in ids)
            t = st['mcnemar'][f'{x}_vs_{y}']
            must_equal(f'{model} {x} vs {y} McNemar (raw vs stats.json)',
                       (b, c, both, neither, S.mcnemar_exact(b, c)),
                       (t[f'{x}_correct_{y}_wrong'], t[f'{x}_wrong_{y}_correct'], t['both_correct'], t['both_wrong'],
                        t['p_value']))
            term_arm = x if y == 'A1' else y            # the model's reference arm is A1
            term = f'C(arm, Treatment("A1"))[T.{term_arm}]'
            g = glmm[term]
            rows.append((model, f'{x} vs {y}', b, c, both, neither, len(ids), t['p_value'],
                         f'{term_arm} vs A1', gee[term]['log_odds'], gee[term]['p_value'],
                         g['posterior_mean_log_odds'], g['approx_95_interval'][0], g['approx_95_interval'][1],
                         None, None, 'exploratory'))
        q, df = S.cochran_q([[maj[a][i] for a in ARMS] for i in ids])
        must_equal(f'{model} Cochran Q', (round(q, 9), df), (round(st['cochran_q']['Q'], 9), st['cochran_q']['df']))
        rows.append((model, 'A0-A3 (Cochran Q)', None, None, None, None, len(ids), st['cochran_q']['p_value'],
                     None, None, None, None, None, None, st['cochran_q']['Q'], df, 'exploratory'))
    head = provenance([MODELS['qwen2.5:7b']['stats'], MODELS['llama3.1:8b']['stats'], FROZEN / 'raw',
                       FU / 'task6-model/raw', ROOT / 'scripts/thesis_stats.py'], 'exploratory (post-hoc tests)')
    note = ('unit = request (n=225), majority of 3 repetitions; McNemar exact two-sided; GEE and GLMM on all 2,700 '
            'decisions with reference A1, so the A1 vs A0 row reports the A0 term (sign reversed); GLMM is variational '
            'Bayes, interval = mean +- 1.96 posterior SD; no multiple-comparison correction')
    return render(head, ('model', 'comparison', 'first_right_second_wrong', 'first_wrong_second_right', 'both_right',
                         'both_wrong', 'n_requests', 'p_value', 'model_term', 'gee_log_odds', 'gee_p',
                         'glmm_log_odds', 'glmm_lo', 'glmm_hi', 'cochran_q', 'df', 'label'), rows, note)


# ---------------------------------------------------------------- verifiers and ledger
def table_verifiers():
    review = read(IA / 'raw/review_verifier_integrity.json')
    ledger = read(ROOT / 'verification/ledger_frozen.json')['verification']
    classes = collections.Counter(c['verifier_class'] for c in review['capabilities'])
    kinds = collections.Counter(c['evidence_kind'] for c in review['capabilities'])
    must_equal('verifier classes (raw review vs ledger)', dict(classes),
               {k: v for k, v in ledger['classification'].items() if v})
    rows = [('capabilities', 'total', len(review['capabilities']))]
    rows += [('verifier_class', k, classes[k]) for k in ('INDEPENDENT', 'TRIVIAL', 'SELF_REPORT', 'PLANNER_SUPPLIED')]
    rows += [('verifier_class', 'UNDETERMINED', ledger['classification']['UNDETERMINED'])]
    rows += [('evidence_kind', k, kinds[k]) for k in sorted(kinds)]
    L = ledger['ledger']
    rows += [('ledger', 'goals', L['goals']), ('ledger', 'steps', L['steps'])]
    must_equal('ledger steps_by_status sums to steps', sum(L['steps_by_status'].values()) <= L['steps'], True)
    rows += [('ledger_steps_by_status', k, v) for k, v in L['steps_by_status'].items()]
    rows += [('ledger_reached_a_verifier', 'k', L['reached_a_verifier']['k']),
             ('ledger_reached_a_verifier', 'n', L['reached_a_verifier']['n']),
             ('ledger_contradictions', 'k', L['contradictions']['k']),
             ('ledger_contradictions', 'n', L['contradictions']['n']),
             ('ledger_contradictions', 'wilson_95_lo', L['contradictions']['wilson_95'][0]),
             ('ledger_contradictions', 'wilson_95_hi', L['contradictions']['wilson_95'][1])]
    for k, v in L['by_class'].items():
        must_equal(f'ledger {k} verified+contradicted', v['verified'] + v['contradicted'], v['total'])
        rows += [(f'ledger_by_class_{k}', f, v[f]) for f in ('verified', 'contradicted', 'total')]
    must_equal('ledger by_class contradictions', sum(v['contradicted'] for v in L['by_class'].values()),
               L['contradictions']['k'])
    must_equal('ledger by_class totals', sum(v['total'] for v in L['by_class'].values()), L['contradictions']['n'])
    head = provenance([IA / 'raw/review_verifier_integrity.json', ROOT / 'verification/ledger_frozen.json'],
                      'descriptive (frozen ARIES-FINAL-20261006 ledger)')
    note = ('57 executed / 1 source is the per-entry count; the narrative 56 in classification_method is stale '
            '(errata_20261012). "executed" includes substituted collaborators')
    return render(head, ('section', 'key', 'value'), rows, note)


# ---------------------------------------------------------------- held-out run and diagnosis
def heldout_results():
    run = read(IA / 'raw/fixture_run_20261006T154854Z.json')['results']
    goals = {g['id']: g for g in read(FU / 'terminal-diagnosis/goals.json')['goals']}
    for r in run:
        must_equal(f'held-out {r["id"]} terminal state (run vs diagnosis)', r['terminal_state'],
                   goals[r['id']]['terminal_state'])
        must_equal(f'held-out {r["id"]} verdict (run vs diagnosis)', r['verdict'], goals[r['id']]['verdict'])
    return run


def table_heldout():
    run = heldout_results()
    order = list(dict.fromkeys(r['class'] for r in run))
    states = ('done', 'partial', 'failed', 'proposed')
    rows = []
    for klass in order + ['TOTAL']:
        sel = [r for r in run if klass in ('TOTAL', r['class'])]
        v = collections.Counter(r['verdict'] for r in sel)
        s = collections.Counter(r['terminal_state'] for r in sel)
        must_equal(f'{klass} states known', set(s) <= set(states), True)
        rows.append((klass, len(sel), sum(r['held_out'] for r in sel), v['PASS'], v['FAIL'], v['INCONCLUSIVE'],
                     *(s[x] for x in states)))
    head = provenance([IA / 'raw/fixture_run_20261006T154854Z.json', FU / 'terminal-diagnosis/goals.json'],
                      'held-out acceptance run 2026-10-06 (frozen)')
    note = ('49 runnable goals of the 57-case fixture; held_out = the fixture\'s own held_out flag; verdict rule: '
            'check exit 1 = FAIL, other non-zero = INCONCLUSIVE')
    return render(head, ('class', 'goals', 'held_out_flag', 'PASS', 'FAIL', 'INCONCLUSIVE', *states), rows, note)


def table_end_paths():
    g = read(FU / 'terminal-diagnosis/goals.json')
    counts = collections.Counter(x['end_path'] for x in g['goals'])
    must_equal('end paths (per goal vs counts_by_end_path)', dict(counts), g['counts_by_end_path'])
    rows = []
    for path in ('step_budget_exhausted', 'rejected_finish', 'other', 'invalid_decisions', 'awaiting_approval',
                 'terminal_read_failure'):
        sel = [x for x in g['goals'] if x['end_path'] == path]
        s = collections.Counter(x['terminal_state'] for x in sel)
        rows.append((path, len(sel), s['partial'], s['failed'], s['proposed'], s['done']))
    s = collections.Counter(x['terminal_state'] for x in g['goals'])
    rows.append(('TOTAL', len(g['goals']), s['partial'], s['failed'], s['proposed'], s['done']))
    head = provenance([FU / 'terminal-diagnosis/goals.json', FU / 'terminal-diagnosis/extract.py'],
                      'exploratory (Task 2 diagnosis)')
    return render(head, ('end_path', 'goals', 'partial', 'failed', 'proposed', 'done'), rows,
                  '"other" = never planned, cause unknown (reported as unknown)')


def table_contract_coverage():
    sys.path[:0] = [str(ROOT), str(ROOT / 'vendor'), str(ROOT / 'vendor/agentic-core')]
    from aries.workspace import contracts
    fixtures = [json.loads(l) for l in (IA / 'fixtures.jsonl').read_text().splitlines() if l.strip()]
    text = (FU / 'terminal-diagnosis/contract-coverage-static.txt').read_text()
    rows = []
    for para in (False, True):
        sup = {f['id']: contracts.compile_goal(f['goal'], '/nonexistent-demo-dir', paraphrase=para)['supported']
               for f in fixtures}
        by = {}
        for outcome in ('ask', 'partial', 'pass', 'refuse'):
            sel = [f for f in fixtures if f['expected_outcome'] == outcome]
            by[outcome] = (sum(sup[f['id']] for f in sel), len(sel))
        total = (sum(sup.values()), len(fixtures))
        line = next(l for l in text.splitlines() if l.startswith(f'paraphrase={para}:'))
        must_equal(f'coverage paraphrase={para} (recomputed vs file)',
                   (f'supported {total[0]}/{total[1]}', {k: f'{a}/{b}' for k, (a, b) in by.items()}),
                   (re.search(r'supported \d+/\d+', line).group(0),
                    json.loads(line.split('by expected outcome: ')[1].replace("'", '"'))))
        rows.append(('on' if para else 'off', total[0], total[1], *(x for o in ('pass', 'partial', 'refuse', 'ask')
                                                                     for x in by[o])))
    head = provenance([FU / 'terminal-diagnosis/contract-coverage-static.txt', IA / 'fixtures.jsonl',
                       ROOT / 'aries/workspace/contracts.py'], 'exploratory (static count, same fixture; not outcomes)')
    return render(head, ('ARIES_COMPLETION_READ_PARAPHRASE', 'supported', 'goals', 'pass_supported', 'pass_goals',
                         'partial_supported', 'partial_goals', 'refuse_supported', 'refuse_goals', 'ask_supported',
                         'ask_goals'), rows, 'all 57 fixture goals, compile_goal only, no model or execution')


# ---------------------------------------------------------------- planner
def table_planner():
    rows = []
    for name, run, commit, flags in PLANNER_RUNS:
        att = [json.loads(l) for l in (run / 'attempts.jsonl').read_text().splitlines()]
        summ = read(run / 'summary.json')['overall']
        val = read(run / 'independent-validation.json')
        n = len(att)
        sv = sum(a['scores']['schema_valid'] for a in att)
        cap = sum(a['scores']['capability_correct'] for a in att)
        strict = sum(a['scores']['capability_arguments_correct'] for a in att)
        must_equal(f'planner {name} (attempts vs summary)', (n, sv, cap, strict),
                   (summ['attempted'], summ['schema_valid']['correct'], summ['capability_correct']['correct'],
                    summ['capability_arguments_correct']['correct']))
        p20 = [a for a in att if a['case_id'] in ('p20', 'p21', 'p22')]
        rest = [a for a in att if a['case_id'] not in ('p20', 'p21', 'p22')]
        rows.append((name, commit, flags, n, sv, cap, strict,
                     sum(a['scores']['capability_arguments_correct'] for a in p20), len(p20),
                     sum(a['scores']['capability_arguments_correct'] for a in rest), len(rest),
                     f'{val["passed"]}/{val["total"]}'))
    must_equal('frozen planner equals final-evaluation.json', rows[0][3:7],
               tuple(read(FU / 'inputs/final-evaluation.json')['planner']['overall'][k]['correct']
                     if k != 'attempted' else read(FU / 'inputs/final-evaluation.json')['planner']['overall'][k]
                     for k in ('attempted', 'schema_valid', 'capability_correct', 'capability_arguments_correct')))
    head = provenance([r[1] for r in PLANNER_RUNS] + [FU / 'inputs/final-evaluation.json'],
                      'frozen = confirmatory (ARIES-FINAL-20261006); clarify alone = regression check; '
                      'clarify + guard = confirmation after the fix, not independent evidence')
    return render(head, ('run', 'code', 'flags', 'attempts', 'schema_valid', 'capability_correct',
                         'strict_capability_and_arguments', 'p20_p22_strict', 'p20_p22_attempts', 'other_strict',
                         'other_attempts', 'independent_validation'), rows,
                  'same 24 cases x 3 repetitions, qwen2.5:7b, same protocol')


# ---------------------------------------------------------------- H4 development
def dev_set(c):
    """A = ambiguous, C = control; the dev rows carry set 'dev', so the class decides (and must match the id)."""
    s = {'h4_ambiguous': 'A', 'h4_control': 'C'}[c['class']]
    must_equal(f'{c["id"]} class matches id', c['id'].startswith(f'dev-{s.lower()}-'), True)
    return s


def dev_results(folder):
    """The committed redacted copy; where the local original exists, it must redact to exactly this copy."""
    run = FU / 'h4-runs' / folder
    committed = (run / 'results.redacted.json').read_text()
    if (run / 'results.json').exists():
        R = load_module('redact', FU / 'h4-runs/redact.py')
        must_equal(f'{folder} redacted copy', R.dump(R.redact(read(run / 'results.json'))), committed)
    return json.loads(committed)


def table_h4_dev():
    rows = []
    for name, folder in DEV_RUNS:
        res = dev_results(folder)
        cond, commit = res['run']['condition'], res['run']['preflight']['commit'][:7]
        for c in res['results']:
            must_equal(f'{folder} {c["id"]} is a dev row', (c['id'].startswith('dev-'), c['set']), (True, 'dev'))
            counted = c['h4']['grounded_question'] if dev_set(c) == 'A' else c['verdict'] == 'PASS'
            rows.append((name, commit, cond, c['id'], dev_set(c), c['terminal_state'], c['verdict'],
                         int(c['h4']['grounded_question']), int(bool(counted))))
    head = provenance([FU / 'h4-runs' / f / 'results.redacted.json' for _, f in DEV_RUNS] + [FU / 'h4-dev/dev.jsonl'],
                      'exploratory (development only, never scored for H4)')
    note = ('counted = grounded question for set A (ambiguous), oracle PASS for set C (controls); one run of 7 per '
            'round; code = HEAD recorded by the run (round 1 ran at 46a5266, which only adds the dev log on top of the guard '
            'commit 5590f41)')
    return render(head, ('run', 'code', 'condition', 'case', 'set', 'terminal_state', 'verdict', 'grounded_question',
                         'counted'), rows, note)


def table_h4_dev_rounds():
    per = collections.OrderedDict()
    for name, folder in DEV_RUNS:
        res = dev_results(folder)
        commit = res['run']['preflight']['commit'][:7]
        a = [c for c in res['results'] if dev_set(c) == 'A']
        c_ = [c for c in res['results'] if dev_set(c) == 'C']
        per[name] = (name, commit, res['run']['condition'], sum(c['h4']['grounded_question'] for c in a), len(a),
                     sum(c['verdict'] == 'PASS' for c in c_), len(c_))
    head = provenance([FU / 'h4-runs' / f / 'results.redacted.json' for _, f in DEV_RUNS],
                      'exploratory (development only, never scored for H4)')
    return render(head, ('run', 'code', 'condition', 'A_asked', 'A_n', 'C_correct', 'C_n'), per.values(),
                  'totals of h4_dev_cases.csv')


# ---------------------------------------------------------------- H8 fault injection
H8 = FU / 'h8'
H8_RUNS = (('run 1', '20261013T211134Z-baseline', 'frozen', None,
            'superseded by Amendment 1 (harness defects); reported, not used'),
           ('baseline-2', '20261018T153000Z-baseline2', 'frozen', None, 'confirmatory (McNemar baseline)'),
           ('hardened', '20261018T154826Z-hardened', 'ARIES_VERIFY_HARDENED=1', 'baseline-2', 'confirmatory'),
           ('sealed set, frozen', '20261018T155010Z-sealed-frozen', 'frozen', None,
            'generalisation check, not a criterion'),
           ('sealed set, hardened', '20261018T154928Z-sealed-hardened', 'ARIES_VERIFY_HARDENED=1', 'sealed set, frozen',
            'generalisation check, not a criterion'),
           ('hardened-23+2', '20261018T155139Z-exploratory-hardened-23plus2',
            'ARIES_VERIFY_HARDENED=1 ARIES_VERIFY_HARDENED_EXTRA=1', 'baseline-2',
            'exploratory (designed after baseline-2; outside the Holm family)'))


def binom_tail_ge(k, n, p):
    from math import comb
    return sum(comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))


def check_ci(what, k, n, ci):
    """Clopper-Pearson, checked from its definition: the binomial tails at the rounded ends straddle 0.025."""
    lo, hi = ci
    if k == 0:
        must_equal(f'{what} lower end', lo, 0.0)
    else:
        must_equal(f'{what} lower end', binom_tail_ge(k, n, lo - 1e-4) < 0.025 < binom_tail_ge(k, n, lo + 1e-4), True)
    if k == n:
        must_equal(f'{what} upper end', hi, 1.0)
    else:
        le = lambda p: 1 - binom_tail_ge(k + 1, n, p)
        must_equal(f'{what} upper end', le(hi + 1e-4) < 0.025 < le(hi - 1e-4), True)


def h8_records(folder):
    return [json.loads(l) for l in (H8 / 'runs' / folder / 'records.jsonl').read_text().splitlines()]


def table_h8():
    runner = hashlib.sha256((H8 / 'run_mutants.py').read_bytes()).hexdigest()
    recs = {name: h8_records(folder) for name, folder, *_ in H8_RUNS}
    rows = []
    for name, folder, verifiers, base, label in H8_RUNS:
        s = read(H8 / 'runs' / folder / 'summary.json')
        meta = read(H8 / 'runs' / folder / 'run.json')
        manifest = ROOT / meta['manifest']
        must_equal(f'{name} manifest sha256', hashlib.sha256(manifest.read_bytes()).hexdigest(), meta['manifest_sha256'])
        must_equal(f'{name} hardened flag recorded', meta['hardened'], verifiers != 'frozen')
        if name != 'run 1':
            must_equal(f'{name} ran the Amendment 1 harness', meta['runner_sha256'], runner)
        mut = [r for r in recs[name] if r['operator'] != 'clean']
        valid = [r for r in mut if not r.get('error') and not r.get('verifier_called_mutated_entry')]
        clean = [r for r in recs[name] if r['operator'] == 'clean' and not r.get('error')]

        def add(metric, group, k=None, n=None, ci=None, value=None, mine=None, theirs=None, with_rate=True):
            if mine is not None:
                must_equal(f'{name} {metric} {group} (records vs summary.json)', mine, theirs)
            if ci is not None:
                check_ci(f'{name} {metric} {group}', k, n, ci)
            rows.append((name, folder, verifiers, label, metric, group, k, n,
                         round(k / n, 4) if with_rate and k is not None and n else None, *(ci or (None, None)), value))

        def rate_rows(metric, sel, theirs):
            add(metric, 'all' if theirs is s['killed_overall'] else sel[0], theirs['k'], theirs['n'], theirs['ci95'],
                mine=(sum(r['killed'] for r in sel[1]), len(sel[1])), theirs=(theirs['k'], theirs['n']))

        rate_rows('killed', ('all', valid), s['killed_overall'])
        for key, field in (('verifier_class', 'kill_rate_by_verifier_class'), ('operator', 'kill_rate_by_operator')):
            for g, v in s[field].items():
                rate_rows(f'killed_by_{key}', (g, [r for r in valid if r[key] == g]), v)
        caps = sorted({r['capability'] for r in valid})
        per = [sum(r['killed'] for r in valid if r['capability'] == c) / sum(r['capability'] == c for r in valid)
               for c in caps]
        add('mean_kill_rate_over_capabilities', f'{len(caps)} capabilities', value=s['mean_kill_rate_over_capabilities'],
            mine=round(sum(per) / len(per), 4), theirs=s['mean_kill_rate_over_capabilities'])
        noop = sorted(r['capability'] for r in valid if r['operator'] == 'noop_success' and not r['killed'])
        add('noop_survivors', 'capabilities', len(noop), None, value=';'.join(noop) or 'none',
            mine=noop, theirs=s['noop_survivors'])
        fa = s['false_alarms']
        add('false_alarms', 'clean replays', fa['k'], fa['n'], fa['ci95'],
            mine=(sum(r['false_alarm'] for r in clean), len(clean)), theirs=(fa['k'], fa['n']))
        for i, key in enumerate(('criterion_1_mean_kill_rate_ge_0_80', 'criterion_2_no_noop_survivor',
                                 'criterion_3_false_alarms_le_2pct'), 1):
            mine = (sum(per) / len(per) >= 0.80, not noop, fa['k'] <= 0.02 * fa['n'])[i - 1]
            add(f'criterion_{i}', key.split('_', 2)[2], value='met' if s[key] else 'not met', mine=mine, theirs=s[key])
        add('survived_false_value_in_evidence', 'secondary', value=s['secondary_survived_with_false_value_in_evidence'],
            mine=sum(bool(r.get('false_value_in_evidence')) for r in valid if not r['killed']),
            theirs=s['secondary_survived_with_false_value_in_evidence'])
        if base:
            old = {r['id']: r for r in recs[base] if r['operator'] != 'clean'}
            pairs = [(old[r['id']], r) for r in valid if r['id'] in old and old[r['id']]['killed'] is not None]
            b = sum(n_['killed'] and not o['killed'] for o, n_ in pairs)
            c = sum(o['killed'] and not n_['killed'] for o, n_ in pairs)
            p = binom_tail_ge(b, b + c, 0.5) if b + c else 1.0
            m = s['primary_mcnemar_vs_baseline']
            must_equal(f'{name} McNemar (records vs summary.json)', (b, c, len(pairs)),
                       (m['b_killed_now_not_before'], m['c_killed_before_not_now'], m['pairs']))
            must_equal(f'{name} McNemar p', abs(p - m['p_one_sided']) <= 1e-12 * max(p, 1e-300), True)
            add('mcnemar_vs', base, b, b + c, value=f'{m["p_one_sided"]:.3g}', with_rate=False)
            add('mcnemar_c', base, c, b + c, with_rate=False)
    head = provenance([H8 / 'runs' / f for _, f, *_ in H8_RUNS] + [H8 / 'mutants.json', H8 / 'sealed/mutants-sealed.json',
                       H8 / 'analyze.py', H8 / 'run_mutants.py', ROOT / 'docs/preregistration/H8-verifier-fault-injection.md'],
                      'hardened vs baseline-2 = confirmatory (Holm family H4b/H5/H6/H8); sealed = generalisation check; '
                      'hardened-23+2 = exploratory; run 1 = superseded')
    note = ('killed = verdict not met or UNVERIFIED, over valid mutants; ci = exact Clopper-Pearson 95%; mean = mean of '
            'per-capability rates; mcnemar_vs: k = b (killed now, not before), n = b + c, value = exact one-sided p; '
            'mcnemar_c: k = c; the sealed set varies the wrong values only, not the targets')
    return render(head, ('run', 'folder', 'verifiers', 'label', 'metric', 'group', 'k', 'n', 'rate', 'ci_lo', 'ci_hi',
                         'value'), rows, note)


# ---------------------------------------------------------------- H6
H6_RUNS = (('qwen2.5:7b', FU / 'h6-run', 'run_router_h6.py', 'confirmatory (Holm family H4b/H5/H6/H8)'),)
H6_FIXTURE = FU / 'h6-items/h6_requests.jsonl'
H6_FIXTURE_SHA = '3068dd8d9b41b58987e6d2270b66629389c8b3b40937502ce9462b9ffce35348'


def cp_end(k, n, which):
    """A Clopper-Pearson 95% end by bisection on binomial_tail_ge, independent of the analysis' beta_ppf."""
    if which == 'lo' and k == 0:
        return 0.0
    if which == 'hi' and k == n:
        return 1.0
    f = (lambda p: binom_tail_ge(k, n, p) - 0.025) if which == 'lo' else (lambda p: binom_tail_ge(k + 1, n, p) - 0.975)
    a, z = 0.0, 1.0
    for _ in range(80):
        mid = (a + z) / 2
        a, z = (mid, z) if f(mid) < 0 else (a, mid)
    return (a + z) / 2


def table_h6():
    A = load_module('analyze_router', FROZEN / 'analyze_router.py')
    must_equal('H6 fixture is the Amendment 2 file', hashlib.sha256(H6_FIXTURE.read_bytes()).hexdigest(), H6_FIXTURE_SHA)
    items = {r['id']: r for r in (json.loads(l) for l in H6_FIXTURE.read_text().splitlines() if l.strip())}
    rows, sources = [], []
    for model, folder, runner, label in H6_RUNS:
        s = read(folder / 'summary.json')
        protocol = read(folder / 'protocol.json')
        must_equal(f'{model} analysis checks all passed', all(s['checks'].values()), True)
        must_equal(f'{model} model', protocol['model']['name'], model)
        must_equal(f'{model} runner unchanged', hashlib.sha256((folder / runner).read_bytes()).hexdigest(),
                   protocol['hashes']['runner'])
        raw = {(arm, rep): [json.loads(l) for l in (folder / 'raw' / f'r{rep}-{arm}.jsonl').read_text().splitlines()]
               for arm in ('A0', 'A1') for rep in (1, 2, 3)}
        for v in raw.values():
            must_equal(f'{model} cell covers the fixture once', sorted(r['id'] for r in v), sorted(items))
        right = {(arm, rep, r['id']): A.correct(r) for (arm, rep), v in raw.items() for r in v}
        major = {arm: {i: sum(right[(arm, rep, i)] for rep in (1, 2, 3)) >= 2 for i in items} for arm in ('A0', 'A1')}

        def add(arm, metric, group, k=None, n=None, ci=None, value=None, mine=None, theirs=None):
            if mine is not None:
                must_equal(f'{model} {arm} {metric} {group} (raw vs summary.json)', mine, theirs)
            if ci is not None:
                check_ci(f'{model} {arm} {metric} {group}', k, n, ci)
            rows.append((model, label, arm, metric, group, k, n, round(k / n, 4) if k is not None and n else None,
                         *(ci or (None, None)), value))

        def rate_row(arm, metric, group, published, k, n):
            add(arm, metric, group, published['k'], published['n'], published['ci95'], mine=(k, n),
                theirs=(published['k'], published['n']))

        pr = s['primary']
        n = len(items)
        for arm in ('A0', 'A1'):
            rate_row(arm, 'binary_majority_of_3', 'all', pr['majority_accuracy'][arm], sum(major[arm].values()), n)
        b = sum(major['A1'][i] and not major['A0'][i] for i in items)
        c = sum(major['A0'][i] and not major['A1'][i] for i in items)
        p = binom_tail_ge(b, b + c, 0.5) if b + c else 1.0
        must_equal(f'{model} McNemar (raw vs summary.json)', (b, c), (pr['b_A1_right_A0_wrong'], pr['c_A0_right_A1_wrong']))
        must_equal(f'{model} McNemar p', abs(p - pr['p_one_sided_exact']) <= 1e-12 * max(p, 1e-300), True)
        add('A1 vs A0', 'mcnemar_b_A1_only', 'requests', b, b + c, value=f'{p:.3g}')
        add('A1 vs A0', 'mcnemar_c_A0_only', 'requests', c, b + c)
        m = b + c
        ends = (cp_end(b, m, 'lo'), cp_end(b, m, 'hi'))                  # Clopper-Pearson for b / m, from the tails
        mine = [round(m / n * (2 * e - 1), 4) for e in ends]
        must_equal(f'{model} difference', round((b - c) / n, 4), pr['accuracy_difference_A1_minus_A0'])
        must_equal(f'{model} paired difference interval', mine, pr['accuracy_difference_ci95_paired_exact'])
        rows.append((model, label, 'A1 vs A0', 'difference_A1_minus_A0', 'majority_of_3', None, None,
                     pr['accuracy_difference_A1_minus_A0'], *mine, None))
        for arm in ('A0', 'A1'):
            sec = s['secondary'][arm]
            pooled = [r for rep in (1, 2, 3) for r in raw[(arm, rep)]]
            rate_row(arm, 'binary_pooled', 'all', sec['binary_pooled'], sum(map(A.correct, pooled)), len(pooled))
            for k_ in ('actionable', 'ambiguous', 'out_of_scope', 'unsafe'):
                ids = [i for i in items if items[i]['klass'] == k_]
                rate_row(arm, 'binary_majority_of_3', k_, sec['binary_by_class_majority'][k_],
                         sum(major[arm][i] for i in ids), len(ids))
            for lang in ('en', 'mk'):
                sel = [r for r in pooled if r['lang'] == lang]
                rate_row(arm, 'binary_pooled', 'lang ' + lang, sec['by_language_binary_pooled'][lang],
                         sum(map(A.correct, sel)), len(sel))
            nonaction = [r for r in pooled if r['klass'] != 'actionable']
            asked = [r for r in pooled if A.valid(r) and r['intent'] in ('ASK', 'OUT_OF_SCOPE')]
            rate_row(arm, 'abstention_precision', 'ASK or OUT_OF_SCOPE', sec['abstention_precision'],
                     sum(r['klass'] != 'actionable' for r in asked), len(asked))
            rate_row(arm, 'abstention_recall', 'nonaction requests', sec['abstention_recall'],
                     sum(A.valid(r) and r['intent'] in ('ASK', 'OUT_OF_SCOPE') for r in nonaction), len(nonaction))
            held = [r for r in pooled if r['klass'] == 'actionable' and A.valid(r) and r['intent'] in A.HOLD]
            rate_row(arm, 'over_abstention', 'actionable held', sec['over_abstention_actionable_held'], len(held),
                     sum(r['klass'] == 'actionable' for r in pooled))
            add(arm, 'errors', 'pooled', value=sec['errors'], mine=sum(bool(r.get('error')) for r in pooled),
                theirs=sec['errors'])
        sources += [folder / 'summary.json', folder / 'raw', folder / 'protocol.json', folder / runner]
    head = provenance(sources + [H6_FIXTURE, FROZEN / 'analyze_router.py', FU / 'h6-run/analyze_h6.py',
                                 ROOT / 'docs/preregistration/H6-abstention-replication.md'],
                      '; '.join(f'{m} = {lab}' for m, _, _, lab in H6_RUNS))
    note = ('correct = frozen analyze_router.correct(); majority_of_3 = per request, at least 2 of 3 repetitions correct; '
            'ci = exact Clopper-Pearson 95%; mcnemar_b_A1_only: k = b, n = b + c, value = exact one-sided p; '
            'difference ci = exact paired interval conditional on the discordant requests; '
            'requests written by OpenAI Codex (gpt-6-astra), not a person')
    return render(head, ('model', 'label', 'arm', 'metric', 'group', 'k', 'n', 'rate', 'ci_lo', 'ci_hi', 'value'),
                  rows, note)


TABLES = {
    'router_arms.csv': table_router_arms,
    'router_by_class.csv': table_router_by_class,
    'router_tests.csv': table_router_tests,
    'verifiers_ledger.csv': table_verifiers,
    'heldout_by_class.csv': table_heldout,
    'terminal_end_paths.csv': table_end_paths,
    'contract_coverage.csv': table_contract_coverage,
    'planner_runs.csv': table_planner,
    'h4_dev_cases.csv': table_h4_dev,
    'h4_dev_rounds.csv': table_h4_dev_rounds,
    'h8_fault_injection.csv': table_h8,
    'h6_abstention.csv': table_h6,
}


def main():
    write = '--write' in sys.argv[1:]
    failures = 0
    for name, build in TABLES.items():
        try:
            text = build()
        except Mismatch as exc:
            print(f'FAIL  {name}: sources disagree: {exc}')
            failures += 1
            continue
        path = HERE / name
        if write:
            path.write_text(text)
            print(f'WROTE {name}  ({text.count(chr(10))} lines)')
        elif not path.exists():
            print(f'FAIL  {name}: missing')
            failures += 1
        elif path.read_text() != text:
            old, new = path.read_text().splitlines(), text.splitlines()
            first = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
            print(f'FAIL  {name}: differs from its sources at line {first + 1}')
            failures += 1
        else:
            print(f'OK    {name}')
    print(f'{len(TABLES) - failures}/{len(TABLES)} tables {"written" if write else "match their sources"}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
