# Advanced workspace integration — 14 September 2026

This release adds concrete browser operation, application controls, generated
Python projects, bounded goal planning and concurrent execution. It is not an
unlimited desktop agent or proof of autonomous system self-improvement.

## User-facing commands

| Request | Result |
| --- | --- |
| `otvori https://www.python.org` | Dedicated visible browser with actual URL and rendered DOM evidence. |
| `browse https://www.kernel.org` | Explicitly use the dedicated browser. |
| `do task Open https://www.python.org, follow the Documentation link, and report the final page title.` | Plan from observations, navigate and finish from independently checked navigation evidence. |
| `napravi zadaca ...` | Same bounded goal entry point, accepting the user's goal text. |
| `inspect app Files` | Discover available AT-SPI controls; actionable cards offer a reviewed action and expected new element. |
| `build python ~/Documents/My-statistics :: Implement mean and median with tests` | Generate a new project, test in OS isolation, optionally repair once, open in VS Code and verify the project window. |
| `evaluate tasks` / `proveri rezultati` | Per-capability historical outcomes, measured execution times and recorded code-repair results. |

Browser response cards provide Follow link, Refresh page evidence, Review field
entry and Close session. They submit ordinary durable goals and open separate
response windows. Browser fields use exact labels and read back the entered value;
approval is bound to the reviewed page URL. Application actions freeze the
process, control path, name, role and supported action, then check for the requested
new element in a fresh observation. A timeout is not a claim of successful action.

The default `workspace.controlled_browser` setting routes ordinary website-open
commands to the dedicated browser. Turning it off restores the previous default
desktop-browser launch behavior. These settings do not change the OS's browser
association or borrow the user's Firefox profile.

## Execution and isolation

The scheduler claims work under a short lock and supervises up to three concurrent
goals. It reserves shared resources for the whole goal: desktop, files, browser and
local model. A process/status read can finish while a coding task runs; competing
desktop work waits. The scheduled tick returns promptly. Shutdown cancels and
reaps supervised tasks before closing the owned browser worker. Cancellation does
not automatically replay uncertain side effects.

The core's namespace restrictions remain enabled. A private Unix socket connects
it to an owned user browser worker. Chromium runs inside a Bubblewrap environment
without home access or a network namespace connection. Its only display access is
the Wayland socket; HTTP resources are supplied through the existing pinned-DNS,
size-limited ARIES transport. The worker accepts a fixed operation list, has a
mode-600 socket and bounded memory, process count and lifetime. Browser redirects
are resolved before main-document navigation so the reported URL matches the
destination. This is a public-web adapter: POST requests, WebSockets, service
workers, uploads and downloads are unavailable. Some sites will not work fully.
Sessions expire when the worker/core closes or restarts; old cards report expiry.

Generated Python source runs in a separate Bubblewrap sandbox: no network, home,
credentials or desktop socket; the project is mounted read-only. CPU, memory,
output and elapsed time are limited. In the installed service, a bounded user unit
owns the sandbox and is stopped on cancellation. Only new project directories are
accepted. Candidate sources and failed-test output remain available for review.

Structured local-model calls use per-request output/context budgets and Ollama's
schema support; the old shared 800-token limit is not changed globally. Coding
records provider-reported token counts and execution time. Generated tests can
trigger one repair attempt. They are explicitly distinguished from independent
acceptance tests. The statistics demonstration additionally passed five separately
authored assertions in the same isolation environment.

## Goal planning and completion

The planner uses the existing catalogue, preparation, tool gates, proposals,
verifiers and durable result schema. It can issue at most eight actions. Every
decision receives observed prior results, not a claim that an action succeeded.
Only effects requested in the original goal become available to the planner;
installation, Trash, moves, field entry and application actions retain their exact
proposal boundaries. An explicit delegated `do task` goal can plan ordinary reads
and navigation without a separate approval for every model decision.

Repeated actions trigger at most one planning correction and are not re-executed.
Known navigation/title requests have a separate completion contract bound to the
requested URL, observed browser session and named link; once satisfied, ARIES
returns the observed title without speculative extra browsing. For general goals,
the final model summary is labelled as a summary of per-step evidence, not an
independent semantic verifier for every possible task. An unfamiliar request can
still fail, require review or reach its action budget.

## Reading

Trafilatura consumes HTML already fetched by the existing protected transport.
Custom comments, related widgets, scripts, navigation and fallback notices are
removed before extraction. Extraction and local-model summarization remain
separate stages; the summary retains its coverage and extractor name. The old
parser remains an explicitly labelled fallback. See
[extraction/comparison.json](../experiments/workspace/extraction/comparison.json)
for the two-page comparison; this is not a broad extraction-quality benchmark.

## Validation and remaining work

The standard test suite passed. Focused follow-up checks cover the latest planner,
browser redirect handling and UI changes. Live results are retained in
`experiments/workspace/acceptance-*.json`, including unsuccessful attempts. The
broad run at 23:22 recorded 15/16 checks: independent concurrency, Python.org DOM,
field read-back, link navigation, generated code plus five independent assertions,
real GTK control activation, and the evaluation surface passed; the planner
continued beyond the requested link. The subsequent navigation completion contract
addresses that overrun. See the final validation report for its follow-up results.

Final follow-up: **3/3** bounded navigation goals passed after the completion and
DOM-link fixes. The broad run remains recorded as 15/16; it is not relabelled as a
new full passing run. [Validation report](../experiments/workspace/advanced-validation.md).

Runtime dependencies are pinned in `requirements.txt`. A fresh checkout also needs
the Playwright browser installed with `.venv/bin/python -m playwright install chromium`,
the existing system Python GTK/AT-SPI bindings, Bubblewrap, a user systemd session
and Wayland. These dependencies are installed and exercised on this machine.

The full initial Jarvis direction is not complete. Remaining work includes broad
application-specific automation and recovery (especially inner VS Code controls),
authenticated browser interactions, account connectors, richer long-term context,
broader repeatable task benchmarks and a controlled production-improvement process.
Additional successful demonstrations must not be counted as proof of all of these.

Research sources and exact revisions are in [GITHUB_RESEARCH.md](GITHUB_RESEARCH.md).
Relevant primary documentation: [Playwright contexts](https://playwright.dev/python/docs/api/class-browsercontext),
[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
[GNOME AT-SPI actions](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Action.do_action.html)
and [VS Code accessibility](https://code.visualstudio.com/docs/configure/accessibility/accessibility).
