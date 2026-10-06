"""Generate a thesis-facing diagnostic report from saved pilot evidence only."""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    args = parser.parse_args()
    report = json.loads(args.results.read_text())
    if not report.get('finished_at') or len(report['episodes']) != report['assigned_n']:
        raise SystemExit('Pilot incomplete: do not publish a completed-results table')
    episodes = report['episodes']
    artifacts = [json.loads(Path(row['artifact']).read_text()) for row in episodes]
    start = min(row['started_at'] for row in artifacts)
    end = max(row['finished_at'] for row in artifacts)
    text = ['# ARIES verification-feedback feasibility pilot', '',
            '**Exploratory development data. No confirmatory effect or production improvement is established.**', '',
            f'Execution window: {start} to {end}. Assigned/completed: {len(episodes)}/{report["assigned_n"]}.',
            'Model: `' + str(episodes[0]['settings'].get('intelligence.local_model')) + '`.',
            f'Code stable across episodes: {report["source_stable_across_episodes"]}; settings stable: {report["settings_stable_across_episodes"]}.', '',
            'Each case has one run per condition. Repeated fault families are not independent tasks. '
            'All arms retain the same execution, approval and completion safeguards.', '',
            '| Surface | Condition | Scored/assigned | Unsupported model completion episodes | User-visible false success | Goal predicate met | Verified recovery |',
            '|---|---|---:|---:|---:|---:|---:|']
    for row in report['groups']:
        if row['surface'] == 'owned_files':
            continue
        n = row['scored_n']
        text.append(f'| {row["surface"]} | {row["condition"]} | {n}/{row["assigned_n"]} | '
                    f'{row["episodes_with_unsupported_claim"]}/{n} | {row["user_visible_false_success"]}/{n} | '
                    f'{row["goal_completed"]}/{n} | {row["verified_recovery"]}/{n} |')
    text += ['', '“Scored” means an observation oracle returned a Boolean, not that the row passed confirmatory admission. '
             'Native faults and synthetic returned-image faults are distinct interventions and are not pooled. '
             'No verified recovery occurred; fault exposure plus an unrelated successful step is not recovery.', '',
             'The screen counts differ by only one case. This pilot is too small and heterogeneous to establish a general benefit. '
             'The completion guard intercepted unsupported proposals in both conditions; zero exposed false successes '
             'does not demonstrate that the planner stopped making those proposals.', '',
             '## Owned-file controls', '',
             '| Fault | Condition | Goal predicate met | Unsupported model proposals |', '|---|---|---:|---:|']
    for row in episodes:
        if row['surface'] == 'owned_files':
            text.append(f'| {row["fault"]} | {row["condition"]} | {int(row["oracle_met"] is True)}/1 | {row["unsupported_model_claims"]} |')
    text += ['', '## Prompt-format development probe', '']
    probe_path = HERE / 'terminal_examples_checks.json'
    if probe_path.exists():
        probe = json.loads(probe_path.read_text())
        counts = probe.get('adjudicated')
        if counts:
            n = counts['valid_pairs_n']
            text += [f'Invalid-terminal episodes: {counts["before_invalid_terminal_episodes"]}/{n} before '
                     f'and {counts["after_invalid_terminal_episodes"]}/{n} after explicit terminal JSON examples.',
                     f'Assigned: {counts["assigned_n"]}; attempted: {counts["attempts_n"]}; '
                     f'infrastructure errors: {counts["infrastructure_errors_n"]}; valid pairs: {n}.',
                     'This sequential development comparison selects previously failing cases. It is not a randomized '
                     'generalization result. The opt-in `--terminal-examples` change exists only in the experimental runner; '
                     'production was not modified. Error attempts remain in the JSON record.', '']
    text += ['## Admission and remaining work', '',
             'The 600-run confirmatory study remains unlaunched. A larger denominator cannot repair an unidentified intervention.', '',
             '- Some native service failures occur before verification; they test capability refusal and output formatting.',
             '- Capture metadata is not a visual description. The text-only planner has no demonstrated image-understanding path here.',
             '- Synthetic screen faults are introduced after capture defences; they do not validate native portal handling.',
             '- The new answer oracle checks exact authored transcripts and structured facts. Other prose remains unknown and needs independent adjudication.',
             '- A permitted alternative route must exist before this fixture can support a recovery comparison.',
             '- Freeze a revised homogeneous intervention and outcome definition, retain these runs as excluded pilot data, and validate normal as well as faulty cases before confirmatory execution.', '',
             '## Raw evidence', '', f'- Pilot manifest: [{args.results.name}]({args.results.resolve()})',
             f'- Prompt-format probe: [terminal_examples_checks.json]({probe_path})', '']
    for row in episodes:
        text.append(f'- {row["case"]} / {row["condition"]} / {row["fault"]}: [run artifact]({row["artifact"]})')
    path = args.results.parent / 'REPORT.md'
    path.write_text('\n'.join(text) + '\n')
    print(path)


if __name__ == '__main__':
    main()
