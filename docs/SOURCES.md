# ARIES — Sources Registry

Every place ARIES may get information from, in one registry. §24's requirement is the design
brief: *agents should query the Sources Registry instead of hard-coding external websites.*

A source is not just a row. It is a stored instruction that some later component will act on —
fetch this URL, read this folder — at a time when the user who typed it is not there. So the
registry is where **"may ARIES go here?"** is answered, once, on the way in.

## Types

| type | reach | location | notes |
|---|---|---|---|
| `rss` | outbound | URL | cheapest and most predictable; prefer over `website` |
| `website` | outbound | URL | when no feed is offered |
| `api` | outbound | URL | usually needs a credential |
| `directory` | **local** | path | a folder on this machine |
| `documents` | **local** | path | a curated document collection |
| `repository` | **local** | path | a local checkout |
| `database` | outbound | connector | connector not built yet |
| `email` | outbound | connector | §21; reading is separate from sending |
| `calendar` | outbound | connector | §22 |

`outbound` is a **declared field**, not something consumers infer from the location. It decides
whether privacy mode applies, whether a credential is involved, and whether §21's "never send
without permission" is in play. A type whose connector does not exist yet is stored and
described, but never offered to an agent — it says so rather than appearing to work.

## What is refused, and why

Validation happens on the way **in**. A location that cannot be checked is rejected with a
reason, never stored with a warning — otherwise the check lives in every consumer, and the one
that forgets is the vulnerability.

**Paths** are expanded and `realpath`-ed *before* any rule is applied. `~/research` may be a
symlink to `~/.ssh`; only a check against the resolved path catches that.

* inside `privacy.excluded_paths` (defaults to `~/.ssh`, `~/.gnupg`, and is `user_only`)
* inside `/etc`, `/proc`, `/sys`, `/dev`, `/boot`, `/root`, `/var/lib`, `/usr/lib`
* relative, non-existent, not a directory, or not readable

**URLs**

* a scheme not allowlisted for the type (`file://` is never allowed)
* credentials embedded in the URL — they would sit in the database in plaintext (§32)
* literal loopback, private, link-local or reserved addresses, unless
  `sources.allow_private_addresses` is on. `169.254.169.254` is named as the cloud metadata
  range, because that is what it is.

**An honest limit.** The address check reads the literal host and does **not** resolve it. A
public name that resolves to a private address passes, as does one that resolves differently
when actually fetched (DNS rebinding). Closing that means resolving at fetch time and pinning
the address, which belongs in whatever fetches. This is a guard against mistakes, not a
complete SSRF defence, and it is written that way in the code so nobody mistakes it for one.

## Ordering

```
1. the user's PRIORITY      high → normal → low
2. the user's TRUST         trusted → normal → untrusted   (blocked is excluded entirely)
3. observed USEFULNESS      items the user actually got, over items seen
4. observed RELIABILITY     syncs that succeeded
5. source id                a stable tiebreak
```

Strictly layered, never a weighted blend. §20 says explicit user preferences must override
learned ones, and any blend eventually lets a run of mediocre results outvote a `HIGH` the
user set. Layering makes that structurally impossible: observation decides ties and nothing
more.

**Unproven sources are not buried.** A source never read has an *unknown* useful rate, and
treating unknown as zero would sort every new source last — where it is never consulted, never
earns a record, and stays there. New sources sort at `sources.unproven_prior` (default 0.5),
mid-pack, until there is evidence.

## What an agent gets

```python
for source in await for_agent(db, type="rss", topics=["ai"], capability="read"):
    ...
```

Absent from that list, rather than flagged: disabled sources, blocked sources, sources not
permitted for the capability asked for, types whose connector does not exist, and — when
`privacy.mode` is on — every outbound source. There is nothing for a consumer to check and
forget.

## Health and performance (§20)

`unused` (never read) · `ok` · `degraded` (recent failures) · `failing` (3 consecutive) ·
`stale` (not read in 3× its interval) · `disabled`.

Rates are `null` until the source has actually been read — a new source is unproven, not bad.

## Using it

```bash
./scripts/aries sources types                     # what can be added, and what each needs
./scripts/aries sources add --name "Reuters AI" --type rss \
    --location https://example.com/ai.xml --topics ai,agents --priority high --trust trusted
./scripts/aries sources                           # list, with health
./scripts/aries sources resolve --topics ai       # exactly what an agent would consult, in order
./scripts/aries sources rm reuters-ai
```

Over HTTP: `GET/POST /api/aries/sources`, `PATCH/DELETE /api/aries/sources/{id}`,
`GET /api/aries/sources/types`, `GET /api/aries/sources/resolve`,
`POST /api/aries/sources/{id}/feedback`. Reading needs `view_data`; adding, changing or
removing needs `manage_tools` — naming somewhere ARIES will go is configuring the system's
reach, not editing content.
