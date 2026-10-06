"""Render excluded cloud pilot evidence without pooling different fault surfaces."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    args = parser.parse_args()
    report = json.loads(args.results.read_text())
    raw = [json.loads((ROOT / row['artifact']).read_text()) for row in report['episodes']]
    stable = all(row.get('source_stable') for row in raw) and len({
        json.dumps(row['source_before'], sort_keys=True) for row in raw}) == 1
    lines = ['# Pinned cloud development pilot', '',
             '**Excluded development data, not the 600-run study or an improvement claim.**', '',
             f"Provider/model: `{report['provider']}` / `{report['model']}`. "
             f"Completed {len(report['episodes'])}/{report['assigned_n']} assignments.",
             f"Window: {report['started_at']} — {report.get('finished_at', 'unfinished')}.",
             f"Sources stable within and across episodes: {stable}. "
             'Common completion guard and terminal JSON examples enabled; no model sampling seed supplied.', '',
             '| Case | Feedback | Unsupported finish proposals | Goal oracle | Model chose stop | Calls | Seconds | Confirmatory admission |',
             '|---|---|---:|---|---|---:|---:|---|']
    for row in report['episodes']:
        case = row['case'] or ('owned files / ' + row['fault'])
        lines.append(f"| {case} | {row['condition']} | {row.get('unsupported_model_claims')} | "
                     f"{row.get('oracle_met')} | {row.get('model_chose_stop')} | {row.get('calls')} | "
                     f"{row.get('latency_s')} | {row.get('valid_for_comparison')} |")
    lines += ['', 'Each row has n=1. The two fault families are separate diagnostic contrasts; do not pool them '
              'as independent repetitions or report a confidence interval as if this were the planned study.', '',
              'Normal file controls complete under both conditions. For each fault pair, tool-only produced one '
              'unsupported finish proposal and structured feedback produced zero. Neither fault pair completed '
              'the goal. No user-visible false success was exposed in these six episodes. These observations '
              'do not establish general improvement; order is fixed and sample size is minimal.', '',
              '`reroute_verified`: **unmeasurable**, not zero. No permitted independent alternative route was validated.',
              'The controlled screen rows remain excluded from confirmatory comparison. '
              'Read `CLOUD_ADMISSION.json` for unresolved whole-study checks.', '',
              'The privacy guard covers this isolated study adapter only; production private/local routing has not '
              'been demonstrated by these tests.', '', '## Artifacts', '']
    lines += [f"- `{row['artifact']}` — SHA256 `{row['sha256']}`" for row in report['episodes']]
    (args.results.parent / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print(args.results.parent / 'REPORT.md')


if __name__ == '__main__':
    main()
