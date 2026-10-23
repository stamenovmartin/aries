# Advanced integration validation — 2026-09-14

- Standard suite: `./scripts/test.sh` passed (log: `/tmp/aries-final-tests.log`).
- Follow-up workspace, coding, goal-planner, browser and native UI rendering checks passed after the final changes.
- UI client checks passed (410 assertions).
- Broad live run: [15/16 checks](acceptance-20260914-232236.json), including generated code and five independently authored acceptance cases, browser field read-back, real GTK action, concurrent progress and evaluation.
- Final navigation follow-up: [3/3 bounded goals](acceptance-20260914-233211.json) — Python About, Python Documentation and kernel.org. Known completion contracts stop these goals from wandering beyond their requested result.
- Earlier failed runs remain beside these files. The final navigation follow-up is not represented as a new full 16/16 run.
- Installed package database confirmed VS Code revision 263, Firefox 8863, GIMP 561 and VLC 3777. This is installation-state verification, not a new fresh-install benchmark.
- Long-running login-session, nested-shell and display-timeout integration suites were not rerun for this change.

Screens: `screens/advanced-monitor.png`, `screens/advanced-development.png`, `screens/advanced-browser.png`.

This evidence validates bounded workflows. It does not establish unrestricted application control, broad autonomous semantic correctness, authenticated account connectors or production self-improvement.
