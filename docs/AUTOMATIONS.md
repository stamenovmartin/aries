# ARIES — Automations

An automation is a **declaration** (`AutomationSpec`, the Automation Genome of §12) plus an
append-only **run history**. It is never just a function somebody scheduled.

That split is what makes §27's Control Centre possible — enabled, version, purpose, trigger,
last run, next run, last result, health, permissions, evolution history — and what makes
§18's controlled evolution possible later: you cannot sandbox, benchmark or roll back a
Python function, but you can do all three to a versioned declaration.

## Standing rules

* **Nothing is enabled by default** (§11). `enabled_setting` names a setting; the setting is
  the truth.
* **Pacing is by the last recorded run**, not a timer, so a missed cycle (asleep, restarted)
  is caught up rather than skipped.
* **A behaviour change is a new version.** An automation may not quietly become something
  else.
* **History is derived, never maintained by hand** — "last result" and "health" are queries
  over `aries_automation_runs`.
* **Honest health**: with no runs in the window, the success rate is `null` with a reason,
  never `0.0`. "Never ran" and "always failed" are different facts.
* **Every automation declares what it costs the machine** — `workload` is one of `light`,
  `inference_light`, `heavy_cpu`, `heavy_gpu`, and `light` is the default so adding the field
  reclassified nothing. It is a different axis from `risk`: risk is what happens if this goes
  *wrong*, workload is what it does to the processor and the thermometer while it goes right.
  Heavy work meets the resource policy before it runs ([POWER.md](POWER.md)); every automation
  that exists today is `light`, so nothing is refused today.
* **`stateful` says whether interrupting it would lose work.** Stateful heavy work is never
  asked to stop mid-run — it is recorded as over budget and its next run waits instead.

## Built

### `aries.health` — System Health Monitor (§13/08)

| | |
|---|---|
| version | 1.0.0 |
| purpose | Watch CPU, memory, disk, temperature, GPU and systemd units; learn what is normal for this machine; tell the user only what is worth knowing. |
| trigger | schedule, every `health.interval_minutes` (default 15) |
| task kind | `aries.health.check` |
| risk | low — read-only; it never changes the machine |
| agents | none — judgement here is deterministic, so it works with the network down |
| tools | `systemctl list-units`, `nvidia-smi` (a four-command read-only allowlist) |
| permissions | `VIEW_DATA` |

**Probes.** cpu (load per core, PSI) · memory (MemAvailable, swap, PSI) · disk (statvfs per
real filesystem) · thermal (`/sys/class/thermal`) · gpu (nvidia-smi) · services (failed
units) · uptime (days, pending reboot).

**The distinction it is built around.** Did the *check* work, and is the *machine* healthy,
are independent questions. A working check on a 97%-full disk has succeeded — it found bad
news. So the run status (`ok`/`degraded`/`failed`) describes the check, a CRITICAL finding
produces an `ActionProposal` for a human while the task still completes, and the lifecycle's
ESCALATE path is reserved for the check itself being broken (every probe unavailable means
ARIES is blind, which is its own incident).

**ARIES never repairs anything here.** It measures, judges and asks.

**Learning (§13/08).** Every measurable reading is recorded; baselines are the median and
p95 over a 14-day window, using robust statistics so one extreme sample cannot widen what
counts as normal. A baseline may then **soften** a finding — never harden it — under two
hard limits:

* a ceiling (`health.baseline_suppress_max_severity`, default `warning`): a CRITICAL is
  never silenced;
* an eligibility list (`baseline.SUPPRESSIBLE`): only genuinely fluctuating metrics.
  Accumulating ones are excluded, because **a disk that has been 96% full for a month has a
  stable baseline and is still about to fail**.

### `aries.data` — Data Lifecycle (Entry 018)

| | |
|---|---|
| version | 1.0.0 |
| purpose | Release the context of finished work, and remove data that has passed the retention window the user set. |
| trigger | schedule, every `data.clean_interval_hours` (default 24) |
| risk | **medium** — it is the one automation that deletes |
| agents | none — deterministic, and a model has no business choosing what to forget |
| permissions | `VIEW_DATA` |

**Two switches, both off.** `data.enabled` decides whether it runs at all;
`data.cleaning_enabled` decides whether a run may *delete*. With the second off, a run still
sweeps abandoned working sets and reports what it would remove.

**It is an automation rather than a hidden cleaner in a worker** for one reason: a process that
deletes the user's data unasked, from a place they cannot see, is precisely the one that must not
be invisible. So it appears in this screen with its purpose, its last run and its history, its
failures open its circuit breaker, and it can be switched off like everything else.

**Nothing deletes on the first pass.** `data.dry_run_first` makes the first real run record its
plan in the audit log and act on the next one. See [DATA.md](DATA.md).

## The four questions before a run

Every run — dispatcher, API, CLI, "Run now" — takes the same path, and is asked the same four
things in the same order. They are separate because their answers have separate fixes:

1. **enabled?** — §11's switch. *You have not switched this on.*
2. **may the machine do this kind of work now?** — the resource policy. *Not while the display
   is off, or not at 84 °C.* Lightweight work answers instantly and measures nothing.
3. **is it broken?** — the circuit breaker. *It has failed five times in a row.*
4. **is it already running?** — the overlap lock. *The previous pass has not finished.*

A refusal at any of the four is recorded as a `skipped` run with the reason, so it is visible
rather than silent.

## How they run

One **dispatcher** (`aries.automations`) registered into the engine's worker roster ticks
every 60 seconds and asks each automation whether it is due. That is how often the *question*
is asked, not how often anything runs: an automation set to 15 minutes is checked fifteen
times and run once.

One dispatcher rather than a timer per automation means twenty automations do not become
twenty asyncio tasks, an interval changed in Settings takes effect on the next tick with no
restart, and pacing lives in the durable run history — so a reboot or a suspended laptop
resumes rather than resetting.

**It ships switched off.** `automations.worker_enabled` defaults to false and is `user_only`,
so no learning loop can ever turn on the thing that runs other things.

Every run — dispatcher, API or CLI — goes through `run_automation`, which creates a Task and
hands it to the engine's lifecycle. The three callers differ only in the `trigger` string, so
the scheduled path and the "Run now" button cannot drift.

A pass that outruns its interval is **refused, not queued**, and the refusal is recorded as a
`skipped` run. Queueing would let a slow automation build a backlog it can never work off.

## Seeing them

```bash
./scripts/aries automations          # registered · enabled · due · last run · success rate
./scripts/aries worker               # the dispatcher: the switch and the task state
./scripts/aries worker --tick        # run one dispatcher pass now
./scripts/aries health               # run one pass now
./scripts/aries settings health      # every threshold, and where its value came from
./scripts/start.sh                   # the Control Centre over HTTP — see docs/API.md
```

## Notification policy (§26)

Findings do not reach the user directly. Three gates stand between:

1. **Level** — at or above `notifications.minimum_level`?
2. **Repeat** — already delivered within the cooldown, without worsening? An escalation
   always breaks through.
3. **Quiet hours** — late, and less than critical?

Every decision is recorded, **including the suppressed ones**, so "ARIES noticed this at
02:14 and held it until morning" is answerable (§29).

The repeat gate is the one monitoring systems forget, and it is why they become wallpaper.

## Adding one

1. Write the body: `async def run(ctx) -> dict`.
2. Declare an `AutomationSpec` and `register()` it.
3. Add its settings, including an `enabled_setting` defaulting to off.
4. If it should run through the task lifecycle, `register_kind(...)` with evaluators.
5. Write the tests, then a Build Journal entry.
