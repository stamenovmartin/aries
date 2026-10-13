#!/usr/bin/env python3
"""H8: the frozen mutant manifest, built from the effect type of each of the 58 capabilities.

Input: experiments/product/independent-acceptance/raw/review_verifier_integrity.json (the frozen
review: name, effect, verifier_class per capability). The operators and their applicability per
effect type are fixed here, before any mutant runs and before any verifier is hardened.
Every mutant carries a variant_seed derived from the set seed and its id. The runner derives the
concrete wrong value, wrong target or partial cut from it, so two sets with different seeds have
the same operators but different wrong values and targets.

Two sets are built:
- mutants.json, set seed 61013, committed, and run at baseline and after hardening;
- sealed/mutants-sealed.json, a set seed from os.urandom, kept local (git-ignored). Only its SHA-256 and
  size are committed (sealed/SEALED.sha256). It is not opened before the hardened run and is used only
  as a generalisation check. This script never prints its content.

Reads files only.

    python3 -I experiments/thesis-followup-20261012/h8/build_manifest.py           # public set
    python3 -I experiments/thesis-followup-20261012/h8/build_manifest.py --sealed  # sealed set (once)
"""
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REVIEW = ROOT / 'experiments/product/independent-acceptance/raw/review_verifier_integrity.json'

OPERATORS = {
    'noop_success': 'the executor does nothing and returns its normal success shape',
    'wrong_target': 'the effect or the report concerns a different target than requested',
    'wrong_value': 'the right target, but a different value or content (or a falsified report of it)',
    'partial_effect': 'only part of a multi-part effect happens',
    'side_effect_outside_scope': 'the requested effect happens, plus a change outside the allowed scope',
    'undone_after_report': 'the effect happens and is reverted before the verifier runs',
}
# Read-only capabilities have no effect to undo or to spill over: their mutants falsify the report.
APPLICABLE = {
    'read': ['noop_success', 'wrong_target', 'wrong_value'],
    'open': ['noop_success', 'wrong_target', 'wrong_value', 'undone_after_report'],
    'create': ['noop_success', 'wrong_target', 'wrong_value', 'partial_effect', 'side_effect_outside_scope',
               'undone_after_report'],
    'file_mutation': ['noop_success', 'wrong_target', 'wrong_value', 'partial_effect', 'side_effect_outside_scope',
                      'undone_after_report'],
    'desktop': ['noop_success', 'wrong_target', 'wrong_value', 'side_effect_outside_scope', 'undone_after_report'],
    'display': ['noop_success', 'wrong_value', 'undone_after_report'],
    'network': ['noop_success', 'wrong_target', 'undone_after_report'],
    'service': ['noop_success', 'wrong_target', 'undone_after_report'],
    'input': ['noop_success', 'wrong_target', 'wrong_value', 'undone_after_report'],
    'notify': ['noop_success', 'wrong_value', 'side_effect_outside_scope'],
}
CLEAN_REPLAYS_PER_CAPABILITY = 3
PUBLIC_SEED = 61013


def variant_seed(set_seed, mid):
    return int.from_bytes(hashlib.sha256(f'{set_seed}:{mid}'.encode()).digest()[:8], 'big')


HARDENED_CLASSES = ('TRIVIAL', 'SELF_REPORT', 'PLANNER_SUPPLIED')


def main(sealed=False):
    set_seed = int.from_bytes(os.urandom(8), 'big') if sealed else PUBLIC_SEED
    review = json.loads(REVIEW.read_text())
    caps = sorted(review['capabilities'], key=lambda r: r['name'])
    mutants, clean = [], []
    for c in caps:
        for op in APPLICABLE[c['effect']]:
            mid = f"{c['name']}::{op}"
            mutants.append({'id': mid, 'capability': c['name'], 'effect': c['effect'],
                            'verifier_class': c['verifier_class'], 'operator': op,
                            'variant_seed': variant_seed(set_seed, mid)})
        for i in range(1, CLEAN_REPLAYS_PER_CAPABILITY + 1):
            clean.append({'id': f"{c['name']}::clean{i}", 'capability': c['name'], 'verifier_class': c['verifier_class']})
    by_class = {}
    for m in mutants:
        by_class[m['verifier_class']] = by_class.get(m['verifier_class'], 0) + 1
    out = {'what': 'H8 frozen mutant manifest' + (' (SEALED generalisation set)' if sealed else ''),
           'set_seed': set_seed, 'review_sha256': hashlib.sha256(REVIEW.read_bytes()).hexdigest(),
           'operators': OPERATORS, 'applicable_by_effect': APPLICABLE,
           'hardened_verifier_classes': HARDENED_CLASSES,
           'hardened_capabilities': sorted(c['name'] for c in caps if c['verifier_class'] in HARDENED_CLASSES),
           'counts': {'capabilities': len(caps), 'mutants': len(mutants), 'clean_replays': len(clean),
                      'mutants_by_verifier_class': by_class,
                      'mutants_by_operator': {op: sum(m['operator'] == op for m in mutants) for op in OPERATORS}},
           'mutants': mutants, 'clean_replays': clean}
    if sealed:
        target = HERE / 'sealed/mutants-sealed.json'
        if target.exists():
            raise SystemExit('REFUSED: the sealed set already exists and is never regenerated')
        target.parent.mkdir(exist_ok=True)
        data = (json.dumps(out, indent=1) + '\n').encode()
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        (HERE / 'sealed/SEALED.sha256').write_text(
            f'{digest}  mutants-sealed.json  {len(data)} bytes  (H8 sealed generalisation set; not opened before '
            'the hardened run)\n')
        print('sealed set written; sha256', digest, 'bytes', len(data))   # counts and content are not printed
        return
    (HERE / 'mutants.json').write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps(out['counts'], indent=1))
    print('hardened:', len(out['hardened_capabilities']))


if __name__ == '__main__':
    main(sealed='--sealed' in sys.argv[1:])
