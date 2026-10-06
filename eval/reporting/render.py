"""Generate denominator corrections and an empty Part B results table.

Smoke artifacts and historical experiments never populate Part B acceptance rows.
Run from any directory; --check verifies both generated documents without writes.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START = '<!-- BUILD-MEASURE-RESULTS:START -->'
END = '<!-- BUILD-MEASURE-RESULTS:END -->'


def render():
    data = json.loads((ROOT / 'eval/reporting/denominators.json').read_text())
    memory = json.loads((ROOT / 'experiments/memory/summary.json').read_text())
    v = data['verification']
    c = v['coverage']
    assert sum(v['buckets'].values()) == v['n']
    assert c['trials'] == sum(v['buckets'].get(k, 0) for k in ('verified', 'accepted', 'unconfirmed'))
    baseline = memory['variants']['verbatim-gated-semantic']['cases']
    answerable = sum(bool(row['expected']) for row in baseline)
    probes = len(baseline)
    assert all(len(variant['cases']) == probes for variant in memory['variants'].values())
    rows = [
        '## Denominator corrections', '',
        'Generated from saved evidence. This section supersedes conflicting historical counts elsewhere in this report.', '',
        f"Verification snapshot captured {data['captured_at']}; window starts {data['window']['cutoff_utc']}, "
        f"ends at capture; goal scan cap {data['window']['goal_scan_cap']}.", '',
        f"All recorded steps: **n={v['n']}**. Apparently successful steps "
        f"(verified + accepted + unconfirmed): **n={c['trials']}**. Verified: **{c['successes']}/{c['trials']}** "
        f"of apparently successful steps, or **{c['successes']}/{v['n']}** of all recorded steps.", '',
        'The historical 200-versus-272 conflict cannot be reconciled as one denominator without matching source snapshots. '
        'Do not reuse either as current coverage. The current snapshot includes fixture traffic, is bounded by the scan cap, '
        'and does not measure verifier-eligible coverage. It establishes no before/after improvement and does not close B6.', '',
        f"Memory experiment: **n={answerable}** answerable retrieval queries; **n={probes}** total privacy/consistency probes. "
        f"The remaining **{probes-answerable}** have no expected answer. Thus the two denominators describe different outcomes, not competing sample counts. "
        f"Historical source run: {memory.get('ran_at_utc', memory['environment']['evaluated_at_utc'])}; "
        'these are retained historical denominators, not a measurement of today’s system.', '',
        'Sources: `eval/reporting/denominators.json` and `experiments/memory/summary.json`.', '',
        '## Results — Part B', '',
        'Intentionally empty. Populate only from completed Part B artifacts with n, time window, actual runtime flags, '
        'fixture hash and code identity. Build smoke tests do not populate this table.', '',
        '| Measurement | Baseline (n) | Candidate (n) | Time window | Flags / code / fixture | Evidence |',
        '|---|---|---|---|---|---|', '',
    ]
    return '\n'.join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    text = render()
    report = ROOT / 'docs/ARIES_REPORT.md'
    old = report.read_text()
    block = START + '\n' + text + '\n' + END
    if START in old:
        expected = old[:old.index(START)] + block + old[old.index(END)+len(END):]
    else:
        expected = old.rstrip() + '\n\n' + block + '\n'
    outputs = {ROOT / 'docs/BUILD_RESULTS.md': text, report: expected}
    stale = [str(path.relative_to(ROOT)) for path, content in outputs.items()
             if not path.exists() or path.read_text() != content]
    if args.check:
        if stale:
            raise SystemExit('Stale generated sections: ' + ', '.join(stale))
        print('Generated denominator corrections and empty Part B results match evidence.')
    else:
        for path, content in outputs.items():
            path.write_text(content)
        print('Generated denominator corrections and empty Part B results.')


if __name__ == '__main__':
    main()
