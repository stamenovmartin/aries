# ARIES — API

One process serves both surfaces. The **engine** owns tasks, proposals, execution, evaluation
and audit under `/api/…`; **ARIES** owns automations, settings and notifications under
`/api/aries/…`. ARIES does not build its own app — it imports the engine's and adds a router,
so there is one middleware stack, one auth path and one audit trail.

```bash
./scripts/start.sh 8000        # → http://127.0.0.1:8000/docs
```

Binds to loopback deliberately: `API_KEY` defaults to empty, which means an open API.
Set `API_KEY` and mint per-person tokens before changing the host.

## Control Centre (§27)

| route | does | permission |
|---|---|---|
| `GET /api/aries/automations` | the main list, plus the dispatcher's state | `view_data` |
| `GET /api/aries/automations/{id}` | inspect — full genome, learning status, evolution history | `view_data` |
| `GET /api/aries/automations/{id}/runs` | view history | `view_data` |
| `GET /api/aries/automations/{id}/metrics` | view metrics — reliability and what it has learned | `view_data` |
| `POST /api/aries/automations/{id}/run` | run now (`{"force": true}` runs a paused one) | **`execute`** |
| `POST /api/aries/automations/{id}/enabled` | pause / resume | `schedule` |
| `GET /api/aries/worker` | dispatcher: the user's switch and the task's state | `view_data` |
| `POST /api/aries/worker/tick` | run one dispatcher pass now | `execute` |

Running an automation needs `execute`, not `schedule` — the engine upgrades any path with a
`run` segment, so running work and scheduling it stay separate permissions.

**Edit, Duplicate and Rollback are deliberately absent**, not stubbed. They operate on a
versioned genome, which is the controlled-evolution engine of §18 — sandbox, benchmark,
compare to baseline, approve, promote, roll back. A route that mutated a spec in place today
would look like that feature while providing none of its safety. The genome already records
`parent_version`, `evolution_history` and `rollback_version`, so the data is being collected.

## Settings (§20, §29, §31)

| route | does | permission |
|---|---|---|
| `GET /api/aries/settings` | every setting, its value, and the control a UI should render | `view_data` |
| `GET /api/aries/settings/{key}` | **why** the value is what it is — winner and every loser | `view_data` |
| `PUT /api/aries/settings/{key}` | set as the user | `manage_tools` |
| `DELETE /api/aries/settings/{key}` | clear the user value; a learned one may take over | `manage_tools` |

The write route hard-codes its author as `"user"` rather than reading it from the request.
That is what makes the §30 write rules mean anything over HTTP: a caller cannot name itself a
human to reach a layer it should not.

```bash
curl -s localhost:8000/api/aries/settings/news.relevance_threshold
# {"value": 0.5, "source": "user",
#  "stack": [{"layer":"user","value":0.5}, {"layer":"learned","value":0.72,
#             "rationale":"12 of 15 low scorers were ignored"}]}
```

## Notifications (§26, §29)

| route | does |
|---|---|
| `GET /api/aries/notifications` | what was delivered **and what was held back**, each with a reason |
| `GET /api/aries/notifications/briefing` | everything waiting for the next briefing |

The held ones are the point: a decision to stay quiet is still a decision, and §29 requires
that nothing ARIES does be invisible.

## Sources (§24)

| route | does | permission |
|---|---|---|
| `GET /api/aries/sources/types` | the kinds of source, for rendering an "Add source" form | `view_data` |
| `GET /api/aries/sources` | every registered source, with health and performance | `view_data` |
| `GET /api/aries/sources/resolve` | **exactly what an agent would consult, in order** | `view_data` |
| `POST /api/aries/sources` | add one — a bad location is a 400, never a stored row | `manage_tools` |
| `PATCH /api/aries/sources/{id}` | change one; a move is re-validated | `manage_tools` |
| `DELETE /api/aries/sources/{id}` | remove one | `manage_tools` |
| `POST /api/aries/sources/{id}/feedback` | the user engaged with, or corrected, this source | `manage_tools` |

Adding a source needs `manage_tools` rather than the `edit_task` a POST would default to:
naming somewhere ARIES will go is configuring the system's reach. See `docs/SOURCES.md` for
what is refused and why.

## Interests (§25)

| route | does | permission |
|---|---|---|
| `GET /api/aries/interests` | the profile: weights, their origin, and what ARIES would have said | `view_data` |
| `POST /api/aries/interests` | add a topic to follow or to ignore | `edit_task` |
| `PATCH /api/aries/interests/{topic}` | change one; `{"clear_weight": true}` falls back to the learned weight | `edit_task` |
| `DELETE /api/aries/interests/{topic}` | remove one | `edit_task` |
| `POST /api/aries/interests/score` | **score text, with the reasoning** — which topic, which word, whose weight | `view_data` |

Editing needs `edit_task` rather than the `manage_tools` sources need: a topic shapes what
reaches the user but names nowhere ARIES will go. See `docs/INTERESTS.md`.

## Health (§13/08)

| route | does |
|---|---|
| `GET /api/aries/health/latest` | the most recent pass in full — every finding, not only the problems |

## Power & Background Mode (Entry 013)

| route | does |
|---|---|
| `GET /api/aries/power` | the measured state: inhibitor as **logind** reports it, display, session, suspend policy, and an honest note on whether the inhibitor changes anything on this machine |
| `PUT /api/aries/power` | change `background_mode` · `allow_suspend` · `allow_gpu_jobs` · `allow_heavy_cpu` · `display_off_after_minutes` and the resource thresholds (`temperature_limit_celsius`, `cpu_limit_pct`, `gpu_limit_pct`, `heavy_job_max_minutes`), then reconcile immediately so the switch acts like a switch |
| `GET /api/aries/power/events` | every time the resource policy refused work or let go again — append-only, newest first |
| `GET /api/aries/power/workloads` | the workload vocabulary, so the UI hard-codes no class names |

Writes need `MANAGE_TOOLS` — Background Mode reaches outside ARIES's own boundary, so it is not
an ordinary settings write. Both routes go through the same audited settings path as
`aries power on`; there is no privileged GUI route. See [POWER.md](POWER.md).

## Integrations (Entry 020)

| route | does |
|---|---|
| `GET /api/aries/connect` | what is connected and readable, which connectors exist, and whether there is a keyring at all — the difference between "a credential can be stored" and "ARIES will refuse to store one" |
| `POST /api/aries/connect` | register a source. A `secret` goes straight to the keyring; the response carries a **reference**, never the credential |
| `DELETE /api/aries/connect/{id}` | remove a source and, unless `forget=false`, its credential |
| `GET /api/aries/connect/{id}/check` | can ARIES reach it right now, and if not, why — measured |
| `GET /api/aries/attention` | the last Attention Pass: what needs you, what can wait, and what tried to instruct ARIES |
| `POST /api/aries/attention/run` | read everything now |

Bodies never travel in a response. Titles, sizes and sources only — the content is in the working
set. See [INTEGRATIONS.md](INTEGRATIONS.md).

## The Operator (Entry 019)

| route | does |
|---|---|
| `GET /api/aries/operator` | whether ARIES may act, whether it can verify anything right now and why not, which model it thinks with and where, and the goal vocabulary with each goal's evidence ceiling |
| `POST /api/aries/operator` | one request. The response always carries `reported_success` and `verified_success` **separately** — a caller showing only the first is showing the claim, not the outcome. `approve` and `dry_run` both default false |
| `GET /api/aries/operator/history` | what ARIES has been asked, read from the audit log rather than a table of its own, with the honesty-gap count |

See [OPERATOR.md](OPERATOR.md).

## Data lifecycle (Entry 018)

| route | does |
|---|---|
| `GET /api/aries/data` | the whole register: every table with its class, its window, what reads it, what would be removed, and the class vocabulary so no screen invents its own wording. Read-only by construction — `preview` counts and never deletes |
| `GET /api/aries/data/working-set` | what is being read right now and by which task. Labels, sources, sizes — **never contents**: the point of a working set is that borrowed material does not travel |
| `POST /api/aries/data/clean` | remove what is past its window. `force` defaults to `false`, so the rehearsal cannot be skipped by accident; `vacuum` gives the freed space back |
| `POST /api/aries/data/sweep` | collect working sets left behind by tasks that died mid-flight |

Every deletion writes an audit event (`data.rehearsed`, `data.cleaned`) before the call returns,
so the record exists whether or not anyone reads the response. See [DATA.md](DATA.md).

## Engine routes worth knowing

`GET /api/health` · `GET /api/observability/workers` (the dispatcher appears here alongside
the engine's five) · `GET /api/tasks/{id}` (the trace of any automation run) ·
`GET /api/proposals` (what needs a human) · `GET /api/audit`.

## Permissions

ARIES appends its routes to the engine's policy table at import. The table fails closed: an
unrecognised path falls back to method defaults, where any mutation needs `EDIT_TASK`. ARIES's
routes were therefore already safe before being registered — they would simply have been safe
by accident, at the wrong permission.

## M14 workspace agent and evidence

The existing executable workspace submission requires `manage_tools` permission.
Read endpoints use the existing workspace `view_data` policy. Approval additionally
requires `approve`. No separate task/run API is introduced.

```http
POST /api/aries/workspace
Content-Type: application/json

{"capability":"agent_task","args":{"task":"Check disk usage and report which filesystem has the highest percentage used."}}
```

Submission returns the existing queued goal ID. Natural requests can also use
`{"request":"..."}`; established exact commands retain their legacy routing.

| Endpoint | Response |
|---|---|
| `GET /api/aries/workspace/capabilities` | registered names, schemas, policy metadata and timeouts |
| `GET /api/aries/workspace/{id}` | task state, versioned steps/evidence, agent decisions and metrics |
| `GET /api/aries/workspace/{id}/steps` | task_id, schema_version, steps |
| `GET /api/aries/workspace/{id}/evidence` | task_id, evidence, final_evidence_refs |
| `POST /api/aries/workspace/{id}/approve` | approves only the frozen pending action; existing endpoint |
| `POST /api/aries/workspace/{id}/cancel` | cancels existing task; existing endpoint |

Missing IDs return 404. Legacy rows have schema version 1 and an empty new evidence
array; their original results are not discarded or invented as verified evidence.
New agent rows use version 2. Evidence records contain `evidence_id`, `type`,
`source`, `timestamp`, `step_id`, `verified`, and structured `data`.

A step's `execution_status=observed` is distinct from
`verification_status=verified`. `execution_error` and `execution_observation`
records have `verified=false`. `done` requires a supported goal contract and fresh
independent checks; `final_evidence_refs` points to those checks. Proposal JSON
cannot be changed through the approve request body. Concurrent approvals use a
conditional update, preserving execution history.

Example:

```bash
curl -s http://127.0.0.1:8000/api/aries/workspace/TASK_ID/steps
curl -s http://127.0.0.1:8000/api/aries/workspace/TASK_ID/evidence
```


## Intelligence API

See [INTELLIGENCE.md](INTELLIGENCE.md) for policy, accounting and evaluation scope.
All core endpoints use the existing authentication/permission middleware:
GET requires VIEW_DATA, POST requires MANAGE_TOOLS.

| Method | Path under `/api/aries` | Meaning |
|---|---|---|
| GET | `/intelligence/health` | Gateway/backend state; core remains available on failure |
| GET | `/intelligence/stats` | Bounded retained routing, usage, cost and completion summary |
| POST | `/intelligence/route` | `{text, background:false}` → typed recommendation; no tool execution |
| POST | `/intelligence/classify` | Local notification classification plus deterministic veto |
| POST | `/intelligence/extract` | Local typed summary/topics/dates extraction |
| POST | `/intelligence/cloud-baseline` | Explicit real cloud classification; no local substitution |
| POST | `/intelligence/ab-task` | `{text, architecture:"A" or "B"}` → existing durable workspace task |

Text is bounded to 12,000 characters; executable workspace goals retain their
2,000-character bound. Unknown fields fail schema validation. Invalid model
classification returns 422; unavailable cloud baseline returns 409/503. A/B tasks
retain normal approvals and verification; architecture A forces cloud planning
and requires explicit configured cloud access before enqueueing.

The local service on `127.0.0.1:11435` exposes `/health`, `/generate`, `/route`,
`/classify`, `/extract` and engine compatibility `/api/chat`, `/api/tags`. It has
no tools, no cloud execution path, no LAN access or browser-origin access.

Cloud configuration now supports `intelligence.cloud_provider=claude-cli|codex-cli`
using terminal login. The A/B cloud gate checks the selected executable instead
of requiring `ARIES_CLOUD_API_KEY`; HTTP credentials are required only when
`openai-compatible` is explicitly selected. See INTELLIGENCE.md.

### Local news summary metadata

`PUT /settings/news.local_summaries` accepts `{"value":true}`. Existing `GET /brief`
news items retain source titles and links and expose `meta.summary_status`
(`generated`, `fallback`, `original_macedonian`, or `budget_exhausted`),
`summary_cached` where applicable, and the source-content digest. Generated summaries
are unverified model text, not task execution evidence. No new model endpoint is needed.

### Desktop capability negotiation

`GET /desktop/capabilities` returns `available`, `methods`, `missing`,
`full_desktop_support` and `core_requires_shell: false`. The probe introspects only
`org.aries.Shell`; a build stamp is not proof of method support. Missing methods
remain explicit limitations rather than model-inferred success.

### Update maintenance lease

`POST /maintenance` (MANAGE_TOOLS) acquires an exclusive 240-second update lease,
returning its token and active-work status. New workspace/automation execution
waits. `GET /maintenance` reports `ready_to_restart`, active task IDs and remaining
automations. `DELETE /maintenance` with `{"token":"..."}` releases it. Conflicting
or wrong-owner requests return 409. Core restart clears the lease; abandoned leases
expire. Existing single-process deployment only.
