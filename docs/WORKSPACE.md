# Goal workspace — 14 September 2026

Latest update: the catalogue now contains 32 capabilities. See
[ADVANCED_WORKSPACE.md](ADVANCED_WORKSPACE.md) for the visible controlled browser,
AT-SPI actions, generated coding, bounded goal planner, concurrent execution and
evaluation report. Earlier sections below describe the preceding milestones.

ARIES Search (Super+Space) and the Control Centre command palette now submit the
same durable goals. Enter starts the work and opens its dashboard. Typing alone
has no side effects. Each dashboard retains steps, observed results, source links,
failures, related goals and explicit personal context. It supports cancellation,
review of sensitive changes and resuming the exact approved action.

## Twenty bounded capabilities

| Capability | Example |
|---|---|
| Open application | `open Firefox` |
| Open website | `otvori https://github.com` |
| Open file/folder | `open ~/Documents` |
| Search the web | `search web for Linux AI agent desktop` |
| Research news | `istrazi AI agents` |
| Processes | `show processes` |
| Refresh news | `refresh news` |
| Briefing | `morning brief` |
| Health | `run system health` |
| System dashboard | `system status` |
| Installed applications | `list apps` |
| Find files | `find files notes.txt` |
| List folder | `list folder ~/Documents` |
| Read file | `read file ~/Documents/notes.txt` |
| Create folder | `create folder ~/Documents/Research` |
| Create file | `create file ~/Documents/Research/notes.txt :: My notes` |
| Move file | `move file ~/Documents/Research/notes.txt to ~/Documents/Research/saved.txt` |
| Trash file | `trash file ~/Documents/Research/saved.txt` |
| Install supported application | `install PyCharm` |
| Remember explicit fact | `remember I am researching Linux desktops` |

The UI also provides catalogue examples backed by structured arguments. Requests
can contain up to six steps, for example
`istrazi AI agents; otvori https://www.kernel.org/`.
Unknown language can use the configured local model to translate into this closed
vocabulary. There is no arbitrary shell execution or unrestricted GUI control.

## Execution and evidence

The queue persists in SQLite; jobs have cancellation, heartbeat, a 30-minute
limit and a maximum of twenty active goals. Research collectors can run together;
mutating steps execute in order. Interrupted side effects are never replayed
automatically. Retention is thirty days for goals. Explicit memories last until
forgotten; task/audit records have their own retention.

Desktop actions use Operator gates, audit and independent observation. A browser
window title is circumstantial evidence, not proof of its complete page contents.
Search additionally checks that the query appears in a visible browser title.
Folder opening checks the file manager's actual open locations. UTF-8 survives
D-Bus decoding. GUI processes launch in separate user services, so the core's
sandbox and restarts do not own their lifetime.

File writes are confined to ordinary paths under the home directory and never
overwrite existing bytes. Move and Trash require review of the exact frozen target
and refuse changed files. Trash verifies a matching recoverable Trash entry.
Installation resolves an exact Snap revision before approval, then invokes system
polkit authentication and checks the installed revision. Current package mappings
are PyCharm, Firefox, VLC and GIMP. ARIES never collects an administrator password.
A new installation may need the person's response to the system dialog.

Research uses enabled local news feeds and, when allowed, Google News RSS. Cards
identify snippets as search evidence; full articles are not represented as read.
Source failures remain visible. External text cannot supply executable steps.
Explicit private memories are not appended to public search queries.

## Automatic dashboards

The installed system now has public research and scheduled dashboards enabled for
artificial intelligence, AI agents and cybersecurity, at a sixty-minute interval.
The automation dispatcher is enabled. The first three topic jobs were submitted
through the real automation runner. Settings expose these topics and switches.
Scheduled topics only collect research; they cannot install or change files.

## Evaluation and limits

`./scripts/test.sh` passes, including 89 workspace assertions, 94 Operator checks,
UI contracts/rendering and the vendored engine. `./scripts/aries-e2e` passes 31 real
desktop assertions; `./scripts/aries-smoke` passes all 13 installed-system checks.

The [live acceptance report](../experiments/workspace/live-results.md) records
20/20 requests reaching their verified completion criteria on the installed
system. It uses YouTube, DuckDuckGo, real news sources and disposable local files.
Separate command-router journeys opened GitHub and kernel.org and built an AI
agents dashboard. Earlier 19/20 and 17/20 runs are retained: they exposed a hidden
browser tab and the service/Snap launch issue rather than being counted as passes.

**Installation qualification:** the live installation request verified an already
installed Firefox revision. It did not exercise a fresh install. The new-install,
approval and revision-verification protocol has controlled package-manager tests;
a fresh PyCharm installation remains unmeasured on this machine.

This is engineering acceptance for twenty capabilities. It is not evidence of
unlimited Jarvis behavior, autonomous GUI interaction, a learned agent team, or a
research advantage over a baseline. Arbitrary task-specific interactive dashboards
and automatic self-improvement remain future work; current dashboards use reusable
native cards for the supported tasks.

## Command-deck screens

The September 14 follow-up adds a dark cyan native interface with distinct layouts:

- `otvori vesti`: News Radar, source-linked article cards and source controls.
- `otvori sistem`: live CPU load, memory, disk, temperature and GPU readings.
- `otvori fajlovi`: locations, file search and actual file-task history.
- `otvori istrazuvanje`: research/command workspace, results and source evidence.
- `otvori monitoring` or `otvori evaluacija`: active/pending tasks, automation
  health, recent completion counts, measured elapsed time and execution timeline.

System and Monitoring poll every five seconds while visible and stop when hidden.
System telemetry uses a shared three-second read-only cache; unavailable readings
stay unavailable. CPU load per core is explicitly not labelled CPU usage. Monitoring
includes old pending work even when it falls outside the latest twenty-five goals.
Elapsed time includes queueing. Cancelled and pending tasks are outside the recent
attempt denominator; partial/failed/interrupted outcomes are included.

The UI's command router and Operator recognize the same screen aliases. It never
tries to install or launch an imaginary application called “vesti” or “monitoring”.
All new pages render against real API payloads. Reproducible screenshots live in
[experiments/workspace/screens](../experiments/workspace/screens); capture them with
`/usr/bin/python3 experiments/workspace/capture_screens.py` against a running core.
The monitor distinguishes operational evidence from still-unmeasured research
claims and self-improvement.

## Independent responses and AI reading (final user direction)

The system control centre remains available, but `aries-ui --section ...` and
commands now open separate, movable ResponseWindows. News, Applications, System
and a reading response can coexist on the desktop. A goal is addressed by its
persisted id; reopening it focuses its own response. Closing the window does not
cancel background work. The original control centre can retain internal tabs for
system administration; ordinary responses no longer require that container.

Added capability 21, `read_article`: `read article https://...` or “Read with ARIES”
on a news card fetches the public HTML, extracts article text, excludes scripts,
navigation and comments, and summarizes all extracted chunks with the local model.
The response contains a generated title, concise summary, key points, source link
and source image when safely available. Summaries are capped at 180 words. A page
requiring login/JavaScript or exceeding the reading limits produces an explicit
failure rather than a claim of complete reading. No browser session is borrowed.

Images come from publisher metadata, are limited by bytes and dimensions, and
retain their source attribution. They are not invented as evidence. AI research
briefings are enabled in the installed system; they summarize collected excerpts
and label that coverage explicitly. Reading a source is a separate full-extraction
operation. Model output never becomes an executable UI layout, command or URL.

Live evidence: a MIT News article on agentic AI produced an AI summary, key points
and its source image. The final recorded response read 6,996 extracted characters in two chunks,
with an attributed source image. The reader uses hierarchical reduction to retain
complete extracted coverage within local model context. Independent-window
acceptance verified three separate windows, no required control-centre container,
and preservation of the saved goal when its response is closed. [Reading screenshot](../experiments/workspace/screens/reading.png).

Design references consulted at the user's request:
- [Cantina Creative: Iron Man 3 HUD design](https://www.cantinacreative.com/film/iron-man-3).
- [Jorge Almeida: Iron Man 2 discovery and tracing interfaces](https://jorgeonline.me/Iron-Man-2).
- [Andy Polaine's interaction-design interview](https://www.polaine.com/2008/05/iron-mans-hud-and-interaction-design/).

The design interpretation is task-specific surfaces and concise responses, with
supporting evidence revealed below. Film graphics are references, not copied assets.
This does not establish unrestricted Jarvis capability or autonomous self-improvement.

## Requested applications update

VS Code is now the primary development application in the installation surface
and command examples. `VS Code`, `vscode`, `Visual Studio Code` and `code` resolve
to Microsoft's `code` Snap; Firefox, VLC and GIMP remain the other displayed
applications. The user explicitly requested installing these applications and
stopping PyCharm. The existing PyCharm backend mapping remains compatible with
older records, but it is no longer offered in the Applications catalogue UI.

## First accessibility and development integration

The catalogue now has 23 entries. `inspect app VS Code` reads a bounded AT-SPI
snapshot through system Python and reports partial coverage when only windows
are exposed. It does not yet click or type. `create python demo ~/Documents/ARIES-python-demo`
creates a new fixed Python demo and environment, executes it, records the output,
opens VS Code and checks the artifacts and project window. Existing directories
are never reused. Both use the existing goal dashboards and monitoring; project
creation uses the Operator gates. See [JARVIS_PROGRESS.md](JARVIS_PROGRESS.md) for
the implementation boundaries, live result and assessment against the original idea.
