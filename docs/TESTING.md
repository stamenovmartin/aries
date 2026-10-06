# ARIES — Testing

## Two levels of done

**A milestone is complete only when both are green.**

| | |
|---|---|
| **ENGINEERING GREEN** | unit, integration and security tests pass — `./scripts/test.sh` |
| **PRODUCT GREEN** | real user journeys work on the **installed** system — `./scripts/aries-e2e`, `./scripts/aries-smoke` |

This is a permanent rule, and it was bought expensively. M13's suite was green at
1511 assertions while `scripts/aries-ui` exec'd itself in an infinite loop, so the
Control Centre could never open — every navigate action in ARIES Search, every
notification click and every dock press was a silent no-op for days.

That is not a coverage gap, it is a gap **in kind**. A launcher is not a
component; it is the *seam* between components, and seams are exactly what
component tests skip by construction. Adding more component tests would not have
found it, and did not.

Three practical consequences:

* **Test the installed artifact**, not only the source. The desktop runs
  `/usr/local/share/...`, not the repository.
* **Never mock the launcher** in a test meant to prove the launcher.
* **Know which revision is running.** `aries version` compares source, installed
  and running; `./scripts/aries-smoke` fails if they differ.

## Two levels of done, for research

A third level applies to capabilities that make a claim: see
[EXPERIMENTS.md](EXPERIMENTS.md). A feature is *engineering-complete* when it
works and passes tests; it is *research-complete* only when it has been evaluated
against a baseline. **Never use implementation test count as evidence that a
research hypothesis is true.**


```bash
cd ~/aries && ./scripts/test.sh
```

**1541 assertions**, all green. Every test file runs in its own process with its own SQLite
database and `APP_ENV=test`.

## What runs

| suite | checks | what it pins |
|---|---|---|
| engine (`agentic_core`) | 13 files | the inherited orchestration guarantees |
| engine reference example | 10 | the Linux agent starter still works |
| `test_settings.py` | 32 | §30 precedence, on read **and** write |
| `test_health.py` | 33 | probes measure, judgement is separate, baselines soften only |
| `test_notify.py` | 22 | the three notification gates |
| `test_automations.py` | 52 | genome, dispatcher pacing, honest health |
| `test_sources.py` | 89 | what may be registered, and what is refused |
| `test_interests.py` | 73 | word boundaries, noisy-OR, avoid disqualifies |
| `test_news.py` | 38 | the workflow graph, dedup, caps, circuit breaker |
| `test_learning.py` | 39 | Wilson intervals; mostly, declining to act |
| `test_reversal.py` | 63 | hysteresis, five diagnoses, pending confirmation |
| `test_feedback.py` | 73 | classification, scope, asking rather than guessing |
| `test_brief.py` | 44 | parallel collection, honest absence, time-of-day |
| `test_security.py` | 53 | loopback gate, SSRF, hostile feeds, input bounds |
| `test_runtime.py` | 49 | unit shape, lifecycle, honest state when it is not installed |
| `test_session.py` | 65 | the five login-session files, and that they agree with each other |
| `test_shell.py` | 138 | the shell's core side, plus one regression test per M13 bug | the shell's core side: router, search, status, tokens |
| `test_power.py` | 145 | Background Mode: the real inhibitor, taken and released; the resource policy's two gates, hysteresis and budget |
| `test_connect.py` | 120 | a credential in no column of any table; content that can never become an action |
| `test_operator.py` | 85 | the verifier's independence, the evidence ladder, and that `unverifiable` is neither success nor dishonesty |
| `test_lifecycle.py` | 136 | retention that cannot starve a dependant; the working set released on every outcome |
| **`test_ui_contract.py`** | **91** | **the UI/core contract** |
| **`test_ui_render.py`** | **2** | **every screen renders live payloads** (the checks it reports are the subprocess's) |
| **`test_ui_client.py`** | **317** | **the Control Centre's own logic** |

## Two suites for the UI, because there are two processes

The Control Centre runs on the system interpreter and imports nothing from `aries` (ADR-0004),
so it cannot be tested by importing ARIES objects. What needs pinning is the **contract** between
them, and it is tested from both sides.

**`test_ui_contract.py`** (venv) drives the real ASGI app and asserts that every endpoint the UI
reads exists and returns the keys it reads, declared as data in `aries_ui/contract.py`. It also
covers the write paths: settings through the boundary are audited with the authenticated
principal; explicit and learned arrive as separate fields; automations enable and disable;
feedback returns a question rather than a guess; a refusal reaches the UI as a refusal;
unavailable integrations are reported honestly.

This exists because the gap bit. When reversal detection sliced the evidence endpoint by time
and source, the Learning screen kept reading the old flat keys and rendered an error page —
and nothing failed until a human looked.

**`test_ui_render.py`** (both) closes the other half of that gap. The contract suite proves the
endpoints return the right keys; nothing proved a screen could build a widget tree out of them —
nine pages, and `render()` had never been called by anything but the user. It captures live
payloads in the venv, then runs `tests/ui_render.py` on the system interpreter, which is the only
one with `gi`. GTK4 constructs and packs widgets with no display at all — only presenting a window
needs one — which is enough to catch missing keys, wrong types and bad markup, all of which throw
during construction. It also asserts each page puts *something* on screen: a page that renders an
empty tree is a blank screen with no error.

**`test_ui_client.py`** (system python) tests what can be wrong without being visible: URL
construction, the error vocabulary, results arriving on the main loop, **stale replies being
dropped**, per-key cancellation, intent routing, and UTC-to-local conversion. No window is
opened.

## End-to-end journeys — the product-green half

```bash
./scripts/aries-smoke          # "can I use ARIES right now?" — five seconds
./scripts/aries-smoke --deep   # …and prove the Control Centre draws
./scripts/aries-e2e            # every journey, real windows
```

`aries-e2e` starts real applications and asserts on **observable state after
crossing a process boundary**. Nothing is mocked; the launcher especially is not,
because the launcher is what broke.

The destination is verified by asking the window, not by trusting the caller: the
Control Centre exports its current section as the **state of a GAction**, and a
separate process reads it back over D-Bus. "Where it was told to go" and "where it
is" are different facts, and only the second one is a test.

| journey | what is actually checked |
|---|---|
| launcher sanity | the chain from PATH terminates, reaches python, no step execs itself |
| cold start | not running → asking for a section starts it *on that section* |
| warm start | already running → asking navigates the existing window |
| every section | all nine land where asked, deterministically |
| unknown section | refused, window unmoved — not silently swallowed |
| router → destination | `news` resolves *and* the resolved action actually opens it |
| close, reopen | quitting and asking again works |
| launch an application | the process exists afterwards that did not before |
| degraded | the shell answers and reports its own state |
| staleness | the running build id equals the source build id |

`aries-smoke` is the fast version: the handful of questions whose answer is "the
product is broken", exiting non-zero if any user-facing path is.

## The shell's HTTP layer, outside a compositor

```bash
./scripts/test-shell-api.sh
```

`shell/aries@aries.local/lib/api.js` imports Gio, GLib, Soup and its own logger —
and nothing from `gnome-shell`. So it loads in plain `gjs`, which is the only way
to produce the states the desktop has to survive: a server that never answers, a
refused connection, a 200 carrying HTML, a truncated body, a reply that arrives
after the widget asking for it is gone.

A fake ARIES (`tests/shell/fake_aries.py`) serves each failure on its own path.
28 assertions, in `scripts/test.sh`.

Two bugs came out of writing it, and both were in production code rather than in
the test: `request()` used a module constant while `get base()` returned
something else — two sources of truth for one address, so overriding it changed
what the getter said and not where requests went; and an error status with a
non-JSON body was reported as *"unreadable reply"*, which sends the reader
looking at the parser when the news was the 500.

## The shell, in a GNOME of its own

```bash
./scripts/test-shell.sh
```

A GNOME Shell extension runs inside `gnome-shell`, and on Wayland a shell that
throws during startup cannot be restarted without logging out. Testing by
enabling it in the live session is therefore a test whose failure mode is losing
the user's desktop.

So the harness starts a **headless GNOME Shell against a virtual monitor on its
own D-Bus session** — a complete, isolated GNOME with real Mutter and real
extension loading — enables the extension there, and checks it reached ENABLED,
logged no component failure, threw no exception, and tore down cleanly. The
user's session is never involved.

It found every bug in that milestone before a person saw one: a parameter GNOME
50 no longer accepts, a `ScrollView` given a non-scrollable child, `Shell.App`
confused with `Gio.DesktopAppInfo`, and overlays the LayoutManager forced visible
because they had opted into `trackFullscreen`.

It asserts more than "it loaded", which said almost nothing — every component is
guarded, so the extension reaches ENABLED whether six surfaces came up or one. It
checks that **every named surface was built**, that ARIES Search and the launcher
respond to being driven over D-Bus, and that the extension **enables cleanly a
second time**. That last is the real teardown test: a leak fails on the second
enable, not the first.

The Python side asserts the *architecture* rather than promising it: no shell
file reaches a database, none makes a synchronous call, the generated stylesheet
matches the tokens exactly, and the severity vocabulary is the same one the
Control Centre uses.

## The login session, proved before it is installed

```bash
./scripts/test-session.sh          # or: ./scripts/aries-session verify
```

A malformed session definition is the one failure in this project that happens
*before* the user has a desktop to fix it from. So the session is proved with
**nothing installed**: `gnome-shell` finds modes by walking `XDG_DATA_DIRS`, so
pointing that at a staging directory loads the real mode file in a real GNOME
Shell started exactly as the session starts it — `--mode=aries` — in a nested
headless session.

It asserts the mode loads, the extension becomes ACTIVE *because the session says
so*, that the system copy won rather than the per-user one, that every surface
came up, and that Ubuntu's own mode is untouched.

`test_session.py` cross-checks the five files against each other — the entry
names a session, the session file exists for that name, the drop-in starts a mode
whose file exists, the mode enables the uuid the extension actually declares.
Four of those five agreements are invisible until a login fails.

## A harness that changed the user's desktop

Worth recording as a rule rather than a bug. `dconf` is per-**user**, not
per-session: `gnome-extensions enable/disable` run inside a nested shell writes
the same keys the real desktop reads. The nested harness had been switching
extensions on and off, and the live session quietly lost its dock and its desktop
icons — and gained `aries@aries.local` in `disabled-extensions`, which is exactly
the key that silently overrides a session mode.

Both harnesses now record those two keys before anything runs and restore them on
every exit path, and `test_session.py` asserts they still do.

## The one test that is not in `test.sh`

```bash
./scripts/test-background-mode.sh 16        # 16 real minutes
```

Background Mode is a claim about what is still true *later*, so part of it can only be tested by
waiting. The test enables Background Mode, lets the display actually blank, waits past the
configured suspend timeout, and checks what survived. It is excluded from `test.sh` because it
takes minutes and because it changes the machine's display timeout — which it records first and
puts back afterwards, along with every setting it borrows.

**What it proves.** That ARIES takes a `sleep`/`block` inhibitor and that *logind itself* lists
it; that the display blanks; that the timeout is restored to the exact previous value; that ARIES
kept running and automations actually fired across the interval; that the machine did not suspend;
and that everything is released when Background Mode is switched off.

**What waiting does not prove.** That the inhibitor *prevented* a suspend. This machine has
`sleep-inactive-ac-type=nothing` and no battery, so it was never going to suspend anyway — waiting
an hour and finding it awake would be a test passing for the wrong reason, and the test says so in
its own output rather than claiming the credit. What stands in for it is the mechanism: logind's
contract is that a `block` lock on `sleep` makes a non-interactive suspend fail, and the test
asserts ARIES holds exactly that, as logind reports it. **The suspend is deliberately never
triggered** — suspending the user's machine to prove a point is not an acceptable test.

**How a suspend would be detected.** Wall-clock and monotonic time advance together while awake
and diverge across a suspend, so the test compares them, and also greps the journal for logind's
own sleep messages.

## Conventions

* A test asserts a **decision**, not a line of code. `check("a machine that is always critically
  hot is still critically hot", …)` reads as the rule it defends.
* Adversarial cases are built as real artefacts — an actual symlink into an excluded directory,
  an actual HTTP server returning 302 to the metadata endpoint — not as strings.
* **A test that arranges state cannot test a default.** Entry 004 shipped an automation enabled
  because every test set the value first.
* **A checker must not read its own documentation as a violation.** Both shell
  scans first failed against the paragraphs explaining why the construct is
  forbidden. Comments are stripped before scanning — otherwise the "fix" is to
  delete the explanation.
* **Injected where a real one cannot be produced on demand.** The resource policy is tested
  against the machine's own sensors where they can be read, and against pinned measurements
  where they cannot: a test must not need the machine to reach 85 °C to prove that 85 °C defers
  heavy work. The *decision* is never mocked — only what it measures.
* **A test that changes the machine puts it back.** `test_power.py` patches the display-timeout
  writer so the suite never touches the real one; the elapsed-time test records every value it
  borrows and restores it, and asserts that it did.
* Unhappy paths are asserted on their **data**, not only their verdict. Entry 007's worst bug
  survived because nothing checked what a total failure *returns*.

## Not tested

GTK rendering itself. Screenshots are produced by rendering widgets to a texture offscreen,
which works without compositor permission, but nothing asserts on pixels. Visual regression
would need a baseline corpus and is not worth its maintenance at this size.
