# ARIES — Runtime

ARIES is a **user-level system layer**, not an application you launch. It starts with your login
session and keeps running whether or not any window is open.

```bash
cd ~/aries && ./scripts/aries-service install    # once — no sudo
aries status                                      # is it running?
```

## The model

```
login
  └─ default.target
       └─ aries.target                 ← "ARIES is running"
            └─ aries-core.service      ← one process
                 ├─ API                  127.0.0.1:8000
                 ├─ scheduler            due tasks, crash sweep
                 ├─ triggers             events → tasks
                 ├─ housekeeping         expires undecided proposals
                 ├─ learning             nightly distillation (engine)
                 ├─ autopilot            runtime-gated, off by default
                 └─ aries.automations    health · news · learning · brief
```

The Control Centre is **not** in this picture. It is a separate process that connects to a
running ARIES; closing it changes nothing.

## Why one service and not six

The API process already hosts every background component — splitting them would separate things
that are together by design, and two of the splits would be **wrong**:

* **The overlap lock is per-process.** It is what stops an automation pass starting while the
  previous one is still running. Two processes would each believe they were alone, and the News
  Radar would double-fetch every source and double-count the evidence the learning loop reads.
* **SQLite has one writer at a time.** Multi-process needs PostgreSQL *and* a database lease to
  replace the in-process lock.

The target exists anyway, because it is the central lifecycle handle: start and stop ARIES as a
whole, and attach a second service later with `WantedBy=aries.target` without changing how it is
operated. Full reasoning in `decisions/ADR-0005`.

## Status

Four states, each **derived** rather than declared:

| state | means |
|---|---|
| `RUNNING` | the service is up, answering, and every enabled component is alive |
| `DEGRADED` | it is up and something inside it is not working |
| `STARTING` | it is coming up |
| `STOPPED` | it is not running — no automation will fire |

`DEGRADED` earns its place: a process that is alive while its dispatcher has crashed, or while
an automation's circuit breaker is open, is not "running" in any sense you care about. Reporting
it as running is the same dishonesty as reporting `0` for "unknown".

```
$ aries status
  RUNNING  ARIES is running and everything inside it is working
  6 workers alive, 4 automation(s) enabled

  enabled at login · api reachable at http://127.0.0.1:8000

    ok   aries-core.service       service     active/running since Sat 2026-09-12 22:02:27 CEST
    ok   database                 storage     answering
    ok   aries.automations        worker      running
    ok   autopilot                worker      running (switched off)
    ok   scheduler                worker      running
    ok   Morning Brief            automation  5 item(s) across 5 sections
    ok   System Health Monitor    automation  healthy — 17 checks
    ok   News Radar               automation  5 delivered from 2 sources
```

**It works when ARIES does not.** Status is assembled in layers — systemd always, the API when
it answers — because the question is asked most urgently when something is broken. It answers
when the service is dead, starting, wedged, or fine.

## Commands

```bash
aries status              # the four states, plus every component
aries status --logs 30    # and the last 30 journal lines
aries start | stop | restart
```

`start` clears a hit start-limit first. A unit that failed five times refuses to start until it
is reset — that is the safe policy doing its job, but "start it" must actually start it, or the
protection becomes a trap needing an obscure incantation to escape.

```bash
./scripts/aries-service install | uninstall | status | logs [n] | reinstall
aries power status | on | off     # Background Mode and the resource policy — see POWER.md
aries power events                # every time heavy work was refused or released
aries connect                     # folders and mailboxes ARIES may read — see INTEGRATIONS.md
aries attention                   # read them, and say what needs you
aries do "open the news screen"   # ask for something, and be told what was CONFIRMED
aries do --yes "open youtube"     # carry out a plan the model made
aries data                        # what is kept, what is held now — see DATA.md
aries data clean | sweep | vacuum # remove what is past its window; rehearses first
```

## Crash recovery

`Restart=on-failure`, `RestartSec=5`, and a start limit of **5 failures in 300 seconds**. After
that systemd stops trying, so a genuine fault surfaces as a stopped service rather than a
machine burning CPU all night.

Verified: `kill -9` on the main process → restarted automatically → `RUNNING` within seconds.

Inside the process, failure isolation is per-automation rather than per-process: the circuit
breaker pauses an automation that keeps failing, and the overlap lock stops a slow pass being
started twice.

## Resuming after a reboot

Nothing is lost, because nothing schedules from a timer:

* **automations** are paced by their **last recorded run** in the database, so a missed cycle is
  caught up rather than skipped. A machine asleep at 07:30 produces the morning brief when it
  wakes.
* **enabled/disabled state** lives in settings, not in memory.
* **in-flight work** is recovered at startup: `recover_stuck` marks operations that were `sent`
  when the process died as `uncertain` — never `failed`, which would auto-retry and risk doing
  a side effect twice.

## Shutdown

`KillSignal=SIGINT`, which uvicorn treats as graceful: it stops accepting, runs the lifespan
shutdown, which stops every worker and disposes the database engine. `TimeoutStopSec=20`.

Logging out stops ARIES, because `Linger` is off. That is deliberate — ARIES does not run while
nobody is logged in. **Background Mode does not change this**: it keeps the machine from
*suspending* while you are logged in and the screen is dark; it is not a way to run headless. To
change that:

```bash
loginctl enable-linger $USER      # needs your password
```

## Staying awake

[Background Mode](POWER.md) holds a `sleep`/`block` logind inhibitor so the machine does not
suspend while ARIES is working, while letting the display power off exactly as it always did. The
lock is a file descriptor held by a child process, so it is released by the kernel if ARIES dies
in any way — including `SIGKILL`. On restart, reconcile takes a fresh one.

The same tick also runs the resource policy: it releases thermal holds whose machine has cooled,
and checks whether any running heavy job has outstayed its budget. Both happen **before** the
`automations.worker_enabled` check, because a heavy job started by hand keeps running while the
dispatcher is off — and a hold taken during it must still be released afterwards.

## Dependencies

`aries-core.service` deliberately does **not** wait for the network. ARIES tolerates being
offline by design: an unreachable source is recorded as a source failure, its health degrades,
and the circuit breaker pauses it. Waiting would delay the health monitor and the brief, which
need no network at all.

## The units

`systemd/aries.target` and `systemd/aries-core.service`, installed to
`~/.config/systemd/user/`. No `sudo`: user units belong to the login session.

Both must be enabled — `aries-core.service` so the target pulls it in, and `aries.target` so the
login session pulls that in. Enabling only the target starts it and pulls in **nothing**; the
installer does both.

## Health from outside and inside

| surface | shows |
|---|---|
| `aries status` | the four states, every component, systemd's view |
| `GET /api/aries/runtime` | the same derivation, as JSON |
| `GET /api/aries/runtime/components` | workers, automations, breakers, database — cheap, no automation runs |
| Control Centre → Home | the state as a chip; `DEGRADED` lists what is broken |
| `journalctl --user -u aries-core` | the log |

One derivation, several surfaces — the engine's rule that one code path or they drift.

## Known limits

* One process is one blast radius. Bounded by the restart policy and, honestly, by the fact that
  a worker able to take the process down is a bug rather than a topology to design around.
* `Linger` off means no ARIES between logout and login. Intentional today.
* The port is fixed at 8000. A second ARIES on one machine would collide — and does: a manually
  started instance blocked the service during development, which the logs said plainly.
