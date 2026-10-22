#!/usr/bin/env python3
"""Development scoring on nl2bash-dev (R1's 100 dev items; never a confirmatory number). Prints top-1 against the
R1 final labels, router acts, gate labels, planner validity, and the confusion on gold OOS vs in scope."""
import json
import sys
from collections import Counter
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / 'thesis-r1-real-data'))
from common import CAPABILITIES, OOS, canonical  # noqa: E402

from common import DATA  # noqa: E402
gold = {k: canonical(v) for k, v in json.loads((HERE.parents[0] / 'thesis-r1-real-data/labels/nl2bash-final.json').read_text())['labels'].items()}
_intent = {k: canonical(v) for k, v in json.loads((HERE.parents[0] / 'thesis-r1-real-data/labels/clinc-final.json').read_text())['labels'].items()}
_val = json.loads((DATA / 'clinc150/data_full.json').read_text())
gold.update({f'cv-{i:05d}': OOS if it == 'oos' else _intent[it] for i, (_, it) in enumerate(_val['val'] + _val['oos_val'])})


def predict(r):
    if not r.get('acts'):
        return OOS
    d = r.get('decision') or {}
    cap = d.get('capability')
    return canonical(cap) if d.get('action') == 'execute' and cap in CAPABILITIES else OOS


for f in sys.argv[1:]:
    rows = [json.loads(l) for l in open(f) if '"id"' in l]
    p = {r['id']: (canonical(r.get('label') or OOS) if 'zeroshot' in f else predict(r)) for r in rows}
    ok = sum(p[i] == gold[i] for i in p)
    ins = [i for i in p if gold[i] != OOS]
    c = Counter()
    for r in rows:
        g, q = gold[r['id']], p[r['id']]
        c['acts'] += bool(r.get('acts'))
        c['planner_invalid'] += bool(r.get('planner_error'))
        c['planner_fail'] += (r.get('decision') or {}).get('action') == 'fail'
        c['gate_oos'] += (r.get('route') or {}).get('gate_capability') == OOS
        c['false_action'] += g == OOS and q != OOS
        c['missed_action'] += g != OOS and q == OOS
        c['wrong_cap'] += g != OOS and q != OOS and q != g
    acts = {r['id']: (p[r['id']] != OOS) if 'zeroshot' in f else bool(r.get('acts')) for r in rows}
    aa = sum(acts[i] == (gold[i] != OOS) for i in p)
    print(Path(f).name, f'act/abstain {aa}/{len(p)}', f'top1 {ok}/{len(p)}', f'in-scope {sum(p[i] == gold[i] for i in ins)}/{len(ins)}',
          f'always-OOS {sum(gold[i] == OOS for i in p)}', dict(c))
