# ADR-0007 — Work declares its cost; two separate gates decide whether it may run

**Status:** accepted · **Date:** 2026-09-12 · **Journal:** Entry 013

## Context

ADR-0006 made the machine stay awake. That is a promise about availability, and on its own it is
one-sided: an always-awake machine that will start anything at any hour is a denial of service
against its own owner. Something has to answer the second question — not *may the machine stay
awake?* but *may this work run right now?*

The requirement set the defaults precisely. While the display is off: lightweight automations,
news fetching, health checks, memory maintenance and lightweight inference all allowed; sustained
heavy GPU work blocked unless explicitly enabled; sustained high-CPU work budgeted or blocked
unless explicitly enabled. Thresholds for CPU, GPU, temperature and maximum heavy-job duration.
On exceeding thermal limits: defer non-critical heavy work, never silently kill critical stateful
work, record the decision in audit, resume when safe.

## Decisions

### 1. Cost is declared in the genome, not measured from history

ARIES could watch what an automation *did* last time and infer that it is heavy. That is a worse
design for a gate: the first run is the one that would hurt, the inference is wrong for work whose
cost depends on its input (a repository scan, an inference batch), and it makes the rule
unreadable. A declaration is checkable before anything runs, and being wrong about it is a visible
bug in a spec rather than an invisible property of history.

It goes in the `AutomationSpec` because that is where every other static fact about an automation
already lives — so it is versioned, diffable, visible in the Control Centre, and a change of cost
is a change of version.

**`workload` is not `risk`.** Risk is about consequences if something goes wrong; workload is
about cost while everything goes right. The Morning Brief is low risk and lightweight; a nightly
local-model re-index would be low risk and very heavy. One field could not have said both, and
collapsing them would have made "is this a big deal?" a question with two incompatible answers.

Four classes: `light`, `inference_light`, `heavy_cpu`, `heavy_gpu`. Three could not tell a model
answering one short question from a model running for an hour; six would be a taxonomy nobody
could apply consistently. `light` is the default, so adding the field reclassified nothing.

### 2. Permission and condition are separate gates

* **Permission** — may this class run unattended at all? Static, from settings, default-closed
  for heavy work, nothing measured.
* **Condition** — is the machine in a state to take it now? Live, from `/proc/stat`, the thermal
  zones and `nvidia-smi`.

They are kept apart because their refusals have different fixes. *"Heavy GPU work is not enabled
while the display is off"* is solved by a toggle; *"the machine is at 84 °C"* is solved by waiting.
A policy reporting one number for both would leave the user guessing which.

`force` — a person pressing **Run now** — carries the permission gate, because someone explicitly
asking *is* the explicit enabling the requirement asks for. It does not carry the thermal gate: no
amount of wanting makes an 88 °C machine a good place to start a GPU job.

### 3. Lightweight work is never deferred

At any temperature. This is the decision most likely to look like an oversight, so it is recorded
as a decision: light work costs a fraction of a core for seconds, and **the health check is how
ARIES finds out the machine is hot**. A policy that silenced its own thermometer to save heat
would be measuring nothing and protecting nothing. The same reasoning covers news fetching and
memory maintenance, which are I/O-bound and idle most of their duration.

### 4. Thermal deferrals take a hold with a margin; utilisation deferrals do not

Temperature is a *condition* — it persists, and the thing that caused it is the thing that would
restart. So crossing the limit takes a hold, and releasing it requires the temperature to come
back below the limit **minus a margin** and stay there for a number of consecutive checks. Entry
010 taught this project that hysteresis expressed as a moved threshold becomes an unreachable
rule; here it is expressed as a margin measured downward from a limit the user chose, and both the
margin and the streak are settings with reachable ranges.

Utilisation is a *moment*. It is re-asked on the next tick, and nothing about waiting makes the
reading oscillate, so it takes no hold and needs no margin.

The hold is a row in an append-only table, and the current state of the policy is read back from
that record rather than remembered beside it. A state kept next to its own history is a state that
can disagree with it.

### 5. Nothing is ever killed

"Stop" is a flag — `governor.stop_requested(automation_id)` — that a cooperating job reads between
units of work. Nothing cancels a task or signals a process, because the requirement was explicit
that stateful work is never *silently* killed, and a job killed at an arbitrary line is the
definition of silently. Work declaring `stateful=True` is not even asked to stop: it is left to
finish, recorded as over budget, and its *next* run waits instead.

A job that ignores the flag keeps running. That is accepted: the record is what a person acts on,
and the alternative — a supervisor empowered to kill work mid-write — is a larger hazard than a
long job.

### 6. An unreadable sensor allows heavy work, with the caveat recorded

Unknown is never zero; the measurement reports `null` with a reason. But blocking heavy work
forever on a machine with no thermal sensor would be Entry 010's unreachable rule again, and heavy
work is already opt-in — the user has explicitly asked for it. So the gate allows, and the verdict
says the guard could not check. This is the one place the policy fails *open*, and it is recorded
here so that it is a decision rather than an accident.

## Consequences

* Every automation that exists today is `light`, so the policy refuses nothing yet. The gate and
  the budget are implemented and tested; what is absent is heavy work to meet them. The status
  panel states which of those two is true, because "the gate is not built" and "nothing meets it
  yet" are very different claims and the first would be a lie.
* The check costs nothing for light work: it returns before measuring anything.
* `power.allow_gpu_jobs`, introduced in ADR-0006 as a declared permission for an undelivered
  capability, is now the live gate for `heavy_gpu`. The permission existed before the capability,
  which was the point of declaring it early.

## Alternatives rejected

**cgroups / `systemd-run --slice` with `CPUQuota=` and `MemoryMax=`.** Genuinely enforcing rather
than advisory, and the right answer eventually. Rejected for now because it constrains work ARIES
*spawns as processes*, and every automation today runs in-process in the asyncio loop — so it
would have enforced nothing while looking like it enforced everything. It belongs with the first
automation that shells out to a long-running job, and it composes with this policy rather than
replacing it: the policy decides whether to start, cgroups would bound what it does after.

**`nice`/`ionice` instead of refusing.** Deprioritising rather than deferring sounds gentler and
does nothing for the actual problem: a de-prioritised GPU job still heats the machine, and `nice`
has no effect at all on a machine that is otherwise idle — which is exactly the unattended case.
