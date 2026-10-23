#!/usr/bin/env python3
"""HAL1 (docs/preregistration/HAL1-hallucination-measures.md): model-level hallucinations and what ARIES let
through. Written before any HAL1 measure was computed. Descriptive.

    hallucination_eval.py   ->  hallucination-summary.json (counts and rates only; no item or request text)

Reads local run folders (records/*.json, results.json, run.json) of H5, H4b and X1, and the R1/R1b raw router
and planner files. A model decision is a planner decision with no `source` (code-made decisions, such as the
contract finish or the clarify resolver's listing, carry one)."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN = HERE.parents[1]
LIVE = Path.home() / 'aries'
FU_LIVE = LIVE / 'experiments/thesis-followup-20261012'
sys.path.insert(0, str(MAIN / 'experiments/thesis-r1-real-data'))
from analyze_r1 import rate  # noqa: E402  (Clopper-Pearson 95%)
from common import OOS, canonical  # noqa: E402

PATH = re.compile(r'(?<![\w/~])(~?/[^\s"\'`<>]+)')
TRAILING = '.,;:!?)"\''


def kind_of(error):
    msg = json.dumps(error)
    for needle, kind in (('string_pattern_mismatch', 'invented value in the wrong format (e.g. a made-up SHA-256)'),
                         ('Field required', 'missing required argument'), ('Extra inputs', 'argument the capability does not have'),
                         ('Unknown capability', 'capability that does not exist'), ('not registered', 'capability that does not exist'),
                         ('Capability required', 'execute without a capability'), ('JSON', 'malformed output'),
                         ('Invalid local decision', 'malformed output'),
                         ('Terminal decisions cannot carry', 'terminal decision with arguments')):
        if needle in msg:
            return kind
    return 'other validation error'


def run_folders(*globs):
    out = []
    for root, pattern in globs:
        for f in sorted(Path(root).glob(pattern)):
            if 'pilot' in f.name or not (f / 'results.json').exists() or not (f / 'records').exists():
                continue
            out.append(f)
    return out


def goal_measures(folder, study):
    run = json.loads((folder / 'results.json').read_text())
    cond = run['run']['condition']
    c = Counter()
    for rec_path in (folder / 'records').glob('*.json'):
        rec = json.loads(rec_path.read_text())
        agent = rec.get('agent')
        if not agent:
            c['records_without_agent'] += 1
            continue
        evidence_ids = {e.get('evidence_id') for e in rec.get('evidence', [])}
        verified_any = any(e.get('verified') for e in rec.get('evidence', []))
        grounded = json.dumps([agent.get('request', '')] + [[s.get('args'), s.get('observation'), s.get('result')]
                                                            for s in rec.get('steps', [])], ensure_ascii=False)
        for d in agent.get('decisions', []):
            if d.get('source'):
                c['code_decisions'] += 1
                continue
            c['model_decisions'] += 1
            if not d.get('valid'):
                c['M1_invalid'] += 1
                c['M1_kind: ' + kind_of(d.get('error'))] += 1
                continue
            dec = d.get('decision') or {}
            if dec.get('action') == 'finish':
                c['finish_model'] += 1
                if any(ref not in evidence_ids for ref in dec.get('evidence_refs') or []):
                    c['M2_invented_evidence'] += 1
                if not verified_any:
                    c['M3_finish_without_verified_evidence'] += 1
            if dec.get('action') in ('finish', 'fail'):
                paths = [p.rstrip(TRAILING) for p in PATH.findall((dec.get('summary') or '') + ' ' + (dec.get('reason') or ''))]
                if paths:
                    c['terminal_with_path'] += 1
                    if any(p not in grounded and p.rstrip('/') not in grounded for p in paths):
                        c['M4_ungrounded_path'] += 1
        checks = agent.get('completion_checks') or []
        c['finish_checked'] += len(checks)
        c['S2_finish_rejected'] += sum(not x.get('met') for x in checks)
        c['goal_runs'] += 1
        state = rec.get('state')
        text = ' '.join(card.get('text', '') for card in rec.get('cards', []))
        c['S3_model_prose_marked'] += 'MODEL CLAIM' in text
        c['S3_done_or_answered'] += state in ('done', 'answered')
    for x in run['results']:
        if 'terminal_state' not in x:
            continue
        c['outcomes'] += 1
        if study == 'h5':
            # Amendment (2026-10-22, before the final computation): false done is over G and N item-runs, as in H5;
            # the first version divided by every outcome, held-out goals included.
            c['outcomes_G_N'] += x.get('set') in ('G', 'N')
            c['heldout_outcomes'] += x.get('set') == 'heldout'
            c['S1_false_done'] += bool((x.get('h5') or {}).get('false_done'))
            c['S1_done_heldout_fail'] += x.get('set') == 'heldout' and x['terminal_state'] == 'done' and x.get('verdict') != 'PASS'
            c['done'] += x['terminal_state'] == 'done'
        else:
            c['S1_twin_wrong_file_done'] += x.get('kind') == 'twin' and x['terminal_state'] == 'done' and x.get('verdict') != 'PASS'
            c['done'] += x['terminal_state'] == 'done'
    return cond, c


def router_m5(raw_files, gold):
    c = Counter()
    for name, path, acts_key in raw_files:
        if not path.exists():
            c[f'missing: {name}'] += 1
            continue
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if 'id' not in r or r['id'] not in gold or gold[r['id']] != OOS:
                continue
            route = r.get('route', r)
            acts = acts_key(r)
            c[f'{name}: gold_oos'] += 1
            c[f'{name}: acts'] += acts
            c[f'{name}: acts_conf_ge_0.9'] += acts and (route.get('confidence') or 0) >= 0.9
    return c


def planner_m1(path, error_key):
    c = Counter()
    if not path.exists():
        return {'missing': str(path)}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if 'id' not in r:
            continue
        called = error_key in r or 'decision' in r or 'raw_output' in r
        if not called:
            continue
        c['planner_calls'] += 1
        if r.get(error_key):
            c['invalid'] += 1
            c['kind: ' + kind_of(r[error_key])] += 1
    return {'invalid': rate(c['invalid'], c['planner_calls']), 'by_kind': {k[6:]: v for k, v in c.items() if k.startswith('kind: ')}}


def summarise(c):
    return {
        'model_level': {
            'M1_invented_action': rate(c['M1_invalid'], c['model_decisions']),
            'M1_by_kind': {k[9:]: v for k, v in c.items() if k.startswith('M1_kind: ')},
            'M2_invented_evidence': rate(c['M2_invented_evidence'], c['finish_model']),
            'M3_finish_without_verified_evidence': rate(c['M3_finish_without_verified_evidence'], c['finish_model']),
            'M4_ungrounded_path_in_claim': rate(c['M4_ungrounded_path'], c['terminal_with_path'])},
        'system_level': {
            'S1_false_done_G_N': rate(c['S1_false_done'], c['outcomes_G_N']) if 'S1_false_done' in c else None,
            'S1_done_on_failed_heldout': rate(c['S1_done_heldout_fail'], c['heldout_outcomes']) if 'S1_false_done' in c else None,
            'S1_twin_done_on_wrong_file': c.get('S1_twin_wrong_file_done'),
            'S2_finish_rejected_by_check': rate(c['S2_finish_rejected'], c['finish_checked']),
            'S3_final_text_with_model_prose_marked': rate(c['S3_model_prose_marked'], c['goal_runs']),
            'done_runs': rate(c['done'], c['outcomes'])},
        'counts': {k: v for k, v in sorted(c.items()) if not k.startswith(('M1_kind', ))}}


def main():
    dest = HERE / 'hallucination-summary.json'
    if dest.exists():
        raise SystemExit('REFUSED: hallucination-summary.json exists')
    out = {'label': 'HAL1, descriptive', 'agent_runs': {}, 'router_M5': {}, 'planner_M1_public': {}}
    groups = defaultdict(Counter)
    sources = {'h5': run_folders((FU_LIVE / 'h5-runs', '2026*'), (HERE / 'h5-reruns', '2026*')),
               'h4b': run_folders((FU_LIVE / 'h4b-runs', '2026*'), (HERE / 'h4b-reruns', '2026*'))}
    for study, folders in sources.items():
        for f in folders:
            cond, c = goal_measures(f, study)
            groups[f'{study}:{cond}'].update(c)
            groups[f'{study}:{cond}']['runs'] += 1
    out['agent_runs'] = {k: summarise(v) | {'runs': v['runs']} for k, v in sorted(groups.items())}

    r1 = MAIN / 'experiments/thesis-r1-real-data'
    r1b = MAIN / 'experiments/thesis-r1b'
    nb1 = {k: canonical(v) for k, v in json.loads((r1 / 'labels/nl2bash-final.json').read_text())['labels'].items()}
    cl1 = {r['id']: r['gold_label'] for r in json.loads((r1 / 'clinc-sample-manifest.json').read_text())['sample']}
    from run_r1 import router_acts
    frozen_acts = router_acts
    raw1 = LIVE / 'experiments/thesis-r1-real-data/raw'
    out['router_M5']['R1'] = dict(router_m5(
        [('nl2bash frozen A1', raw1 / 'router-qwen2_5_7b-A1-nl2bash-test.jsonl', frozen_acts),
         ('clinc frozen A1', raw1 / 'router-qwen2_5_7b-A1-clinc.jsonl', frozen_acts),
         ('clinc frozen A0', raw1 / 'router-qwen2_5_7b-A0-clinc.jsonl', frozen_acts)], {**nb1, **cl1}))
    out['planner_M1_public']['R1 frozen planner, NL2Bash'] = planner_m1(raw1 / 'planner-qwen2_5_7b-nl2bash-test.jsonl', 'error')
    if (r1b / 'labels/nl2bash-final.json').exists():
        nb2 = {k: canonical(v) for k, v in json.loads((r1b / 'labels/nl2bash-final.json').read_text())['labels'].items()}
        cl2 = {r['id']: r['gold_label'] for r in json.loads((r1b / 'clinc-sample-manifest.json').read_text())['sample']}
        raw2 = r1b / 'raw'
        current = lambda r: bool(r.get('acts'))  # noqa: E731
        files = [('nl2bash frozen A1', raw2 / 'router-qwen2_5_7b-A1-nl2bash-r1b.jsonl', frozen_acts),
                 ('clinc frozen A1', raw2 / 'router-qwen2_5_7b-A1-clinc-r1b.jsonl', frozen_acts)]
        for cfg in ('C1', 'C0', 'G', 'S', 'C3'):
            files += [(f'nl2bash {cfg}', raw2 / f'aries-{cfg}-qwen2_5_7b-nl2bash-r1b.jsonl', current),
                      (f'clinc {cfg}', raw2 / f'aries-{cfg}-qwen2_5_7b-clinc-r1b.jsonl', current)]
            out['planner_M1_public'][f'R1b {cfg}, NL2Bash'] = planner_m1(raw2 / f'aries-{cfg}-qwen2_5_7b-nl2bash-r1b.jsonl', 'planner_error')
        out['planner_M1_public']['R1b frozen planner, NL2Bash'] = planner_m1(raw2 / 'planner-qwen2_5_7b-nl2bash-r1b.jsonl', 'error')
        out['router_M5']['R1b'] = dict(router_m5(files, {**nb2, **cl2}))
    for block in out['router_M5'].values():
        for name in sorted({k.split(': ')[0] for k in block if ': ' in k and not k.startswith('missing')}):
            block[f'{name}: M5 confident wrong action'] = rate(block.get(f'{name}: acts_conf_ge_0.9', 0), block[f'{name}: gold_oos'])
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(out, indent=1)[:6000])


if __name__ == '__main__':
    main()
