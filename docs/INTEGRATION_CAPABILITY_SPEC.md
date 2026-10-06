# ARIES Integration & Capability Layer — implementation specification

**Status:** Proposed specification; repository audit completed; implementation not started.
**Author:** Codex, at the user's request.
**Audit date:** 2026-09-13.
**Repository baseline:** `467b15514a3e1873cfcf988e5e770057ecee1e49`, including the working tree visible during inspection.
**Recorded:** 2026-09-13, following the user's instruction to save the report.

This document records the completed read-only audit and proposed next milestone. It is not evidence that the integrations or security changes described below have been implemented. References and observations describe the audited baseline; subsequent changes require revalidation.

the terminal agent was working on the live ARIES Shell during the audit. Codex made no code, Shell, GNOME extension, UI, keybinding, dock, wallpaper, or shell-setting changes; read no credential values; did not restart services or interact with GNOME. Saving this standalone report was subsequently authorized by the user.

## Recommendation

Implement a resource-scoped capability layer over the existing execution engine. Start with safe local-project access. External writes follow only after approval binding, execution identity, secret handling, and failure semantics are hardened.

```text
External or local resource
  → Connector
  → Capability
  → Permission / Delegation
  → Audited execution
  → Orchestrator / Workflow / UI
```

One authoritative capability definition should drive execution adapters, discovery, and future UI descriptions. Provider-specific behavior belongs beneath the connector boundary.

## 1. Current architecture findings

The actual repository has three useful boundaries:

- `aries`: application policy, settings, sources, automations, integrations catalogue, and API.
- `vendor/agentic-core`: tools, agents, workflows, approvals, execution operations, lifecycle, and persistence.
- Separate presentation processes communicating through HTTP.

The Integration Hub is a **catalogue and source-status projection**, not a functioning connector framework. In [registry.py](../aries/integrations/registry.py), an enabled source can produce `connected` without a successful connector operation.

The engine already defines:

- `ToolSpec`: schemas, coarse permission, risk, side effects, approval, timeout, availability.
- `Connector`: coarse `read/write/execute/metrics/listen` operations.
- Durable `ActionProposal`, `ExecutionOperation`, and `ExecutionPlan`.
- Director workflows and the existing evaluation/verdict lifecycle.

Sources carry location, scope, trust, allowed read operations, provenance, and observed health. Settings already support `project:<id>` scopes.

Preserve these boundaries. A source, project, connection, capability, and grant are different objects; none should become a synonym for another.

## 2. Reusable abstractions and ownership

| Existing abstraction | Use in this milestone |
|---|---|
| `ToolSpec` and tool registry | Executable adapter and model-facing description |
| `call_tool` | One guarded execution path, after generic hardening |
| `ActionProposal` / approval records | Human consent and decision history |
| `ExecutionOperation` | Sole ledger for consequential external operations |
| Director / `WorkflowSpec` | Compose capabilities into existing workflow nodes |
| `AriesSource` | Source selection, trust, priority, ingestion provenance |
| Settings Service | Preferences and security restrictions |
| Existing audit | Unified security and execution history |
| News fetch safety | Starting point for shared guarded HTTP transport |
| Automation breaker/governor | Existing scheduling and workload policy patterns |

Introduce ARIES-owned modules for capabilities, resource grants, projects, credential brokerage, and concrete connectors. Retain one capability definition as the authority; generate tool descriptions and discovery responses rather than maintaining independent copies.

The existing connector interface is useful precedent, but its substring routing is unsuitable for authenticated accounts. Use exact connector IDs and explicit connection IDs for ARIES. See [connectors.py](../vendor/agentic-core/agentic_core/tools/connectors.py).

## 3. Technical debt before integrations

These findings come from implementation inspection, not merely architecture documents.

| Finding | Consequence / required treatment |
|---|---|
| `call_tool` checks permission only when a principal exists | Workers need explicit service identity and a grant; absence must deny capability execution. |
| `_has_approval` checks only `status == approved` | Bind approval to exact capability, account, resource, task, immutable input, and operation. |
| Tool journals serialize payload fragments; proposals store payloads | Never pass credentials or unrestricted private content through these paths. Use protected artifact references and allowlisted audit projections. |
| Early registry/schema/permission refusals bypass tool execution audit | Audit every invocation decision, including denied reads. |
| Generic exceptions are classified largely by message text | Connector failures need explicit dispatch and outcome information, especially after writes. |
| `fs.read` defaults to `/`, uses `startswith`, and does not resolve symlinks | Cannot implement safe project access. |
| `http.get` follows redirects without ARIES SSRF checks | Must not provide a bypass around connector transport. |
| `sandbox.run_command` uses a shell and command-prefix checks | Not filesystem/network isolation for hostile repository code. |
| Credential storage uses global key names and custom cryptography | Add account-aware brokerage and vetted cryptography for new integration credentials. |
| Migration is `create_all()` | Introduce versioned migrations before evolving persisted contracts. |
| Source permission decoding can fall back to `["read"]` on malformed JSON | Capability authorization must fail closed on malformed grants or policy. |
| Connection status follows source configuration | Separate implementation availability, configuration, and successful access. |

Evidence: [calling.py](../vendor/agentic-core/agentic_core/tools/calling.py), [builtins](../vendor/agentic-core/agentic_core/tools/builtin.py), [secrets_store.py](../vendor/agentic-core/agentic_core/security/secrets_store.py), [migrate.py](../vendor/agentic-core/agentic_core/database/migrate.py), [source models](../aries/sources/models.py).

Two isolated checks confirmed:

- `/projects/app-other/file` passes the inherited prefix predicate for `/projects/app`.
- The existing fetch target validator accepts a mocked metadata address when `allow_private=True`.

Neither check read protected files or contacted a metadata endpoint. Shared transport must distinguish explicit private-network exceptions from always-forbidden destinations.

## 4. Capability schema and taxonomy

Keep existing RBAC permissions as coarse authority:

- `VIEW_DATA`: inspect permitted information.
- `MANAGE_TOOLS`: configure resources and grants.
- `APPROVE`: approve a consequential operation.
- `EXECUTE`: initiate execution through the execution API.

Add resource-scoped capability grants beneath RBAC. Do not expand the RBAC enum into hundreds of provider permissions.

Use **domain + resource + operation**, with providers represented separately:

| Domain | Initial capabilities | Later, separately granted |
|---|---|---|
| Projects | `projects.metadata.read`, `projects.files.read`, `projects.files.search`, `projects.git.read` | `projects.files.patch`, `projects.commands.execute` |
| Repositories | `repositories.metadata.read`, `repositories.contents.read`, `repositories.issues.read`, `repositories.pull_requests.read` | `repositories.issues.create`, `repositories.issues.comment`, `repositories.pull_requests.create`, `repositories.contents.update` |
| Calendar | `calendar.calendars.read`, `calendar.events.read`, `calendar.availability.read` | `calendar.events.create`, `calendar.events.update`, `calendar.events.delete` |
| Mail | `mail.messages.read`, `mail.messages.search` | `mail.drafts.create`, `mail.drafts.update`, `mail.messages.send`, `mail.attachments.read` |
| Web | `web.documents.fetch` | Browser navigation belongs to a later browser connector |
| Internal services | `news.items.read` | Scoped memory retrieval when its boundary is ready |

Avoid broad `projects.modify`, `github.repo.write`, and `mail.modify` permissions: their effects are too different to review meaningfully.

Illustrative capability definition:

```json
{
  "id": "calendar.events.read",
  "version": 1,
  "description": "Read events within a bounded time interval.",
  "resource_type": "calendar",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["start", "end"],
    "properties": {
      "start": {"type": "string", "format": "date-time"},
      "end": {"type": "string", "format": "date-time"},
      "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
      "cursor": {"type": "string", "maxLength": 2048}
    }
  },
  "output_schema_ref": "aries://schemas/calendar-event-page/v1",
  "required_permission": "view_data",
  "effect": "read",
  "risk": "low",
  "consequential": false,
  "reversibility": "not_applicable",
  "approval_policy": "none",
  "network_access": "provider_only",
  "data_classification": "private",
  "result_trust": "untrusted_content",
  "retry_policy": "bounded_read",
  "timeout_seconds": 20,
  "supports_pagination": true,
  "supports_reconciliation": false
}
```

Limits above are proposed defaults, not provider guarantees. Additional executable constraints include maximum interval, bytes, pages, calls, allowed fields, output destinations, and preconditions. Validate schemas and semantic constraints at runtime; descriptions enforce nothing.

Separate three questions:

1. Is the operation implemented?
2. Can this connection support it?
3. May this principal use it on this resource now?

Discovery never substitutes for invocation-time authorization.

## 5. Connector interface and execution boundary

Proposed asynchronous interface:

```python
class Connector:
    def describe(self) -> ConnectorDescriptor: ...
    async def open(self, context: ConnectorContext) -> None: ...
    async def discover(self, context) -> CapabilitySnapshot: ...
    async def probe(self, context) -> HealthObservation: ...
    async def invoke(self, request, permit) -> ConnectorResult: ...
    async def reconcile(self, operation, permit) -> ReconciliationResult: ...
    async def disconnect(self, context, revoke_remote: bool) -> DisconnectResult: ...
    async def close(self) -> None: ...
```

`ConnectorContext` contains trusted configuration, account/resource references, transport, and broker access. Never put it in model context or workflow checkpoints. An invocation-bound `permit` is issued by the execution boundary; model-supplied JSON cannot construct one.

Lifecycle requirements:

- Registration performs no network access.
- `open` initializes clients without interactive authentication.
- `discover` reports implemented and observed support, with freshness.
- `probe` performs a bounded harmless operation.
- `invoke` accepts typed operations, never arbitrary HTTP requests or shell commands.
- `reconcile` gathers evidence and must not replay the original mutation.
- `close` releases resources without disconnecting the account.

```text
Authenticated caller or scoped service identity
  → validate capability and input
  → resolve connection and canonical resource
  → evaluate restrictions, grants, delegation and egress
  → evaluate live gate, policy and exact approval
  → persist invocation/audit intent
  → claim existing ExecutionOperation for consequential work
  → connector obtains broker-authorized transport
  → dispatch
  → normalize and protect result
  → persist outcome
  → existing EVALUATE → VERDICT
```

Preserve one ledger and one live gate. Connector libraries must not add uncoordinated mutation retry loops.

**Proposed engine integration decision:** introduce generic authorization, approval-binding, safe-journaling, and typed-failure extension points in the guarded path through a reviewed upstream change/vendor refresh. ARIES supplies resource policy through those hooks.

Current extension points do not fully provide these guarantees. Registration alone does not fix this. Until hardening is available, keep external writes unavailable rather than introducing a second executor.

## 6. Credential architecture

The broker is an authority boundary, not a general `get_secret()` tool.

```text
Agent → authorized capability → connector
                              → broker-authorized transport
                              → fixed provider endpoint
```

Requirements:

- Store credential references in connection records.
- Bind credentials to provider, account, connection, kind, and version.
- Accept only internally authorized invocations.
- Verify connection generation, credential status, required scopes, and endpoint audience immediately before use.
- Inject authentication inside trusted transport.
- Never return tokens to agents, tool results, UI, prompts, memory, checkpoints, or general logs.
- Keep refresh tokens encrypted at rest; access tokens may be short-lived broker memory.
- Serialize refresh per credential with transactional version checks.
- Revoked or expired records never fall back to environment credentials.
- Audit credential version IDs, not token suffixes.

Recommended storage: vetted AEAD encryption for credential records, with the master key obtained through the desktop secret service when available. A locked/unavailable key store produces `AUTH_REQUIRED` with a specific reason; no plaintext fallback.

The existing [crypto implementation](../vendor/agentic-core/agentic_core/security/crypto.py) uses custom HMAC-based encryption. Do not extend it for new OAuth credentials. Preserve existing data through an explicit compatibility migration.

Authentication flow belongs to the broker's authentication component:

- System browser, single-use high-entropy state, and PKCE where supported.
- Exact redirect handling and provider/account binding.
- Short-lived authentication transactions.
- No callback query strings in access logs.
- Refresh and authorization codes excluded from normal persistence.
- Reauthorization never silently widens ARIES grants.

For Google desktop authorization, use its installed-application flow with PKCE and a temporary loopback listener. Its documentation at audit time says incremental authorization is not supported for installed apps; scope expansion needs explicit reauthorization. [Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app).

A same-process broker prevents accidental secret exposure to model context. It does not isolate secrets from arbitrary Python in that process. Executable dynamic agents require an OS boundary first.

## 7. Delegation and lifetime semantics

Represent delegation as a restricted child of an existing grant:

```text
grant_id / parent_grant_id
issuer_principal_id
subject_agent_instance_id
task_id / workflow_run_id
capability_id + version
connection_id / resource_selector
constraints
not_before / expires_at
remaining_call_budget
delegable = false
revoked_at / policy_generation
```

Authorization is the intersection of existing RBAC authority, current security/privacy restrictions, root resource grant, every ancestor delegation, task/agent lifetime, provider permissions, and operation-specific approval when required.

Rules:

- A grant ID is not authentication.
- Resource selectors are typed IDs and bounded constraints, not arbitrary predicates.
- Child scope, expiry, budget, and destinations cannot exceed the parent.
- No redelegation in v1.
- Approval and credential-management authority are never delegated to temporary agents.
- Revocation cascades to descendants.
- Check expiry and task state at use, not just during cleanup.
- Count aggregate budget across descendants to prevent fan-out amplification.
- Retry/resume reuse operation identity; expired delegation requires fresh authorization.

Example: one research agent gets `repositories.contents.read` on one registered GitHub repository, for one task, with 20 calls and a maximum 30-minute lifetime. Task completion ends the grant earlier.

After revocation commits, no new dispatch may begin. Already-dispatched effects cannot be recalled; record that distinction.

## 8. Connection state machine and UI contract

Keep catalogue implementation status separate: `NOT_IMPLEMENTED | AVAILABLE`.

| Connection state | Meaning |
|---|---|
| `DISCONNECTED` | Locally disabled; new invocations denied |
| `CONNECTING` | Authentication or initial validation in progress |
| `CONNECTED` | Permitted baseline operation succeeded and is sufficiently fresh |
| `DEGRADED` | Some capabilities usable; others failing, stale, or throttled |
| `AUTH_REQUIRED` | Credentials missing, expired without refresh, revoked, or inaccessible |
| `PERMISSION_REQUIRED` | Requested access needs provider permission or ARIES consent |
| `UNAVAILABLE` | No useful live operation possible due to transport/provider availability |
| `ERROR` | Configuration/connector defect requires intervention |

Store facts and derive display state. Include capability-level availability so one denied calendar does not falsely disconnect a working account.

- Explicit connect: `DISCONNECTED → CONNECTING`.
- Successful authentication and baseline probe: `CONNECTING → CONNECTED`.
- Authentication failure: applicable state → `AUTH_REQUIRED`.
- Partial service failure: `CONNECTED → DEGRADED`.
- Sustained total outage: `CONNECTED/DEGRADED → UNAVAILABLE`.
- Recovery probe: state follows current facts.
- Explicit disconnect: deny locally immediately, then attempt remote revocation.
- Unknown post-dispatch outcome belongs to the invocation, not the connection.

An agent lacking a grant must not change the account's global state to `PERMISSION_REQUIRED`.

Future Connections response:

```text
provider / connector version / connection ID
display account identity
state / reason code / observed_at / stale_after
supported / granted / currently usable capabilities
resource scope summary
last successful operation
health / sanitized error / retry_at
remote revocation status
available actions and reasons other actions are unavailable
```

Actions: connect, disconnect, test, reauthorize, manage permissions. Test must not mark mail read or alter provider resources. No UI implementation is authorized by this specification.

## 9. Local Project Registry

Projects are first-class resources, optionally linked to existing sources.

Persist:

- Stable opaque project ID and editable name.
- Canonical root path and observed filesystem identity for replacement detection.
- Optional Git/worktree metadata and approved metadata roots.
- Grant references; derive allowed capabilities from grants.
- Project-specific exclusions.
- Settings scope reference `project:<id>`.
- Last successful ARIES activity, separately from observed repository activity.
- Active/missing/revalidation lifecycle status.

Registration is explicit. Never scan home automatically or register `/`, whole home, credential stores, or ARIES runtime storage by default.

Safe access algorithm:

1. Expand and resolve the registration path before authorization.
2. Reject prohibited roots and ambiguous overlapping registrations.
3. At every operation, resolve the relative target beneath the registered root.
4. Apply global/project exclusions to requested and resolved paths.
5. Enforce path-component containment, never string-prefix containment.
6. Open through directory descriptors with race-resistant containment.
7. Deny symlink traversal in v1 if safe resolution cannot be enforced atomically.
8. Bound file type/size, output bytes, directory depth, total scan budget.
9. Refuse devices, sockets, FIFOs, and unapproved mount traversal.
10. Revalidate root identity; moving/replacing a project never grants authority automatically.

Use a reviewed Linux `openat2` approach or conservative directory-descriptor traversal denying symlinks. `realpath()` followed by ordinary `open()` leaves a race.

Default exclusions cover `.env` variants, private keys, credential files, runtime databases, caches, and generated/vendor trees where appropriate. Gitignore is a search preference, not security policy. Content secret detection is additional protection, not proof of safety.

Git handling:

- Recognize `.git` directories and worktree pointer files.
- Authorize external Git metadata paths separately.
- Do not follow alternates/submodules outside approved roots.
- Sanitize remote URLs before storage/display.
- Read metadata without hooks, external diff, text conversion, credential helpers, or repository-selected executables.
- Treat README, `AGENTS.md`, package scripts, and comments as data, not authorization.

`projects.commands.execute` stays unavailable until a real execution sandbox exists. Running tests can execute arbitrary code; it is not a read.

## 10. GitHub connector

Use provider-neutral repository capabilities with `provider_id = github`. Bind resources to provider host + repository ID + connection ID. Owner/name is a display/routing attribute. Handle rename/transfer without silently following resources into unauthorized ownership contexts.

| Capability | GitHub operation family | Provider permission |
|---|---|---|
| Metadata read | Repository details | Endpoint-required metadata access |
| Contents read | Contents, commits, trees | Contents: read |
| Issues read | Issues/comments | Issues: read |
| Pull requests read | PR metadata/files/reviews | Pull requests: read |
| Issue create/comment, later | Specific issue mutations | Issues: write |
| PR create, later | Create PR | Pull requests: write |
| Contents update, later | Approved path/ref update | Contents: write |

Validate exact endpoint mappings during implementation; alternatives/combined requirements exist. [GitHub permission matrix](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).

For the first personal implementation, support an explicitly enrolled repository-selected fine-grained PAT through the broker. For durable installation, prefer GitHub App authentication with selected repositories and short-lived installation tokens. Avoid broad classic OAuth `repo` just to read private repositories. [GitHub authentication choice](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/deciding-when-to-build-a-github-app).

Requirements:

- Fixed supported API origin; no caller-provided base URL.
- REST first; GraphQL only for justified operations.
- Supported API version pinned in connector configuration.
- Bounded pagination/fields and conditional requests where applicable.
- Account-wide rate budget and bounded concurrency.
- Respect reset/secondary-limit responses and `Retry-After`.
- Validate pagination/redirect destinations before attaching credentials.
- Preserve sanitized provider request IDs for audit.
- Treat private-resource 404 as ambiguous absence/access failure.
- Never clone/execute a repository merely to answer a read.

Follow provider backoff without hardcoding a universal quota. [GitHub REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api).

Writes require approved destination, exact content, branch/ref preconditions, and stable operation identity. Issues/PRs may notify people or trigger automation; later deletion does not remove their consequential nature.

## 11. Calendar connector

Canonical event model preserves connection/calendar/event IDs, title/description/location, start/end, all-day versus timed semantics, original timezone, recurrence/occurrence identity, organizer/attendees, responses/cancellation, provider version/ETag, observation time, and provenance.

Use bounded UTC query intervals while preserving original timezone and all-day semantics. Compute tomorrow in the user's timezone, including daylight-saving transitions.

- Availability returns busy intervals without event content.
- Event reads return authorized fields.
- Creation, update, deletion are separate grants.
- Specify occurrence versus series changes.
- Attendee notifications must be explicit.
- Updates use provider version preconditions where supported.

For Google, choose narrow scopes such as `calendar.events.readonly`, `calendar.calendarlist.readonly`, and the applicable free/busy scope. Provider write scopes do not replace per-calendar ARIES grants. [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth).

Writes involving attendees are externally consequential; restoring an event does not undo notifications. Implement one real provider first. Preserve provider-specific recurrence features in namespaced extensions and report unsupported operations rather than simplifying silently.

## 12. Email connector

Separate message, thread, attachment, and draft identities.

Initial read/search operations:

- Bounded date ranges and typed filters.
- Distinguish metadata from body access.
- Plain-text content with provenance and untrusted-content marking.
- Do not mark messages read.
- Disable remote images, tracking, scripts, and automatic link following.
- Separate attachment access.
- Bound MIME depth, decoded size, attachment count, archive extraction.
- Never execute attachments or apply instructions from messages.

Reject unsupported search filters instead of dropping them.

Gmail `gmail.readonly` enables reading; `gmail.metadata` is narrower and cannot be assumed equivalent. **`gmail.compose` permits both draft management and sending**: ARIES must independently enforce draft-only access. Several read/compose scopes are restricted, so deployment/data-transmission requirements need review before release. [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).

Local draft preparation and uploading a provider draft are distinct operations.

Sending requires a separate grant, exact sender/To/Cc/Bcc/subject/body/attachment identities, immutable content digest, explicit human approval initially, live gate, durable operation identity, and reconciliation.

A send timeout after dispatch is uncertain. Message-ID or Sent-folder evidence must not be assumed to guarantee deduplication.

## 13. API contracts and orchestrator compatibility

All relative paths below are beneath `/api/aries/v1`.

| Endpoint | Contract |
|---|---|
| `GET /capabilities` | Authorized discovery with implementation/availability facts |
| `GET /connections` | Account-level state |
| `POST /connections` | Configure an implemented connector |
| `POST /connections/{id}/auth-sessions` | Start explicit authentication |
| `POST /connections/{id}/test` | Queue bounded probe |
| `POST /connections/{id}/disconnect` | Deny locally, attempt remote revocation |
| `GET/POST /projects` | Authorized listing or explicit registration |
| `PATCH /projects/{id}` | Version-checked metadata update |
| `GET/POST /grants` | Inspect/issue permitted grants |
| `POST /grants/{id}/revoke` | Revoke and cascade |
| `POST /capability-invocations` | Validate/queue invocation |
| `GET /capability-invocations/{id}` | Authorized status/result |
| `POST /capability-invocations/{id}/cancel` | Cancel pending work; report dispatched status honestly |

Explicit route policies, not engine fallbacks:

- Connection/project/grant management: `MANAGE_TOOLS` plus resource checks.
- Invocation submission: `EXECUTE`, consistent with existing execution API.
- Read endpoints: `VIEW_DATA` plus resource/result ownership.
- Approvals: existing `APPROVE` path.
- Agents use scoped runtime identity, never owner shared API keys.

Example invocation:

```json
{
  "capability": "repositories.pull_requests.read",
  "version": 1,
  "connection_id": "conn_7",
  "resource_id": "repo_42",
  "arguments": {"state": "open", "page_size": 30},
  "task_id": 123,
  "idempotency_key": "client-generated-request-id"
}
```

Server verifies task ownership and derives requester, agent instance, workflow, and grant chain. Caller-supplied attribution is not authoritative. Accepted calls return `202` plus invocation ID; same idempotency key with different immutable input returns `409`.

Discovery exposes schemas, resource types, freshness, filters, effects, approval needs, cost estimates, and eligibility. Do not enumerate unauthorized resources.

For “Prepare me for tomorrow,” a future orchestrator selects calendar reads, mail search, project metadata, and news, then builds existing Director nodes. Missing access is a gap requiring established consent, not permission for the orchestrator to issue grants. Do not advertise memory retrieval as ready until scoped retrieval and exclusions are enforced.

## 14. Data model

Use the existing SQLAlchemy `Base` and database.

| Proposed entity | Purpose |
|---|---|
| `aries_connections` | Connector/account identity, configuration, generation, lifecycle facts |
| `aries_resources` | Connection-scoped typed provider resources |
| `aries_projects` | Local root identity and metadata |
| `aries_project_exclusions` | Structured exclusions |
| `aries_capability_grants` | Root/delegated authority, constraints, expiry/revocation |
| `aries_capability_invocations` | Request identity, authorization references, progress/result reference |
| `aries_approval_bindings` | Exact operation binding to existing `ActionProposal` |
| `aries_connection_observations` | Probe/operation facts, sanitized failures, cooldown evidence |
| `aries_credential_bindings` | Connection-to-broker references, no plaintext |
| `aries_source_resource_links` | Existing source links to projects/provider resources |
| Protected integration artifacts | Private request bodies/results with scoped access/retention |

Capability definitions remain in code; persist version/digest per invocation. Do not duplicate preferences, grants' allowed-capability lists, operation state, or source trust/learning data.

Require unique provider-resource identity within a connection, requester-scoped client idempotency keys, and exact approval bindings. Use UTC timestamps with explicit serialization. Quotas/dispatch claims require transactional updates; network calls stay outside long-running database transactions.

## 15. Audit model

Every attempt, including denied reads, must be attributable. Allowlisted event fields:

```text
event / invocation / correlation IDs
requester principal and kind
agent definition / agent-instance IDs
workflow / run / task IDs
capability ID/version
connection / provider / account-reference / resource IDs
root grant / delegation chain
permission decision / reason / policy generation
approval ID / approved-input digest
operation ID / dispatch phase
outcome / typed error / provider request ID
duration / bounded item and byte counts
consequential flag / reversibility classification
```

Events: requested, denied, authorized, dispatched, completed, uncertain, reconciled.

Never audit tokens, headers, OAuth codes, raw query strings, email bodies, file contents, or unrestricted provider errors. Use internal IDs and protected artifact references; prefer keyed digests when ordinary hashes expose low-entropy private values.

The [existing audit serializer](../vendor/agentic-core/agentic_core/observability/audit.py) does not itself scrub arbitrary payloads; its writer catches construction errors. Immutability protection is application-level, not protection against the database owner.

Require persisted intent/audit before dispatch. If outcome persistence fails afterward, retain sent/uncertain and reconcile; never report an ordinary retryable failure.

## 16. Security threat model

| Threat | Required control |
|---|---|
| OAuth/token leakage | Broker-only access, encryption, fixed audiences, no secret-bearing logs/checkpoints |
| Malicious email | Data-only handling; no automatic tools/links/attachments/permission changes |
| Malicious repository | No execution on read; safe Git; files cannot grant authority |
| Prompt injection | Separate trusted instructions/content; deterministic authorization/output controls |
| Confused deputy | Bind identity/task/grant/account/resource/input at dispatch |
| Excessive permissions | Provider scopes intersect narrower ARIES grants |
| Stale/revoked credentials | Generation/expiry checks, no fallback, serialized refresh |
| Cross-project leakage | Scope reads, artifacts, caches, retrieval, results, destinations |
| SSRF | Fixed origins; DNS/redirect checks; metadata/local control always blocked |
| Credential logging | Allowlisted serialization, sensitive wire logs disabled, synthetic-secret tests |
| Poisoned external data | Provenance, freshness/version, bounded parsing, no automatic memory promotion |
| Unsafe delegation | Runtime identity, ancestry, expiry, budgets, no redelegation |
| Local API privilege bypass | No owner key for agents; capability identity required even on loopback |
| Read-to-write exfiltration | Separate egress permission for mail, uploads, remote search, model transmission |
| Resource exhaustion | Byte/page/time/call bounds, concurrency limits, cooldowns, governor |

A trusted source can be credible evidence without being authorized to issue instructions. Privacy must cover later transmission of retrieved content to external LLMs.

Do not claim protection against hostile code running as the same unrestricted Unix user. Executable temporary agents need filesystem/network/environment isolation and isolation from local ARIES control endpoints.

## 17. Failure semantics and environment check

| Failure | Handling |
|---|---|
| Invalid input | `VALIDATION`; repair/replan |
| Unsupported operation | `CAPABILITY`; implemented alternative |
| ARIES grant denial | `POLICY`; no automatic scope expansion |
| Credential expiry/revocation | `AUTH`; permitted refresh or reconnect |
| Missing provider scope | `AUTH` with `permission_required` reason |
| Rate limit | `TRANSIENT`; defer to retry time |
| Read DNS/transport failure | Bounded retry with jitter/deadline |
| Write definitely not dispatched | Retry only with reliable evidence and same operation identity |
| Write may have reached provider | `UNCERTAIN`; reconcile |
| Version conflict | Re-read; new approval for changed intent |
| Invalid response after mutation | `UNCERTAIN` when effect cannot be established |
| Cancellation after dispatch | Do not imply provider cancellation |
| Partial result | Return completeness/cursor; do not imply complete success |

Proposed read default: maximum three total attempts within one end-to-end deadline. Respect cooldowns and delegation expiry. Scheduler and connector retries share one budget.

Keep `ExecutionOperation` authoritative. Unique keys help, but concurrent dispatch needs atomic claims, not lookup-then-insert alone.

Do not use `idempotent=False` to handle retries of email/calendar operations: current suffix generation is inappropriate for retrying uncertain sends. Deliberately new intent gets a new explicit operation identity.

### Observed host connectivity

**Measured 2026-09-13 at 01:05 UTC**, with unauthenticated HTTPS HEAD requests, no redirect following, 5-second connect/12-second total timeouts, TLS verification enabled.

| Endpoint | HTTP |
|---|---:|
| `github.com/login/oauth/authorize` | 302 |
| `github.com/login/oauth/access_token` | 404 |
| `api.github.com/` | 200 |
| `accounts.google.com/.well-known/openid-configuration` | 200 |
| `accounts.google.com/o/oauth2/v2/auth` | 302 |
| `oauth2.googleapis.com/token` | 404 |
| `www.googleapis.com/calendar/v3/users/me/calendarList` | 401 |
| `gmail.googleapis.com/gmail/v1/users/me/profile` | 401 |

All host probes: curl exit 0, TLS verification result 0, approximately 0.12–0.28 seconds. No credentials sent.

Initial execution-sandbox probes failed DNS resolution. An approved host-level repetition used the machine's existing network configuration and established reachability. Token-endpoint HEAD 404s do not test token exchange; 401s do not test account access. Browser redirects, OAuth POSTs, refresh, quotas, and authenticated operations remain unvalidated. No network restrictions were bypassed or TLS protections weakened.

## 18. Test strategy

Use isolated temporary databases/project trees, fake transports, and fake clocks; do not target the live desktop runtime.

- Authorization: no principal, wrong task/account/project, expired ancestor, revoked parent, budget exhaustion, scope expansion.
- Approval: unrelated proposal, modified payload/recipients, stale version, cross-task/account replay.
- Projects: sibling-prefix escape, traversal, symlinks/swaps, root replacement, excluded descendants, external worktrees/submodules, hard-link policy, special files.
- Transport: private/mixed DNS, rebinding, redirects, credential stripping, forbidden metadata, TLS failure, oversized/decompression-heavy responses.
- Credentials: refresh races, rotation, locked/missing key, revocation/no fallback, synthetic secrets absent from all persistence/telemetry.
- Execution: crashes before/after dispatch and before commit, concurrent duplicates, lost responses, cancellation/reconciliation.
- Providers: pagination/scopes, 401/403/404 distinctions, throttling, recurrence, MIME, unsupported filters.
- Data isolation: cache and persisted result access after expiry/revocation.
- UI/API: honest states/errors, null first-success timestamps, no implementation claims from fixtures.

Live read tests are opt-in on explicitly selected resources. Live writes require dedicated resources and exact approved operations.

Audit validation actually performed: inspection of existing security/tool/operation tests plus the two isolated checks in section 3. The full suite was not run and is not claimed to pass.

## 19. Migration plan

1. Preserve live working tree; complete Shell independently.
2. Add versioned migrations and test on copied database.
3. Add schemas/grants/invocations/projects without enabling connectors.
4. Land generic engine hardening via reviewed vendor refresh.
5. Treat existing project sources as migration candidates, not automatically authorized projects.
6. Present canonical roots/exclusions for explicit adoption.
7. Keep legacy source permissions for existing readers until migrated; new authority requires grants.
8. Preserve legacy Connections API through compatibility projection while adding versioned instances.
9. Explicitly migrate account-bound credentials, preserving revocation tombstones.
10. Enable local reads, external reads, then individually gated writes.
11. Incrementally move relevant automations through shared capability execution.

Rollback disables dispatch without deleting operations, approvals, grants, or audit. Downgrades refuse schemas they cannot safely interpret.

## 20. Milestone breakdown

| Milestone | Exit condition |
|---|---|
| I0 — Security/persistence foundation | Identity, exact approval binding, safe journals, typed failures, atomic dispatch, migrations tested |
| I1 — Local Project Registry | Explicit projects with bounded metadata/read/search and containment/exclusion tests |
| I2 — Capability/connection contracts | Authoritative catalogue, discoverable grants/operations, honest states |
| I3 — Broker/GitHub reads | Real enrollment, repository-scoped reads, revocation/rate handling/audit |
| I4 — Calendar reads | Real provider, timezone/recurrence, availability privacy, bounded workflows |
| I5 — Mail reads/drafts | Real provider, hostile-content handling, protected artifacts, draft/send separation |
| I6 — Consequential operations | Individually enabled writes pass approval/crash/timeout/reconciliation tests |
| I7 — Orchestrator handoff | Deterministic preparation workflow discovers grants and handles missing access |

I1 needs no external credentials. Do not bundle I6 into connecting accounts. I7 proves compatibility without building the full goal-based orchestrator.

## 21. Required ADRs and architectural objections

Required decisions:

1. Capability taxonomy relative to RBAC, sources, tools.
2. Single guarded path and generic engine hardening.
3. Resource identity, local containment, Git/worktrees.
4. Broker boundary, credential storage, crypto migration.
5. Delegation identity, expiry/revocation, aggregate budgets.
6. Exact approval binding, operation identity, reconciliation.
7. Connection observations, derived state, cache freshness.
8. External-content trust, protected artifacts, retention/egress.
9. Provider authentication and scope limitations.
10. Versioned database/API migration.

| Classification | Reject |
|---|---|
| Duplicated | New workflow engine, approval system, operation ledger, preference store, independent capability lists |
| Premature | Dynamic agents, universal browser automation, broad integration marketplace, vectorizing all connected data |
| Unsafe | Whole-home access, generic authenticated HTTP tools, prefix path checks, OAuth scopes equated with ARIES consent |
| Unsafe | Draft assumed send-safe, all reads assumed harmless, same-process code assumed secret-isolated |
| Unsafe | Blind mutation retries, unrelated approval reuse, registration equated with successful connection |
| Overengineered | Per-connector microservices, distributed queues, graph database, custom policy language for this single-user milestone |
| Overengineered | Exhaustive provider normalization before one real implementation |
| Necessary despite added work | Race-resistant filesystem access, strict invocation identity, broker, durable uncertainty |

The vendored-engine boundary is valuable but does not remove implementation gaps. Resolve them with reviewed upstream changes/vendor refresh and an ADR, not a silent second guarded executor in ARIES.

## 22. Explicit non-goals

- Shell, extensions, UI implementation, keybindings, dock, wallpaper, shell settings.
- Autonomous sending, merging, deployment, destructive project changes.
- Arbitrary repository command execution.
- Whole-home indexing or automatic credential discovery.
- Full goal orchestrator, dynamic agents, model router, slow evolution.
- General memory ingestion of mail/repository contents.
- Browser automation, SSH, Docker, databases, arbitrary API connectors.
- Public webhook ingress or hosted OAuth relay.
- Multiple production calendar/mail providers before one is proven.
- Exactly-once external-effect claims or protection from a compromised desktop user.

## Completion record

- Repository audit and next-milestone specification: completed.
- Unauthenticated endpoint reachability check: completed, with limitations above.
- Full test suite: not run.
- Integration implementation: not started.
- Code/live Shell changes by Codex for this task: none.
- This standalone documentation file: saved on the user's explicit request.
- Further implementation requires a new task; stop after saving the report.
