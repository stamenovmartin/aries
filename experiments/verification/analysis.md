# Why 11% of ARIES's successful steps are independently verified

**Every number below is from `file:/home/stamenovmartin/aries/var/aries.db?mode=ro`
(the live database `aries-core.service` is writing to), 7-day window,
`goal_scan` cap 500 — not reached, so nothing is a sample. One snapshot,
`2026-09-30T19:46:22`: 291 goals, 288 steps. Read-only, no transaction held.**

The caller's figures were `n=200` apparently-successful with `verified=22`. Ten
minutes of live traffic moved that to `n=215` / `verified=34`; `research` moved
141 → 144, `play_music` is unchanged at 0 of 25. The structural findings do not
move, the counts do, and every count here is from the one snapshot named above.

Reproduce: `experiments/verification/probe.py` (dumps the snapshot),
`coverage_by_engine.py`, `verifier_strength.py`, `research_relevance.py`,
`surface.py` + `table.py` (the table).

---

## The answer, in one table

| engine that wrote the step | steps | buckets | coverage (verified / looks-successful) |
|---|---|---|---|
| `service.py` research loop | 144 | accepted 144 | **0/144 = 0.000 [0.000–0.026]** |
| `capabilities.execute()` (CATALOGUE) | 81 | accepted 29, no_outcome 23, withheld 14, unconfirmed 8, failed 7 | **0/37 = 0.000 [0.000–0.094]** |
| M14 registry (`orchestration.py` / `agent.py`) | 63 | verified 34, failed 17, pending 12 | **34/34 = 1.000 [0.898–1.000]** |
| all | 288 | looks-successful 215 | 34/215 = 0.158 [0.115–0.213] |

**Hypothesis 2 is true. The M14 verifier is not broken — it fires on 100% of the
steps that reach it, and not one M14 step in the window landed in `accepted` or
`unconfirmed`.** All 181 apparently-successful-but-unverified steps come from the
two paths that do not use the registry, and 225 of 288 steps (78%) never touch
the registry at all.

Structurally it cannot be otherwise on the registry side: `Capability.verifier`
is a **required positional field of a frozen dataclass**
(`aries/workspace/capability_types.py`). A registry capability without a verifier
cannot be constructed. All 58 registered capabilities have one; measured, none is
`None`.

### But the honest statement is not the caller's either

Two corrections, both measured, and the second is worse than the 11%.

**(a) 27 of the 181 were independently verified and the verdict is already in the
record.** It is written where nothing reads it:

| where the verdict sits | steps | read by `STEP_BUCKET`? |
|---|---|---|
| `result.operator.verified_success` (`play_music` 17, `open_app` 6, `open_url` 1) | 24 | no |
| `result.verification.met` (`open_url` via controlled browser) | 3 | no |
| genuinely no verdict anywhere (`research` 144, `system` 2, `play_music` unconfirmed 8) | 154 | — |

`aries/analytics/core.py:150` classifies on `$.verification_status`,
`$.execution_status`, `$.state` and nothing else. The CATALOGUE path writes
`step['state'] = result['state']` (`service.py:503`) and leaves the verdict
nested inside `result`. Direct proof in the data: the 3 `open_url` steps carrying
`result.verification.met = True` are bucketed `accepted`, i.e. "nothing checked
it". So `integrity.py`'s own docstring is wrong on one point — *"Legacy operator
steps … that engine had no verifier at all"*. The legacy operator engine has a
full one: `operator/service.py:118` reserves `Run.outcome == 'done'` for
`all(s.verification.met)`, records a grade, and has a `honesty_gap` property for
reported-success-that-was-contradicted. Its verdict is discarded at the
`capabilities.execute()` boundary.

Surfacing what is already recorded: **34 → 61 of 215, 0.158 → 0.284
[0.228–0.347]**. Seven lines of code (P1 below).

**(b) 32 of the 34 steps counted `verified` met a check that cannot fail.**
`verify_probe`, `verify_observe`, `verify_tabs`, `verify_read_brightness`,
`verify_targets` all return `{'met': True, …}` on every path. Classified from the
verifiers' own source (`verifier_strength.py`): 11 of 58 registry capabilities
are unconditional, and they carry almost all the traffic that reaches a verifier.

| verified step | verifier | could it have returned False? | n |
|---|---|---|---|
| `desktop.windows` | `verify_observe` | no | 10 |
| `system.status` | `verify_probe(status)` | no | 8 |
| `desktop.observe` | `verify_observe` | no | 6 |
| `system.storage` | `verify_probe(storage)` | no | 5 |
| `file.list` | `verify_probe(listing)` | no | 2 |
| `browser.tabs` | `verify_tabs` | no | 1 |
| `file.read` | `verify_read` (SHA-256 compare) | **yes** | 2 |

**2 of 34 = 0.059 [0.016–0.191].** Against all apparently-successful steps: 2 of
215. The 100% M14 coverage above is 94% "the subject is still observable", not
"the executor's claim was tested". This matters for question 3: the pattern the
M14 *file* capabilities are being held up as — `verify_probe` — is the
unconditional one, and copying it into the spoken read-only capabilities would
raise coverage without adding evidence. `file.read`'s `verify_read` is the shape
worth copying.

### So the honest sentence

> 84% of apparently-successful steps are recorded as unverified. Of those 181:
> 144 (80%) are `research`, which has no verifier on any code path; 27 (15%) were
> verified and the verdict is in the record under a key no metric reads; 8 (4%)
> honestly reported that they could not confirm; 2 are read-only steps whose
> registry twin has a verifier the spoken path never calls. Separately, of the 34
> steps that *are* counted verified, 32 met a check with no failure mode.

---

## 1. Per capability: verifier, invoked, recorded

`verifier exists` counts the M14 registry twin, because it is the same effect
through the same module. `invoked` is read from the source of
`capabilities.execute()` (`surface.py` splits it into branch regions and
attributes each `return` to the narrowest enclosing `if kind` guard). `recorded`
is measured. 54 CATALOGUE entries; 26 return a `verification` key, 28 do not.

| spoken capability | verifier exists | invoked by the spoken path | verdict recorded on the step | steps | buckets measured |
|---|---|---|---|---|---|
| `research` | NO — anywhere | no · never reaches execute() | none | 144 | accepted 144 |
| `play_music` | yes · in execute() | yes | `result.operator.verified_success` (17) — not read by any metric | 41 | accepted 17, withheld 10, unconfirmed 8, no_outcome_recorded 5, failed 1 |
| `open_app` | yes · operator.run | yes, verdict discarded | `result.operator.verified_success` (6) — not read by any metric | 26 | no_outcome_recorded 10, accepted 6, failed 6, withheld 4 |
| `agent_task` | yes · M14 agent | yes, outer step left blank | none | 7 | no_outcome_recorded 7 |
| `open_url` | yes · operator.run | yes, verdict discarded | `result.verification` (3) — not read by any metric | 4 | accepted 4 |
| `system` | yes · system.status | no | none | 2 | accepted 2 |
| `install_app` | yes · in execute() | yes | none | 1 | no_outcome_recorded 1 |
| `abilities` | yes · in execute() | yes | none |  |  |
| `brief` | yes · operator.run | yes, verdict discarded | none |  |  |
| `brightness` | yes · display.brightness | no | none |  |  |
| `browser_close` | yes · in execute() | yes | none |  |  |
| `browser_fill` | yes · in execute() | yes | none |  |  |
| `browser_follow` | yes · in execute() | yes | none |  |  |
| `browser_inspect` | yes · browser.observe | no | none |  |  |
| `browser_open` | yes · in execute() | yes | none |  |  |
| `build_python` | yes · in execute() | yes | none |  |  |
| `can_you` | NO | no | none |  |  |
| `clipboard_read` | yes · in execute() | yes | none |  |  |
| `clipboard_write` | yes · in execute() | yes | none |  |  |
| `create_file` | yes · in execute() | yes | none |  |  |
| `create_folder` | yes · in execute() | yes | none |  |  |
| `disk` | yes · system.disk | no | none |  |  |
| `editable_fields` | yes · input.editable_targets | no | none |  |  |
| `evaluation` | NO | no | none |  |  |
| `find_files` | yes · file.search | no | none |  |  |
| `health` | yes · operator.run | yes, verdict discarded | none |  |  |
| `inspect_app` | NO | no | none |  |  |
| `learning_eval` | NO | no | none |  |  |
| `list_apps` | NO | no | none |  |  |
| `list_folder` | yes · file.list | no | none |  |  |
| `media_control` | yes · in execute() | yes | none |  |  |
| `move_file` | yes · in execute() | yes | none |  |  |
| `network_status` | yes · network.status | no | none |  |  |
| `open_path` | yes · in execute() | yes | none |  |  |
| `package_info` | yes · system.packages | no | none |  |  |
| `processes` | yes · system.processes | no | none |  |  |
| `python_project` | yes · in execute() | yes | none |  |  |
| `read_article` | NO | no | none |  |  |
| `read_file` | yes · file.read | no | none |  |  |
| `read_screen` | yes · in execute() | yes | none |  |  |
| `refresh_news` | yes · operator.run | yes, verdict discarded | none |  |  |
| `remember` | NO | no | none |  |  |
| `say` | yes · in execute() | yes | none |  |  |
| `screenshot` | yes · in execute() | yes | none |  |  |
| `search_web` | yes · operator.run | yes, verdict discarded | none |  |  |
| `service_control` | yes · in execute() | yes | none |  |  |
| `services` | yes · system.services | no | none |  |  |
| `set_brightness` | yes · in execute() | yes | none |  |  |
| `set_volume` | yes · in execute() | yes | none |  |  |
| `trash_file` | yes · in execute() | yes | none |  |  |
| `type_text` | yes · in execute() | yes | none |  |  |
| `ui_action` | yes · in execute() | yes | none |  |  |
| `wifi_connect` | yes · in execute() | yes | none |  |  |
| `wifi_list` | yes · network.wifi_list | no | none |  |  |

Six capabilities have **no verifier anywhere**: `research`, `can_you`,
`evaluation`, `learning_eval`, `inspect_app`, `read_article`, `remember`,
`list_apps`, `brief`/`health`/`refresh_news` (these three do reach
`operator.run`, which verifies, but the verdict is discarded). Of those, only
`research` has traffic.

---

## 2. Is `research` verifiable at all? Partly — and it is lying today

`research` never reaches `capabilities.execute()`. `validate_action`
(`capabilities.py:1103`) stamps `kind: "research"`, and `service.py:443-455`
handles those steps in their own loop:

```python
step["state"] = "done" if cards else "empty"
```

**`done` means "at least one row matched the query".** Nothing else. Measured:
all 144 research steps carry `state` and nothing else — no result, no card count,
no evidence, no source count. You cannot tell from a saved research step how many
sources it found.

What it actually produced (144 goals, all `state: done`):

- 19–25 source cards each, all but one carrying a `url` that passed `safe_link`
- 144 of 144 have an AI briefing card with exactly 12 `source_links`
- `source_links ⊆ collected urls` in 144 of 144 — **tautologically**, because
  `service.py:462` builds the links from the cards it just collected. A subset
  check would be decorative.
- the briefing names a source domain in **0 of 144**. The summary never says
  where a claim came from.
- share of source cards containing a query word (same word list
  `service.research()` builds): median 0.778, p25 0.583, **min 0.263**. All on
  topic 42; majority on topic 123; minority on topic 21; none 0.
- **4 of 144 briefings share not one six-letter word with any source they list.**
  Read them and it is not a grounding bug, it is worse:

  > "The provided material does not directly discuss AI agents. Instead, it
  > covers various news items including military upgrades, sports, politics…"
  > — sources: *Bremerhaven port to receive defense boost*, *Man City's Premier
  > League charges*, *Fernando Alonso to stay with Aston Martin*

  ARIES's own model said the material was off topic, and the step still recorded
  `done` and the goal still recorded `done`. The user asked for AI agents and got
  25 cards about Formula One.

The cause is in `service.research()`: the stored-news branch filters rows by query
word (`service.py:254`), the **Google News branch appends every parsed item with
no relevance filter at all** (`service.py:265-270`). When the local news table has
few matches, the cards are whatever the search returned.

### What honest verification means here

Three things are independently checkable, and one is not.

| check | failure mode | cost | fires today |
|---|---|---|---|
| **provenance** — every displayed card has a `safe_link` URL; every `source_links` entry is one of the collected cards | a briefing citing a source that was not collected | free, offline | 0 of 144 |
| **relevance** — at least one collected source contains a query word; record the on-topic share as evidence | a `done` that answered a different question | free, offline | 0 of 144 at "≥1", **21 of 144** at "majority" |
| **liveness** — a bounded sample of the URLs resolves through the existing pinned `aries.news.fetch.fetch` | dead or redirected links presented as sources | network, seconds | not measured — needs a fetch, not in the DB |
| **truth of the summary** | — | — | **not independently verifiable** |

The fourth line is the important one. The briefing is a local-model synthesis of
feed *excerpts* — `aries/workspace/reader.py:109` already instructs the model
*"Do not claim independent verification"*. ARIES did not read the articles, has no
second source, and cannot adjudicate a publisher's claim. **`research` must not
claim verified success. It can honestly claim verified provenance and verified
topicality, with an explicit scope sentence saying that is all.**

Recommendation: give `research` a verifier that checks provenance and relevance
and records the on-topic share, and demote `state` to `partial` when the majority
of sources are off topic. That is a real check with a real failure mode that fires
on 21 of 144 steps in this window — the only proposal here that would change a
reported outcome on today's data.

---

## 3. The read-only capabilities: smallest change

`read_file`, `list_folder`, `find_files`, `processes`, `list_apps`, `disk`,
`system`, `package_info`. Two groups, because the work differs by a factor of ten.

**Group A — `disk`, `package_info`, `services`: the verifier already exists and
the branch already holds its arguments.** `execute()` calls
`sysadm.disk({}, ctx)` / `sysadm.packages({...}, ctx)` / `sysadm.services(...)`
and `system_capabilities.py` already defines `verify_disk`, `verify_packages`,
`verify_services` with signature `(args, result, ctx)`. All three are *comparing*
verifiers with real failure modes (`verify_disk` re-runs statvfs and re-stats the
reported directories; `verify_packages` re-queries dpkg/snap and compares
versions; `verify_services` fails when a manager refuses to answer). One line
each. This is what `service_control` already does at `capabilities.py:902`.

**Group B — `read_file`, `list_folder`, `find_files`, `processes`, `list_apps`,
`system`: no verifier exists, and the registry twin's is unconditional.** Do not
copy `verify_probe`. The honest re-read is a *comparison* of the part of the
observation that cannot change in a second, and each needs its own named failure
mode:

| capability | compare on re-read | failure mode |
|---|---|---|
| `read_file` | SHA-256 of the bytes | the file changed under the read (this is `verify_read`) |
| `list_folder` | sorted entry paths | an entry appeared or vanished |
| `find_files` | sorted match paths | the match set moved |
| `list_apps` | sorted desktop-entry titles | an app was installed/removed mid-read |
| `system` | probe metric *names*, and that none with a value now reports unavailable — **never the values**, which move between probes | a probe broke between reads |
| `processes` | no reported PID now maps to a *different* name; a PID that exited is not a wrong observation | PID reuse; /proc unreadable. Narrow, and say so |

Sketch in P4 below: one helper plus one attach point, because five of the six
already fall through to the same `return` at `capabilities.py:1045`.

---

## 4. The two contradictions: a flaky check, not an executor bug

Both are the same goal (`03d8f34cd621…`, 2026-09-24 20:51), the same session
(`e98df7a40b28`), the same page — a YouTube results page — and the same single
clause.

`registry.verify_browser`:

```python
met = bool(fresh.get('title') and fresh.get('url') and fresh['url'] == result.get('url'))
```

Recorded evidence for both steps:

- `url` = `https://www.youtube.com/results?search_query=2Bona%20Lozano` — **exactly
  equal** to the executor's, and for `browser.search` the query-specific clause
  (hostname `www.youtube.com`, path `/results`, `search_query == ['2Bona Lozano']`)
  would also have passed
- `title` = `""`
- `browser.search`: 15 requests, `links: []`, `text: ""` — nothing had rendered
- `browser.observe` 80 s later: 18 requests, 12 footer links present, `fields`
  present — the page *had* rendered — and `title` still `""`

So `met` was False solely because `document.title` was empty. YouTube is a SPA
that sets its title after hydration; the footer links arriving while the title
never does is the signature. **Flaky check.** The executor was correct, the
navigation was correct, and the step was recorded as a verification failure with
`retryable: false` — which under `agent.py:62` also blocks any resume past it.

It is worse than a false negative on `browser.observe`, an `effect='read'`
capability: the only thing `verify_browser` adds there beyond re-reading the same
page is "the title is non-empty". A read capability whose verifier fails on a
titleless page will fail on every titleless page.

Fix (P5): require the title only where a title is the evidence. For
`browser.search` the URL query *is* the evidence and is already checked
separately; for `browser.observe`/`browser.read` the correct claim is "the session
is still the same document". Two lines in `registry.py`.

---

## 5. Is `verification` decorative? In the CATALOGUE path, yes

**Nothing reads `step['result']['verification']` to make a decision.** Grepped
across `aries/`, `aries_ui/`, `tests/`: the only reader is
`aries/workspace/reviews.py:26-27`, which copies `met` and `evidence` into a
human-review record — and that module's own docstring says *"Reviews never change
execution status, settings, or model weights."* `aries/analytics` does not read it
at all. Measured proof: 3 `open_url` steps with `result.verification.met = True`
are bucketed `accepted`, "nothing checked it".

The **verdict** does have teeth; the **field** does not. Each branch computes
`"state": "done" if out.get("verified") else "unconfirmed"` from the same source
as `met`, and `state` gates the plan (`service.py:516-519` breaks the plan when a
step is not `done`) and is what analytics buckets. So a false `met` today stops
the plan and is visible as `unconfirmed` — it just never appears as *verification*
anywhere.

In the M14 path `verification_status` is load-bearing in five places:

- `orchestration.py:373-381` — a false `met` becomes a typed step failure
- `agent.py:62` — a resumed plan refuses to advance past a step that is not `verified`
- `agent_planner.py:121-122` — only verified steps are offered to the replanner as
  supporting evidence, and re-checked with `contracts.evidence_matches`
- `contracts.evidence_matches` (`contracts.py:106`) — `if not verification.get('met'): return False`
- `orchestration.py:435` / `recovery.py:141` — goal completion and recovery are
  gated on evidence, not on the executor's word

**So: would coverage rising change a reported outcome?** Only P1 and P2 would.
P1 changes what the dashboard reports (0.158 → 0.284) without changing behaviour —
it publishes verdicts that already exist. P2 changes behaviour: 21 of 144 research
steps would stop saying `done`. P3 and P4 close capabilities that had no traffic
in this window and would change nothing measurable *today*, which is an honest
reason to rank them third and fourth rather than first. Anything that raises
coverage by adding an unconditional verifier changes the number and nothing else,
which is the failure mode this whole file exists to name.

---

## What cannot be answered from the data

- **Liveness of research source links.** Not recorded. Answering it needs either a
  fetch now (different population than the window) or a new field: record, per
  research step, the HTTP status of a bounded sample at collection time.
- **Per-step source counts for `research`.** The step records only `state`; the
  cards are appended to the goal. Any per-step research metric needs the step to
  record `sources`, `on_topic`, `briefing_source_links`.
- **Whether `capabilities.verify()` ever returned `None`/`False` in production.**
  `verify()`'s `met` is folded into `state` and the tuple is discarded; `evidence`
  survives as `summary`. A `state: 'unconfirmed'` cannot be told apart from
  `met is None` vs `met is False` without recording the verdict itself — which is
  exactly what P1 fixes.
- **The 23 `no_outcome_recorded` steps** (`open_app` 10, `agent_task` 7,
  `play_music` 5, `install_app` 1) carry no status field at all. For `agent_task`
  the outer step is intentionally left blank because `agent.run` takes over the
  goal; for the other 16 it is a recording gap and a separate bug from this one.

---

# Proposed patches, priority = measured coverage gain per line changed

| # | change | files | ~lines | measured effect on this snapshot |
|---|---|---|---|---|
| **P1** | lift the verdict that already exists into `step['verification_status']` | `capabilities.py` +22, `service.py` +4 | 26 | **+27 steps: 34/215 → 61/215, 0.158 → 0.284 [0.228–0.347]**. Validated by replaying the helper over the live snapshot: exactly 27 |
| **P2** | give `research` a provenance + grounding verifier | `capabilities.py` +36, `service.py` +9 | 45 | 144 steps reach a verifier for the first time; **4 of 144 fail it today**, and those 4 are the ones whose own briefing says the material is off topic while the step records `done` |
| **P3** | call the `system_capabilities` verifiers that already exist | `capabilities.py` +6 | 6 | 0 on this window (no traffic), closes 3 of the 28 undecided capabilities. Costs a second statvfs / dpkg+snap query / systemd enumeration |
| **P4** | comparing re-read for the six read-only spoken capabilities | `capabilities.py` +32 | 32 | +2 (`system`), closes 6 capabilities. Deliberately not `verify_probe` |
| **P5** | stop `verify_browser` failing on a titleless SPA page | `registry.py` +4, `contracts.py` +2 | 6 | recovers the 2 contradictions |
| **P6** | stop counting an unconditional verifier as confirmation | `analytics/` or `registry.py` | — | reclassifies 32 of 34 current `verified`. Not proposed as code — it is a decision about what `verified` means |

---

## P1 — the verdict already exists; put it where something reads it

**`aries/workspace/capabilities.py`** — add above `async def execute(db, step, *, approved=False):` (currently line 579):

```python
def verdict(result):
    """Where a step's independent verdict goes so that something reads it.

    Three engines produce a verdict and `analytics.core.STEP_BUCKET` reads only
    the M14 field, so a step that WAS checked is bucketed `accepted` — "nothing
    checked it". Measured on the live database 2026-09-30: 27 of the 181
    apparently-successful unverified steps already carry an affirmative verdict
    inside `result`, where no metric, page or planner looks.

    A verifier that returned `met: False` is deliberately NOT reported here. The
    branches that produce it already call that state `unconfirmed` — ARIES could
    not confirm it — and `verification_failed` would move it into `failed` and
    assert the effect was contradicted, which is a stronger and different claim.
    Only `operator.honesty_gap` is a contradiction: the tool reported success and
    the desktop said otherwise.
    """
    result = result or {}
    check = result.get("verification")
    if isinstance(check, dict) and check.get("met") is True:
        return "verified"
    run = result.get("operator") or {}
    if run.get("verified_success") is True:
        return "verified"
    if run.get("honesty_gap") is True:
        return "verification_failed"
    return None
```

**`aries/workspace/service.py`** — after `step["state"] = result["state"]` (line 503):

```python
                step["result"] = result
                step["state"] = result["state"]
                # A verdict nothing reads is not verification. STEP_BUCKET
                # classifies on the step's OWN verification_status, so lift the one
                # the executor already produced out of the nested result.
                status = capabilities.verdict(result)
                if status is not None:
                    step["verification_status"] = status
```

Verified against the live snapshot: the helper returns `verified` for exactly 27
steps that are currently bucketed `accepted`, and never contradicts the state a
branch chose for itself. `aries_ui/pages/dashboard.py:272` will start printing
`/ verified` for these steps, which is the intended effect. `tests/test_analytics.py`
stays green — its fixtures carry no `result`.

## P2 — `research`: verify provenance and grounding, and stop claiming more

**`aries/workspace/capabilities.py`** — add near `verdict()`. Needs one import:
`from datetime import datetime, timezone` (the module has no `datetime` today).

```python
# The one capability with no verifier on any path, and 144 of the 288 steps in the
# last week. Two clauses, both with a real failure mode, neither with a threshold
# invented here:
#   sources    at least one card carries a public link that passed safe_link
#   grounded   the briefing shares a substantive word with the titles of the
#              sources it cites. Measured over the last week: 140 of 144 pass, and
#              the 4 that fail are the ones whose briefing says in its own words
#              "The provided material does not directly discuss AI agents" while
#              the step recorded `done` and showed 25 stories about Formula One.
# What is NOT checked, and must not be claimed: whether the summary is TRUE. It is
# a local-model synthesis of feed EXCERPTS — reader.py already instructs the model
# not to claim independent verification — and a publisher's claim cannot be
# adjudicated from an excerpt. `research` can honestly report verified provenance
# and verified grounding, with that scope stated in the evidence.
# `\w{6,}` is script-agnostic on purpose: the spoken surface is bilingual and a
# Latin-only check would flag every Macedonian briefing. All 144 briefings in the
# measured window were Latin, so the two agree today; they will not always.
RESEARCH_STOPWORDS = frozenset({
    "me", "to", "my", "of", "on", "in", "za", "mi", "se", "da", "research", "dashboard",
    "about", "news", "find", "for", "the", "and", "istrazi", "vesti", "najdi",
    "истражи", "вести", "најди"})
_SUBSTANTIVE = re.compile(r"[^\W\d_]{6,}", re.UNICODE)


def verify_research(query, cards):
    """Provenance and grounding of a research answer, from what it produced."""
    words = [w.casefold() for w in re.findall(r"\w+", query)
             if len(w) > 1 and w.casefold() not in RESEARCH_STOPWORDS]
    sources = [c for c in cards if c.get("url")]
    briefing = next((c for c in cards if c.get("source_links")), None)
    on_topic = [c for c in sources if words and any(
        w in (c.get("title", "") + " " + c.get("text", "")).casefold() for w in words)]
    cited = [l for l in (briefing or {}).get("source_links") or []]
    grounded = None
    if briefing is not None:
        text = (briefing.get("text") or "") + " " + (briefing.get("title") or "")
        titles = " ".join(l.get("title", "") for l in cited)
        grounded = any(w in text for w in set(_SUBSTANTIVE.findall(titles)))
    return {"met": bool(sources) and grounded is not False,
            "evidence": ("%d sources, %d on topic, %d cited by the briefing; "
                         "provenance and grounding only — NOT a check that the summary is "
                         "true, which ARIES cannot make from excerpts it did not read in full"
                         % (len(sources), len(on_topic), len(cited))),
            "sources": len(sources), "on_topic": len(on_topic), "cited": len(cited),
            "on_topic_share": round(len(on_topic) / len(sources), 3) if sources else None,
            "briefing_grounded": grounded,
            "observed_at": datetime.now(timezone.utc).isoformat()}
```

`on_topic_share` is recorded, not gated. A threshold on it would be a quality bar
invented in this file; the share belongs in the evidence where a person can see
it. Measured distribution over the window: median 0.778, p25 0.583, min 0.263.

**`aries/workspace/service.py`** — replace the `else` arm of the research result
loop (lines 449-455). The call must come **after** the briefing card is inserted,
so move it below the briefing block at line 472 and key it by step, or — smaller —
run it where the briefing is already in `data['cards']`:

```python
        # After the briefing block at line 472, before the final save.
        for step in research_steps:
            if step["state"] not in ("done", "empty"):
                continue
            mine = [c for c in data["cards"] if c.get("url") or c.get("source_links")]
            check = capabilities.verify_research(
                step.get("args", {}).get("query", step["request"]), mine)
            step["result"] = {"state": step["state"], "verification": check,
                              "summary": check["evidence"]}
            # `done` used to mean "at least one row matched the query". It now means
            # the answer is grounded in sources that are about the question.
            step["verification_status"] = "verified" if check["met"] else "verification_failed"
            if not check["met"]:
                step["state"] = "partial"
                data["gaps"].append("The briefing is not grounded in the sources it cites: "
                                    + step.get("args", {}).get("query", step["request"]))
        await save(goal_id, data)
```

Known limitation of the smaller form: a goal with two research steps attributes all
cards to both. 144 of 144 research goals in the window had exactly one research
step, so it is correct on all observed traffic — but it is an approximation and the
step should record its own card ids to make it exact.

## P3 — call the verifiers that already exist (`disk`, `package_info`, `services`)

All three are *comparing* verifiers with real failure modes. `execute()` already
holds `out` and `ctx`. This is what `service_control` already does at line 902.

```python
        if kind == "services":
            request = {"scope": "both", "kind": "service"}
            out = await sysadm.services(request, ctx)
            check = await sysadm.verify_services(request, out, ctx)   # fails if a manager refuses
            ...
            return {"state": "partial" if out["truncated"] or out["unavailable"] else "done",
                    "summary": summary,
                    "verification": {"met": check["met"],
                                     "evidence": "both managers answered a second independent "
                                                 "enumeration"},
                    "cards": [...]}

        if kind == "disk":
            out = await sysadm.disk({}, ctx)
            check = await sysadm.verify_disk({}, out, ctx)   # fresh statvfs + re-stat; no re-walk
            ...
            return {"state": "partial" if home["truncated"] else "done",
                    "summary": ...,
                    "verification": {"met": check["met"], "evidence": check["data"]["scope"]},
                    "cards": [...]}

        if kind == "package_info":
            request = {"package": args["package"]}
            out = await sysadm.packages(request, ctx)
            check = await sysadm.verify_packages(request, out, ctx)   # second dpkg/snap query
            return {"state": "done" if check["met"] else "unconfirmed",
                    "summary": ...,
                    "verification": {"met": check["met"],
                                     "evidence": "a second independent dpkg and snap query "
                                                 "returned the same versions"},
                    "cards": [...]}
```

Cost, honestly: `services` doubles a systemd enumeration on a 45-second-timeout
capability, `package_info` doubles two subprocesses, `disk` repeats statvfs and
re-stats the reported directories without repeating the bounded home walk. If the
`services` cost is unacceptable, leave it and take the other two — but then say so
in `UNVERIFIED_SPOKEN` rather than leaving it undecided.

## P4 — comparing re-read for the six read-only capabilities

Five of the six already fall through to one `return` (line 1045), so one helper and
one attach point covers `list_apps`, `processes`, `list_folder`, `read_file`,
`system`; `find_files` returns early at 1015 and needs the same two lines.

`read_file` needs its branch to record the digest, because the card holds only the
first 12,000 characters and a SHA of a truncated preview is not a SHA of the file:

```python
        else:
            if not path.is_file() or path.stat().st_size > 100000:
                raise ValueError("Read accepts a regular UTF-8 text file up to 100 KB")
            data = path.read_bytes()
            text = data.decode("utf-8")
            cards = [{"title": path.name, "text": text[:12000], "source": str(path),
                      # The digest of the WHOLE file, so a re-read can contradict it.
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "evidence": "Read from disk" + ("; preview limited to 12000 characters"
                                                      if len(text) > 12000 else "")}]
```

```python
# The cheap independent check for a read is the same read, twice, comparing only
# what CANNOT change in a second. Deliberately NOT the registry's `verify_probe`
# shape, which returns met=True on every path and therefore has no failure mode —
# 32 of the 34 steps currently counted `verified` came from that shape, which is
# how coverage can rise without evidence rising. Every entry below names the
# failure mode it has; `None` means no check exists and must stay distinguishable
# from a check that ran and passed.
async def verify_read_only(db, kind, args, cards):
    if kind == "read_file":
        path = await checked_path(db, args["path"])
        again = await asyncio.to_thread(path.read_bytes)
        return {"met": hashlib.sha256(again).hexdigest() == cards[0].get("sha256"),
                "evidence": "the file's SHA-256 is unchanged on a second full read; a "
                            "concurrent write would contradict it"}
    if kind in {"list_folder", "find_files"}:
        # Re-enumerate INLINE rather than calling execute() again: execute()'s tail
        # is where this verifier is attached, so recursing through it would never
        # terminate.
        if kind == "list_folder":
            root = await checked_path(db, args["path"])
            after = []
            for entry in sorted(root.iterdir())[:100]:
                if entry.name.startswith("."):
                    continue
                try:                      # the same privacy filter the branch applies,
                    after.append(str(await checked_path(db, str(entry))))
                except ValueError:        # or the two lists differ for the wrong reason
                    continue
            after.sort()
        else:
            from aries.shell.search import search_files
            from aries.settings import SettingsService
            excluded = await SettingsService(db).get("privacy.excluded_paths")
            again = await asyncio.to_thread(search_files, args["query"],
                                            excluded=excluded, limit=30)
            after = sorted(r["action"]["path"] for r in again["results"])
        before = sorted(c.get("path", "") for c in cards)
        return {"met": before == after,
                "evidence": "the same %d paths came back from a second independent "
                            "enumeration; an entry appearing or vanishing contradicts it"
                            % len(before)}
    if kind == "list_apps":
        after = sorted(c["title"] for c in await asyncio.to_thread(installed_apps))
        return {"met": sorted(c["title"] for c in cards) == after,
                "evidence": "the same application list came back from a second read of the "
                            "desktop entries; an install or removal mid-read contradicts it"}
    if kind == "processes":
        from aries.operator.desktop import read_processes
        fresh = {p.pid: p.name for p in await asyncio.to_thread(read_processes)}
        # A process that EXITED between the two reads is not a wrong observation.
        # A PID that now names something else is. Narrow, and that is the honest
        # scope of a re-read against a table that changes every millisecond.
        def pid_of(card):
            tail = (card.get("text") or "").rsplit(" ", 1)[-1]
            return int(tail) if tail.isdigit() else None
        moved = [c for c in cards
                 if (pid := pid_of(c)) in fresh and fresh[pid] != c["title"]]
        return {"met": bool(fresh) and not moved,
                "evidence": "/proc is still enumerable and no reported PID now names a "
                            "different process; an exited process is not a contradiction"}
    if kind == "system":
        from aries.health.probes import run_all
        fresh = {r.metric: r.value is not None
                 for p in await run_all() for r in p.readings}
        had = {c["title"]: c["text"] != "Unavailable" for c in cards}
        # Probe VALUES move between two reads; probe identities do not, and a probe
        # that had a value and now has none is a probe that broke.
        return {"met": set(fresh) == set(had) and not [m for m, ok in had.items()
                                                       if ok and not fresh.get(m)],
                "evidence": "the same probes answered a second time and none that had a "
                            "reading lost it; the readings themselves move and are not compared"}
    return None
```

Attach at line 1045 (and the same two lines before the `find_files` return at 1015):

```python
    check = await verify_read_only(db, kind, args, cards)
    return {"state": "done" if check is None or check["met"] else "unconfirmed",
            "summary": f"{len(cards)} results", "cards": cards,
            **({"verification": check} if check else {})}
```

`remember` falls through the same tail, gets `None`, and keeps `done` with no
verification key — which is correct: re-reading the row proves the write, not the
fact.

## P5 — `verify_browser`: require a title only where a title is the evidence

**`aries/workspace/registry.py`**, in `verify_browser`:

```python
    # The pinned transport already checked response status, redirects and public
    # IPs. A non-empty document.title is evidence for a NAVIGATION; it is not
    # evidence for a READ, and a SPA sets its title after hydration. Two steps on
    # one YouTube results page failed on this clause alone with a byte-identical
    # URL and 12 rendered footer links (goal 03d8f34c…, 2026-09-24 20:51).
    met = bool(fresh.get('url')) and fresh['url'] == result.get('url')
    if 'query' in args:
        ...                      # unchanged — for a search the URL query IS the evidence
    elif 'url' in args:
        # A navigation still has to have rendered something.
        met = met and bool(fresh.get('title') or fresh.get('links') or fresh.get('text'))
```

**`aries/workspace/contracts.py:124`** carries the same clause and will still fail
a titleless page for a goal contract:

```python
    if 'url' in requirement:
        ...
        if not (data.get('title') or data.get('links') or data.get('text')):
            return False
```

## P6 — the decision this diagnosis cannot make for you

32 of 34 `verified` steps came from a verifier that cannot return `False`. Either:

* **rename it.** `verify_probe`/`verify_observe`/`verify_tabs` produce a *fresh
  observation*, not a contradiction test. A fourth bucket — `observed` — between
  `verified` and `accepted` would make the dashboard honest without touching a
  single verifier, and `verification_honesty` would then report two coverages: how
  much was re-observed, and how much was tested. This is the smaller change.
* **or make them comparing**, on the P4 model: compare the stable part of the
  observation and let the check fail when it moves.

Do not do neither. Landing P1–P4 without P6 raises reported coverage from 0.158 to
roughly 0.9 while the share of steps confirmed by a check that could have failed
stays near 0.01, and that is a worse number than 11% because it reads as progress.
