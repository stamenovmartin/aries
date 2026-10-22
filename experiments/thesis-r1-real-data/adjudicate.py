#!/usr/bin/env python3
"""R1 agreement and adjudication (Labels section).

    adjudicate.py nl2bash|clinc   ->  labels/<set>-agreement.json, labels/<set>-final.json

Cohen's kappa between labelers A and B over the canonical labels (alias classes merged) and over the binary
in-scope/out-of-scope reduction. Every disagreement goes to a third fresh `claude -p` session (no tools, empty
directory) that sees the item, the label list and the two labels in a seeded random order without their source;
its choice is final."""
import json
import random
import sys
import tempfile
from collections import Counter
from common import HERE, LABELS, LOCAL, OOS, canonical, sha
import label as L


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0, po


def main(name):
    A = json.loads((HERE / 'labels' / f'{name}-A.json').read_text())
    B = json.loads((HERE / 'labels' / f'{name}-B.json').read_text())
    for f in ('final', 'agreement'):
        if (HERE / 'labels' / f'{name}-{f}.json').exists():
            raise SystemExit(f'REFUSED: {name}-{f}.json exists')
    ids = sorted(set(A['labels']) & set(B['labels']))
    a = [canonical(A['labels'][i]) for i in ids]
    b = [canonical(B['labels'][i]) for i in ids]
    k, po = kappa(a, b)
    kb, pob = kappa([x == OOS for x in a], [x == OOS for x in b])
    pool = {it['id']: it for it in L.items(name)}
    missing = sorted(set(pool) - set(ids))
    disagree = [i for i, x, y in zip(ids, a, b) if x != y]
    rng = random.Random(20261027)
    tdir = LOCAL / 'transcripts' / f'{name}-adjudication'
    tdir.mkdir(parents=True, exist_ok=True)
    decided, events = {}, []
    for bi in range(0, len(disagree), 25):
        chunk = disagree[bi:bi + 25]
        shown = []
        for i in chunk:
            pair = [A['labels'][i], B['labels'][i]]
            rng.shuffle(pair)
            shown.append({**pool[i], 'proposed_labels': pair})
        text = (f'{L.INSTRUCTION[name]}\n\nTwo annotators disagreed on the items below; each item shows their two '
                'proposed labels in random order. Decide the correct label for each item: one of the two proposed '
                'labels, or another label from the list if both are wrong.\n\nCapabilities:\n' + L.LABEL_LIST +
                '\n\nItems (one JSON object per line):\n' + '\n'.join(json.dumps(s, ensure_ascii=False) for s in shown) +
                '\n\nAnswer with only a JSON array, one object per item in the same order: '
                '[{"id": "<id>", "label": "<label>"}]. Do not use any tools, do not read any files, do not explain.')
        for attempt in (1, 2):
            with tempfile.TemporaryDirectory(prefix='r1-adj-') as wd:
                answer, tool_use, model, raw = L.call('A', text, wd)
            (tdir / f'batch{bi // 25:02d}-try{attempt}.txt').write_text(raw)
            try:
                got = None if tool_use else L.parse(answer, shown)
            except Exception as exc:
                got = None
                events.append({'batch': bi // 25, 'attempt': attempt, 'discarded': str(exc)[:200]})
            if got:
                decided.update(got)
                break
    final = {}
    for i, x, y in zip(ids, a, b):
        final[i] = x if x == y else canonical(decided[i]) if i in decided else None
    unresolved = sorted(i for i, v in final.items() if v is None)
    agreement = {'set': name, 'n_items': len(pool), 'labelled_by_both': len(ids), 'missing': missing,
                 'models': {'A': A['models'], 'B': B['models']},
                 'kappa_labels': round(k, 4), 'raw_agreement_labels': round(po, 4),
                 'kappa_binary': round(kb, 4), 'raw_agreement_binary': round(pob, 4),
                 'disagreements': len(disagree), 'adjudicated': len(decided), 'unresolved': unresolved,
                 'adjudicator_picked': dict(Counter(
                     'A' if canonical(decided[i]) == canonical(A['labels'][i]) else
                     'B' if canonical(decided[i]) == canonical(B['labels'][i]) else 'other' for i in decided)),
                 'events': events, 'label_counts_final': dict(Counter(v for v in final.values() if v)),
                 'sources_sha256': {'A': sha(HERE / 'labels' / f'{name}-A.json'), 'B': sha(HERE / 'labels' / f'{name}-B.json')}}
    (HERE / 'labels' / f'{name}-agreement.json').write_text(json.dumps(agreement, indent=1) + '\n')
    (HERE / 'labels' / f'{name}-final.json').write_text(json.dumps(
        {'set': name, 'canonical': True, 'labels': {i: v for i, v in sorted(final.items()) if v}}, indent=1) + '\n')
    print(json.dumps({k2: v for k2, v in agreement.items() if k2 not in ('label_counts_final',)}))


if __name__ == '__main__':
    main(sys.argv[1])
