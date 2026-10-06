# Window navigation and explicit learning

Native ARIES windows use small section icons beside ARIES, without a sidebar.
Every icon has an accessible label and tooltip; a narrow header scrolls its icons.
Window title bars explicitly expose minimize, maximize and close. F11 toggles
full screen. Long setting values truncate with full-value tooltips instead of
forcing a window wider than its display.

The desktop extension now places 18px application icons beside the ARIES mark.
The all-applications icon opens the launcher. It no longer creates bottom/side
dock chrome. This extension passed a real isolated GNOME load/disable/re-enable
check. **The running Wayland shell keeps cached modules until the next login.**
The native UI updates independently; no logout was forced.

## Window ownership and completion

- A new temporary result window closes 45 seconds after observing `done`.
- Pin keeps it open. Deliberately reopened history stays open. Failures and
  approval requests remain visible. Results remain in the durable task history.
- A finished/failed/cancelled agent task closes only its own controlled browser
  contexts. Ownership is recorded by the browser worker when opening a context,
  including the small interval before the step result reaches the database.
- Paused approval requests keep their browser context. A direct command to open
  a website leaves that website open for the user. Existing personal browser
  windows and editors with potentially unsaved work are not closed by this rule.
- Monitor reads current controlled browser state and the desktop's real window
  list, including focus/minimization. Failed observation is displayed as
  unavailable, not as an empty/closed desktop. The planner receives a fresh
  observation before selecting its next action.

## Learning

Write feedback in Learning and select **Remember for future tasks** for a
standing rule. Supported corrections update the corresponding typed setting.
Other explicit global rules are saved, shown in history and supplied to future
bounded goal plans (latest 12, at most 1,000 characters each). A newer explicit
preference takes precedence over an older conflicting one. Retire rule removes
an unapplied standing rule from future planner context while keeping its history.

Implementation notes have their own provenance and never execute correction
patterns or mutate settings. Record change batches with
`./scripts/aries-record-learning experiments/learning/<record>.json`; the planner
receives the latest six lessons separately from explicit user rules. The root
`AGENTS.md` preserves this user-requested workflow for future code changes.

This is preference learning and operational evaluation, not model-weight RL.
No reward labels are fabricated from these messages, and no unattended model
training is enabled. Rules do not expand the action catalogue or grant effects
outside the current task. The RL target is marked as future in the architecture.

Two settings control cleanup: `workspace.auto_close_tools` and
`workspace.auto_close_results`. Supported feedback examples include “Always
close temporary agent browsers” and “Always keep completed result windows open”.

## Evidence

- Standard suite passed: `/tmp/aries-navigation-learning-tests.log`.
- Follow-up planner, workspace, browser, UI rendering and 410 UI client checks passed.
- Lifecycle/ownership/feedback regressions: `tests/test_window_lifecycle.py`.
- Real GTK state transitions: `experiments/workspace/verify_window_controls.json`
  (6/6 checks, including independent compositor confirmation of minimization).
- Real public browser completion/cleanup: `experiments/workspace/verify_browser_cleanup.json`.
- Explicit saved user feedback: `experiments/workspace/navigation-learning-validation.json`.
- Architecture: [interactive view](architecture/index.html), [Mermaid source](architecture/jarvis.mmd),
  [SVG](architecture/jarvis.svg), [Markdown](JARVIS_ARCHITECTURE.md).

## Reusing an application's existing window

`open_app` observes the shell immediately before launching. An exact desktop
application ID match reuses the existing window, preferring the focused window,
then an unminimised window. Titles are never used to choose an app. A focused,
visible match needs no action; other matches use the separate `FocusWindow`
D-Bus method with both the observed stable window ID and application ID. The
shell checks these again before restoring, switching workspace and focusing.
It never launches or closes a window through this method.

A stale target or unavailable inventory stops the open attempt instead of
launching a possible duplicate. The ordinary audited open-app tool gates still
apply. Independent verification now requires a focused, unminimised window with
matching app/class identity; a process or a title mentioning an app is insufficient.
VS Code aliases are normalised for both action and verification.

This requires a new login to load the changed GNOME extension. Until then,
already-focused reuse works, but a missing FocusWindow method is reported with
its reason, without launching a replacement. Opening an explicit URL remains a
separate operation; this does not merge browser tabs or close personal windows.
There remains a race with applications manually launched after the inventory
snapshot. Exact shell app identity is required for reuse; mismatched launcher
and runtime IDs cannot currently be reconciled automatically.

Validation: nine operator regressions cover reuse, already-focused state,
stale targets, unavailable inventory, title spoofing, presentation and VS Code
aliases. `tests/integration/focus_window_probe.py` also passed inside the isolated
GNOME harness: a real minimised GTK window was restored and focused with the same
ID and no duplicate, while wrong app identity and stale IDs were refused.
