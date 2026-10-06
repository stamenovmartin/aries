# ARIES — Error Log

Bugs found while building, and what each one taught. The Build Journal records these in
context; this is the index, so a recurring shape is visible as a shape.

Recorded because the same mistakes keep arriving in new modules. Two have now happened
**twice**, in different subsystems, months of work apart — which is the argument for a
convention rather than for being more careful.

## Recurring

### Two clocks

| | |
|---|---|
| **Entry 003** | Notification cooldown compared `datetime.now()` (local) against a `func.now()` timestamp (UTC). A seconds-old notification read as two hours old; west of UTC the age would be **negative** and the repeat gate would fail open. |
| **Entry 009** | A re-rendered brief printed `18:54` for a brief produced at `20:54` — `created_at` is UTC, formatted as local. |

**Convention:** database timestamps are UTC. Anything shown to a human is converted at the
point of display. Anything compared against a stored timestamp uses `utcnow()`. Where both
clocks legitimately appear in one function, name them (`now_local`, `now_utc`).

### A reporting step downstream of what it reports

| | |
|---|---|
| **Entry 007** | When every news source failed, `deliver` skipped as a dependent — so the pass returned an empty result and **a run in which every source was dead was recorded as a success**. |
| **Entry 009** | The same design, caught before it shipped: gating brief sections on `briefing.sections` would have let a disabled section skip `compose`. |

**Convention:** the node that assembles or reports depends only on the node that starts the
work, never on the nodes whose outcomes it describes.

### Unknown is not zero

Appears in Entries 003 (health baselines, automation success rate), 005 (source useful rate),
008 (engagement rate), and as `reversal_rate` in this entry. Every one reports `null` with a
reason. A new thing reported as `0.0` sorts last, looks broken, and — in the sources case —
would never have been consulted again, so it could never have proved otherwise.

### A default written before the thing it configures

| | |
|---|---|
| **Entry 009** | `briefing.sections` was defined in Entry 002, before any collector existed. It named a section that was never built and omitted the three that mattered most. |

**Convention:** a setting defined ahead of its consumer is a guess. Revisit it when the
consumer lands; `choices` on the setting makes a stale name a validation error rather than a
silent no-op.

### Two meanings sharing one signal

| | |
|---|---|
| **Entry 003 onward** | `null` vs `0` — "unknown" and "zero" are different facts |
| **Entry 011** | `info` mapped to the success colour, so *"Not built yet"* rendered with a green tick |
| **Entry 011** | A page action packed where the title goes, reading as a heading |

**Convention:** a signal — a colour, a position, a number — carries one meaning. If two states
share it, the signal means neither.

### A boundary removes the compiler

| | |
|---|---|
| **Entry 011** | The UI read `/learning/evidence`'s old flat keys after Entry 010 sliced it by time and source. The Learning screen rendered an error page; nothing failed until a human looked. |

**Convention:** where two processes cannot import each other, the expectation is declared as
data (`aries_ui/contract.py`) and a test enforces it.

### Clocks, a third time — now in a test

| | |
|---|---|
| **Entry 012** | `test_notify.py` and `test_news.py` began failing with every check passing. It had gone past 22:00, quiet hours had started, and notifications the tests expected *delivered* were correctly being *held until morning*. They had passed at 20:5x the same evening. |

**Convention:** a test that reads the wall clock must pin it. `emit(..., now=NOON)` or disable
the time-dependent policy — a test that fails only in the evening fails when nobody is looking.

### Exit zero is not evidence

Five instances in one day, in five subsystems, found by five agents who were not talking to
each other. That is not five bugs, it is one shape.

| | |
|---|---|
| **Entry 018** | `org.freedesktop.portal.Screenshot` returned response code **0** with a valid 1920×1080 PNG whose every pixel was zero. The screen was blanked (`idle-delay` is 60 s here), so the compositor painted nothing. A successful call, a well-formed file, no image. |
| **Entry 019** | `systemctl show <unit-that-does-not-exist>` exits **0** and reports `LoadState=not-found`. Read only the exit status and a service that never existed looks like a service that is merely stopped. |
| **Entry 020** | `nmcli -t -f GENERAL.STATE connection show <inactive-profile>` prints an empty string and exits **0**, because the whole `GENERAL.*` group only exists while a profile is active. An inactive profile and an unreadable one are indistinguishable from the exit code. |
| **Entry 021** | `Mutter.RemoteDesktop.NotifyKeyboardKeysym` accepted Cyrillic keysyms and typed **nothing**. Mutter resolves each keysym against the active keyboard layout; on a Latin layout there is no keycode, so the character is dropped and no error is raised anywhere. `'aries42'` worked exactly; `'шар'` produced `''`. |
| **Entry 022** | `Mutter.SetCrtcGamma` accepted a **1025-entry** ramp where the hardware table is 1024, without complaint. The wrong size was only visible on reading the ramp back. |

**Convention:** a capability verifies by **re-reading the thing itself**, never by the exit
status of the tool that changed it. Every M14 capability already has a separate verifier for
this reason — use it, and make it read the *subject*, not the *report*. Where the subject is
content rather than state, measure the content: the screenshot path now decodes the stored
PNG and refuses a frame whose intensity deviation is under 0.5, because a uniform frame is
not a result. Corollary: when a tool has two ways to be silent — absent and empty — make two
calls that distinguish them, as `connection_state()` does.

### A list maintained by hand drifts from the code

| | |
|---|---|
| **Entry 023** | `docs/CAPABILITIES.md` documented about twenty capabilities while the registry held **58**. Everything added on 2026-09-29–30 — every `screen.*`, `network.*`, `display.*`, `input.*` and `system.service*` entry — was missing. A reader trusts a documentation file, so a wrong one costs more than an absent one. |

**Convention:** a list that restates what the code already knows is **generated**, and a test
runs the generator in `--check` mode so forgetting to regenerate fails in the suite rather
than months later in someone's reading. `./scripts/aries-capability-docs` and
`tests/test_docs.py` are the pattern; `aries/workspace/introspection.py` is the same idea for
the spoken answer to "what can you do", which is derived at call time and therefore cannot
drift at all. Where a grouping table is unavoidable, make the gap **visible**: membership
comes from the catalogue, and a capability nobody grouped appears under "ungrouped" rather
than disappearing. That is how the two newest ones were caught.

### A schema that validates is not a schema a grammar compiler accepts

| | |
|---|---|
| **Entry 028** | The local goal planner had succeeded **0 times out of 18** while the cloud planner was 77 of 77, so ARIES was silently planning in the cloud while presenting itself as local-first. Every local call returned HTTP 503 "Local inference failed". The schema was valid JSON Schema and valid Pydantic; the grammar compiler simply refuses an **unbounded string**, a `title`, a `pattern`, and a `maxLength` large enough to blow up the expansion. `reason` and `summary` were bare `{"type": "string"}`. |

**Convention:** a schema handed to a constrained decoder is a **grammar**, not a
validator — it is expanded, so every string needs a small bound and no regex.
Generate it from the registry through a narrowing function, keep only
`type/enum/minimum/maximum/minLength/maxLength/items`, and let the real validator
enforce the rest after parsing. When a constrained decode fails, **measure one
keyword at a time against the live runtime**; the failure is a 503 with no detail
and reasoning about it from the spec will not find it. Related trap: a checker that
walks such a schema must not treat the keys inside a `properties` map as keywords —
`notification.send` has a field named `title` and `system.services` one named
`pattern`.

## One-offs worth remembering

| entry | bug | lesson |
|---|---|---|
| 2026-09-29 | Whisper's `initial_prompt` held whole "Ari, play some music." sentences. On music it echoed them back, the echo began with the wake word, and each echo started another song: **44 self-issued goals in 20 minutes**, 9 YouTube windows and 13 result windows | Anything a model can regurgitate must never be an executable instruction. Bias vocabulary with words, not with commands — and watch the *pattern* (repeat, rate), because every single command in a loop looks legitimate |
| 2026-09-29 | 1602 `database is locked`: news `collect()` flushed a source-health write, then fetched up to 25 feeds (20 s timeout each) inside the same transaction; SQLite had no WAL and a 5 s busy timeout. Spoken "open settings" failed on it | Never hold a write transaction across network I/O. A per-test sqlite file cannot show contention — the suite was green throughout |
| 2026-09-29 | At boot `aries-core` started before the session imported `PATH`, so `aries-ui` "was not installed" and every result dashboard failed — until any manual restart hid the bug | A service must not inherit what it depends on from whoever happened to start first; pin it in the unit |
| 2026-09-29 | Spoken `pause.`, `next.`, `stop.`, `mute.` never matched: Whisper ends utterances with punctuation, the patterns ended in `$` | Test the recogniser with what the recogniser's *input source* produces, not with what a person would type |
| 021 | The experiment's verifier-integrity block reported 8 verifier failures. It had not applied its own exclusion rule: those trials were already marked `contaminated` — a YouTube window left by an earlier task, in a second Firefox window the reset could not reach — and the main rates had excluded them | A summary must apply every rule it publishes, including to itself. And a bug in a derivation is fixed by recomputing from the raw rows, never by re-running the trials: **re-running to repair a report of a measurement changes the measurement** |
| 003 | Two thermal zones both named `acpitz` shared a baseline and an alert identity | A sensor's *type* is not its identity |
| 004 | The health automation shipped **enabled**, contradicting §11 and our own docs | A test that arranges state cannot test a default |
| 006 | Noisy-OR computed `1-(1-0.2)` as `0.19999999999999996`, so a topic weighted 0.2 failed a 0.2 threshold — but 0.6 and 0.9 worked | Floating point disagrees with algebra for *some* inputs; round where a number becomes a decision |
| 007 | The DOCTYPE guard refused `github.blog`, valid RSS quoting `<!DOCTYPE html>` in article content | A security check that rejects legitimate input gets turned off |
| 007 | Relevance mistaken for urgency: 26 items delivered against a cap of 8 | Being relevant decides *how* something is delivered, not *how many* |
| 007 | One prolific source won the whole briefing — optimal by the user's own relevance numbers | Optimising a metric is not serving the goal |
| 008 | Cyrillic source names slugified to nothing: `source`, `source-2` | An ASCII-only slug is a latent bug in any system whose user does not write in ASCII |
| 008 | The loop read five sixths less evidence than existed — it counted `delivered` but not `held` | "Shown to the user" and "delivered as an interrupt" are different sets |
| 010 | Hysteresis implemented by moving the threshold (0.10 → 0.06) demanded literally zero engagement across sixty observations | An unreachable rule is the same as an absent one. "Be more certain" belongs in the confidence level, not the threshold |
| 010 | Contextual collapse and fatigue were unreachable — they sat *after* the "is this contradictory?" test, and neither looks contradictory in aggregate | Diagnoses come before strength tests |
| 010 | A pending reversal was only withdrawn on a contradicting verdict, so recovering evidence left it standing to be confirmed by the next dip | A state machine must handle every input, including the ones that mean "never mind" |
| 010 | Two `FeedbackRequest` classes in one routes module; `from __future__ import annotations` made FastAPI bind the **sources** route to the learning model | Lazy annotation resolution turns a name collision into action at a distance |
| 010 | A daemon `http.server` thread killed at interpreter shutdown raised `BrokenPipeError`, so a fully passing suite exited non-zero | A green suite that reports failure trains you to ignore the exit code |
| 011 | "scan for news" opened the News screen instead of scanning — navigation intents were declared before actions, and matching is first-wins | In a router with overlapping patterns, order encodes precedence; a verb is more specific than a noun |
| 011 | GNOME refuses `org.gnome.Shell.Screenshot` to unprivileged callers, and no screenshot CLI is installed | Render the widget tree to a texture offscreen — deterministic, and needs no compositor permission |
| 012 | Enabling `aries.target` alone started a target that pulled in nothing — `WantedBy` describes a symlink that `enable` creates | Declaring a relationship in systemd is not establishing it |
| 012 | `systemctl show --value` returns properties in systemd's order, not the order requested, so status printed the timestamp as the result | A tool free to reorder its output has not promised not to |
| 012 | The start limit protected against a crash loop and then blocked `aries start`, which needed `reset-failed` to escape | A safety mechanism with no recovery through the normal interface is half built |
| 012 | Two tests failed only after 22:00 — quiet hours began and notifications were correctly held | A test that reads the wall clock has a hidden input; pin the hour |
| 013 | `gsettings get` prints the type with the value (`uint32 0`); stripping non-digits left `"32"` from the type name and read a timeout of *never* as **320 seconds** | A parser that discards what it does not understand will quietly consume part of the answer. Take the field, not the leftovers |
| 013 | A UI test passed a `session` string where the API returns an object, so the panel would have crashed on a real reply | A hand-written fixture is a second opinion about the shape, and the wrong one is not caught by the test using it |
| 020 | The folder connector's privacy guard answered "nothing is excluded" when the settings read raised — so a database hiccup would have quietly removed every exclusion and ARIES would have walked into `~/.ssh` with nothing in any log to say why | A privacy guard that degrades to "allow everything" under failure is worse than no guard, because it looks like one. Fail closed, to a default that is known without a database |
| 020 | The test forbidding `\Seen` in the mail connector matched the docstring that exists to explain why the connector must not set it — the FOURTH scan in this project to match its own documentation | Strip comments and docstrings before scanning, every time, in every language. The tempting fix deletes the explanation |
| 020 | A test asserted "email is reported as not implemented" — true when written, a lie the day the connector landed. The Connections screen agreed with it, because status came from a static `needs_connector` flag | The invariant is not which integrations are built; it is that the screen's answer tracks what is REGISTERED. Assert the derivation, not today's answer |
| 020 | `understand()`'s refusal branch for a non-local provider turned out to be unreachable: `intelligence.location` offers only `local` and `none`, so `arm()` had already made a remote call impossible | Test the gate that is reachable and READ the one that is not. An unreachable guard that was never written is the same as no guard when the day comes |
| 020 | Four API names guessed wrong in one sitting — `all_sources`, `Matchable.topic`, `resolve_all`, `genome.all` | Writing against a large codebase from memory instead of reading it first. Cheap to fix, and it is four round trips that a single grep would have saved |
| 019 | `aries-ui` computed its own location from `$0` — which is the SYMLINK when run by name, the way the shell runs it — so PYTHONPATH became `~/.local` and every launch from the desktop died. Running the same file by its real path worked perfectly, which is what every test did | Invoke a launcher the way the product invokes it, or the product is untested. Second failure at this exact seam |
| 019 | The intent router returned near matches ranked by keyword as *suggestions*, and the planner took the top one — turning "send an email to my boss" into "open the Connections screen" | The deterministic layer became the dishonest one. A ranked suggestion is not a decision; only an exact match may act |
| 019 | The prompt listed the valid sections and the validator did not check them, so the model answered with `open_section: weather` — a step shaped exactly like a real one, naming a screen that does not exist | Asking politely in a prompt is not a constraint. An enum you state is an enum you enforce |
| 019 | The at-most-once register recognised the second "open the news screen" as a replay of the first and returned the recorded result without doing anything | Correct for sending an email, exactly wrong for opening a window. `idempotent` is about whether a repeat is *new work*, not about whether the operation is safe to repeat |
| 019 | The `run_automation` tool reported `ran` as success — but `ran` means the automation was *reached*, and a body that failed has `ran: True, status: "failed"` | A tool that lies to its own verifier would be believed everywhere the verifier is not |
| 019 | The News Radar inserted cluster MEMBERS without checking whether they were already stored; `item_id` is unique, so the flush raised, the session was poisoned, and three passes of that opened its circuit breaker. The pass returned `success: True` from its body while the lifecycle recorded `failed` | Two answers about one run and nothing comparing them. The fix then reused `known` for a second meaning and broke the per-source counter — one variable, two facts |
| 019 | Four experiment variants ran the same task in sequence, so a variant that refused and did nothing inherited the previous one's success — B1 "verified" three tasks it had explicitly refused | An experiment without a reset between trials measures the order of the trials |
| 019 | The engine's hourly action cap fired mid-experiment and was recorded as a planning failure | A rule refusing is not a capability failing; `held` must be a different outcome from `failed`, everywhere |
| 019 | The first honesty-gap definition counted `unverifiable` as dishonesty — so the metric would have been dominated by whether the user happened to be in the ARIES session | "I cannot check" is the honest answer to a missing observation. A metric that punishes it measures the session, not the system |
| 019 | The verifier read the automation's run row through the CALLER's session, which held a snapshot from before the run committed — so a health pass that had just succeeded was reported as "a run from before this task began" | A verifier must read the world freshly. It also compared a microsecond timestamp against a whole-second column, which made a run in the same second look older |
| 018 | `working.release()` existed, the design said "released when the task ends", and nothing in the system ever ended a task. It would have shipped as a comment | A cleanup with no caller is documentation; wire it into the single run path and then break it on purpose to prove the test can see it missing |
| 018 | The retention register's docstring said "everything ARIES writes appears here" while the test that enforces it `discard()`ed one table — an exception I wrote myself, in the same hour | An invariant with a documented exception is an invariant nobody can rely on. Change the design so the rule holds, not the test so it passes |
| 018 | Every retention policy assumed a `created_at` column; seven tables use `recorded_at`, `first_seen_at`, `started_at`, `at` or `requested_at`, so the first preview raised `no such column` | A schema assumed across seventeen tables is seventeen chances to be wrong; read the columns from `sqlite_master` in the test rather than trusting the declaration |
| 018 | Seventeen of the engine's own tables had no retention policy at all, `stored_credentials` and `memory_items` among them. They were empty, so nothing complained | Emptiness is why it was easy to miss and why it mattered — decide before something starts filling the table, not after |
| 018 | Nine Control Centre screens, and no test had ever called `render()`. The contract suite proved the endpoints return the right keys; nothing proved a screen could build a widget tree from them | The same seam as Entry 017 in a different place: both halves tested, the join between them not. Ask what the tested graph excludes |
| 017 | St's CSS parser does not understand 8-digit `#RRGGBBAA` hex and drops the declaration silently — so every translucent surface had **no background at all**: the dock lost its panel, ARIES Search was fully transparent over the window behind it, while the 6-digit colours beside them rendered fine | A parser that ignores what it cannot read turns a colour into a missing feature; emit `rgba()` and assert no 8-digit hex survives generation |
| 017 | `get_preferred_height()` ignores a child whose height was set explicitly, so the command bar's surface was shorter than its own scroll view and rows drew outside it onto the wallpaper. Deferring the measurement by an idle turn changed nothing | The number was not stale, it was measuring the wrong thing — when a fix for staleness does not help, stop assuming staleness |
| 017 | A new scan asserted `"get_preferred_height" not in body` and matched the comment explaining why it is not used — the third time this file has made that mistake, with the rule already written in it twice | A rule written down is not a rule applied; put the comment-stripping in a shared helper, not in each scan |
| 017 | `Clutter.cairo_set_source_color()` does not exist in GNOME 50 — every repaint of the panel mark threw and drew nothing. The shell's own widgets use `cr.setSourceColor()` | Copy the platform's idiom from the platform's source, not from memory |
| 017 | The nested harness grepped `JS ERROR.*aries`; the message was `TypeError: (intermediate value).cairo_set_source_color is not a function` and named the extension nowhere, so a clean run was reported twice while the logo was invisible | In a session that exists to load one extension, ANY exception is that extension's until proven otherwise |
| 017 | The dock drew a gap where the ARIES icon should be: the icon theme resolved the name to an SVG, and this machine has `libpixbufloader_svg.so` on disk but unregistered | An icon that *resolves* is not an icon that *renders* |
| 017 | Shipping the SVG made it worse than absent — GTK prefers a scalable icon when present, so it actively hid the PNG sizes that would have worked | A preferred format that cannot be drawn is a worse failure than a missing one; detect the capability and install only what renders |
| 017 | `scripts/aries-ui` contained `exec "$HOME/aries/scripts/aries-ui"` — **itself**. An infinite loop; the Control Centre could never open, so every navigate action, notification click and dock press was a silent no-op for days, with 1511 assertions green | A launcher is not a component, it is the seam between them — and seams are what component tests skip by construction. Test the installed artifact across process boundaries |
| 017 | `--section` set a pending field then called `activate()`, and applied the section *again* if the window already existed. Which branch ran depended on whether `do_activate` had cleared the field, so cold and warm starts differed | A fallback that duplicates a code path is a race wearing a helpful name. GTK had one mechanism for this (a stateful GAction) and its state is readable, which is what makes the destination testable |
| 017 | The e2e harness read the section via `Gio.DBusActionGroup`, which populates asynchronously and needs a main loop the script did not have — eleven journeys "failed" against a harness that was never going to hear an answer | A convenience wrapper that needs an event loop is not convenient in a script; ask the bus synchronously |
| 017 | The launcher-chain check assumed the PATH entry was a wrapper script and parsed its `exec` line — but it is a symlink, so the check parsed the real launcher and reported `/usr/bin/python3.14` as a fault | Assert the invariant ("following the chain terminates and reaches the launcher"), not one implementation of it |
| 016 | Disabling and re-enabling an extension does **not** reload its code — GJS caches the module, so `disable()`/`enable()` run on the object loaded at login. Two rounds of "live reload" reloaded nothing | On Wayland, new extension code needs a new gnome-shell process; say "log out" instead of pretending otherwise |
| 016 | The ARIES shell added an indicator to GNOME's panel and called it an ARIES top bar. At rest the desktop was Ubuntu plus one label | "The extension loads" is not the goal; look at the actual screen before claiming a visual milestone |
| 016 | ARIES drew its own workspace pills beside GNOME 50's, which already has them inside the Activities button | A duplicate is invisible to every log and obvious in one glance at the screen |
| 016 | The wallpaper was set to `${extension}/share/backgrounds/…`, a path that exists in the repo and not in `/usr/local/share`. GNOME answers a missing wallpaper by keeping the old one, so the log said "background set" and nothing changed | An extension is copied elsewhere: it must carry every file it references |
| 016 | The nested harness asserted a fixed list of surfaces; the new mark was not in the list, so "every surface was built" passed while it was missing | A checklist that does not grow with the code stops being a checklist |
| 016 | `aries-dock` recorded `enabled-extensions` only, but a uuid also ended up in `disabled-extensions` — the rollback would have restored the list and not the dock | A rollback must own every key that can override what it restores |
| 015 | `sudo` refused with "a terminal is required to authenticate" when the installer was run from anywhere without a TTY | Escalation needs a route the *caller* can authenticate through; pick it at run time instead of assuming a terminal |
| 015 | `"${link:+link}${link:-copy}"` expands to `linkyes` when `link=yes`, so `--link` would have silently installed a copy | A shell parameter expansion that reads like a conditional is not one |
| 015 | The nested-shell harness ran `gnome-extensions disable` inside its own session — but dconf is per-USER, so it reconfigured the real desktop: the live session lost its dock and desktop icons | A sandbox that shares the user's settings store is not a sandbox; record and restore anything global before touching it |
| 015 | `aries@aries.local` left in `disabled-extensions` by that harness made a correct session install start silently without ARIES — that key takes precedence over a session mode | A precedence rule you did not know about turns a working install into a no-op with no error anywhere |
| 015 | GNOME refuses to load a per-user extension as part of a session mode — the session found the extension and left it INITIALIZED | "Installed" and "installed somewhere this mechanism will accept" are different facts |
| 015 | The test asserted the absence of a log message rather than which copy loaded — with both a per-user and a system copy present, the message is the mechanism working | Assert the outcome, not the absence of a warning about the outcome |
| 014 | `api.js` built its URL from a module constant while also exposing `get base()` — overriding the address changed what the getter said and not where requests went, so a suite pointed at a fake server silently tested the real one | Two sources of truth for one value; the getter that lies is worse than no getter |
| 014 | A 500 carrying a plain-text body was reported as "unreadable reply" — the JSON parse failure masked the status | When a request fails, the status is the news; a parser complaint sends the reader to the wrong place |
| 014 | The fake ARIES used a single-threaded `HTTPServer`, so `/slow` blocked every later request and three tests reported timeouts while testing the fixture | A fixture that serialises requests cannot test concurrency-shaped failures |
| 014 | The shell "loaded and reached ENABLED" while individual surfaces had been guarded out — the harness could not tell six built from one | Containment makes failure quiet by design, so the test must ask *what is up*, not *did it start* |
| 014 | `affectsInputRegion` is no longer a parameter GNOME 50's `addChrome` accepts; it threw and two components were silently left out | An extension API that looks like the one you remember is the one to check against the version installed |
| 014 | Chrome actors are parented to a group that does not lay them out — setting only the position left them allocated at zero height, so every row drew over the one before | Opting out of a layout manager means owning size as well as position |
| 014 | `trackFullscreen: true` makes the LayoutManager set `visible` itself, overriding the `visible: false` an overlay was constructed with | Opting into a helper is opting out of controlling what it helps with |
| 014 | `AppSystem.get_installed()` returns `Gio.DesktopAppInfo`, not `Shell.App` — they share two methods and nothing else | Two types with overlapping interfaces are the hardest kind of wrong object |
| 014 | Two test checkers matched the comments explaining what they forbid — the CSS scan flagged its own header, the sync-call scan flagged the paragraph warning against sync calls | A checker that reads its own documentation as a violation is checking nothing, and the tempting fix deletes the explanation |
| 024 | `checked_path(write=True)` allowed `aries/workspace/capabilities.py` itself. The ARIES tree lives under `$HOME`, so the home confinement, the symlink check and the hidden-path check all waved it through, and `privacy.excluded_paths` held only `~/.ssh` and `~/.gnupg` | A confinement expressed as one outer boundary misses the subsets inside it that matter. Ask "what is inside this boundary that should not be?" — and keep the **read** path open, because self-knowledge is read out of the same tree |
| 025 | `pgrep -f "scripts/test.sh"` reported the suite still running when it had finished twenty minutes earlier — the pattern matched the `bash -c` invocation containing it | A process check whose pattern appears in the checking command always finds itself. Look for the finished artefact (a marker file, the final line of the log), not for the process |
| 026 | `./scripts/test.sh` globs `tests/test_*.py`, so it collected an agent's half-written test file and reported `SOME SUITES FAILED` while that agent was still typing | Parallel authorship and a filename glob do not mix. When work is in flight, read the failure's *owner* before reading it as a regression |
| 027 | A first `systemctl start` probe without `--no-ask-password` **blocked on a polkit dialog** until it was killed, and the authentication it raised then stayed cached, so a later `systemctl restart chrony.service` silently succeeded | An unprivileged probe that can raise an auth prompt is not read-only: it changes what the *next* call is allowed to do. Pass `--no-ask-password` so the refusal is data instead of a dialog |
| 014 | A new "build the brief" intent was declared before the "shorter" correction, so "make my morning brief shorter" rebuilt the briefing | A comment warning about precedence does not prevent the precedence bug; the test enumerating phrase → action does |
| 014 | The file-search privacy test put its probe in `~/.ssh`, which the walk skips for being hidden — it would have passed with the exclusion removed | Proving a guard works needs the control case: show it *would* have been found without the guard |
| 013 | A test automation was refused as `disabled` before the resource gate it was testing was ever reached | The checks before a run are ordered; a test that does not satisfy the earlier ones is not testing the later one |
| 013 | `Reading.name` does not exist — the field is `metric`. The governor reads the sensors *through* the health probes on purpose, and this is the cost of that reuse | Two readers of one sensor drift; knowing someone else's field names is the cheaper problem |
| 013 | `gpu_jobs_note` said the GPU switch was "declared, not implemented" — true in the morning, false once the switch became a live gate that afternoon | A note explaining that something is unfinished must be revisited by the change that finishes it. A stale honesty note is worse than none, because it is believed |
| 013 | A section titled "Power & Background" rendered **untitled**: `Adw.PreferencesGroup` parses its title as Pango markup and rejected the bare `&`, with the reason only on stderr. `row()` had escaped since day one; `section()` never did | Escape at every door into a markup parser, not at most of them — and a parser that fails by rendering nothing fails invisibly |
