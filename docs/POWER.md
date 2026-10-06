# ARIES — Power & Background Mode

**Background Mode keeps the machine awake while the screen goes dark.**

The use case is exact: you stay logged in, the display powers off as normal, and Linux does not
suspend. ARIES keeps running — the scheduler, enabled automations, the learning loop, the News
Radar, the Morning Brief — and the network stays up. The Control Centre does not have to be open,
because it never was the thing doing the work.

```bash
aries power status          # what is actually true right now
aries power on              # Background Mode on
aries power off             # and back to normal power behaviour
```

The same switch is in the Control Centre under **Settings → Power & Background**, and both go
through the same audited settings path. There is no privileged GUI route.

---

## How logind inhibitors work

`systemd-logind` arbitrates who may put the machine to sleep. Any program can ask it for an
**inhibitor lock**, and logind consults the outstanding locks before it acts.

A lock has three parts:

| part | what it means |
|---|---|
| `what` | which event is being held back — `sleep`, `idle`, `shutdown`, `handle-lid-switch`, … |
| `mode` | `block` — refuse the event outright. `delay` — let it happen, but not before I have finished reacting (bounded by `InhibitDelayMaxSec`, a few seconds). |
| `who` / `why` | free text, shown in `systemd-inhibit --list`. This is how a user finds out what is keeping their laptop awake. |

**The lock is a file descriptor, and that is the whole design.** `Inhibit()` returns an fd over
D-Bus. The lock exists exactly as long as that fd is open. Close it and the lock is gone. There is
no "release" call to forget, no timeout to tune, and no stale lock left in a database — because the
kernel closes every fd of a process that dies, *however* it dies. Crash, `SIGKILL`, OOM killer,
power cut: the lock is released by the same mechanism in every case.

ARIES holds its lock by running

```
systemd-inhibit --what=sleep --who=ARIES --mode=block --why="…"  /bin/sh -c 'read -r _ <&0'
```

as a child process whose stdin is a pipe ARIES holds the write end of. The shell blocks forever on
an empty read; `systemd-inhibit` keeps the fd open for as long as that shell lives. To release,
ARIES closes the pipe: the read returns, the shell exits, `systemd-inhibit` exits, the fd closes,
the lock is gone. Nothing is left behind in either direction.

This was verified rather than assumed, before any of it was written: the lock appeared in
`systemd-inhibit --list`, disappeared when the pipe was closed, and disappeared when the holder was
`SIGKILL`ed.

## The exact inhibitor ARIES takes

```
what = sleep      mode = block      who = ARIES
```

**`sleep`, not `idle`.** This is the load-bearing choice. An `idle` inhibitor tells the session the
user is still there, which stops the screen blanking and stops the screensaver — the opposite of
what was asked for. `sleep` holds back *only* suspend and hibernate. The display powers down
exactly as it always did.

**`block`, not `delay`.** `delay` only buys a few seconds before the suspend proceeds anyway; it is
for programs that need to save state first. `block` makes a non-interactive suspend request fail
outright, which is what "do not suspend while ARIES is working" requires.

**One lock, not one per job.** Background Mode is a state, not a queue.

ARIES deliberately takes **no** `idle` inhibitor, and the Control Centre asserts this on screen —
if a future change ever took one, the display would stop blanking and the user would want to know
which program did it.

## Lifecycle

`reconcile()` is the only thing that takes or releases the lock. It compares the setting with the
machine and fixes the difference, and it is idempotent, which is what lets it be called from three
places without coordination:

| called | why |
|---|---|
| at startup | a reboot or a crash means no lock is held, whatever the setting says |
| when the switch is toggled | so the switch feels like a switch instead of taking up to a minute |
| on every dispatcher tick | because the holder can die without asking |

The tick call sits **before** the automations-enabled check, on purpose. Background Mode must hold
its lock whether or not the automations dispatcher is switched on, and this is also where a lost
lock is noticed and retaken.

"Is the lock held?" is never answered from a remembered flag. `held()` checks the actual child
process, and the status panel additionally reads `systemd-inhibit --list` — the honest answer to
*is suspend inhibited* is the one **logind** would act on, not the one ARIES believes.

## What happens if ARIES dies while holding it

Nothing that needs cleaning up. The lock is released by the kernel closing the dead process's file
descriptors, in every failure mode including `SIGKILL` and a hard power loss. The machine returns
to normal suspend behaviour on its own.

When systemd restarts `aries-core.service`, startup reconcile takes a fresh lock because the
setting still says Background Mode is on. The gap is the restart delay (`RestartSec=5`), during
which the machine could in principle suspend. That is the correct trade: a lock that outlived the
program holding it would be a lock nobody could find and release.

The one thing that *does* persist across a crash is the display timeout, because it is a GNOME
setting and not a file descriptor — see below.

## The display timeout: the one thing ARIES writes outside itself

The brief was explicit: *do not permanently change global GNOME power settings if a scoped
inhibitor is sufficient*. For suspend, the inhibitor is sufficient, and no GNOME setting is touched.

"Display off after" is different — there is no scoped mechanism for it; the timeout is
`org.gnome.desktop.session idle-delay`, a global GNOME setting. So it is treated as borrowed:

1. before changing it, the current value is recorded in `power.restore_idle_delay`;
2. on switching Background Mode off, the recorded value is written back exactly and the record is
   cleared.

Because the record is in the ARIES database rather than in memory, a crash does not lose it —
restoration still happens on the next reconcile. The recorded value is shown in the Control Centre
as *"will restore to N s"* rather than offered as an editable control: editing it would destroy the
value the machine has to be returned to.

If you never want ARIES to touch it, set **Display off after** to the value your desktop already
has, and nothing is written.

## The resource policy: what ARIES may *do* while it is awake

Keeping the machine awake is a promise about availability. On its own it is
dangerous, because the obvious next step is a machine that never sleeps and will
start anything at any hour — so Background Mode also answers a second question:
not *may the machine stay awake?* but *may this work run right now?*

### Workload classes

Work declares what it costs. The class lives in the automation's genome, next to
its permissions, so it is versioned and diffable and a change of cost is a change
of version.

| class | what it is | while the display is off |
|---|---|---|
| `light` | files, feeds, arithmetic over rows | **always allowed** |
| `inference_light` | a model answering a bounded question | **always allowed** |
| `heavy_cpu` | several cores busy for minutes | **blocked** unless `power.allow_heavy_cpu`, then budgeted |
| `heavy_gpu` | the GPU busy — local inference or training | **blocked** unless `power.allow_gpu_jobs`, then budgeted |

`workload` is not `risk`. Risk is about consequences if something goes wrong;
workload is about cost while everything goes *right*. The Morning Brief is low
risk and lightweight; a nightly local-model re-index would be low risk and very
heavy indeed, and one field could not have said both.

Every automation that exists today is `light`, so nothing is currently being
refused. The gate is live regardless — the first automation that declares a heavy
class meets it — and the status panel says which of those two things is true,
because "the gate is not built" and "nothing meets it yet" are very different
claims.

**Lightweight work is never deferred**, whatever the temperature. That is
deliberate rather than an omission: it costs a fraction of a core for seconds,
and the health check in particular is *how ARIES finds out the machine is hot*.
A policy that silenced its own thermometer to save heat would be measuring
nothing and protecting nothing.

### Two gates, kept apart

* **Permission** — may this *class* run unattended at all? Static, from settings,
  default-closed for heavy work, and nothing is measured to answer it.
* **Condition** — is the machine in a state to take it *now*? Live, from the
  processor, the GPU and the thermal sensors.

Keeping them apart is what makes a refusal legible. *"Heavy GPU work is not
enabled while the display is off"* and *"the machine is at 84 °C"* are different
problems with different fixes; one number for both would leave you guessing.

A person pressing **Run now** carries the permission gate — that is exactly the
"explicitly enabled" the policy asks for — but not the thermal one. No amount of
wanting makes an 88 °C machine a good place to start a GPU job, and the refusal
names the limit that stopped it.

### Thresholds

| setting | default | what it gates |
|---|---|---|
| `power.temperature_limit_celsius` | 80 °C | heavy work is deferred at or above it |
| `power.cpu_limit_pct` | 70 % | a `heavy_cpu` job is not *started* above it |
| `power.gpu_limit_pct` | 70 % | a `heavy_gpu` job is not started above it |
| `power.heavy_job_max_minutes` | 20 min | how long one heavy job may run |
| `power.thermal_resume_margin_celsius` | 5 °C | how far below the limit it must come back |
| `power.thermal_clear_checks` | 2 | consecutive cool readings before resuming |

80 °C is below where consumer silicon starts throttling itself, so ARIES gives
way before the hardware has to. Both defaults are reachable in both directions —
a limit nothing ever crosses is decoration, and one crossed constantly is an off
switch wearing a number.

### Measurement

CPU utilisation is a delta of `/proc/stat` between calls, so on the dispatcher's
cadence it reports the average since the last check — the right window for a rule
about *sustained* load. The first call has nothing to subtract and samples over
250 ms instead. Temperature and GPU reuse the health probes rather than reading
the sensors a second way: two readers of one sensor drift, and the health screen
and the power policy disagreeing about how hot the machine is would be worse than
either being slightly stale. A GPU's own temperature counts toward the thermal
limit — on most desktops it is the hottest thing in the case.

Readings are cached for a few seconds, so four automations asking in one tick is
one measurement.

**An unreadable sensor is never a zero.** It reports `null` with the reason. For
the gate itself the decision is deliberate and worth stating plainly: heavy work
is *allowed* when temperature cannot be read, with the caveat recorded in the
verdict. Blocking heavy work forever on a machine with no thermal sensor would be
Entry 010's unreachable rule all over again, and heavy work is already opt-in —
the user has explicitly asked for it.

### Deferring, and resuming

Crossing the temperature limit takes a **hold** on that workload class. The hold
is a row in `aries_resource_events`, and the current state of the policy is read
back from that record rather than remembered next to it — a state kept alongside
its own history is a state that can disagree with it.

Resuming is the half of a protective rule that usually gets forgotten, and a rule
that only ever tightens ends with everything switched off. So the hold is
released when the temperature comes back below the limit **minus the margin**,
and stays there for `thermal_clear_checks` consecutive checks. Both are settings,
both reachable. Without the margin the first reading under the limit restarts the
job that caused the heat and the machine oscillates — the same trap Entry 010's
hysteresis bug fell into, in its second home.

Utilisation deferrals take **no** hold. Utilisation is a moment, not a condition:
it is re-asked on the next tick and needs no margin, because nothing about
waiting makes the reading oscillate.

### The budget, and what "stop" means

A heavy job that outruns `power.heavy_job_max_minutes` is recorded as over budget
and the flag `governor.stop_requested(automation_id)` is raised. That flag is the
whole of "stop": something a cooperating job reads between units of work.

**Nothing is cancelled or signalled**, because the requirement was explicit that
stateful work is never silently killed — and a job killed at an arbitrary line is
the definition of silently. Work declaring `stateful=True` is not even asked to
stop: it is left to finish, recorded as over budget, and its *next* run waits
instead. A job that ignores the flag keeps running; the record is what a person
acts on.

### The record

Every decision — `blocked`, `deferred`, `over_budget`, `resumed` — is written
twice: a row in `aries_resource_events` (queryable, and what the policy reads
back) and a line in the engine's audit log (what a human paging through
everything ARIES did will find). Neither is the other's copy.

```bash
aries power events          # newest first
```

## Energy and thermal implications

Honest ones, because this feature exists to stop a machine going to sleep:

* **A machine that does not suspend uses power continuously.** An idle desktop is typically tens of
  watts; a laptop on battery will flatten in hours. Background Mode is `user_only` — ARIES may never
  infer it for itself — precisely because it spends the user's electricity and battery.
* **The display is not the load.** Blanking the screen saves most of the panel's power, and that
  still happens. What Background Mode costs is the rest of the machine staying powered.
* **Thermals are the same as any idle machine.** ARIES's own work is a health probe, an RSS fetch
  and some arithmetic — not a sustained load. Fans should not spin up because of it.
* **Heavy work is gated rather than trusted.** Sustained CPU and GPU jobs are refused while the
  display is off unless you enable them, and even then they give way to the temperature limit and
  are budgeted. See the resource policy above.
* **Suspend still works when you ask for it.** A `block` inhibitor stops *automatic* suspend;
  `systemctl suspend` from a logged-in user is interactive and prompts rather than silently failing,
  and closing a laptop lid is governed by a different lock (`handle-lid-switch`) that ARIES does not
  take.

## On this machine, specifically

`sleep-inactive-ac-type` is `nothing` and `/sys/class/power_supply` is empty — a desktop that was
already configured never to suspend. So on **this** hardware the inhibitor changes nothing
observable, and `aries power status` says exactly that instead of taking credit:

```
this machine is already set never to suspend on mains power, so the inhibitor
changes nothing while it is plugged in — it matters on battery
```

That is not a defect of Background Mode; it is the difference between the mechanism working and the
mechanism mattering. It does matter on a laptop, on a machine with GNOME's default AC suspend, or
if the AC policy is ever changed back.

## Rollback

Background Mode is designed to be undoable with no residue.

```bash
aries power off        # releases the lock, restores the display timeout
```

If you want it gone entirely:

| to remove | how | left behind |
|---|---|---|
| the lock | `aries power off`, or stop ARIES, or kill it | nothing — the fd closes |
| the display timeout change | `aries power off` | nothing — the recorded value is written back |
| the settings | `aries settings reset power.background_mode` (and siblings) | nothing |
| the resource policy | it only ever *refuses* work; nothing to undo | the `aries_resource_events` rows, which are history |
| the feature | stop ARIES | nothing — no system file, unit, or root-owned state was created |

Nothing in Background Mode requires `sudo`, writes outside `~/aries` except the one GNOME key it
borrows and returns, or survives ARIES being stopped.

## Verifying it yourself

```bash
systemd-inhibit --list | grep ARIES        # logind's own answer
aries power status                         # measured, not remembered
aries power events                         # every time the policy said no
```

To watch the thermal gate act without waiting for a hot machine, lower the limit
below the current reading for a moment:

```bash
curl -s -X PUT localhost:8000/api/aries/power \
     -H 'Content-Type: application/json' -d '{"temperature_limit_celsius":45}'
aries power status        # heavy classes now read "deferred", light ones "allowed"
curl -s -X PUT localhost:8000/api/aries/power \
     -H 'Content-Type: application/json' -d '{"temperature_limit_celsius":80}'
```

And the elapsed-time test, which takes real minutes and puts the machine back as it found it:

```bash
./scripts/test-background-mode.sh 16
```

See [TESTING.md](TESTING.md) for what that test can and cannot prove.
