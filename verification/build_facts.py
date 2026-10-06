#!/usr/bin/env python3
"""Derive document facts only from SHA-256 checked frozen evidence.

No ARIES imports, database, models, services, shell commands, or live measurements.
Changing evidence requires a new audited snapshot, never --refreeze against runtime.
"""
from __future__ import annotations
import collections
import copy
import hashlib
import json
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / 'data/snapshot'
OUT = HERE / 'data/facts.json'
HOLD = {'ASK', 'OUT_OF_SCOPE'}
NON_ACTION = HOLD | {'UNKNOWN'}
OOD_ARMS = (
    ('baseline', 'A0 основа, без речник за одбивање'),
    ('with-abstention', 'A1 + речник за одбивање'),
    ('with-capability-surface', 'A2 + површина на способности'),
    ('with-machine-limits', 'A3 + измерени лимити на машината'),
)
SUITE = 'eval/agent_suite/20261004T095522Z-B8-final-full/results.json'
ACC = 'experiments/product/independent-acceptance/'
AUDIT = 'experiments/document-review/20261006/'


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Evidence:
    """Verify every frozen byte before deriving facts or replacing output."""
    def __init__(self, directory):
        self.directory = directory
        manifest_bytes = (directory / 'manifest.json').read_bytes()
        self.manifest = json.loads(manifest_bytes)
        self.manifest_sha256 = digest(manifest_bytes)
        if self.manifest.get('schema_version') != 1:
            raise ValueError('Unsupported frozen evidence manifest schema')
        if self.manifest.get('snapshot_id') != 'ARIES-DOC-20261006':
            raise ValueError('Unexpected snapshot ID; audit the new snapshot explicitly')
        self.contents = {}
        for relative, entry in sorted(self.manifest['files'].items()):
            path = directory / relative
            if not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError(f'Manifest path escapes frozen bundle: {relative}')
            data = path.read_bytes()
            if digest(data) != entry['sha256'] or len(data) != entry['bytes']:
                raise ValueError(f'Frozen evidence integrity mismatch: {relative}')
            self.contents[relative] = data

    def read(self, relative):
        if relative not in self.contents:
            raise ValueError(f'Unmanifested evidence: {relative}')
        return json.loads(self.contents[relative])

    def raw(self, original_path):
        return self.read('raw/' + original_path)

    def provenance(self, relative):
        return {'bundle_file': 'verification/snapshot/' + relative,
                'sha256': self.manifest['files'][relative]['sha256'],
                'original_source': self.manifest['files'][relative]['source']}


def ratio(k, n, places=4):
    return {'k': k, 'n': n, 'value': round(k / n, places) if n else None}


def wilson(k, n, z=1.96):
    if not n:
        return None
    p, divisor = k / n, 1 + z * z / n
    center = (p + z * z / (2 * n)) / divisor
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / divisor
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def router(evidence, path, label):
    all_rows = evidence.raw(path)['results']
    rows = [r for r in all_rows if 'intent' in r]
    act = [r for r in rows if r['klass'] == 'actionable']
    hold = [r for r in rows if r['klass'] != 'actionable']
    oos = [r for r in rows if r['klass'] == 'out_of_scope']
    abst = [r for r in rows if r['intent'] in HOLD]
    correct = (sum(r['intent'] not in NON_ACTION for r in act)
               + sum(r['intent'] in NON_ACTION for r in hold))
    return {
        'arm': label, 'n': len(rows), 'raw_file': path,
        'provenance': evidence.provenance('raw/' + path),
        'total_rows': len(all_rows), 'scored_rows': len(rows),
        'excluded_error_rows': len(all_rows) - len(rows),
        'class_counts': dict(collections.Counter(r['klass'] for r in all_rows)),
        'accuracy': ratio(correct, len(rows)),
        'oos_abstention': ratio(sum(r['intent'] in HOLD for r in oos), len(oos)),
        'abstention_precision': ratio(sum(r['klass'] != 'actionable' for r in abst), len(abst)) if abst else None,
        'false_holds': ratio(sum(r['intent'] in HOLD for r in act), len(act)),
        'unknown_by_class': dict(collections.Counter(r['klass'] for r in rows if r['intent'] == 'UNKNOWN')),
    }


def confidence(evidence, path):
    rows = [r for r in evidence.raw(path)['results'] if 'intent' in r]
    act = [r for r in rows if r['klass'] == 'actionable']
    hold = [r for r in rows if r['klass'] != 'actionable']
    positive = [float(r['confidence']) for r in act]
    negative = [float(r['confidence']) for r in hold]
    wins = sum(x > y for x in positive for y in negative)
    ties = sum(x == y for x in positive for y in negative)
    pairs = len(positive) * len(negative)
    return {
        'raw_file': path, 'provenance': evidence.provenance('raw/' + path),
        'auc': (wins + ties / 2) / pairs if pairs else None,
        'auc_method': 'P(confidence_actionable > confidence_should_hold) + 0.5 * P(tie)',
        'positive_class': 'actionable', 'wins': wins, 'ties': ties, 'pairs': pairs,
        'mean_confidence_should_act': round(statistics.mean(positive), 3),
        'mean_confidence_should_hold': round(statistics.mean(negative), 3),
        'unknown_on_should_act': ratio(sum(r['intent'] == 'UNKNOWN' for r in act), len(act)),
        'unknown_on_should_hold': ratio(sum(r['intent'] == 'UNKNOWN' for r in hold), len(hold)),
        'abstentions_without_the_vocabulary': sum(r['intent'] in HOLD for r in rows),
    }


def baseline(arm):
    n, act = arm['n'], arm['false_holds']['n']
    return {'n': n, 'actionable': act, 'should_hold': n - act,
            'refuse_everything': ratio(n - act, n), 'act_on_everything': ratio(act, n)}


def build(e):
    base = e.read('base-facts.json')
    f = copy.deepcopy(base)
    frozen, m = e.read('ledger-frozen.json'), e.manifest
    f['generated_by'] = 'verification/build_facts.py (offline frozen evidence derivation)'
    # Preserve the legacy key without pretending it was a ledger measurement time.
    f['snapshot_utc'] = m['historical_facts_generated_at']
    f['snapshot_frozen_at'] = 'точниот првичен датум на замрзнување не е запишан'
    f['snapshot'] = {
        'id': m['snapshot_id'], 'bundle_assembled_at': m['bundle_assembled_at'],
        'historical_facts_generated_at': m['historical_facts_generated_at'],
        'historical_facts_commit': m['historical_facts_commit'],
        'ledger_measured_at': m['ledger_measured_at'],
        'ledger_measurement_note': m['ledger_measurement_note'],
        'manifest_file': 'verification/snapshot/manifest.json',
        'manifest_sha256': e.manifest_sha256, 'ledger': e.provenance('ledger-frozen.json'),
        'verified_artifact_count': len(e.contents), 'live_measurement_performed': False,
    }
    f['volatility_note'] = (
        'Овој документ користи само замрзнат пакет ARIES-DOC-20261006 со SHA-256 проверки. '
        'Повторно градење не чита жив регистар, база, знаменца или сервиси. Датумот на '
        'составување на пакетот не е датум на историското мерење; точниот датум на '
        'замрзнување на дневникот недостасува.')
    f['rule'] = 'Document numbers derive from identified frozen evidence; inherited claims retain their original limitations.'
    f['system'] = copy.deepcopy(frozen['system'])
    f['system']['provenance'] = e.provenance('ledger-frozen.json')
    f['system']['volatility'] = (
        'Историски пребројувања задржани од замрзнатиот агрегат; не се повторно измерени '
        'при градењето и не ја опишуваат нужно тековната инсталација.')

    ab = f['abstention']
    ab['ablation_ood'] = [router(e, f'experiments/router-ood/{name}.json', label) for name, label in OOD_ARMS]
    ab['english_fixture'] = [router(e, f'experiments/router-en/B8-abstain-{name}.json', label)
                              for name, label in (('off', 'исклучено'), ('on', 'вклучено'))]
    ab['metric_definition'] = {
        'acted': 'intent not in {ASK, OUT_OF_SCOPE, UNKNOWN}',
        'binary_accuracy': 'Correct action decisions on actionable + non-action decisions on other classes, divided by scored rows.',
        'explicit_refusal': 'ASK or OUT_OF_SCOPE only',
        'unknown': 'Non-action for binary accuracy: correct on should-hold and incorrect on actionable. Never an explicit refusal.',
        'error_policy': 'Historical missing-intent rows are excluded and counted separately; all six published arms have zero excluded errors. Errors are not relabeled UNKNOWN or credited as refusals.',
        'scope': 'Router intent decisions, not observed effects or whole-system success.',
        'rescoring_note': 'The original OOD runner used a different UNKNOWN accuracy convention. All six document arms are re-scored from preserved raw rows with the binary definition above, matching the executable English score.py calculation.',
    }
    ab['fixture_composition'] = {
        'router_ood': ab['ablation_ood'][0]['class_counts'],
        'router_en': ab['english_fixture'][0]['class_counts'],
        'note': 'router-ood names a 225-request package; only 40 requests have the out_of_scope label.',
    }
    en_conf = confidence(e, 'experiments/router-en/B8-abstain-off.json')
    ood_conf = confidence(e, 'experiments/router-ood/baseline.json')
    ab['confidence_is_not_the_signal'] = {
        **en_conf, 'auc': round(en_conf['auc'], 3), 'auc_exact': en_conf['auc'],
        'auc_source': en_conf['raw_file'],
        'correction': 'The old 0.642 value belonged to the OOD baseline, not these English confidence means. English AUC is 0.7251923077.',
        'interpretation': 'Confidence has ranking information in this fixture; AUC alone does not establish a useful threshold or justify declaring all thresholds unusable.',
    }
    ab['confidence_by_fixture'] = {'router_en_off': en_conf, 'router_ood_baseline': ood_conf}
    ab['trivial_baselines'] = {
        'ood_fixture': baseline(ab['ablation_ood'][0]),
        'english_fixture': baseline(ab['english_fixture'][0]),
        'why': base['abstention']['trivial_baselines']['why'],
    }

    suite = e.raw(SUITE)
    rows = suite['goals']
    categories = collections.defaultdict(collections.Counter)
    for r in rows:
        categories[r['category']][r['outcome']] += 1
    f['execution_suite'] = {
        'raw_file': SUITE, 'provenance': e.provenance('raw/' + SUITE),
        'fixture_sha256': suite['fixture_sha256'], 'n': len(rows), 'runs_per_goal': 1,
        'started_at': suite['started_at'], 'finished_at': suite['finished_at'],
        'by_category': {k: dict(v) for k, v in sorted(categories.items())},
        'totals': dict(collections.Counter(r['outcome'] for r in rows)),
        'by_surface': {s: {'n': sum(r['surface'] == s for r in rows),
                          'outcomes': dict(collections.Counter(r['outcome'] for r in rows if r['surface'] == s))}
                       for s in sorted({r['surface'] for r in rows})},
        'original_labels_preserved': True,
        'case_disagreements': [r for r in rows if r['outcome'] == 'false_success'],
        'case_audit': e.raw(AUDIT + 'metrics-audit.json')['execution_suite']['case_disagreements'],
        'historical_case_evidence': e.provenance('raw/' + AUDIT + 'historical-goal-extracts.json'),
        'runtime_changed': suite['runtime_changed'],
        'changed_source_paths': [p for p, old in suite['source_hashes_start'].items() if suite['source_hashes_end'].get(p) != old],
        'core_invocation_unchanged': suite['core_invocation_start'] == suite['core_invocation_end'],
        'requested_flags_applied_to_api_surface': suite['flags']['applied_to_api_surface'],
        'voice_included': False,
        'scope': '75 text HTTP cases exercise service routing/execution, not always an LLM planner. 15 direct capability fault cases run inside the harness process and do not test the agent loop. No spoken turns.',
        'limitations': [
            'One run per case; original 88 pass / 0 fail / 2 false_success labels are historical oracle outputs, not 90 successful task completions.',
            'system_capabilities.py changed during the run. Core invocation stayed the same; the source condition was not fully frozen.',
            'Requested flag settings were not applied to the HTTP service; this is not a controlled HTTP flag ablation.',
            'Historical no-microphone wording is not a confirmed hardware fact; only voice exclusion is established by this protocol.',
        ],
    }

    v = f['verification'] = copy.deepcopy(frozen['verification'])
    cls = e.raw(ACC + 'raw/review_verifier_integrity.json')
    counts = collections.Counter(r['verifier_class'] for r in cls['capabilities'])
    v['classification'] = {name: counts[name] for name in frozen['verification']['classification']}
    kinds = collections.Counter(r['evidence_kind'] for r in cls['capabilities'])
    v['classification_provenance'] = e.provenance('raw/' + ACC + 'raw/review_verifier_integrity.json')
    v['classification_evidence'] = {
        'total': len(cls['capabilities']), 'by_kind': dict(kinds),
        'source_only': [r['name'] for r in cls['capabilities'] if r['evidence_kind'] == 'source'],
        'recorded_method': cls['method'],
        'correction': 'Per-capability entries count 57 executed and 1 source-only. The original narrative count 56/58 is stale; executed checks include synthetic inputs and substituted collaborators.',
    }
    v['classification_method'] = (
        'Historical second-AI source review of all 58 registry verifiers; per-entry inventory: '
        '57 executed with synthetic inputs or substituted collaborators and 1 source-only '
        '(desktop.launch). These are not 57 full unmocked integration tests; the classification '
        'is historical and is not re-measured on current code.')
    ledger = v['ledger']
    status = ledger['steps_by_status']
    reached = status['verified'] + status['verification_failed']
    if sum(x['total'] for x in ledger['by_class'].values()) != reached:
        raise ValueError('Frozen ledger class totals disagree with verifier denominator')
    ledger['reached_a_verifier'] = ratio(reached, ledger['steps'])
    ledger['contradictions'] = {**ratio(status['verification_failed'], reached, 5),
                               'wilson_95': wilson(status['verification_failed'], reached)}
    ledger['provenance'] = e.provenance('ledger-frozen.json')
    ledger['measurement_scope'] = 'Historical stored statuses; reaching a verifier does not prove its verdict is independent.'
    per = ledger['by_class']
    reg_total = sum(x['total'] for name, x in per.items() if name != 'OUTSIDE_REGISTRY')
    independent = per['INDEPENDENT']['total']
    measured = f['measured_by_review']
    measured['registry_path_only'] = {
        'verified_or_contradicted': reg_total, 'independent': independent,
        'share_independent': round(independent / reg_total, 4),
        'unfalsifiable': sum(per[name]['total'] for name in ('TRIVIAL', 'SELF_REPORT')),
        'note': 'Derived from the same frozen ledger, not a newer live DB. OUTSIDE_REGISTRY legacy steps are unclassified.',
        'provenance': e.provenance('ledger-frozen.json'),
    }
    review = e.raw(ACC + 'findings.json')
    f['independent_review'].update({
        'findings': sum(r['id'].startswith('F-') for r in review['findings']),
        'refuted_hypotheses': sum(r['id'].startswith('N-') for r in review['findings']),
        'corrections_to_our_own_claims': sum(r['id'].startswith('C-') for r in review['findings']),
        'provenance': e.provenance('raw/' + ACC + 'findings.json'),
        'reviewer_type': 'Second AI agent in a separate working environment; not external human peer review.',
    })
    for field, name in (('scope_attacks', 'scopes_adversarial'), ('budget_concurrency', 'budgets_concurrent')):
        path = ACC + 'raw/' + name + '.json'
        raw = e.raw(path)
        measured[field].update({'passed': raw['passed'], 'n': raw['n'], 'provenance': e.provenance('raw/' + path)})
    corrected = measured['fault_injected_corrected_baseline']
    corrected['runs'] = {}
    for run, name in (('20261003T224608Z-B1c-off-inhibited', 'B1c'), ('20261003T225302Z-B2c-on-inhibited', 'B2c')):
        path = f'eval/agent_suite/{run}/results.json'
        fault_rows = [r for r in e.raw(path)['goals'] if r['category'] == 'fault_injected']
        corrected['runs'][name] = {'pass': sum(r['outcome'] == 'pass' for r in fault_rows),
                                   'n': len(fault_rows), 'provenance': e.provenance('raw/' + path)}
    corrected['final'] = {'pass': categories['fault_injected']['pass'], 'n': sum(categories['fault_injected'].values())}

    f['provenance'] = {
        'recomputed_from_frozen_raw': ['abstention', 'execution_suite', 'verification.classification',
                                     'independent_review.findings', 'measured_by_review.scope_attacks',
                                     'measured_by_review.budget_concurrency', 'measured_by_review.fault_injected_corrected_baseline'],
        'derived_from_frozen_aggregate': ['verification.ledger', 'measured_by_review.registry_path_only'],
        'carried_forward': {
            'source': e.provenance('base-facts.json'),
            'fields': ['speech', 'claims_found_in_source', 'post_snapshot_repairs', 'post_snapshot_note',
                       'independent_review.fixture', 'measured_by_review.oracle_validation_before',
                       'measured_by_review.oracle_validation_after'],
            'meaning': 'Existing documented values preserved, not re-measured or independently reproduced by this rebuild. Speech claims need their own acoustic raw evidence for stronger conclusions. Fixture summary is carried forward; held-out cases were not read or rerun.',
        },
        'system_counts': {'source': e.provenance('ledger-frozen.json'), 'meaning': 'Historical inventory, not a live machine inspection.'},
        'audit': e.provenance('raw/' + AUDIT + 'metrics-audit.json'),
    }
    f['speech']['provenance_status'] = 'Carried from archived base facts; separate from the HTTP/capability suite and not re-measured in this correction.'
    f['post_snapshot_note'] = (base['post_snapshot_note'] + ' Статусот на наведените поправки е '
                               'задржан од претходниот запис; не се проверува повторно врз живата '
                               'инсталација при градењето.')
    return f


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args:
        if '--refreeze' in args:
            raise SystemExit('--refreeze is disabled: create a new separately audited snapshot with dated raw evidence and SHA-256 manifest; do not mix current runtime state into ARIES-DOC-20261006.')
        raise SystemExit('Usage: python verification/build_facts.py (offline frozen evidence only)')
    try:
        evidence = Evidence(SNAPSHOT)
        facts = build(evidence)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f'Frozen facts build failed; existing output preserved: {exc}') from exc
    OUT.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + '\n')
    ledger = facts['verification']['ledger']
    print(f"{facts['snapshot']['id']}: verified {len(evidence.contents)} frozen artifacts")
    print(f"ledger: {ledger['goals']} goals, {ledger['steps']} steps, {ledger['reached_a_verifier']['k']} reached verification")
    print(f'saved {OUT}; no live runtime reads or measurements')


if __name__ == '__main__':
    main()
