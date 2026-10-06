# ARIES — Data Lifecycle

**A browser opens a page, you read it, you close it, and the page is gone. What survives is a
bookmark — not the HTML.**

That is the whole rule. ARIES pulls in mail, files and pages to do a piece of work, uses them, and
discards them. What persists is the conclusion and enough provenance to answer *"where did you get
that?"*.

```bash
aries data            # what is kept, what is held right now, what is past its window
aries data clean      # remove what is past its window (rehearses first)
aries data sweep      # collect context left behind by a task that died
aries data vacuum     # give the freed space back to the filesystem
```

The same thing is in the Control Centre under **Data**, and both go through the same audited
service. There is no privileged route.

---

## Why this exists before the Operator, not after

An Operator that can read your mail and nothing telling it what to forget will hoard: message
bodies in a SQLite file, forever, because nothing ever said to remove them. This is not
hypothetical — before ARIES had read a single personal thing, `automation_logs` was already the
largest table in the database at 3,400 rows.

So the lifecycle is a precondition of the Operator, not a tidy-up after it.

---

## Five classes

| class | what it is | lifetime |
|---|---|---|
| **working** | the context pulled in to do one task — mail bodies, file contents, pages | released when the task ends, whatever the outcome |
| **operational** | logs, samples, runs | a window, then noise |
| **memory** | what ARIES concluded, and what you told it | until you remove it |
| **provenance** | a pointer back to where a memory came from | exactly as long as the memory it supports |
| **audit** | the record of what ARIES did, including its own deletions | **never** removed automatically |

The classes are declared once, in `aries/lifecycle/policy.py`, and served from
`GET /api/aries/data` as `classes` — so no screen invents its own wording for them.

### The working set is not a cache

`aries_working_set` holds what one task is reading. It is a table rather than variables because
work is resumable: the engine's plans survive a restart with at-most-once side effects, so a task
interrupted halfway has to be able to pick up its context. Holding that only in memory would mean
either losing it or quietly re-fetching — and re-fetching is how a system that promised
at-most-once sends an email twice.

Its lifetime is **the task's, not a timer's**. `_run_through_lifecycle` releases it in a `finally`,
so a pass that died halfway — the one still holding borrowed mail bodies — releases too. The only
reason it has an age at all is that a crashed process cannot release its own context; the sweep
collects what is older than `SWEEP_HOURS` (6), far longer than any task ARIES runs.

Nothing ARIES *concluded* may live here. A conclusion belongs in memory with its provenance; if it
is only in the working set it disappears when the task ends, and the user is told something ARIES
can no longer explain.

Contents are never served over HTTP. `GET /api/aries/data/working-set` returns labels, sources,
sizes and the owning task — the point of a working set is that borrowed material does not travel,
and a route that served it would be the hole in that.

---

## The part that is easy to get wrong

Deleting a row another subsystem reads.

The circuit breaker decides whether an automation is broken by reading its run history. The
learning loop measures engagement from news items. Health baselines are computed from samples.
Delete those too eagerly and **nothing fails** — the subsystem quietly starts answering
differently, which is worse than a crash, because a crash is visible.

So every policy names its dependants and the shortest window that keeps them correct:

```python
Retention(
    "aries_automation_runs", OPERATIONAL,
    "One row per run. The circuit breaker decides whether an automation is broken by reading "
    "these, and pacing reads the last one — so this window is a correctness constraint, not a "
    "preference.",
    ...)
```

A window below the minimum is **refused, not clamped silently** — twice, in two places, because
one of them can be bypassed:

* the setting schema carries `minimum=minimum_days`, so a value that low is rejected at the door,
  by the settings service, with the reason;
* `service._window_for` checks again, because a row written straight into `aries_settings` never
  passes the schema at all.

A retention window that starves a dependant is a correctness bug wearing a preference's clothes.

---

## Nothing deletes on the first try

`preview()` counts what would go and touches nothing. `data.dry_run_first` (on by default) makes
the *first real pass* a rehearsal too: it records the plan in the audit log, turns itself off, and
acts on the next pass. Anything that deletes should be boring by the time it runs.

`aries data clean --force` and `POST /api/aries/data/clean {"force": true}` skip the rehearsal, and
have to say so explicitly — the default in both is `false`, so neither can skip it by accident.

Every deletion writes an audit event (`data.rehearsed`, `data.cleaned`) **before** the call
returns, so the record exists whether or not anyone reads the response. The audit log is itself
never cleaned: a retention policy that erased the evidence of its own deletions is the one policy
nobody could check.

---

## It ships off, and says so

`aries.data` is a declared `AutomationSpec`, so it appears in the Automations screen with its
purpose, its last run and its history; it can be switched off; and its failures open its circuit
breaker. A process that deletes the user's data unasked, from a place they cannot see, is the one
automation that must not be invisible.

Two switches, both off by default:

* `data.enabled` — whether the automation runs at all;
* `data.cleaning_enabled` — whether a run is allowed to *delete*. With it off, a run still sweeps
  abandoned working sets and reports what it would remove.

Off means nothing is ever removed automatically, the database grows without limit, and
`aries data clean` is the only way anything goes.

---

## No table is left undecided

A table absent from the register is a table nobody decided about, which is how a database grows
forever by accident. `test_no_table_is_left_undecided` reads `sqlite_master` and fails on anything
`POLICIES` does not name — which is how seventeen of the engine's own tables were found with no
policy at all, `stored_credentials` and `memory_items` among them. They were empty, which is
exactly why it was easy to miss.

Credentials and tokens are classed **memory**, never on a timer. A credential that expired because
a cleaner ran would break a connection with no explanation; revocation removes these, not age.

---

## Surfaces

| surface | where |
|---|---|
| capability | `aries/lifecycle/` — `policy`, `working`, `service`, `automation`, `settings` |
| orchestrator | `_run_through_lifecycle` releases the working set on every terminal outcome |
| automation | `aries.data`, risk `medium`, ships disabled |
| CLI | `aries data [status\|preview\|clean\|sweep\|vacuum]` |
| API | `GET /api/aries/data`, `GET /api/aries/data/working-set`, `POST /api/aries/data/clean`, `POST /api/aries/data/sweep` |
| UI | Control Centre → **Data** |
| settings | `data.*` — one window per operational policy, generated from the register |
| audit | `data.rehearsed`, `data.cleaned` |

---

## Still to do

* **The Operator's own working set.** Nothing writes to `aries_working_set` yet except tests — it
  is the seam the Operator will use when it starts reading mail, and until then the class is
  proven but unexercised by real work.
* ~~**Provenance has no table of its own.**~~ Built 2026-09-29 with semantic memory:
  `aries_workspace_conclusion_sources` is a real foreign key from every conclusion to the
  utterances it was drawn from, and `store.conclude` refuses a conclusion that has none — a thing
  ARIES decided that cannot be explained may not exist. Remaining: the *episodic* tables
  (`aries_news_items`, `aries_briefs`) still carry their source inline.
* **Retention is by row age, not by size.** A machine that fills up cannot ask ARIES to free a
  target number of megabytes; it can only shorten a window and clean.
