"""Draw the comparison figures for the thesis and IIS results as SVG.

Every number is read from the committed result files below; nothing is typed in.
Standard library only, so it runs in a fresh clone with no model, service or
network. The output is deterministic: `--check` redraws in memory and fails on
any difference from the committed figures.

    python experiments/analysis/make_figures.py          # write figures/
    python experiments/analysis/make_figures.py --check  # verify figures/
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / 'experiments/thesis-followup-20261012/thesis-tables'
R1_SUMMARY = ROOT / 'experiments/thesis-r1-real-data/summary.json'
# M1 runs (2026-10-22T19:35Z): every earlier system plus MMR and relative learning, same data and seeds
MIND = ROOT / 'experiments/iis/real-data/mind/results/mind-dev-20261022T193501Z.json'
LOCOMO = ROOT / 'experiments/iis/real-data/locomo/results/locomo-20261022T200243Z.json'   # M1: BM25, e5, hybrid
OUT = Path(__file__).resolve().parent / 'figures'

ACCENT = '#2f6f9f'    # ARIES, or the new version
MUTED = '#a3a9b0'     # baselines and the old version
SECOND = '#c4793a'    # a second ARIES variant
GOOD, BAD, NEUTRAL = '#2e7d4f', '#b3412f', '#6b7280'
FG, FG2, GRID = '#1f2328', '#59636e', '#e5e7ea'
FONT = 'font-family="Helvetica, Arial, sans-serif"'
CHAR_W = 6.4  # approximate width of one 12px character, for layout


def table(name: str) -> list[dict]:
    with open(TABLES / name) as f:
        return list(csv.DictReader(line for line in f if not line.startswith('#')))


def pct(v: float) -> str:
    return f'{100 * v:.1f}%'


class Svg:
    def __init__(self, width: int, height: int, title: str, subtitle: str = ''):
        self.w, self.h, self.parts = width, height, []
        self.rect(0, 0, width, height, '#ffffff')
        self.text(16, 26, title, size=15, weight='bold', color=FG)
        if subtitle:
            self.text(16, 45, subtitle, size=11.5, color=FG2)

    def rect(self, x, y, w, h, fill, rx=0, opacity=1.0):
        self.parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" fill-opacity="{opacity}"/>')

    def line(self, x1, y1, x2, y2, color, width=1.0, dash=''):
        d = f' stroke-dasharray="{dash}"' if dash else ''
        self.parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}" stroke-linecap="round"{d}/>')

    def circle(self, x, y, r, fill, stroke='none'):
        self.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')

    def text(self, x, y, s, size=12, color=FG2, anchor='start', weight='normal'):
        self.parts.append(f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{escape(str(s))}</text>')

    def legend(self, x, y, items):
        for name, color in items:
            self.rect(x, y - 9, 10, 10, color, rx=2)
            self.text(x + 15, y, name, size=11.5)
            x += 15 + CHAR_W * len(name) + 22

    def axis(self, x0, x1, y_top, y_bot, lo, hi, ticks, fmt):
        for i in range(ticks + 1):
            v = lo + (hi - lo) * i / ticks
            x = x0 + (x1 - x0) * i / ticks
            self.line(x, y_top, x, y_bot, GRID)
            self.text(x, y_bot + 15, fmt(v), size=11, anchor='middle')

    def render(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}">\n' + '\n'.join(self.parts) + '\n</svg>\n')


def bars_ci(title, subtitle, rows, lo=0.0, hi=1.0, fmt=pct, tick_fmt=None, dots=False, ticks=5):
    """rows: (label, value, ci_lo, ci_hi, color, faded)."""
    tick_fmt = tick_fmt or (lambda v: f'{100 * v:.0f}%')
    left = 24 + CHAR_W * max(len(r[0]) for r in rows)
    width, row_h, top = 760, 30, 70
    x0, x1 = left, width - 80
    sx = lambda v: x0 + (x1 - x0) * (v - lo) / (hi - lo)
    svg = Svg(width, top + row_h * len(rows) + 40, title, subtitle)
    bottom = top + row_h * len(rows)
    svg.axis(x0, x1, top - 6, bottom, lo, hi, ticks, tick_fmt)
    for i, (label, v, cl, ch, color, faded) in enumerate(rows):
        cy = top + row_h * i + row_h / 2
        svg.text(x0 - 10, cy + 4, label, anchor='end', color=FG if color == ACCENT else FG2)
        if dots:
            svg.circle(sx(v), cy, 5.5, color)
        else:
            svg.rect(sx(lo), cy - 9, sx(v) - sx(lo), 18, color, rx=4, opacity=0.4 if faded else 1)
        end = sx(v)
        if cl is not None:
            svg.line(sx(cl), cy, sx(ch), cy, FG, 1.4)
            svg.line(sx(cl), cy - 5, sx(cl), cy + 5, FG, 1.4)
            svg.line(sx(ch), cy - 5, sx(ch), cy + 5, FG, 1.4)
            end = max(end, sx(ch))
        svg.text(end + 6, cy + 4, fmt(v), color=FG)
    return svg


def grouped(title, subtitle, groups, series, value, labels=None, ticks=5):
    """series: (name, color); value(group, name) -> rate or None."""
    labels = labels or {}
    names = [labels.get(g, g) for g in groups]
    left = 24 + CHAR_W * max(len(n) for n in names)
    bar_h, gap = 13, 16
    group_h = bar_h * len(series) + gap
    width, top = 760, 82
    x0, x1 = left, width - 70
    sx = lambda v: x0 + (x1 - x0) * v
    bottom = top + group_h * len(groups)
    svg = Svg(width, bottom + 40, title, subtitle)
    svg.legend(16, 66, series)
    svg.axis(x0, x1, top - 4, bottom, 0, 1, ticks, lambda v: f'{100 * v:.0f}%')
    for i, g in enumerate(groups):
        y = top + group_h * i
        svg.text(x0 - 10, y + bar_h * len(series) / 2 + 4, names[i], anchor='end')
        for j, (name, color) in enumerate(series):
            v = value(g, name)
            if v is None:
                continue
            yy = y + bar_h * j
            svg.rect(sx(0), yy + 1, max(sx(v) - sx(0), 1.5), bar_h - 2, color, rx=3)
            svg.text(sx(v) + 5, yy + bar_h - 2.5, pct(v), size=10.5)
    return svg


# ---------------------------------------------------------------- figures

def fig_tests():
    holm = {r['hypothesis']: r for r in table('holm_family.csv')}
    h6 = {(r['arm'], r['group']): r for r in table('h6_abstention.csv')
          if r['model'] == 'qwen2.5:7b' and r['metric'] == 'binary_majority_of_3'}
    h8 = {r['run']: r for r in table('h8_fault_injection.csv') if r['metric'] == 'killed' and r['group'] == 'all'}
    h5 = {(r['part'], r['condition']): r for r in table('h5_completion.csv')}
    h4b = {(r['part'], r['condition']): r for r in table('h4b_clarification.csv')}
    rows = [  # (label, new-version row, comparison row, Holm row)
        ('H6  A1 vs A0', h6['A1', 'all'], h6['A0', 'all'], holm['H6']),
        ('H8  hardened vs frozen', h8['hardened'], h8['baseline-2'], holm['H8']),
        ('H5  contract vs control', h5['primary', 'treatment'], h5['primary', 'control'], holm['H5']),
        ('H4b resolver vs none', h4b['primary', 'treatment'], h4b['primary', 'baseline'], holm['H4b']),
    ]
    out = []
    for label, a, b, h in rows:
        rej = h['null at 0.05 (Holm)'] == 'rejected'
        out.append((label, int(a['k']) / int(a['n']), int(b['k']) / int(b['n']), float(h['p_holm']),
                    GOOD if rej else NEUTRAL, f"{a['k']}/{a['n']} vs {b['k']}/{b['n']}"))
    r1 = json.load(open(R1_SUMMARY))
    rate = {(r['dataset'], r['system']): r for r in table('r1_real_data.csv') if r['metric'] in ('top1', 'correct')}
    short = {'aries': 'ARIES', 'embedding': 'embedding', 'bm25': 'BM25', 'zeroshot_qwen': 'zero-shot',
             'router_A1': 'A1', 'router_A0': 'A0'}
    for tid, t in r1['tests'].items():
        ds = 'NL2Bash test' if t['dataset'] == 'nl2bash-test' else 'CLINC150'
        a, b = rate[ds, t['first']], rate[ds, t['second']]
        sig = t['significant_holm_0_05']
        color = (GOOD if t['b_first_only'] > t['c_second_only'] else BAD) if sig else NEUTRAL
        out.append((f"{tid} {ds.split()[0]}: {short[t['first']]} vs {short[t['second']]}",
                    float(a['rate']), float(b['rate']), t['p_holm'], color, f"{a['k']}/{a['n']} vs {b['k']}/{b['n']}"))
    breaks = [4, len(out)]
    r1b = json.load(open(R1B))
    sysname = {'aries_treatment': 'ARIES fixed', 'aries_frozen': 'frozen', 'zeroshot_qwen': 'zero-shot',
               'router_A1_frozen': 'frozen'}
    for tid, t in r1b['tests'].items():
        d = 'nl2bash' if t['dataset'].startswith('nl2bash') else 'clinc150'
        metric = 'top1' if d == 'nl2bash' else 'correct'
        a, b = r1b[d][t['first']][metric], r1b[d][t['second']][metric]
        sig = t['significant_holm_0_05']
        color = (GOOD if t['b_first_only'] > t['c_second_only'] else BAD) if sig else NEUTRAL
        out.append((f"{tid.replace('H-', '')} {'NL2Bash' if d == 'nl2bash' else 'CLINC150'}: ARIES fixed vs {sysname[t['second']]}",
                    a['rate'], b['rate'], t['p_holm'], color, f"{a['k']}/{a['n']} vs {b['k']}/{b['n']}"))
    breaks.append(len(out))
    m2 = json.load(open(M2))
    for tid, t in m2['tests'].items():
        d = t['dataset']
        metric = 'top1' if d == 'nl2bash' else 'correct'
        a, b = m2['models'][t['model']][d]['aries_treatment'][metric], m2['models'][t['model']][d]['aries_frozen'][metric]
        sig = t['significant_holm_0_05']
        color = (GOOD if t['b_first_only'] > t['c_second_only'] else BAD) if sig else NEUTRAL
        out.append((f"{tid} {t['model']} {'NL2Bash' if d == 'nl2bash' else 'CLINC150'}: fixed vs frozen",
                    a['rate'], b['rate'], t['p_holm'], color, f"{a['k']}/{a['n']} vs {b['k']}/{b['n']}"))

    left = 24 + CHAR_W * max(len(r[0]) for r in out)
    width, row_h, top = 860, 30, 82
    x0, x1 = left, width - 250
    sx = lambda v: x0 + (x1 - x0) * v
    bottom = top + row_h * len(out)
    svg = Svg(width, bottom + 40, 'Every confirmatory test: ARIES (filled) vs the comparison (hollow)',
              'Families, top to bottom: H4b-H8, R1, R1b, M2 (Holm inside each). Green: ARIES better; red: comparison better; grey: n.s.')
    svg.legend(16, 66, [('ARIES / new version', ACCENT), ('comparison', MUTED)])
    svg.axis(x0, x1, top - 4, bottom, 0, 1, 5, lambda v: f'{100 * v:.0f}%')
    svg.text(x1 + 14, top - 10, 'counts', size=11, weight='bold')
    svg.text(x1 + 140, top - 10, 'p (Holm)', size=11, weight='bold')
    for i, (label, a, b, p, color, counts) in enumerate(out):
        cy = top + row_h * i + row_h / 2
        if i in breaks:
            svg.line(16, cy - row_h / 2, width - 16, cy - row_h / 2, FG2, 0.8, '3 3')
        svg.text(x0 - 10, cy + 4, label, anchor='end', color=FG)
        svg.line(sx(min(a, b)), cy, sx(max(a, b)), cy, color, 3.5)
        svg.circle(sx(b), cy, 5, '#ffffff', MUTED)
        svg.circle(sx(a), cy, 5.5, ACCENT)
        svg.text(x1 + 14, cy + 4, counts, size=11)
        svg.text(x1 + 140, cy + 4, f'{p:.2g}', size=11, color=color, weight='bold')
    return svg


def fig_r1(dataset, title, metrics=('top1', 'correct'), note='faded: outside the test family'):
    rows = [r for r in table('r1_real_data.csv') if r['dataset'] == dataset and r['metric'] in metrics]
    names = {'aries': 'ARIES', 'zeroshot_qwen': 'zero-shot qwen2.5:7b', 'embedding': 'embedding (e5)', 'bm25': 'BM25',
             'router_A1': 'ARIES router A1', 'router_A0': 'ARIES router A0',
             'aries_llama_secondary': 'ARIES, llama3.1:8b (secondary)',
             'router_A1_llama_secondary': 'ARIES A1, llama3.1:8b (secondary)',
             'always OUT_OF_SCOPE': 'always out of scope (reference)', 'always abstain': 'always abstain (reference)'}
    out = []
    for r in rows:
        confirm = r['label'].startswith('confirmatory') or 'in-scope' in r['metric']
        aries = r['system'].startswith(('aries', 'router'))
        out.append((names.get(r['system'], r['system']), float(r['rate']), float(r['ci_lo']), float(r['ci_hi']),
                    ACCENT if aries else MUTED, not confirm))
    n = rows[0]['n']
    return bars_ci(title, f'n = {n}; bars: share correct, lines: 95% Clopper-Pearson; {note}', out)


def fig_h6():
    rows = {(r['arm'], r['group']): float(r['rate']) for r in table('h6_abstention.csv')
            if r['model'] == 'qwen2.5:7b' and r['metric'] == 'binary_majority_of_3'}
    groups = ['all', 'actionable', 'ambiguous', 'out_of_scope', 'unsafe']
    labels = {'all': 'all 300', 'actionable': 'actionable', 'ambiguous': 'ambiguous',
              'out_of_scope': 'out of scope', 'unsafe': 'unsafe'}
    return grouped('H6: router decisions correct, by kind of request',
                   'qwen2.5:7b, majority of 3 repetitions; the instruction helps most on out-of-scope requests',
                   groups, [('A0 no instruction', MUTED), ('A1 abstention instruction', ACCENT)],
                   lambda g, s: rows.get(('A0' if s.startswith('A0') else 'A1', g)), labels)


def fig_h8():
    run = {'frozen': 'baseline-2', 'hardened': 'hardened'}
    rows = {(r['run'], r['group']): float(r['rate']) for r in table('h8_fault_injection.csv')
            if r['metric'] in ('killed_by_operator', 'killed')}
    groups = ['all', 'noop_success', 'wrong_target', 'wrong_value', 'partial_effect', 'undone_after_report',
              'side_effect_outside_scope']
    labels = {'all': 'all mutants', 'noop_success': 'success, nothing changed', 'wrong_target': 'wrong target',
              'wrong_value': 'wrong value', 'partial_effect': 'partial effect', 'undone_after_report': 'undone after report',
              'side_effect_outside_scope': 'side effect outside scope'}
    return grouped('H8: injected faults detected, by kind of fault',
                   'Frozen vs hardened verifiers; neither detects side effects outside the declared scope',
                   groups, [('frozen verifiers', MUTED), ('hardened verifiers', ACCENT)],
                   lambda g, s: rows.get((run[s.split()[0]], g)), labels)


def fig_heldout():
    rows = [r for r in table('heldout_by_class.csv') if r['class'] != 'TOTAL']
    total = next(r for r in table('heldout_by_class.csv') if r['class'] == 'TOTAL')
    left = 24 + CHAR_W * max(len(r['class']) for r in rows)
    width, row_h, top = 760, 28, 82
    x0, x1 = left, width - 70
    top_n = max(int(r['goals']) for r in rows)
    sx = lambda v: x0 + (x1 - x0) * v / top_n
    bottom = top + row_h * len(rows)
    svg = Svg(width, bottom + 40, f"Held-out goals end to end: {total['PASS']}/{total['goals']} pass the independent check",
              'Each goal run on the live system, then checked by a script that does not trust the agent')
    svg.legend(16, 66, [('pass', GOOD), ('fail', BAD), ('inconclusive', MUTED)])
    svg.axis(x0, x1, top - 4, bottom, 0, top_n, top_n, lambda v: f'{v:.0f}')
    for i, r in enumerate(rows):
        cy = top + row_h * i + row_h / 2
        svg.text(x0 - 10, cy + 4, r['class'].replace('_', ' '), anchor='end')
        acc = 0
        for key, color in (('PASS', GOOD), ('FAIL', BAD), ('INCONCLUSIVE', MUTED)):
            v = int(r[key])
            if v:
                svg.rect(sx(acc) + 1, cy - 8, sx(acc + v) - sx(acc) - 2, 16, color, rx=3, opacity=0.9)
            acc += v
        svg.text(sx(acc) + 6, cy + 4, f"{r['PASS']}/{r['goals']}", color=FG)
    return svg


def fig_mind():
    m = json.load(open(MIND))['all_impressions']
    names = {'aries-interests': 'ARIES interests', 'aries-learning': 'ARIES + online learning',
             'aries-learning-relative': 'ARIES + relative learning (M1)',
             'aries-interests+diverse': 'ARIES + round-robin topics', 'aries-interests+mmr': 'ARIES + MMR diversity (M1)',
             'embedding': 'embedding (e5)', 'popular': 'popularity',
             'bm25': 'BM25', 'tfidf': 'TF-IDF', 'recent': 'most recent', 'random': 'random'}
    rows = sorted(((names.get(k, k), v['auc']['mean'], *v['auc']['ci95'], ACCENT if k.startswith('aries') else MUTED, False)
                   for k, v in m['systems'].items()), key=lambda r: -r[1])
    return bars_ci('MIND-small: news ranking, AUC by system',
                   f"{m['impressions']:,} impressions, {m['users']:,} users; 95% bootstrap over users; the axis starts at 0.48",
                   rows, lo=0.48, hi=0.63, fmt=lambda v: f'{v:.3f}', tick_fmt=lambda v: f'{v:.2f}', dots=True, ticks=5)


def fig_locomo():
    lc = json.load(open(LOCOMO))
    cats = ['all', '1 multi-hop', '2 temporal', '3 open-domain', '4 single-hop', '5 adversarial']
    series = [('BM25 (baseline)', 'bm25', MUTED), ('ARIES before (e5 similarity)', 'embedding-only-e5', SECOND),
              ('ARIES after M1 (BM25 + e5, RRF)', 'hybrid-similarity-e5', ACCENT)]
    labels = {c: (c.split(' ', 1)[1] if ' ' in c else 'all questions') + f" (n={lc['variants']['bm25']['metrics'][c]['n']})"
              for c in cats}
    key = {name: v for name, v, _ in series}
    return grouped('LoCoMo: evidence turn among the top 5 retrieved (hit@5)',
                   'Before M1 BM25 beat ARIES; with hybrid retrieval and similarity ranking ARIES beats BM25',
                   cats, [(n, c) for n, _, c in series],
                   lambda g, s: lc['variants'][key[s]]['metrics'][g]['hit@5']['mean'], labels)


R1B = ROOT / 'experiments/thesis-r1b/summary.json'
M2 = ROOT / 'experiments/thesis-m2-models/summary.json'
P1 = ROOT / 'experiments/thesis-p1-performance'
MODELS = ('qwen2.5:1.5b', 'qwen2.5:7b', 'llama3.1:8b', 'qwen2.5:14b')


def fig_r1b():
    n = json.load(open(R1B))['nl2bash']
    names = [('aries_treatment', 'ARIES with the remedies', ACCENT, False), ('zeroshot_qwen', 'zero-shot qwen2.5:7b', MUTED, False),
             ('embedding', 'embedding (e5)', MUTED, True), ('bm25', 'BM25', MUTED, True),
             ('aries_frozen', 'ARIES frozen (as in R1)', SECOND, False),
             ('always_out_of_scope', 'always out of scope (reference)', MUTED, True)]
    rows = [(label, n[k]['top1']['rate'], *n[k]['top1']['cp95'], color, faded) for k, label, color, faded in names]
    return bars_ci('R1b NL2Bash: right tool or out of scope, new sample (top-1)',
                   'n = 500, disjoint from R1; lines: 95% Clopper-Pearson; faded: outside the test family', rows)


def fig_m2():
    m = json.load(open(M2))['models']
    series = [('ARIES frozen', SECOND), ('zero-shot (the model alone)', MUTED), ('ARIES with the remedies', ACCENT)]
    key = {'ARIES frozen': 'aries_frozen', 'zero-shot (the model alone)': 'zeroshot', 'ARIES with the remedies': 'aries_treatment'}
    return grouped('M2: the same architecture with four local models (NL2Bash r1b, top-1)',
                   'remedies vs frozen significant for every model (Holm, 6 of 6); qwen2.5:1.5b gains only by refusing',
                   [x for x in MODELS if x in m], series, lambda g, s: m[g]['nl2bash'][key[s]]['top1']['rate'])


def fig_p1_latency():
    s = json.load(open(P1 / 'summary.json'))['decision_full_samples']
    rows = [(f'{x}', s[x]['decision_total_s']['median'], s[x]['decision_total_s']['median'],
             s[x]['decision_total_s']['p90'], ACCENT if x == 'qwen2.5:7b' else MUTED, False) for x in MODELS]
    return bars_ci('P1: time to decide (router + planner), 1,100 requests per model',
                   'bar: median; line: median to 90th percentile; one machine (RTX 3060 12 GB)',
                   rows, lo=0, hi=7, fmt=lambda v: f'{v:.2f} s', tick_fmt=lambda v: f'{v:.0f} s', ticks=7)


SERIES = [('p1', '1. as it was (screen blanked by ARIES)'), ('p1c2', '2. screen awake'),
          ('p1c3', '3. + old context fix'), ('p1c4a', '4. current source'), ('p1c4b', '5. repaired system')]


def fig_system_runs():
    rows = []
    for label, name in SERIES:
        runs = [json.load(open(f)) for f in sorted((P1 / 'suite').glob(f'{label}-run*/results.json'))]
        runs = [r for r in runs if r.get('finished_at')]          # a run still in progress is not drawn
        if len(runs) != 3:
            continue
        rates = [r['counts']['pass'] / r['counts']['scored'] for r in runs]
        rows.append((name, sum(rates) / 3, min(rates), max(rates), ACCENT if label == 'p1c4b' else MUTED, False))
    return bars_ci('The installed system end to end: 90-goal agent suite, three runs per measurement',
                   'bar: mean pass rate over the scored goals; line: lowest to highest run; each step changes one thing',
                   rows)


FIGURES = {
    'tests.svg': fig_tests,
    'r1_nl2bash.svg': lambda: fig_r1('NL2Bash test', 'R1 NL2Bash: right tool or out of scope (top-1)'),
    'r1_nl2bash_in_scope.svg': lambda: fig_r1('NL2Bash test', 'R1 NL2Bash, in-scope requests only (exploratory)',
                                              ('top1 on in-scope gold items',), 'chosen after the results'),
    'r1_clinc150.svg': lambda: fig_r1('CLINC150', 'R1 CLINC150: act or abstain, correct'),
    'h6_by_class.svg': fig_h6,
    'h8_by_fault.svg': fig_h8,
    'heldout.svg': fig_heldout,
    'mind_auc.svg': fig_mind,
    'locomo_hit5.svg': fig_locomo,
    'r1b_nl2bash.svg': fig_r1b,
    'm2_models.svg': fig_m2,
    'p1_latency.svg': fig_p1_latency,
    'p1_system_runs.svg': fig_system_runs,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--check', action='store_true', help='fail if a committed figure differs from a fresh drawing')
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    bad = []
    for name, make in FIGURES.items():
        svg = make().render()
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text() != svg:
                bad.append(name)
        else:
            path.write_text(svg)
    if args.check:
        print(f'figures: {len(FIGURES) - len(bad)}/{len(FIGURES)} match' + (f'; differ: {", ".join(bad)}' if bad else ''))
        return 1 if bad else 0
    print(f'wrote {len(FIGURES)} figures to {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
