# ARIES — Changelog

Milestones, newest first. Each links to the Build Journal entry with the reasoning, the
alternatives considered, and the errors hit on the way.

## The local planner never worked, and now does · 2026-09-30

`aries/analytics/` measured what nothing had surfaced: `local/qwen2.5:7b/
workspace.m14-planner` **0 of 18**, `cloud/cli-default` **77 of 77**. ARIES is
presented as local-first and its planning brain was 0% local, falling through to
the cloud without telling anyone — 1,397,433 input tokens on 77 calls.

- **Not the model.** Every local call returned 503 because the generated schema
  contained forms the grammar compiler refuses. Measured one keyword at a time:
  an **unbounded string** is rejected, as are `title`, `pattern`, and
  `maxLength: 2000`; `maxLength: 80`, integers, booleans, enums and arrays pass.
  `reason` and `summary` were bare strings.
- `grammar_safe()` narrows every field to what the compiler takes and bounds
  strings at 512. Constraints are dropped, not translated — per-capability
  validation still runs after parsing, so a dropped `pattern` is still enforced.
- Same request: **503 → 200**. All 58 capabilities still offered.
  `tests/test_planner_grammar.py` pins the shape statically.
- **The plans are still weak** — the blocker is gone, the quality problem is not
  solved, and it is a different and smaller problem.

## Documentation that cannot go stale · 2026-09-30

Two lists restating what the code already knew, one of them already wrong.

- **`docs/CAPABILITIES.md` is generated.** It described about twenty capabilities
  while the registry held 58. `./scripts/aries-capability-docs` rewrites the table
  between markers and leaves the hand-written prose alone, because the reasoning in
  that prose is not derivable from anything. `--check` exits 1 when it is stale.
- **`tests/test_docs.py` is what makes the generator worth anything** — a generator
  nobody runs is exactly as stale as the file it replaced. One of its checks
  deliberately distrusts the script: it reads the registry and the file
  independently, because `--check` compares the file to the generator's own output
  and a generator that dropped a row would agree with itself forever. Verified by
  deleting one row: `--check` exited 1 and the test named `screen.read`.
- **`docs/SPEECH.md`** written to the per-subsystem convention, with every factual
  claim checked against the code rather than against memory — default engines, the
  `speak()` signature, that `ARIES_SPEECH_MK_FALLBACK` is honoured, that Piper
  refuses Macedonian by name, that both fetch scripts are executable, and that
  `bench.py` really accepts the flags the document cites.
- **`docs/ERROR_LOG.md`**: entries 018–027. The important one is a recurring shape
  found five times in one day in five subsystems by five agents who were not
  talking to each other — **exit zero is not evidence**. A portal screenshot
  returning code 0 with an all-black PNG, `systemctl show` exiting 0 for a unit
  that does not exist, `nmcli` printing nothing and exiting 0 for an inactive
  profile, Mutter accepting Cyrillic keysyms and typing nothing, Mutter accepting a
  wrong-sized gamma ramp. Verify by re-reading the subject, never the report.

## ARIES cannot rewrite itself · 2026-09-30

A measured hole, not a principle. `checked_path(write=True)` allowed
`aries/workspace/capabilities.py` itself: the ARIES tree lives under `$HOME`, so
the home confinement, the symlink check and the hidden-path check all waved it
through, and `privacy.excluded_paths` held only `~/.ssh` and `~/.gnupg`.

Nothing could silently rewrite running code even then — `create_file` refuses to
overwrite and `file.edit` needs approval — but new files could appear inside the
package unapproved. A hole in the fence rather than the lock.

- `INSTALLATION` plus one guard in `checked_path`: no write under the ARIES tree.
- **Reads stay allowed.** `introspection.report()` is read out of that tree, and
  any reviewed self-development will need to read it too. A guard that blocked
  reads would have broken self-knowledge to fix a write problem.
- The user's own folders are untouched, Cyrillic included — `~/Документи`,
  `~/Мои проекти/Скопје` all still resolve. An alphabet was never a reason to
  refuse a path, and a new guard is not an excuse to become a wider one.
- `tests/test_self_protection.py`, 14 checks, keeps it closed. Six existing
  suites re-run unchanged.
- `introspection.limits()` now reports it as a limit, derived from the guard
  rather than written down, so the answer to "што можеш" cannot drift from it.

Also: **developing ARIES belongs to a reviewed flow**, not to "create a file at
this path". That flow does not exist yet; the guard is what holds until it does.

## ARIES knows what it can do · 2026-09-29

Four capability families and self-knowledge, built by five agents in parallel —
each in its own new file so they could not collide; every shared-file edit
applied serially afterwards.

- **`screen_capabilities.py`** — ARIES can see. `org.gnome.Shell.Screenshot`
  returns **AccessDenied** on GNOME Shell 50.1, so capture goes through
  `org.freedesktop.portal.Screenshot` (0.51 s, unprompted). OCR is tesseract
  5.3.4 by ctypes into `libtesseract.so.5` inside the gnome-46-2404 snap — no
  binary, no compiler, no root. `eng+mkd` measured confidence 85 and recovered a
  Macedonian paragraph from the terminal with one error; `eng` alone read "Ѓорѓи"
  as "fopfn". **Black-frame trap reproduced, not theorised**: during screen
  blanking the portal returns code 0 with a valid 1920×1080 PNG of deviation
  0.00, so `ScreenSaver.GetActive` is checked before and the decoded pixels are
  measured after. Frames live in `var/screen` at 0700/0600, max 8, pruned at 15 min.
- **`system_capabilities.py`** — systemd units, disk, packages. `pkcheck` says
  `auth_admin_keep` and an un-flagged `systemctl start` **blocks on a password
  dialog**, so every call passes `--no-ask-password` and system scope is refused
  by name. Verification is by `InvocationID`, never by exit code: a restart that
  really happened has a new one, a no-op has the same one.
- **`network_capabilities.py`** — connectivity, wifi, brightness. `link_up`,
  `internet_reachable`, `dns_resolves` and `nm_connectivity` are reported
  **separately and never collapsed**; the TCP probe goes to a literal IP so a
  broken resolver does not read as a dead internet. `wifi_connect` activates an
  already-saved profile **by UUID** and has no password path at all — a
  passphrase belongs in GNOME's own dialog. No brightness control exists on this
  machine and the setter refuses with all four probed mechanisms named.
- **`input_capabilities.py`** — clipboard and typing over
  `org.gnome.Mutter.RemoteDesktop`. Its keysym path works for Latin and
  **silently drops Cyrillic**, because Mutter resolves keysyms against the active
  layout, so typing uses AT-SPI `EditableText` into one control the caller
  already observed, re-verified on app, pid, role and name.
- **`introspection.py`** — ARIES can answer "што можеш" and "можеш ли X". Every
  list is derived at call time from `CATALOGUE`, `ARGUMENTS`, `SENSITIVE` and the
  registry, and every readiness claim from a subsystem's own live check. A
  hand-maintained feature list is a lie with a delay on it; a capability nobody
  grouped shows up as "ungrouped" rather than disappearing. `limits()` reports
  seven limits **with the evidence**, measured where measurable.
- Spoken capabilities 37 → **54**; typed registry capabilities 41 → **58**, 29 of
  them read-only, 9 needing approval.

## ARIES speaks · 2026-09-29

It listened and never answered, and the silence is what made it not feel alive.
The hard part was not synthesis — it was whether Macedonian exists at all.

- **It does not exist in neural TTS.** Checked, not assumed: Piper's 177 voices
  in 58 languages, Meta MMS-TTS's 1143 languages (from its own file manifest),
  XTTS-v2, Kokoro, Coqui's zoo, sherpa-onnx — none has `mk`. Piper's one "sr_RS"
  voice is Lower Sorbian data, mislabelled upstream.
- **It does exist in RHVoice**, which is written for blind users and packaged in
  Ubuntu: **Kiko** (male, © Government of North Macedonia) and **Suze** (female,
  recorded at FEEIT UKIM Skopje with UNICEF funding). Both NonCommercial, hence
  Debian `non-free`. Found only after the user insisted the search was too shallow.
- **`aries/speech/`** (new): `speak(text, language=None, blocking=False)`, plus
  `stop()`, `speaking()`, `warm()`, `available()`. Four interchangeable engines
  selectable per language via `ARIES_SPEECH_MK` / `ARIES_SPEECH_EN`. Language is
  decided by script: one Cyrillic letter means Macedonian.
- **Chosen by ear, then confirmed by measurement.** Kiko: 68 ms to first sound,
  +1.8 MB RSS, 1.1 ms engine init, offline. Whisper round-trip WER 0.387 — better
  than Microsoft's `mk-MK-AleksandarNeural` (0.421, and 410–1600 ms over the
  network, which stays as the fallback). English is Piper `en_US-ryan-medium`,
  78 ms. Numbers and method in `experiments/speech/`.
- **Bulgarian was built, measured and deleted.** `bg_BG-dimitar` driven by
  espeak-ng's Macedonian front end scored WER 0.578 and was refused outright —
  "нејќам на бугарски". Piper now raises by name if asked for Macedonian rather
  than quietly speaking another language.
- **`say` capability**: `кажи` / `изговори` / `повтори` / `say` / `speak`.
  `кажи ми …` is deliberately excluded — that is a question, not text to read
  aloud, and it belongs to the planner.
- `scripts/aries-fetch-voice` (Piper) and `scripts/aries-fetch-rhvoice` (RHVoice
  without root — `apt-get download` plus `dpkg-deb -x`, since there is no
  compiler on this machine).
- Rule recorded in the module: **speak only when spoken to.** Nothing in
  `aries/speech/` can tell whether ARIES was addressed; only the wake gate can.

## Stabilisation after the voice loop · 2026-09-29

Engineering green, product red: the suite passed while ARIES issued itself
44 commands from a song, failed spoken commands on `database is locked`, and
opened a window per sentence. Fixed on the installed system, not only in tests.

- **Loop guard** (`aries/workspace/runaway.py`): the 3rd identical request in
  2 min, or more than 6 a minute, from voice pauses voice for 10 min with a
  notification. `GET /api/aries/shell/guard`, `POST …/guard/resume`.
- **Voice**: prompt is a word list, not commands; segments over the standard
  Whisper hallucination thresholds are dropped and logged; `pause.`/`play`/
  `пушти` work with punctuation; spoken goals run **without a window** and
  answers or failures arrive as notifications.
- **Database**: WAL + 15 s busy timeout; news fetches before it writes; the 2 s
  queue poll no longer writes a row per empty pass (was 88% of `automation_logs`).
- **Shell watchdog**: re-enables the ARIES shell when GNOME leaves it INACTIVE
  with the screen unlocked; each repair is audited.
- **Music**: an already-open video is focused instead of reopened; YouTube (only)
  is granted autoplay the first time Firefox is closed.
- **Questions** end `answered` with an Answer card instead of `failed`.
- `aries-core.service` pins `PATH`, so `aries-ui` resolves at boot.

## Operator experiment, run 2 · *Entry 021*

The first evaluation of the Operator that could actually observe the machine.
372 trials — 31 tasks × 4 variants × 3 repeats — in a fresh ARIES session on the
current shell build, with **nothing unverifiable**. Run 1 could not check 7 of
its 26 tasks.

**The verifier was tested before anything else.** Five new *control* tasks act
on one thing and are checked against another, so the correct verdict for each is
UNMET: **52 of 52 correct, 0 wrongly MET.** The same controls caught 27 claimed
successes across the four variants that the verifier contradicted.

**The pre-registered failure criterion was not met, for the second time.**
A − B2 = 0.0 on every axis — verified rate, honesty gap, false successes,
unverifiable rate, tokens. Recorded as stated, not rewritten.

**What the run does establish.** Verification does not reduce the false claims a
planner produces; it reduces the ones a user receives. And the largest honesty
gap belongs to the cheapest baseline: **B0, which issues the command and trusts
the exit status, claims +11.8% more than it achieves** and does so 0.05 s after
acting.

**Dominant failure mode:** the model invents a plausible address rather than
refusing — *"what is the weather tomorrow"* became `https://www.example.com/weather`
in every repeat, and is 3 of the 4 false successes in both model variants.

Not one line of the Operator changed: this was a clean evaluation of the current
implementation. Everything is in `experiments/`.

**Still open, and not the Operator's fault:** ARIES Search does nothing for
"open youtube". The search bar posts to the intent table, which deliberately has
no `open_url`; the Operator, which plans it correctly, is never asked. Two
routers, nothing connecting them.

## Integrations v0.1 · *Entry 020*

Folders and mailboxes ARIES may read. `aries connect` · `aries attention` ·
Control Centre → **Connections** · [docs/INTEGRATIONS.md](INTEGRATIONS.md)

* **A credential appears in exactly one place.** The OS keyring. Everything else
  holds a reference that is meaningless without it — safe in the database, the
  audit log, a screenshot and a prompt. Without a keyring ARIES **refuses** to
  store one rather than writing it to a file. A test sweeps every text column of
  every table for the password.
* **Content can never become an action.** A model that has read your mail may
  produce a summary and a category — there is no `goal`, `tool`, `recipient` or
  `url` in the schema its reply is validated against. The worst a successful
  prompt injection achieves is a wrong summary.
* **Attempts are reported, never filtered.** A planted injection was detected on
  four signals, classified `suspicious`, and *described* rather than followed.
* **Read-only by having no write method.** Mail is fetched with `BODY.PEEK[]` on
  a `readonly` mailbox — ARIES never marks anything as read. IMAP rather than
  the Gmail API, because an OAuth token that can send is a token that will send
  eventually.
* **The Attention Pass** — the first real orchestration: a workflow graph
  (collect → understand → weigh → report) through the task lifecycle, reporting
  what needs you and acting on none of it. Ships disabled, `medium` risk.
* **The Connections screen stopped lying** — status is derived from whether a
  connector is registered, not from a static flag that said "not built yet"
  about email.
* Understanding happens on `qwen2.5:7b` on this machine, and refuses rather than
  falling back.

## ARIES Operator v0.1 · *Entry 019*

Natural language that produces **verified** action. `aries do "…"` ·
Control Centre → **Operator** · [docs/OPERATOR.md](OPERATOR.md)

* **Two numbers, never merged.** What the tool reported, and what ARIES
  confirmed by looking at the machine afterwards. The difference is the honesty
  gap — the thing 1,511 green assertions failed to measure in M13.
* **An evidence ladder, and ARIES says which rung it reached.** proof (a run
  row; the Control Centre answering for itself) · strong (a process *and* its
  window) · circumstantial (a browser window titled for the site — the ceiling
  for anything on the web) · none, which produces **unverifiable**: "I did it
  and I cannot confirm it", a third verdict beside done and failed.
* **The model picks goals, never commands.** A step ARIES cannot verify is a
  step it will not take — and the enums the prompt states are now enforced,
  after the model named a screen that does not exist.
* **A guess is proposed; an exact match acts.** The interesting failure is not a
  model refusing, it is a model answering plausibly.
* **Local by default.** `qwen2.5:7b` on the GPU, ~0.43 s median to a plan, and
  ARIES refuses rather than falling back to a remote provider.
* **Evaluated, with a falsified criterion recorded** rather than rewritten —
  [`experiments/operator/analysis.md`](../experiments/operator/analysis.md).
* Four real bugs found by the verifier along the way, including a News Radar
  that had opened its own circuit breaker while reporting success.

## Data lifecycle · *Entry 018*

What ARIES keeps, for how long, and what it discards — built before the Operator
rather than after it, because an Operator that reads mail with nothing telling it
to forget will hoard.

* **The browser rule.** Open a page, read it, close it, the page is gone; what
  survives is a bookmark, not the HTML. Five classes — working, operational,
  memory, provenance, audit — declared once and served to every screen, so none
  invents its own wording.
* **The working set's lifetime is the task's, not a timer's.** Released on every
  terminal outcome in a `finally`, because a pass that died halfway is the one
  still holding borrowed mail bodies. Its contents are never served over HTTP.
* **A window below its minimum is refused, not clamped** — and checked twice,
  because a row written straight into `aries_settings` never passes the schema.
  Deleting what a dependant reads does not crash anything; it makes the circuit
  breaker, the learning loop and the health baselines quietly answer differently.
* **No table is left undecided.** The test reading `sqlite_master` found
  seventeen engine tables with no policy, `stored_credentials` among them.
  Credentials are never on a timer.
* **Nothing deletes on the first pass.** `data.dry_run_first` makes the first
  real run a rehearsal, recorded in audit. The cleaner is a declared automation
  that ships disabled, with a second switch for deletion.
* **Every Control Centre screen is now rendered in a test** against live
  payloads, on the system interpreter — nine pages, and `render()` had never
  been called by anything but the user.

`aries data` · Control Centre → **Data** · [docs/DATA.md](DATA.md)

## M14 — The ARIES login session · *Entry 015*

`POWER → ARIES → ARIES Login → ARIES Desktop`, with Ubuntu still on the login
screen as the permanent recovery path.

* **ARIES is a session, not an extension you switch on.** A GNOME session in an
  ARIES *session mode* — the mechanism Ubuntu uses for its own, read out of the
  installed files rather than guessed at. Logging into ARIES gives you the ARIES
  desktop with nothing to enable.
* **Five new files, none owned by a package.** Ubuntu's session entry, session
  file and mode are untouched — asserted by a test that scans the installer for
  writes to anything Ubuntu owns, because "we only add files" is a claim that
  rots.
* **Proved before it is installed.** `aries-session verify` loads the real mode
  in a real GNOME Shell — nested, headless, `--mode=aries` — by pointing
  `XDG_DATA_DIRS` at a staging directory. A broken session definition is the one
  failure here that a user cannot fix from inside the system.
* **The extension is installed system-wide**, because GNOME refuses to load a
  per-user extension as part of a session mode — correctly. `--link` is offered
  for development and says plainly what it costs.
* **The precedence trap**: `disabled-extensions` overrides a session mode, so a
  uuid left there makes a correct install silently do nothing. `install` clears
  it; `status` warns about it.
* **The nested harnesses now put the desktop back.** dconf is per-user, so
  `gnome-extensions disable` inside a nested shell had been reconfiguring the
  real session — it lost its dock and desktop icons until they were restored.

* **One privileged script, one authentication.** `sudo` needs a terminal that a
  script launched from an editor or an agent does not have, so everything that
  runs as root moved into `scripts/aries-session-root` — about fifty lines that
  validate every input and refuse to run unless root — and the caller escalates
  through passwordless sudo, `pkexec` (a graphical dialog) or a terminal,
  whichever this machine can authenticate with.
* `test-session.sh --installed` verifies what is **on disk** rather than a staged
  copy: "would work if installed" and "what got installed works" are different
  claims.

**65 new assertions.** 1507 total.

## M13 stabilisation — product green · *Entry 017*

M13 was engineering-green and product-broken. This closes that.

* **The launcher regression, fixed and fenced.** `scripts/aries-ui` exec'd
  itself; the Control Centre could never open, so every navigate action,
  notification click and dock press was a silent no-op — with 1511 assertions
  green. A launcher is not a component, it is the seam between them.
* **`--section` is a stateful GAction**, not a pending field racing activation.
  All nine sections land deterministically, cold-start and already-running.
  Verified by reading the action's state back over D-Bus — asking the window
  where it is, rather than trusting the caller.
* **`./scripts/aries-e2e`** — real journeys on the installed system: launcher
  chain, cold and warm start, every section, unknown section refused, router →
  destination, close and reopen, an application that actually launches,
  degraded state, and staleness. 26 checks, nothing mocked.
* **`./scripts/aries-smoke`** — "can I use ARIES right now?" in five seconds,
  non-zero if a user-facing path is broken.
* **`aries version`** — source, installed and running compared by content hash,
  so "is the running thing the thing I changed?" is answerable. It found a stale
  `/usr/local` copy the first time it ran.
* **One regression test per M13 bug**, in the ordinary suite: self-exec,
  SVG-loader dependence, silent ellipsizing, section race, stale builds, and a
  resolved command whose target cannot run.
* **Two levels of done**, documented as a permanent rule: ENGINEERING GREEN and
  PRODUCT GREEN. A milestone needs both.
* **`docs/EXPERIMENTS.md` and `experiments/`** — the research evaluation
  principle: no major capability is complete without a baseline. The ARIES
  Operator evaluation is designed there *before* its implementation, which is
  the order the rule requires.

**30 new assertions.** 1541 total, plus 26 end-to-end journey checks.

## M13 — ARIES Shell v0.1 · *Entry 014*

The desktop stopped being Ubuntu with an AI application on it.

* **A GNOME Shell extension**, because Mutter does not implement `wlr-layer-shell`
  — measured on this machine, so no GTK window can anchor to a screen edge on
  this session. ADR-0008. GNOME is not replaced, no compositor is written, the
  bootloader, display manager and login session are untouched.
* **ARIES top bar**: status with a severity dot judged by the *server*, decisions
  badge, what ARIES is about to do next, and workspace pills — which GNOME shows
  only inside the overview.
* **ARIES Search** (`Super+Space`): applications, files, settings, automations and
  everything ARIES can do, in one surface. Applications are drawn on the
  keystroke; the ARIES request is debounced and merges in, so typing never waits
  for the network — and with ARIES stopped it still launches applications.
* **One router, two front ends.** The intent table moved out of the GTK process
  into `aries/shell/intents.py` behind `POST /api/aries/command`; the Control
  Centre's palette calls the same endpoint. Results are *actions* — data — that
  each surface carries out in its own medium.
* **ARIES Quick Settings**: Wi-Fi, audio, Bluetooth, brightness, Background Mode,
  privacy and autonomy in one panel — ARIES's surface, over NetworkManager, Gvc,
  gsd-power and gsd-rfkill. Joining a network hands off to the system picker,
  visibly, rather than failing at WPA-Enterprise.
* **ARIES dock** with pinned and running applications and a focus indicator; it
  stands down if another dock is enabled rather than drawing over it.
* **ARIES notifications** as a source in the desktop's own centre, with §26's
  policy respected — a notification ARIES held is never raised here.
* **One design language, two toolkits.** `aries/shell/tokens.py` generates both
  stylesheets: theme-relative for GTK, fully resolved literals for St, which has
  no variables. A test asserts the generated file matches the tokens.
* **`org.aries.Shell`** on D-Bus — `Search()`, `Launcher()`, `Close()`, `Ping()`.
* **Identity**: an application entry with per-screen actions, an icon, and ARIES
  backgrounds with light and dark variants.
* **A nested-GNOME test harness.** `./scripts/test-shell.sh` runs the extension
  in a headless GNOME Shell on its own D-Bus session — the user's desktop is
  never the thing under test. It caught every bug in this milestone.
* **`docs/PRODUCT_IDENTITY.md`**: ARIES is the product, Linux is the foundation;
  five surfaces per capability; Ubuntu stays a permanent fallback session.

* **Workspace overview integration.** ARIES registers as a search provider, so
  typing in GNOME's overview reaches automations, settings and everything the
  command router knows — the same `POST /api/aries/command`, making it one router
  with three front ends. The dock steps aside while the overview is open.
* **The background is borrowed, not taken.** `shell.wallpaper` defaults to
  `system`; choosing an ARIES background records the previous one in ARIES's
  settings first, so `system` puts back exactly what was there.
* **Three levels of test**, because the shell has three kinds of code: the core
  side in Python (106), the HTTP layer in plain gjs against a deliberately broken
  ARIES (28 — timeout, refusal, HTML-with-a-200, truncation, empty body, stale
  reply after teardown), and the extension in a nested GNOME Shell, which now
  asserts *which* surfaces were built and that it enables cleanly a **second**
  time after being disabled.

**161 new assertions.** 1442 total.

## M12 — Background Runtime & Power · *Entry 013* — **milestone complete**

The machine stays awake while the screen goes dark, by asking logind rather than by pretending to
be a user.

* One **`sleep`/`block` logind inhibitor**, held as an open file descriptor by a child process —
  so it is released by the kernel if ARIES dies in any way, including `SIGKILL`. No cleanup path
  exists because none is needed. ADR-0006.
* **`sleep`, never `idle`**: the display powers off exactly as before. The status panel asserts
  that no `idle` lock is held, so a regression would be visible.
* `reconcile()` at startup, on the toggle, and on every dispatcher tick — idempotent, and placed
  *before* the automations-enabled check so a lost lock is noticed even with automations off.
* **"Display off after" is borrowed, not taken**: the previous value is recorded in the database
  before it is changed and written back exactly on switch-off. The only GNOME key ARIES touches.
* **Settings → Power & Background** with a live status panel — Background Mode, suspend inhibitor,
  display, display-off-after, system, ARIES — every line measured at request time, and the
  inhibitor read from `systemd-inhibit --list` rather than from ARIES's own memory.
* `GET`/`PUT /api/aries/power` (writes need `MANAGE_TOOLS`), `aries power status | on | off`.
* Honest about its own effect: on a machine already set never to suspend, the panel says the
  inhibitor changes nothing rather than taking the credit.
* A **real elapsed-time test**, excluded from `test.sh`: enables the mode, lets the display
  actually blank, waits past the suspend timeout, proves automations ran and the lock held, then
  restores every value it borrowed and asserts that it did.

* **Resource policy.** Background Mode promises the machine stays awake; this says what it may
  do while it is. Automations declare a workload class in their genome (`light` ·
  `inference_light` · `heavy_cpu` · `heavy_gpu`) — a different axis from `risk`, which is about
  consequences rather than cost.
* **Two gates, kept apart**: permission (static, default-closed for heavy work while the display
  is off) and condition (live, from `/proc/stat`, the thermal zones and the GPU). A refusal names
  which one, because they have different fixes.
* **Lightweight work is never deferred** at any temperature — the health check is how ARIES finds
  out the machine is hot.
* **Configurable limits**: temperature, CPU %, GPU %, heavy-job duration, plus a resume margin and
  a cool-reading streak. The margin is the Entry 010 hysteresis lesson in its second home.
* **Nothing is ever killed.** The budget raises a flag a cooperating job reads; work declaring
  itself `stateful` is not even asked to stop — it is left to finish and its *next* run waits.
* Every decision written twice: an append-only `aries_resource_events` row the policy reads back,
  and a line in the engine's audit log. `aries power events`, `GET /api/aries/power/events`.
* `power.allow_gpu_jobs` stopped being declared-and-unread; `power.allow_heavy_cpu` joins it. Both
  `user_only` — learning may never decide to spend the user's electricity.

**220 new assertions.** 1281 total.

## M11 — ARIES as part of the environment · *Entry 012*

ARIES now starts with the login session and runs whether or not anything is watching. The
Control Centre became what it was meant to be: an optional window onto a running system.

* `aries.target` + `aries-core.service` as **systemd --user** units — no `sudo`, installed to
  `~/.config/systemd/user`.
* **One service, not six.** The API process already hosts all six workers, and the overlap lock
  is per-process — splitting would let the News Radar double-run. ADR-0005.
* **Four derived states**: `RUNNING · DEGRADED · STOPPED · STARTING`. A process alive with a dead
  dispatcher is DEGRADED, not running.
* `aries status | start | stop | restart`, working **when ARIES is stopped, starting or wedged**.
* Crash recovery verified with `kill -9`; start limit of 5 failures in 300s so a fault stops
  rather than spins — and `start` clears a hit limit, so the protection is not a trap.
* Reboot-safe: automations are paced by their last *recorded* run, so a missed 07:30 brief is
  produced when the machine wakes.
* `GET /api/aries/runtime` and `/runtime/components`; Home shows the state and lists what is
  broken when DEGRADED.

**49 new assertions.** 1061 total.

## M10 — ARIES Control Centre v0.1 · *Entry 011*

The first graphical interface: a GTK4 + libadwaita application, in its **own process**, speaking
to ARIES only over HTTP.

* **Nine screens** — Home, Brief, News, Interests, Learning, Automations, System, Connections,
  Settings. Every value is real ARIES state; nothing is mocked.
* **Explicit and learned are never blurred** — two numbers side by side, differing in form
  (solid vs dotted) as well as colour, so the distinction survives greyscale.
* **Settings are generated from the schema** — adding a setting to ARIES makes it appear,
  correctly rendered, with no UI change.
* **Connections is honest** — connected / available / **not built yet**, with status *derived*
  from whether a connector exists.
* **Command bar** (`Ctrl+Space`) over 16 real intents; unrecognised input says so plainly.
* **Never blocks** — worker threads, `GLib.idle_add`, and generation counters so a late reply
  cannot repaint a screen the user has left.
* **No privileged path** — the UI cannot import `aries`, so every write goes through the same
  authenticated, audited API as the CLI.
* `aries/integrations/` — §23's registry, added to ARIES proper.

**290 new assertions** (76 contract, 214 UI logic). 996 total. ADR-0004 records the technology
decision.

## M9 — Reversal detection and the fast learning loop · *Entry 010*

**Reversal detection.** A learned preference may now be taken back when the evidence
contradicts it — under hysteresis, so reversing is harder than forming.

* Evidence sliced by **time** (whole window, recent third, four buckets) and by **source**, so
  five situations that share an overall rate can be told apart: noise, temporary, contextual,
  fatigue, sustained.
* **Hysteresis as a confidence level**, not a moved threshold: reversing evaluates the same
  bar with a wider interval. `0/60` reverses; `1/60` does not, though the ordinary path would
  act on it.
* **Confirmation across passes** — a pending reversal is opened, confirmed, and *abandoned*
  the moment the contradiction stops. Alternating evidence therefore never reverses anything.
* **Damping and freezing** — each turnaround halves the allowed step; after
  `learning.max_reversals` the target is handed back to the user.
* Full provenance: previous value, evidence window, confidence interval, reason, new value,
  scope, timestamp, **policy version** (`reversal-v1`).
* `aries learning reversals`, `aries learning history`; `GET /api/aries/learning/reversals`.

**Fast loop.** Something the user says becomes something ARIES does — in seconds, and scoped.

* Classification: correction · preference · instruction · approval · rejection · one-off ·
  persistent rule · **not_feedback**. Ordinary conversation changes nothing.
* **Ambiguity is asked about, never guessed.** "shorter" returns a question; "always keep
  briefs shorter" is applied at once.
* Scope maps onto the layers built in Entry 002 and unused until now: `INSTRUCTION` for a
  narrow correction, `PROJECT` for a project, `USER` for an explicit standing rule — an
  explicit statement carries user authority because the user made it.
* `aries learning feedback | answer | preferences | explain`;
  `POST /api/aries/learning/feedback`, `GET …/preferences`, `GET …/explain/{subject}`.

**136 new assertions** (63 reversal, 73 fast loop). 706 total.

## M8 — Morning Brief · *Entry 009*
Parallel collection through the Director — the first concurrent workflow; three lengths that
keep different things rather than truncating; honest absence; time-of-day scheduling.

## M7 — Medium learning loop and source catalogue · *Entry 008*
Wilson intervals so small samples cannot move a weight; evidence only from what the user could
act on; the relevance bar only ever rises. 23 verified feeds to pick from.

## M6 — News Radar · *Entry 007*
`collect → cluster → verify → rank → deliver` as a workflow; address-pinning fetcher; RSS/Atom
parsing with no new dependency; duplicate clustering; source diversity; circuit breaker.

## Security hardening · *committed with M6*
Loopback-only without an API key; the two-stage SSRF guard completed; hostile-input bounds;
the audit trail names the authenticated principal.

## M5 — Personal Interest Profile · *Entry 006*
Word-boundary matching, synonyms, noisy-OR scoring, avoid-stance that disqualifies outright.

## M4 — Sources Registry · *Entry 005*
Nine source types; validation that refuses rather than warns; symlinks resolved before judging;
layered ordering so learning never outvotes the user.

## M3 — Dispatcher and Control Centre · *Entry 004*
One dispatcher paced by each automation's last recorded run; the §27 Control Centre over CLI
and HTTP; route permissions registered explicitly.

## M2 — System Health automation · *Entry 003*
Seven probes, learned baselines with robust statistics, three notification gates.

## M1 — Settings Service · *Entry 002*
Typed schema, layered store with provenance, precedence enforced on read *and* write.

## M0 — Foundation · *Entry 001*
Python 3.12 via `uv`; the `agentic_core` engine vendored and verified on this machine.
