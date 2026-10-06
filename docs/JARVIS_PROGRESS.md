# ARIES progress against the original Jarvis direction

Assessment updated 2026-09-14 after the advanced integration work.
**Approximately 65/100** (weighted estimate: 64; uncertainty range 60–70).
This is an engineering estimate, not a benchmark score or percentage of remaining
implementation time. The original fictional Jarvis direction remains broader than
this bounded Linux product. It has not reached 100%.

| Area | Available points | Estimated earned | Current evidence and remaining gap |
| --- | ---: | ---: | --- |
| Independent response windows and dashboards | 15 | 13 | Separate task windows now include browser controls, development outputs and evaluation. Layouts remain reusable native components. |
| Commands and bounded end-to-end workflows | 15 | 12 | 32 catalogue entries and an eight-action goal planner. General language and unfamiliar goals still need broader evaluation. |
| Work inside desktop applications | 20 | 7 | Gated AT-SPI actions with changed-element checks, fixed and generated Python workflows. Live GTK action verified; VS Code still exposes no inner controls on this installation. |
| Browser interaction | 10 | 7 | Real visible public sessions, actual DOM/URL, link navigation, field read-back and session controls. No borrowed accounts, POST submissions, uploads or downloads. |
| News, research and reading | 10 | 8 | Trafilatura integration, safe existing transport, AI summaries and source images. Extraction comparison covers only a small fixture set. |
| Background execution and coordination | 10 | 7 | Up to three independent goals; shared desktop/files/browser/model resources coordinated; cancellation and shutdown handling. Not arbitrary distributed orchestration. |
| Evaluation and improvement | 15 | 8 | Measured tool time and coding token usage, outcome reports, bounded generated-code repair, independent acceptance cases. No proven autonomous production self-improvement. |
| Personal context and conversational continuity | 5 | 2 | Explicit memories remain; broad adaptive long-term assistance and account connectors remain incomplete. |
| **Total** | **100** | **64** | **Rounded to approximately 65/100; do not present as measured success rate.** |

## Advanced integration delivered

See [ADVANCED_WORKSPACE.md](ADVANCED_WORKSPACE.md) for commands, runtime boundaries,
validation evidence and the remaining work. The 45/100 assessment was the earlier
baseline; 60/100 was the intermediate status before final integration checks.

## First GitHub-informed integration delivered

The GNOME recommendation to use libatspi through GObject introspection is now
implemented as a bounded system-Python worker. `inspect app VS Code` (also
`proveri aplikacija VS Code`) runs through the existing durable goal queue and
renders observation cards in the response dashboard. It selects an application
by exact name/alias, limits traversal and elapsed time, suppresses password-node
labels and descendants, and terminates/reaps an unresponsive worker. It does not
retrieve text/value interfaces or invoke GUI actions. Labels are local untrusted
evidence and are not submitted to a model by this capability.

The live VS Code observation returned application/window nodes but **zero inner
elements**. ARIES records that as **partial**, not complete application access.
Binding availability does not establish usable control access in every app.

The OSWorld artifact-verification pattern informed a first development workflow:
`create python demo ~/Documents/ARIES-python-demo` (also
`napravi python proekt ~/Documents/ARIES-python-demo`). This creates a new folder,
writes a fixed inspectable demo, creates a Python environment without downloading
packages, runs it in isolated Python mode, records stdout/exit code, opens VS Code,
and checks source, environment, execution record and project window. Existing
directories are refused. The existing Operator switch, tool gates and audit apply.

This is a fixed demo scaffold, not arbitrary AI-generated program execution or
editing through VS Code controls. Python executes as a subprocess; VS Code presents
the resulting project. The window title supplies circumstantial UI evidence; the
file checks and recorded process output supply the workflow's artifact evidence.
Interrupted workflows may leave their newly created project directory for inspection;
they are not replayed over it automatically.

Live run: `python_project` completed with expected output `total: 55` and a matching
VS Code project window. `inspect_app` correctly returned partial coverage.
See [integration-results.json](../experiments/workspace/integration-results.json).

## Original next priorities (historical; see advanced report for current status)

1. Enable and verify inner application accessibility, then introduce precisely
   targeted gated actions and recovery checks.
2. Add a dedicated browser adapter with DOM observations and exact page verifiers.
3. Compare and integrate article extraction against saved real-page fixtures.
4. Extend existing orchestration with resource-aware concurrency.
5. Run a fixed, repeated evaluation set and report completion, partial outcomes,
   latency and recovery separately. Autonomous improvement is not yet established.

Source selection and pinned revisions: [GITHUB_RESEARCH.md](GITHUB_RESEARCH.md).

## Window and learning follow-up

See [WINDOWS_AND_LEARNING.md](WINDOWS_AND_LEARNING.md): compact top navigation,
6/6 live native window controls, 5/5 live browser-cleanup checks, current desktop
observation, explicit standing rules and separately recorded implementation
lessons. These changes do not establish model-weight RL or unrestricted app
control; the approximately 65/100 maturity estimate remains an estimate.

## Task review follow-up

[Task reviews](TASK_REVIEW_LEARNING.md) now bind explicit human judgments to
bounded task evidence and supply relevant historical corrections to planning.
Counts remain separate from execution success. This is experience retrieval,
not trained reinforcement learning or proof of better general task success.

## Version comparison follow-up

[Learning comparison](LEARNING_COMPARISON.md) adds reproducible paired retrieval
evaluation, visible regressions and an explicit version selector with rollback.
The first developer fixture scored 15/20 vs 19/20; this is not a general
end-to-end improvement claim or model-weight RL.

## Recovery follow-up

[Task recovery](TASK_RECOVERY.md) adds explicit continuation for saved bounded
plans, with effect rechecks and no mutation replay. Dynamic agent/browser
reconstruction remains incomplete; this does not establish general recovery.

### Application window reuse

Open-app now reuses exact observed app windows and verifies visible focus. The
new shell focus command passed the isolated real-window harness. A new login is
required for its use in the current desktop; unknown inventory and stale targets
stop without launching duplicates. See `WINDOWS_AND_LEARNING.md`.
