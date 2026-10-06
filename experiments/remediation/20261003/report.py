"""Generate today's census supplement; no acceptance claim from missing logs."""
import json
from pathlib import Path

directory = Path(__file__).parent
root = directory.parents[2]
data = json.loads((directory / 'census.json').read_text())
rows = ['# Census measured ' + data['measured_at'], '',
        f"14-day goals: {data['goal_n']}; unsuccessful states: {data['unsuccessful_n']}. "
        f"Future-dated goals excluded: {data['future_dated_goals_excluded_n']}.",
        f"Known frozen-fixture goals: {data['known_assistant_fixture_goals_n']}; "
        f"unsuccessful among them: {data['known_assistant_fixture_unsuccessful_n']}.",
        '', '| Recorded cause | All unsuccessful (n) | Excluding known fixture (n) |',
        '|---|---:|---:|']
for reason, count in data['reason_counts'].items():
    rows.append(f"| {reason} | {count} | {data['reason_counts_excluding_known_assistant_fixture'].get(reason, 0)} |")
rows += ['', data['classification'], data['non_fixture_classification_caveat'], '',
         'Unknown causes must be reviewed before declaring the leading two causes fixed.', '',
         '## SQLite observation coverage', '',
         f"Requested window: {data['locking']['window_start']} to {data['locking']['window_end']}.",
         f"Lock-message records: {data['locking']['matching_records_n']} / "
         f"{data['locking']['journal_records_n']} available journal records.",
         data['locking']['coverage_note'],
         'A zero denominator supplies no evidence of stability.', '',
         '## Registry inventory', '', '| Capability | Registered verifier |', '|---|---|']
rows += [f"| {row['name']} | {row['verifier'] or 'none'} |" for row in data['registry_capabilities']]
rows += ['', '## Spoken catalogue observations', '',
         '| Capability | Static verification marker | Observed steps (n) | Without top-level verified |',
         '|---|---|---:|---:|']
rows += [f"| {row['capability']} | {row['executor_records_verification_static']} | {row['steps_n']} | {row['unverified_steps']} |"
         for row in data['capabilities']]
rows += ['', 'Registration/static markers do not prove a verifier was called in every execution. '
         'These registry and spoken-catalogue surfaces have different names and denominators. '
         'No whole-population verification target is declared complete.', '']
rendered = '\n'.join(rows)
(directory / 'REPORT.md').write_text(rendered)
monograph = root / 'docs/ARIES_REPORT.md'
previous = monograph.read_text()
start, end = '<!-- CURRENT-CENSUS:START -->', '<!-- CURRENT-CENSUS:END -->'
block = start + '\n' + rendered + '\n' + end
if start in previous:
    previous = previous[:previous.index(start)] + block + previous[previous.index(end) + len(end):]
else:
    previous += '\n\n' + block + '\n'
monograph.write_text(previous)
print(directory / 'REPORT.md')
