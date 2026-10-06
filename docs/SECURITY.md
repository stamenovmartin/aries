# ARIES — Security

ARIES runs on a personal machine, reads that machine, will hold mail and calendar
credentials, and acts on instructions that partly come from the internet. That combination is
the whole problem: **content ARIES reads is attacker-controlled, and ARIES has local
privileges.**

Every control below is enforced in code and pinned by a test. Where something is *not*
covered, it says so — a guard mistaken for a guarantee is worse than no guard.

## Principles inherited from the engine

* **The AI proposes; a human approves; an executor acts.** Consent is a separate object.
* **Credentials are not consent.** `DRY_RUN` must be off *and* the tool named in `LIVE_TOOLS`.
* **Fail closed.** An unrecognised route needs `edit_task`; an unknown client address is remote;
  an unvalidated source is refused.
* **`uncertain` is never retried.** An action dispatched whose result was lost is reconciled by
  evidence, never repeated.
* **Honest observability.** `null` with a reason, never a zero that looks like data.

## The network boundary

**With no `API_KEY`, ARIES serves loopback only.** Enforced by middleware on every request,
registered outermost so it runs before authentication.

This exists because of what the audit found: with `API_KEY` empty the engine maps every caller
to `shared_key_owner()` — **all eleven permissions, including `MANAGE_USERS`**. `scripts/start.sh`
binds `127.0.0.1`, but a shell script is a convention, not a control: one `--host 0.0.0.0`, one
container port mapping, one hand-typed `uvicorn`, and the machine is administrable by anyone on
the LAN. The middleware makes the binding irrelevant.

To expose ARIES: set `API_KEY`, set `SECRET_KEY`, mint per-person tokens with roles (approver ≠
executor), set `APP_ENV=production` — the engine then refuses to boot insecurely.

## Reaching outward: the two-stage SSRF guard

A source URL is user-supplied and its content is attacker-supplied. The guard is in two halves
because no single check covers both moments.

**At add time** (`aries/sources/safety.py`) — literal inspection, no DNS: scheme allowlisted per
type, credentials in URLs refused, and literal loopback/private/link-local/reserved addresses
refused. Paths are `realpath`-ed **before** judging, so a symlink at `~/research` pointing to
`~/.ssh` is caught; `privacy.excluded_paths` and system directories are enforced.

**At fetch time** (`aries/news/fetch.py`) — the half that needs a live request:

| attack | control |
|---|---|
| public name resolving to `127.0.0.1` | resolve, then check **every** address returned |
| host answering with one public and one private address | refused outright, not raced |
| **DNS rebinding** | the socket connects to the **validated IP**; `Host` and TLS SNI keep the real name, so the certificate is still verified. There is no second resolution to win. |
| **redirect to `169.254.169.254`** | automatic redirects are **off**; each hop is re-validated |
| endless redirects | hop limit |
| endless response body | byte cap enforced **while streaming** |

Pinning without `sni_hostname` would mean disabling certificate verification — trading one hole
for a worse one. httpcore's support for it was verified on this machine before the design
depended on it.

**Not covered:** this guards against ARIES being *aimed* at the wrong place. A genuinely public
host that is malicious remains reachable, which is correct — that is a content question, handled
below.

## Hostile content

**Feeds are parsed as data, never as markup.** Verified on this machine rather than assumed:

```
xml.etree.ElementTree:  XXE -> refused    billion laughs -> EXPANDED (vulnerable)
```

So external entities are safe but **nested internal entities are not** — a few hundred bytes
expanding to gigabytes. The fix is not a size cap (expansion happens after parsing starts) but
refusing the construct: **any document declaring a `DOCTYPE` is rejected before parsing.** No
legitimate RSS or Atom feed needs one.

Every field is stripped of markup, and entities are unescaped **after** stripping — the other
order lets `&lt;script&gt;` become a real tag once the stripper has run. Fields are length-bounded.

## Local reach

Health probes run four read-only commands through the engine's sandbox on an ARIES-specific
allowlist, narrower than the engine's global one. `/proc` and `/sys` are read in-process (virtual
files, no side effects, no shell). The sandbox's dangerous-pattern denylist applies to everything
else; `DRY_RUN` is on by default and no tool is in `LIVE_TOOLS`.

**ARIES never repairs anything on its own.** The health automation measures, judges, and raises
an `ActionProposal` for a human.

**Background Mode is the one place ARIES reaches outside its own boundary**, and it is bounded
twice over. The suspend lock is a logind inhibitor held as an open file descriptor — it cannot
outlive the ARIES process, in any failure mode, because the kernel closes it. The single GNOME key
it borrows (`idle-delay`) is recorded in the database before it is written and restored exactly on
switch-off, so a crash loses nothing. Writes to `/api/aries/power` need `MANAGE_TOOLS` rather than
ordinary settings permission, and all three switches are `user_only`: the learning loop may never
decide to keep the machine awake. Nothing here needs `sudo`, and no `idle` inhibitor is taken —
the screen lock and the screensaver behave exactly as they did.

The **resource policy** is the availability half of the same boundary. An always-awake machine
that will start anything at any hour is a denial of service against its owner, so heavy CPU and
GPU work is refused while the display is off unless explicitly enabled, is deferred above a
temperature limit, and is budgeted in time. Every refusal and release is written to an
append-only table *and* the engine's audit log. The enabling switches are `user_only`: learning
may never decide to spend the user's electricity. Nothing is ever force-killed — the budget
raises a flag a cooperating job reads, and work declaring itself stateful is left to finish, so
the policy cannot corrupt the work it governs. See `POWER.md`.

## Input bounds

User input that becomes a regex, a path, or a stored row is bounded at the HTTP edge *and* at the
core, because the CLI and in-process callers do not pass the edge: terms 120 chars, 50 synonyms,
50 topics, names 200, locations 2000, scored text 20 KB. `re.escape` removes ReDoS from
metacharacters; the length bound removes it from size.

## Permissions

| surface | read | write |
|---|---|---|
| automations | `view_data` | `schedule` — but **`execute`** to run one |
| sources | `view_data` | `manage_tools` — naming where ARIES may go is configuring its reach |
| settings | `view_data` | `manage_tools` |
| interests | `view_data` | `edit_task` — shapes what reaches you, names nowhere ARIES goes |

Running work and scheduling it are separate permissions, and no role below owner holds both
`APPROVE` and `EXECUTE`.

## Provenance

The audit trail records **who** acted. It previously recorded the literal string `"user"` for
every change; the actor is now derived from the authenticated principal (`user:<identity>` — the
prefix is load-bearing, since the Settings Service uses it to distinguish human from machine
writes). Every settings change, source addition and interest edit is audited with before/after
values.

## Secrets

Never in source URLs (refused), never in settings, never in general memory. `CREDENTIALS_KEY`
gates the encrypted store, which **refuses to operate** without it rather than storing plaintext.
Logs pass three-layer redaction covering token shapes, `Authorization` headers, DSN passwords and
PEM blocks.

## Learning cannot escalate

The precedence rule of §30 is enforced on the **write** path, not only the read path: a non-human
author can write only `DEFAULT`, `HISTORICAL`, `LEARNED`. Settings marked `user_only` refuse
machine writes entirely — `autonomy.level`, `ai.daily_cost_limit`, `ai.send_file_contents`,
`privacy.*`, `sources.allow_private_addresses`, `automations.worker_enabled`. **No learning loop
can turn on the thing that runs other things, or widen what ARIES may read.**
Learning may weigh a topic; it may not invent one.

## Known gaps

Recorded rather than hidden.

1. **`record_sync` is trusted.** Whatever reads a source reports its own counts, so a buggy
   reader can distort ranking. Acceptable while every reader is ARIES's own.
2. **Semantic memory keeps text the user never asked it to keep.** `privacy.excluded_memory_topics`
   and a credential-pattern gate are enforced *before* anything is embedded, on the machine write
   path as well as the user's (`aries/workspace/memory/extraction.py`, asserted in
   `tests/test_memory.py`). What remains: the gate refuses commands and credentials by pattern, so
   a statement that is neither still reaches the store, and `experiments/memory/analysis.md` records
   one such false keep per 45 utterances. `workspace.semantic_memory` turns the unasked write off
   entirely, and `privacy.remember_conversations` still governs whether anything is kept at all.
3. **No rate limiting on ARIES routes.** Loopback-only plus `max_actions_per_hour` on tools
   covers the current exposure; a real limiter is needed before ARIES is exposed with a key.
4. **The overlap lock is per-process.** Two API processes on one database could double-run an
   automation. A database lease is needed before multi-process.
5. **`robots.txt` is not consulted.** The fetcher identifies itself honestly but does not yet
   obey exclusion rules. Owed before any broad crawling.
6. **No supply-chain pinning beyond version numbers** — `requirements.txt` pins versions, not
   hashes.

## Reporting

This is a personal system with no external users. If it grows any, this section gets a real
disclosure process.
